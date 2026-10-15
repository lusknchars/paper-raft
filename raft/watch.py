"""raft watch: the flow view on localhost, with live progress from this machine's runs. Nothing goes online."""
import http.server
import json
import threading
import webbrowser
from pathlib import Path

from . import flow, live

TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json"}


def read_progress(study_dir: Path) -> dict:
    out = {}
    for p in sorted((Path(study_dir) / "runs" / ".progress").glob("*.json")):
        try:
            out[p.stem] = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
    return out


def make_server(root: Path, study: str | None, port: int) -> http.server.ThreadingHTTPServer:
    root, static = Path(root).resolve(), flow.template_dir().resolve()
    sd = root / "studies" / study if study else None

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json_or_error(self, make) -> None:
            try:
                body = json.dumps(make()).encode()
            except Exception as e:  # noqa: BLE001 (any failure becomes a readable 500)
                body = json.dumps({"error": f"{type(e).__name__}: {e}"}).encode()
                self.send_response(500)
                self.send_header("Content-Type", TYPES[".json"])
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send(body, TYPES[".json"])

        def do_GET(self):  # noqa: N802 (http.server's name)
            port = self.server.server_address[1]
            if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return self.send_error(403)
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                page = "watch.html" if study else "live.html"
                return self._send((static / "flow" / page).read_bytes(), TYPES[".html"])
            if path == "/live.html":
                return self._send((static / "flow" / "live.html").read_bytes(), TYPES[".html"])
            if path == "/live.json":
                return self._json_or_error(lambda: live.sessions(root, study))
            if path == "/flow.json" and study:
                return self._json_or_error(lambda: flow.build_flow(root, study))
            if path == "/progress.json" and study:
                return self._json_or_error(lambda: read_progress(sd))
            try:
                target = (static / path.lstrip("/")).resolve()
            except (ValueError, OSError):
                return self.send_error(404)
            if target.is_relative_to(static) and target.is_file() and target.suffix in TYPES:
                return self._send(target.read_bytes(), TYPES[target.suffix])
            self.send_error(404)

        def log_message(self, *args):
            pass

    return http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)


def background(root: Path, port: int = 8765, open_browser: bool = True):
    """The live page in a daemon thread for the length of one command; a taken port never stops the run."""
    try:
        srv = make_server(root, None, port)
    except OSError:
        print(f"• live view: port {port} is in use, so it was not started; run `uv run raft watch --port <another>`",
              flush=True)
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"• watch live: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    return srv


def serve(root: Path, study: str | None, port: int, open_browser: bool) -> None:
    try:
        srv = make_server(root, study, port)
    except OSError:
        raise SystemExit(f"raft: port {port} is in use; pass --port <another>")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"✓ watching {study or 'live sessions'} at {url} (local only; Ctrl-C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
