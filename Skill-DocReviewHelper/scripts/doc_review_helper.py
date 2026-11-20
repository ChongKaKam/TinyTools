#!/usr/bin/env python3
"""DocReviewHelper command-line interface. Run from the document's agent workspace."""

import argparse
import errno
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlencode

# The skill may be installed outside the user's workspace, including read-only mounts.
sys.dont_write_bytecode = True

from review_server import serve
from review_store import Conflict, Store


def version_option(parser):
    parser.add_argument("--version", type=int, help="版本号，默认使用最新版")


def base_option(parser):
    parser.add_argument("--base", type=int, help="预期的最新版本号，首次发布为 0；不匹配则取消")


def arguments():
    parser = argparse.ArgumentParser(description="管理当前工作目录的 HTML 文档审阅与版本")
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish", help="将 Markdown 发布为新的审阅版本")
    publish.add_argument("doc", help="稳定的文档 ID")
    publish.add_argument("source", type=Path, help="工作目录中的 UTF-8 Markdown 文件")
    publish.add_argument("--title", help="指定页面标题")
    base_option(publish)
    commands.add_parser("list", help="列出工作目录中的审阅文档")
    history = commands.add_parser("history", help="列出版本和各版本的标注数")
    history.add_argument("doc")
    notes = commands.add_parser("notes", help="读取指定版本的非空标注及原文")
    notes.add_argument("doc")
    version_option(notes)
    source = commands.add_parser("source", help="将指定版本的 Markdown 原文写到标准输出")
    source.add_argument("doc")
    version_option(source)
    source.add_argument("--pin-images", action="store_true", help="使用库中已保存的图片，可在工作目录内任意位置修订")
    find = commands.add_parser("find", help="按字面关键词返查历史正文和标注")
    find.add_argument("doc")
    find.add_argument("query")
    find.add_argument("--version", type=int, help="指定检索的版本，默认检索所有版本")
    restore = commands.add_parser("restore", help="从旧版本创建新的审阅版本")
    restore.add_argument("doc")
    restore.add_argument("version", type=int)
    base_option(restore)
    reader = commands.add_parser("serve", help="启动本机 HTML 审阅页面")
    reader.add_argument("--port", type=int, default=8765, help="默认 8765；0 表示自动分配")
    reader.add_argument("--doc", help="在启动链接中定位文档")
    version_option(reader)
    reader.add_argument("--theme", default="folio", help="审阅页面的默认主题 ID")
    return parser.parse_args()


def matches(store, doc, query, version):
    if not query.strip():
        raise ValueError("请输入检索词")
    versions = [version] if version is not None else [v["version"] for v in store.history(doc)]
    for number in versions:
        for block in store.view(doc, number)["blocks"]:
            fields = [key for key in ("source", "note") if query.casefold() in block[key].casefold()]
            if fields:
                anchor = "?" + urlencode({"doc": doc, "version": number}) + f"#block-{block['id']}"
                yield {"version": number, "block": block["id"], "kind": block["kind"],
                       "matched": fields, "source": block["source"], "note": block["note"], "link": "/" + anchor}


def main():
    args = arguments()
    workspace = Path.cwd().resolve()
    store = Store(workspace)
    if args.command == "publish":
        version = store.publish(args.doc, args.source, title=args.title, base=args.base)
        result = {"doc": args.doc, "version": version}
    elif args.command == "restore":
        version = store.restore(args.doc, args.version, base=args.base)
        result = {"doc": args.doc, "version": version, "restored_from": args.version}
    elif args.command == "list":
        result = store.list_docs()
    elif args.command == "history":
        result = store.history(args.doc)
    elif args.command == "notes":
        result = store.notes(args.doc, args.version)
    elif args.command == "source":
        data = store.source(args.doc, args.version, pin_images=args.pin_images)
        sys.stdout.buffer.write(data.encode("utf-8"))
        return
    elif args.command == "find":
        result = list(matches(store, args.doc, args.query, args.version))
    else:
        if not 0 <= args.port <= 65535:
            raise ValueError("端口号需要在 0 到 65535 之间")
        serve(store, workspace, args.port, args.doc, args.version, args.theme)
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (Conflict, KeyError, ValueError, OSError, sqlite3.Error) as error:
        message = str(error)
        if isinstance(error, OSError) and error.errno == errno.EADDRINUSE:
            message += "；可用 serve --port 0 选择空闲端口。"
        sys.exit(f"DocReviewHelper: {message}")
