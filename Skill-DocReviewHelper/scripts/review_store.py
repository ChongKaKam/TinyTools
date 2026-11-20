"""Workspace-scoped Markdown snapshots and block annotations for DocReviewHelper."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Conflict(Exception):
    """The caller's base version or annotation revision is stale."""


_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_LIST = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])[ \t]+")
_QUOTE = re.compile(r"^ {0,3}>")
_RULE = re.compile(r"^ {0,3}([*_\-])(?:[ \t]*\1){2,}[ \t]*$")
_IMAGE = re.compile(
    r"""^ {0,3}!\[(?:\\.|[^\]\\])*\]\([ \t]*(?:<([^>]+)>|((?:\\.|[^\s])+?))"""
    r"""(?:[ \t]+(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\([^()]*\)))?[ \t]*\)[ \t]*$"""
)
_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
}


def _line(text):
    return text.rstrip("\r\n")


def _table_header(lines, i):
    if i + 1 >= len(lines) or "|" not in lines[i] or "|" not in lines[i + 1]:
        return False
    cells = lines[i + 1].strip().strip("|").split("|")
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _kind(lines, i):
    line = _line(lines[i])
    if _FENCE.match(line):
        return "code"
    if _HEADING.match(line):
        return "heading"
    if _RULE.match(line):
        return "divider"
    if _IMAGE.match(line):
        return "figure"
    if _LIST.match(line):
        return "list"
    if _QUOTE.match(line):
        return "quote"
    if _table_header(lines, i):
        return "table"
    if i + 1 < len(lines) and _SETEXT.fullmatch(_line(lines[i + 1])):
        return "heading"
    return "paragraph"


@dataclass
class Block:
    kind: str
    source: str
    gap: str
    asset: str | None = None


