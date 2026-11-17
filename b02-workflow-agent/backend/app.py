from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .adapters import MEMBERS
from .controller import DiscussionController
from .errors import WorkflowError
from .exporter import export_run
from .store import BlackboardStore
from .websocket import WorkflowEventHub, WebSocketClient, serve_websocket, websocket_accept
from .workflow_definition import PSEUDOCODE, STAGES, TRANSITIONS


class ApplicationService:
    def __init__(self, root: Path):
        self.root = root
        self.events = WorkflowEventHub()
        self.controller = DiscussionController(BlackboardStore(root / "data"), on_event=self.events.publish)


class RequestHandler(BaseHTTPRequestHandler):
    service: ApplicationService

    def _json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise WorkflowError("请求内容过大。", 413)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as error:
            raise WorkflowError("请求必须是合法 JSON。") from error

    def _error(self, error: Exception) -> None:
        if isinstance(error, WorkflowError):
            self._json({"error": str(error)}, error.status)
        else:
            self._json({"error": f"{type(error).__name__}: {error}"}, 500)

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            service = self.service
            if path == "/api/health":
                self._json({"status": "ok", "block": "B02", "role": "WorkflowAgent", "controller": "discussion_controller", "websocket": "/ws/runs/{run_id}"})
                return
            if path == "/api/workflow":
                self._json({"stages": STAGES, "transitions": TRANSITIONS, "pseudocode": PSEUDOCODE, "members": MEMBERS})
                return
            if path == "/api/runs":
                self._json({"runs": service.controller.store.list()})
                return
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[:2] == ["ws", "runs"]:
                self._websocket(parts[2])
                return
            if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                self._json({"run": service.controller.get(parts[2])})
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "replay":
                self._json({"replay": service.controller.replay(parts[2])})
                return
            if path.startswith("/api/"):
                self._json({"error": "API endpoint not found"}, 404)
                return
            self._static(path)
        except Exception as error:
            self._error(error)

    def _websocket(self, run_id: str) -> None:
        if self.headers.get("Upgrade", "").lower() != "websocket":
            raise WorkflowError("该地址需要 WebSocket Upgrade 连接。")
        client_key = self.headers.get("Sec-WebSocket-Key", "")
        if not client_key:
            raise WorkflowError("WebSocket 握手缺少 Sec-WebSocket-Key。")
        run = self.service.controller.get(run_id)
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", websocket_accept(client_key))
        self.end_headers()
        self.close_connection = True
        serve_websocket(WebSocketClient(self.connection, self.rfile), self.service.events, run)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            payload = self._payload()
            controller = self.service.controller
            if path == "/api/runs":
                run = controller.create_run(str(payload.get("idea") or ""), str(payload.get("constraints") or ""), str(payload.get("scenario") or "normal"), int(payload.get("max_rounds") or 2))
                self._json({"run": run}, 201)
                return
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "runs"]:
                run_id, action = parts[2], parts[3]
                if action == "step":
                    run = controller.step(run_id)
                elif action == "until-control-point":
                    run = controller.run_until_control_point(run_id)
                elif action == "pause":
                    run = controller.pause(run_id)
                elif action == "resume":
                    run = controller.resume(run_id)
                elif action == "human-decision":
                    run = controller.resolve_human_decision(run_id, str(payload.get("decision") or ""))
                elif action == "confirm":
                    run = controller.confirm_requirements(run_id, payload.get("members") or [])
                elif action == "export":
                    run = controller.get(run_id)
                    self._json(export_run(run, controller.replay(run_id), str(payload.get("format") or "json")))
                    return
                else:
                    self._json({"error": "API endpoint not found"}, 404)
                    return
                self._json({"run": run})
                return
            self._json({"error": "API endpoint not found"}, 404)
        except Exception as error:
            self._error(error)

    def _static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        if relative not in ("index.html", "styles.css", "app.js", "favicon.svg"):
            self._json({"error": "Resource not found"}, 404)
            return
        file_path = self.service.root / "static" / relative
        body = file_path.read_bytes()
        self.send_response(200)
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string: str, *args) -> None:
        print(f"[HTTP] {self.address_string()} {format_string % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="B02 WorkflowAgent · discussion_controller")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7100)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    RequestHandler.service = ApplicationService(root)
    server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    server.daemon_threads = True
    print(f"B02 WorkflowAgent: http://{args.host}:{args.port}/")
    print(f"Project root: {root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
