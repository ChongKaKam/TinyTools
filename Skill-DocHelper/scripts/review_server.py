"""Serve the bundled reader and its workspace-local review API on loopback."""

import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from review_store import Conflict


ASSETS = Path(__file__).resolve().parent.parent / "assets"
THEME_ID = re.compile(r"[a-z][a-z0-9-]{0,63}")
STATIC = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/render.js": ("render.js", "text/javascript"),
    "/app.css": ("app.css", "text/css"),
}
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
)


def theme_files(workspace):
    """Workspace styles can add a theme or override a bundled theme of the same id."""
    result = {}
    for directory in (ASSETS / "themes", workspace / ".dochelper" / "themes"):
        if not directory.is_dir() or directory.resolve() != directory:
            continue
        for path in sorted(directory.glob("*.css")):
            if THEME_ID.fullmatch(path.stem) and not path.is_symlink() and path.is_file():
                result[path.stem] = path
    return result


def theme_label(path):
    with path.open(encoding="utf-8") as file:
        match = re.fullmatch(r"/\*\s*(.*?)\s*\*/", file.readline(256).strip())
    return match.group(1) if match and match.group(1) else path.stem


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "DocHelper"

    def log_message(self, fmt, *args):
        # Do not write document identifiers, search strings or annotation data to logs.
        pass

    def send_data(self, status, mime, data, csp=CSP):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD" and data:
            self.wfile.write(data)

    def send_json(self, status, value):
        self.send_data(status, "application/json; charset=utf-8",
                       json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def dispatch(self, action):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            hosts.update(("127.0.0.1", "localhost"))
        host = self.headers.get("Host", "")
        if host not in hosts:
            self.send_json(HTTPStatus.FORBIDDEN, {"error": "请使用服务输出的本机地址。"})
            return
        if self.command == "POST":
            origin = self.headers.get("Origin")
            if ((origin is not None and origin != f"http://{host}") or
                    self.headers.get("Sec-Fetch-Site") == "cross-site"):
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "请从本机审阅页面保存标注。"})
                return
        try:
            action()
        except Conflict as error:
            self.send_json(HTTPStatus.CONFLICT, {"error": str(error)})
        except (KeyError, FileNotFoundError) as error:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": str(error)})
        except (TypeError, ValueError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "读写审阅数据失败，请检查工作目录的权限和可用空间。"})

    def do_GET(self):
        self.dispatch(self.read)

    do_HEAD = do_GET

    def do_POST(self):
        self.dispatch(self.write_note)

    def read(self):
        url = urlsplit(self.path)
        path = url.path
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if path in STATIC:
            name, mime = STATIC[path]
            self.send_data(200, mime + "; charset=utf-8", (ASSETS / name).read_bytes())
            return
        if path == "/api/themes" or path.startswith("/themes/"):
            files = theme_files(self.server.workspace)
            if path == "/api/themes":
                self.send_json(200, {"default": self.server.theme, "themes": [
                    {"id": key, "label": theme_label(file)} for key, file in files.items()
                ]})
            else:
                match = re.fullmatch(r"/themes/([a-z][a-z0-9-]{0,63})\.css", path)
                if not match or match[1] not in files:
                    raise KeyError("未找到该主题")
                self.send_data(200, "text/css; charset=utf-8", files[match[1]].read_bytes())
            return
        store = self.server.store
        if path == "/api/docs":
            self.send_json(200, {"docs": store.list_docs()})
            return
        if path in ("/api/history", "/api/view"):
            query = parse_qs(url.query)
            doc = query.get("doc", [""])[0]
            if not doc:
                raise ValueError("缺少文档 ID")
            if path == "/api/history":
                self.send_json(200, {"versions": store.history(doc)})
            else:
                version = int(query["version"][0]) if "version" in query else None
                self.send_json(200, store.view(doc, version))
            return
        match = re.fullmatch(r"/asset/([0-9a-f]{64})", path)
        if match:
            mime, data = store.asset(match[1])
            self.send_data(200, mime, data, "sandbox; default-src 'none'; style-src 'unsafe-inline'")
            return
        raise KeyError("未找到该资源")

    def write_note(self):
        if urlsplit(self.path).path != "/api/note":
            raise KeyError("未找到该接口")
        if self.headers.get_content_type() != "application/json":
            self.send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "请求需要使用 JSON。"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 2 * 1024 * 1024:
            raise ValueError("标注请求为空或超过 2 MiB")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        fields = {"doc": str, "version": int, "block": int, "text": str, "rev": int}
        if not isinstance(payload, dict) or any(
            type(payload.get(key)) is not kind for key, kind in fields.items()
        ):
            raise ValueError("标注需要文档 ID、版本、块号、内容和修订号")
        result = self.server.store.save_note(payload["doc"], payload["version"], payload["block"],
                                             payload["text"], payload["rev"])
        self.send_json(200, result)


def serve(store, workspace, port, doc, version, theme):
    if theme not in theme_files(workspace):
        raise ValueError(f"找不到主题 {theme}")
    query = {}
    if doc:
        versions = store.history(doc)
        if not versions or (version is not None and version not in {v["version"] for v in versions}):
            raise ValueError("找不到指定文档或版本")
        query["doc"] = doc
        if version is not None:
            query["version"] = version
    elif version is not None:
        raise ValueError("--version 需要同时指定 --doc")
    with ThreadingHTTPServer(("127.0.0.1", port), ReviewHandler) as server:
        server.store, server.workspace, server.theme = store, workspace, theme
        suffix = "?" + urlencode(query) if query else ""
        print(f"http://127.0.0.1:{server.server_port}/{suffix}", flush=True)
        server.serve_forever()