def _parse(text):
    # Keep the exact blank lines and line endings separate from deduplicated block text.
    gap = "\ufeff" if text.startswith("\ufeff") else ""
    lines = text[len(gap):].splitlines(keepends=True)
    blocks = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            gap += lines[i]
            i += 1
            continue
        start = i
        kind = _kind(lines, i)
        open_fence = False
        i += 1
        if kind == "code":
            fence = _FENCE.match(_line(lines[start])).group(1)
            closing = re.compile(r"^ {0,3}" + fence[0] + "{" + str(len(fence)) + r",}[ \t]*$")
            open_fence = True
            while i < len(lines):
                i += 1
                if closing.fullmatch(_line(lines[i - 1])):
                    open_fence = False
                    break
        elif kind == "heading" and not _HEADING.match(_line(lines[start])):
            i += 1
        elif kind == "table":
            i += 1  # Delimiter row
            while i < len(lines) and "|" in lines[i] and _kind(lines, i) == "paragraph":
                i += 1
        elif kind == "quote":
            while i < len(lines) and _QUOTE.match(lines[i]):
                i += 1
        elif kind in ("list", "paragraph"):
            while i < len(lines) and lines[i].strip():
                following = _kind(lines, i)
                if following != "paragraph" and not (kind == "list" and following == "list"):
                    break
                i += 1
        raw = "".join(lines[start:i])
        ending = None if open_fence else re.search(r"(?:\r\n|\r|\n)\Z", raw)
        body = raw[:ending.start()] if ending else raw
        blocks.append(Block(kind, body, gap))
        gap = ending.group() if ending else ""
    return blocks, gap


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS bodies (
        id INTEGER PRIMARY KEY, digest BLOB NOT NULL UNIQUE, payload BLOB NOT NULL,
        compressed INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS assets (
        digest TEXT PRIMARY KEY, mime TEXT NOT NULL, payload BLOB NOT NULL) WITHOUT ROWID""",
    """CREATE TABLE IF NOT EXISTS manifests (
        id INTEGER PRIMARY KEY, digest BLOB NOT NULL UNIQUE, tail TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS blocks (
        manifest INTEGER NOT NULL REFERENCES manifests, ordinal INTEGER NOT NULL,
        kind TEXT NOT NULL, body INTEGER NOT NULL REFERENCES bodies, gap TEXT NOT NULL,
        asset TEXT REFERENCES assets, PRIMARY KEY (manifest, ordinal)) WITHOUT ROWID""",
    """CREATE TABLE IF NOT EXISTS versions (
        doc TEXT NOT NULL, version INTEGER NOT NULL, title TEXT NOT NULL, created TEXT NOT NULL,
        manifest INTEGER NOT NULL REFERENCES manifests, PRIMARY KEY (doc, version)) WITHOUT ROWID""",
    """CREATE TABLE IF NOT EXISTS notes (
        doc TEXT NOT NULL, version INTEGER NOT NULL, ordinal INTEGER NOT NULL,
        note TEXT NOT NULL, rev INTEGER NOT NULL, PRIMARY KEY (doc, version, ordinal),
        FOREIGN KEY (doc, version) REFERENCES versions) WITHOUT ROWID""",
)


def _unpack(row):
    payload = zlib.decompress(row["payload"]) if row["compressed"] else row["payload"]
    return payload.decode("utf-8")


def _body_id(db, text):
    raw = text.encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    row = db.execute("SELECT id FROM bodies WHERE digest=?", (digest,)).fetchone()
    if row:
        return row[0]
    packed = zlib.compress(raw) if len(raw) >= 256 else raw
    compressed = len(packed) < len(raw)
    return db.execute(
        "INSERT INTO bodies(digest,payload,compressed) VALUES(?,?,?)",
        (digest, packed if compressed else raw, compressed),
    ).lastrowid


def _first_title(blocks):
    for block in blocks:
        if block.kind != "heading":
            continue
        match = _HEADING.match(block.source)
        if match and len(match[1]) == 1:
            title = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", match[2] or "").strip()
        elif not match and block.source.splitlines()[-1].strip().startswith("="):
            title = block.source.splitlines()[0].strip()
        else:
            continue
        if title:
            return title
    return ""


def _doc_id(doc):
    if not isinstance(doc, str) or not re.fullmatch(r"[^\W_][\w.-]{0,119}", doc):
        raise ValueError("文档 ID 应以字母或数字开头，可包含字母、数字、下划线、点和连字符（最多 120 字符）")
    return doc


def _integer(value, name, minimum):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} 须为大于等于 {minimum} 的整数")


def _get_version(db, doc, version):
    _doc_id(doc)
    if version is None:
        row = db.execute(
            "SELECT * FROM versions WHERE doc=? ORDER BY version DESC LIMIT 1", (doc,)
        ).fetchone()
    else:
        _integer(version, "版本", 1)
        row = db.execute("SELECT * FROM versions WHERE doc=? AND version=?", (doc, version)).fetchone()
    if row is None:
        raise KeyError(f"找不到文档或版本 {doc} / {version if version is not None else 'latest'}")
    return row


def _next_version(db, doc, base):
    latest = db.execute("SELECT MAX(version) FROM versions WHERE doc=?", (doc,)).fetchone()[0] or 0
    if base is not None:
        _integer(base, "基础版本", 0)
        if base != latest:
            raise Conflict(f"基础版本为 {base}，当前最新版本为 {latest}")
    return latest + 1


def _record_version(db, doc, version, title, manifest):
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute("INSERT INTO versions VALUES(?,?,?,?,?)", (doc, version, title, created, manifest))


class Store:
    def __init__(self, workspace: Path):
        self._given_root = Path(os.path.abspath(workspace))
        self.workspace = self._given_root.resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("工作区须为目录")
        self.directory = self.workspace / ".dochelper"
        self.database = self.directory / "reviews.sqlite3"
        self._check_storage()
        self.directory.mkdir(mode=0o700, exist_ok=True)
        with self._connection(write=True) as db:
            for statement in _SCHEMA:
                db.execute(statement)

    def _check_storage(self):
        if self.directory.is_symlink() or (self.directory.exists() and not self.directory.is_dir()):
            raise ValueError(".dochelper 须为工作区内的实际目录")
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = self.database.with_name(self.database.name + suffix)
            if path.is_symlink():
                raise ValueError(f"存储路径不能是符号链接：{path.name}")
            try:
                mode = path.stat()
            except FileNotFoundError:
                continue
            if mode.st_nlink != 1 or not stat.S_ISREG(mode.st_mode):
                raise ValueError(f"存储文件须为工作区内的独立常规文件：{path.name}")

    @contextmanager
    def _connection(self, write=False):
        self._check_storage()
        db = sqlite3.connect(self.database, timeout=15, isolation_level=None)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA temp_store=MEMORY")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        finally:
            db.close()  # An unfinished transaction is rolled back.

    def _local_file(self, path):
        path = Path(path)
        if path.is_absolute():
            for root in (self.workspace, self._given_root):
                try:
                    path = path.relative_to(root)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"文件须位于工作区：{path}")
        current = self.workspace
        for part in path.parts:
            current = current.parent if part == ".." else current / part
            if not current.is_relative_to(self.workspace) or current.is_symlink():
                raise ValueError(f"不允许越出工作区或经由符号链接读取文件：{path}")
        if not current.is_file():
            raise FileNotFoundError(f"找不到文件：{path}")
        return current

    def _image(self, db, source, block):
        match = _IMAGE.fullmatch(block.source)
        target = re.sub(r"\\([^\w\s])", r"\1", match[1] or match[2])
        if target.startswith("dochelper-asset:"):
            digest = target.removeprefix("dochelper-asset:")
            if not re.fullmatch("[0-9a-f]{64}", digest) or not db.execute(
                "SELECT 1 FROM assets WHERE digest=?", (digest,)
            ).fetchone():
                raise ValueError(f"工作区中找不到快照图片：{target}")
            return digest
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError(f"图片须使用本地文件路径：{target}")
        path = self._local_file(source.parent / unquote(parsed.path))
        mime = _MIME.get(path.suffix.lower())
        if mime is None:
            raise ValueError(f"不支持的图片格式：{path.name}")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        db.execute("INSERT OR IGNORE INTO assets VALUES(?,?,?)", (digest, mime, data))
        return digest

    def publish(self, doc: str, source: Path, title: str | None = None, base: int | None = None) -> int:
        _doc_id(doc)
        source = self._local_file(source)
        raw = source.read_bytes()
        blocks, tail = _parse(raw.decode("utf-8"))
        if not blocks:
            raise ValueError("文档没有可审阅的内容块")
        title = (title or "").strip() or _first_title(blocks) or source.stem or doc
        # Include the parser format and every resolved figure, so replacing a figure at
        # the same source path creates a distinct snapshot even if Markdown is identical.
        manifest_hash = hashlib.sha256(b"dochelper-md-1" + hashlib.sha256(raw).digest())
        with self._connection(write=True) as db:
            version = _next_version(db, doc, base)
            for block in blocks:
                if block.kind == "figure":
                    block.asset = self._image(db, source, block)
                    manifest_hash.update(bytes.fromhex(block.asset))
            digest = manifest_hash.digest()
            row = db.execute("SELECT id FROM manifests WHERE digest=?", (digest,)).fetchone()
            if row:
                manifest = row[0]
            else:
                manifest = db.execute("INSERT INTO manifests(digest,tail) VALUES(?,?)", (digest, tail)).lastrowid
                for ordinal, block in enumerate(blocks, 1):
                    db.execute(
                        "INSERT INTO blocks VALUES(?,?,?,?,?,?)",
                        (manifest, ordinal, block.kind, _body_id(db, block.source), block.gap, block.asset),
                    )
            _record_version(db, doc, version, title, manifest)
            return version

    def restore(self, doc: str, version: int, base: int | None = None) -> int:
        _integer(version, "要回溯的版本", 1)
        with self._connection(write=True) as db:
            old = _get_version(db, doc, version)
            new = _next_version(db, doc, base)
            _record_version(db, doc, new, old["title"], old["manifest"])
            return new

    def list_docs(self):
        with self._connection() as db:
            return [dict(row) for row in db.execute("""
                SELECT v.doc AS id,v.title,v.version FROM versions v
                JOIN (SELECT doc,MAX(version) AS version FROM versions GROUP BY doc) latest
                USING (doc,version) ORDER BY v.doc
            """)]

    def history(self, doc):
        with self._connection() as db:
            _get_version(db, doc, None)
            return [dict(row) for row in db.execute("""
                SELECT version,title,created,(SELECT COUNT(*) FROM notes n WHERE n.doc=v.doc
                    AND n.version=v.version AND n.note!='') AS notes
                FROM versions v WHERE doc=? ORDER BY version DESC
            """, (doc,))]

    @staticmethod
    def _blocks(db, row, annotated_only=False):
        query = """
            SELECT b.ordinal AS id,b.kind,b.asset,t.payload,t.compressed,
                   COALESCE(n.note,'') AS note,COALESCE(n.rev,0) AS rev
            FROM blocks b JOIN bodies t ON t.id=b.body
            LEFT JOIN notes n ON n.doc=? AND n.version=? AND n.ordinal=b.ordinal
            WHERE b.manifest=?
        """
        if annotated_only:
            query += " AND n.note!=''"
        result = []
        for item in db.execute(query + " ORDER BY b.ordinal", (row["doc"], row["version"], row["manifest"])):
            block = {key: item[key] for key in ("id", "kind", "note", "rev")}
            block["source"] = _unpack(item)
            if item["asset"]:
                block["asset"] = item["asset"]
            result.append(block)
        return result

    def view(self, doc, version=None):
        with self._connection() as db:
            row = _get_version(db, doc, version)
            view = {key: row[key] for key in ("doc", "version", "title", "created")}
            view["blocks"] = self._blocks(db, row)
            return view

    def notes(self, doc, version=None):
        with self._connection() as db:
            return self._blocks(db, _get_version(db, doc, version), annotated_only=True)

    def source(self, doc, version=None, *, pin_images=False):
        with self._connection() as db:
            manifest = _get_version(db, doc, version)["manifest"]
            pieces = []
            for row in db.execute("""
                SELECT b.gap,b.asset,t.payload,t.compressed FROM blocks b JOIN bodies t ON b.body=t.id
                WHERE b.manifest=? ORDER BY b.ordinal
            """, (manifest,)):
                body = _unpack(row)
                if pin_images and row["asset"]:
                    match = _IMAGE.fullmatch(body)
                    start, end = match.span(1 if match[1] is not None else 2)
                    body = body[:start] + "dochelper-asset:" + row["asset"] + body[end:]
                pieces.extend([row["gap"], body])
            pieces.append(db.execute("SELECT tail FROM manifests WHERE id=?", (manifest,)).fetchone()[0])
            return "".join(pieces)

    def asset(self, digest):
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise KeyError("无效图片 ID")
        with self._connection() as db:
            row = db.execute("SELECT mime,payload FROM assets WHERE digest=?", (digest,)).fetchone()
            if row is None:
                raise KeyError("找不到图片")
            return row["mime"], row["payload"]

    def save_note(self, doc, version, block, text, rev):
        _integer(version, "版本", 1)
        _integer(block, "内容块编号", 1)
        _integer(rev, "批注修订号", 0)
        if not isinstance(text, str):
            raise ValueError("批注须为文本")
        if not text.strip():
            text = ""
        with self._connection(write=True) as db:
            manifest = _get_version(db, doc, version)["manifest"]
            if not db.execute("SELECT 1 FROM blocks WHERE manifest=? AND ordinal=?", (manifest, block)).fetchone():
                raise KeyError(f"找不到内容块 {block}")
            key = (doc, version, block)
            row = db.execute("SELECT rev FROM notes WHERE doc=? AND version=? AND ordinal=?", key).fetchone()
            current = row[0] if row else 0
            if rev != current:
                raise Conflict(f"批注已更新，当前修订号为 {current}")
            db.execute("""
                INSERT INTO notes VALUES(?,?,?,?,?) ON CONFLICT (doc,version,ordinal)
                DO UPDATE SET note=excluded.note,rev=excluded.rev
            """, (*key, text, current + 1))
            return {"note": text, "rev": current + 1}
