from __future__ import annotations

import argparse
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .adapters import MEMBERS, RequirementGateway
from .controller import DiscussionController
from .errors import WorkflowError
from .exporter import export_run
from .phase_bridge import r1_to_design_spec
from .llm import OpenAICompatibleClient
from .store import BlackboardStore
from .task_api import TaskApi
from .websocket import WorkflowEventHub, WebSocketClient, serve_websocket, websocket_accept
from .workflow_definition import PSEUDOCODE, STAGES, TRANSITIONS


class ApplicationService:
    def __init__(self, root: Path, task_root: Path | None = None):
        self.root = root
        self.events = WorkflowEventHub()
        self.llm_client = OpenAICompatibleClient()
        self.controller = DiscussionController(
            BlackboardStore(root / "data"),
            requirements=RequirementGateway(self.llm_client),
            on_event=self.events.publish,
        )
        # 任务编排与讨论流程共用同一 HTTP 服务，但状态存于独立的任务库里。
        self.task_api = TaskApi(task_root or (root / "data" / "task-state.db"))


class RequestHandler(BaseHTTPRequestHandler):
    service: ApplicationService

    # B05 前端运行在不同端口（Vite 5173 / preview 4321），浏览器会做跨源请求。
    # 这里允许任意本机源；服务只监听 127.0.0.1，且不携带 Cookie 凭据。
    CORS_ALLOWED_ORIGIN_PATTERN = re.compile(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$")

    def _cors_origin(self) -> str | None:
        origin = self.headers.get("Origin", "")
        return origin if self.CORS_ALLOWED_ORIGIN_PATTERN.match(origin) else None

    def _send_cors_headers(self) -> None:
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
            self.send_header("Access-Control-Max-Age", "600")

    def _json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        """预检请求：只回 CORS 头，不做任何业务处理。"""
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._send_cors_headers()
        self.end_headers()

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

    def _query(self) -> dict:
        return parse_qs(urlparse(self.path).query)

    def _error(self, error: Exception) -> None:
        if isinstance(error, WorkflowError):
            self._json({"error": str(error)}, error.status)
        elif hasattr(error, "http_status"):
            # B03 领域错误自带 HTTP 映射（VersionConflict=409、NotFound=404 等）。
            self._json({"error": str(error)}, int(getattr(error, "http_status")))
        elif error.__class__.__name__ in ("GatewayError",):
            # B04 执行契约不满足属于客户端请求错误。
            self._json({"error": str(error)}, 400)
        else:
            self._json({"error": f"{type(error).__name__}: {error}"}, 500)

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            query = self._query()
            service = self.service
            if path == "/api/health":
                self._json({"status": "ok", "block": "B02", "role": "WorkflowAgent", "controllers": ["discussion_controller", "task_orchestrator"], "websocket": "/ws/runs/{run_id}", "task_api": service.task_api.describe(), "llm": service.llm_client.config.public()})
                return
            if path == "/api/workflow":
                self._json({"stages": STAGES, "transitions": TRANSITIONS, "pseudocode": PSEUDOCODE, "members": MEMBERS})
                return
            if path == "/api/llm/config":
                self._json({"llm": service.llm_client.config.public()})
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
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "design-spec":
                run = service.controller.get(parts[2])
                self._json({"design_spec": r1_to_design_spec(run), "source_run_id": parts[2]})
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "replay":
                self._json({"replay": service.controller.replay(parts[2])})
                return
            if self._task_get(parts, query):
                return
            if path.startswith("/api/"):
                self._json({"error": "API endpoint not found"}, 404)
                return
            self._static(path)
        except Exception as error:
            self._error(error)

    def _task_get(self, parts: list[str], query: dict[str, list[str]]) -> bool:
        """任务编排只读接口；返回 True 表示已处理。"""
        api = self.service.task_api
        if parts[:2] == ["api", "task-plans"]:
            if len(parts) == 2:
                self._json(api.list_plans())
                return True
            if len(parts) == 3:
                self._json(api.get_plan(parts[2]))
                return True
            return False
        if parts[:2] != ["api", "task-runs"]:
            return False
        if len(parts) == 2:
            self._json(api.list_runs())
            return True
        run_id = parts[2] if len(parts) > 2 else ""
        if len(parts) == 3:
            self._json(api.get_run(run_id))
            return True
        if len(parts) == 4:
            suffix = parts[3]
            if suffix == "events":
                self._json(api.events(run_id, query))
                return True
            if suffix == "dag":
                self._json(api.dag(run_id))
                return True
            if suffix == "restore":
                self._json(api.restore(run_id))
                return True
        return False

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
            if self._task_post(path, payload):
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

    def _task_post(self, path: str, payload: dict) -> bool:
        """任务编排写接口；返回 True 表示已处理。"""
        api = self.service.task_api
        parts = path.strip("/").split("/")
        if path == "/api/llm/config":
            changes = {key: payload[key] for key in ("base_url", "model", "api_key", "timeout_seconds", "enabled") if key in payload}
            if "enabled" in changes:
                changes["enabled"] = bool(changes["enabled"])
            self.service.llm_client.configure(**changes)
            self._json({"llm": self.service.llm_client.config.public()})
            return True
        if path == "/api/task-plans/load":
            self._json(api.load_plan(payload), 201)
            return True
        if path == "/api/task-runs":
            self._json(api.create_run(payload), 201)
            return True
        if path == "/api/task-runs/from-spec":
            self._json(api.create_run_from_spec(payload), 201)
            return True
        if path == "/api/task-runs/from-discussion":
            run = self.service.controller.get(str(payload.get("discussion_run_id") or ""))
            spec = r1_to_design_spec(run)
            self._json(api.create_run_from_spec({
                **payload,
                "spec": spec,
                "source_metadata": spec.get("phase1_source"),
            }), 201)
            return True
        if len(parts) == 3 and parts[:2] == ["api", "task-plans"]:
            return False
        if len(parts) == 4 and parts[:2] == ["api", "task-runs"]:
            run_id, action = parts[2], parts[3]
            if action == "step":
                self._json(api.step(run_id, payload))
                return True
            if action == "run":
                self._json(api.run(run_id, payload))
                return True
            if action == "replay":
                self._json(api.replay(run_id))
                return True
        return False

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
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string: str, *args) -> None:
        print(f"[HTTP] {self.address_string()} {format_string % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="B02 WorkflowAgent · discussion_controller + task_orchestrator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7100)
    parser.add_argument("--task-db", default=None, help="任务编排状态库路径，默认 <root>/data/task-state.db")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    task_db = Path(args.task_db) if args.task_db else root / "data" / "task-state.db"
    RequestHandler.service = ApplicationService(root, task_db)
    server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    server.daemon_threads = True
    print(f"B02 WorkflowAgent: http://{args.host}:{args.port}/")
    print(f"Project root: {root}")
    print(f"Task state db: {task_db}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
