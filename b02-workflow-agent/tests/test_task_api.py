"""B02 任务编排 HTTP 接口测试（D15/D16）。

使用真实 HTTP 服务器（临时目录 + 随机端口 + 临时任务库），验证：
路由、状态码、事件绑定字段、DAG 结构与回放一致性。
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from backend.app import ApplicationService, RequestHandler  # noqa: E402

PLAN_FIXTURE = REPO / "b01-spec-planner" / "docs" / "fixtures" / "campus-lost-found.plan.json"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TaskApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        base = Path(cls.temporary.name)
        cls.plan = json.loads(PLAN_FIXTURE.read_text(encoding="utf-8"))
        RequestHandler.service = ApplicationService(base / "root", base / "task.db")
        cls.port = free_port()
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), RequestHandler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temporary.cleanup()

    def call(self, method: str, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8") or "{}")

    # ---------- 计划 ----------

    def test_load_plan_and_list(self):
        status, body = self.call("POST", "/api/task-plans/load", {"plan": self.plan})
        self.assertEqual(status, 201)
        plan = body["plan"]
        self.assertEqual(plan["plan_version"], self.plan["plan_version"])
        self.assertEqual(plan["task_count"], len(self.plan["tasks"]))
        self.assertIn("input_snapshot", plan)
        listed = self.call("GET", "/api/task-plans")[1]["plans"]
        self.assertTrue(any(item["plan_id"] == plan["plan_id"] for item in listed))
        self.assertEqual(self.call("GET", f"/api/task-plans/{plan['plan_id']}")[0], 200)

    def test_load_plan_by_path(self):
        relative = PLAN_FIXTURE.relative_to(REPO).as_posix()
        status, body = self.call("POST", "/api/task-plans/load", {"plan_path": relative})
        self.assertEqual(status, 201)
        self.assertEqual(body["plan"]["plan_version"], self.plan["plan_version"])

    def test_load_plan_rejects_empty_payload(self):
        self.assertEqual(self.call("POST", "/api/task-plans/load", {})[0], 400)

    def test_load_plan_rejects_unknown_path(self):
        status, _ = self.call("POST", "/api/task-plans/load", {"plan_path": "docs/nope.json"})
        self.assertEqual(status, 400)

    def test_load_plan_rejects_cyclic_plan(self):
        broken = json.loads(json.dumps(self.plan))
        broken["plan_version"] = "PLAN-campus-lost-found-v9.9"
        ids = [task["task_id"] for task in broken["tasks"]]
        broken["tasks"][0]["depends_on"] = [ids[-1]]
        status, body = self.call("POST", "/api/task-plans/load", {"plan": broken})
        self.assertEqual(status, 400)
        self.assertIn("环", body["error"])

    def test_design_spec_creates_plan_and_run(self):
        relative = (REPO / "b01-spec-planner" / "docs" / "fixtures" / "lab-equipment-loan.spec.md").relative_to(REPO).as_posix()
        status, body = self.call(
            "POST",
            "/api/task-runs/from-spec",
            {"spec_path": relative, "run_id": "TASK-RUN-SPEC-INPUT"},
        )
        self.assertEqual(status, 201)
        self.assertGreater(body["plan"]["task_count"], 0)
        self.assertEqual("TASK-RUN-SPEC-INPUT", body["run"]["run_id"])
        self.assertEqual(body["plan"]["plan_id"], body["run"]["plan_id"])
        status, second = self.call(
            "POST",
            "/api/task-runs/from-spec",
            {"spec_path": relative, "run_id": "TASK-RUN-SPEC-INPUT-2"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["plan"]["plan_id"], second["plan"]["plan_id"])

    def test_phase_one_r1_can_create_phase_two_run(self):
        discussion = RequestHandler.service.controller.create_run("制作一个通用协作系统")
        discussion = RequestHandler.service.controller.run_until_control_point(discussion["run_id"])
        RequestHandler.service.controller.confirm_requirements(discussion["run_id"], [
            "成员 A", "成员 B", "成员 C", "成员 D", "成员 E", "成员 F",
        ])
        status, body = self.call("GET", f"/api/runs/{discussion['run_id']}/design-spec")
        self.assertEqual(status, 200)
        self.assertEqual(discussion["run_id"], body["design_spec"]["phase1_source"]["run_id"])

        status, phase_two = self.call(
            "POST",
            "/api/task-runs/from-discussion",
            {"discussion_run_id": discussion["run_id"], "run_id": "TASK-RUN-FROM-R1"},
        )
        self.assertEqual(status, 201)
        self.assertEqual("TASK-RUN-FROM-R1", phase_two["run"]["run_id"])
        self.assertEqual(discussion["run_id"], phase_two["source"]["phase1_source"]["run_id"])
        self.assertRegex(phase_two["plan"]["plan_version"], r"^PLAN-[A-Za-z0-9._-]+-v[0-9]+\.[0-9]+$")

    def test_get_unknown_plan_is_404(self):
        self.assertEqual(self.call("GET", "/api/task-plans/PLAN-missing-v1.0")[0], 404)

    def test_repeated_phase_bridge_advances_to_a_free_plan_version(self):
        """同一项目多次桥接时，plan_version 必须推进到未被占用的版本。

        回归：早期实现只调用一次 next_plan_version，第二次桥接会撞上已被占用的
        v1.1，register_plan 抛 VersionConflict → HTTP 409，课堂演示的第二次运行必然失败。
        """
        versions: list[str] = []
        for index in range(3):
            idea = f"第 {index + 1} 次桥接演示"
            discussion = RequestHandler.service.controller.create_run(idea)
            RequestHandler.service.controller.run_until_control_point(discussion["run_id"])
            RequestHandler.service.controller.confirm_requirements(discussion["run_id"], [
                "成员 A", "成员 B", "成员 C", "成员 D", "成员 E", "成员 F",
            ])
            status, body = self.call(
                "POST",
                "/api/task-runs/from-discussion",
                {
                    "discussion_run_id": discussion["run_id"],
                    "run_id": f"TASK-RUN-REPEAT-{index + 1}",
                },
            )
            self.assertEqual(status, 201, body)
            versions.append(body["plan"]["plan_version"])

        self.assertEqual(len(set(versions)), 3, f"plan_version 重复: {versions}")

    # ---------- 运行 ----------

    def _start_run(self, run_id: str):
        plan_id = self.call("POST", "/api/task-plans/load", {"plan": self.plan})[1]["plan"]["plan_id"]
        status, body = self.call("POST", "/api/task-runs", {"plan_id": plan_id, "run_id": run_id})
        self.assertEqual(status, 201)
        return plan_id, body["run"]

    def test_run_lifecycle_and_replay(self):
        _, run = self._start_run("TASK-RUN-T01")
        roots = sum(1 for task in self.plan["tasks"] if not task["depends_on"])
        self.assertEqual(run["status"], "RUNNING")
        self.assertEqual(run["total"], len(self.plan["tasks"]))
        # 无依赖的任务直接 READY，其余等待依赖。
        self.assertEqual(run["counts"]["READY"], roots)
        self.assertEqual(run["counts"]["WAITING_DEPENDENCY"], len(self.plan["tasks"]) - roots)

        status, stepped = self.call("POST", f"/api/task-runs/{run['run_id']}/step")
        self.assertEqual(status, 200)
        self.assertEqual(len(stepped["dispatched"]), 1)
        self.assertTrue(stepped["transitions"])

        status, body = self.call("POST", f"/api/task-runs/{run['run_id']}/run", {"max_steps": 200})
        self.assertEqual(status, 200)
        self.assertEqual(body["run"]["status"], "SUCCEEDED")
        self.assertEqual(body["run"]["completed"], body["run"]["total"])

        replayed = self.call("POST", f"/api/task-runs/{run['run_id']}/replay")[1]["replay"]
        self.assertTrue(replayed["consistent"])
        self.assertEqual(replayed["mismatches"], [])

        restored = self.call("GET", f"/api/task-runs/{run['run_id']}/restore")[1]["restore"]
        self.assertEqual(len(restored["completed_tasks"]), body["run"]["total"])
        self.assertEqual(restored["resumable_tasks"], [])

    def test_events_are_bound_to_attempt_and_versions(self):
        _, run = self._start_run("TASK-RUN-T02")
        self.call("POST", f"/api/task-runs/{run['run_id']}/run", {"max_steps": 200})
        events = self.call("GET", f"/api/task-runs/{run['run_id']}/events?limit=5000")[1]["events"]
        self.assertTrue(events)
        sequences = [event["sequence"] for event in events]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(len(sequences), len(set(sequences)))
        bound = {
            "TASK_DISPATCHED", "TASK_STARTED", "TASK_OUTPUT_SUBMITTED", "TASK_REVIEW_REQUESTED",
            "TASK_ACCEPTED", "TASK_REJECTED", "TASK_RETRY_SCHEDULED", "TASK_BLOCKED",
            "TASK_COMPLETED", "TASK_FAILED",
        }
        for event in events:
            self.assertEqual(event["run_id"], run["run_id"])
            self.assertEqual(event["plan_version"], run["plan_version"])
            self.assertEqual(event["input_snapshot"], run["input_snapshot"])
            if event["type"] in bound:
                self.assertIsNotNone(event["task_id"], event)
                self.assertIsNotNone(event["attempt_id"], event)
            if event["type"] in ("TASK_OUTPUT_SUBMITTED", "TASK_ACCEPTED"):
                self.assertTrue(event["candidate_commit"], event)

    def test_event_cursor_pagination(self):
        _, run = self._start_run("TASK-RUN-T03")
        self.call("POST", f"/api/task-runs/{run['run_id']}/run", {"max_steps": 200})
        first = self.call("GET", f"/api/task-runs/{run['run_id']}/events?limit=3")[1]["events"]
        self.assertEqual(len(first), 3)
        cursor = first[-1]["sequence"]
        rest = self.call("GET", f"/api/task-runs/{run['run_id']}/events?after={cursor}")[1]["events"]
        self.assertTrue(all(event["sequence"] > cursor for event in rest))

    def test_dag_shape(self):
        _, run = self._start_run("TASK-RUN-T04")
        status, body = self.call("GET", f"/api/task-runs/{run['run_id']}/dag")
        self.assertEqual(status, 200)
        dag = body["dag"]
        self.assertEqual(len(dag["nodes"]), run["total"])
        self.assertEqual(
            len(dag["edges"]),
            sum(len(task["depends_on"]) for task in self.plan["tasks"]),
        )
        node = dag["nodes"][0]
        for field in ("id", "label", "block_id", "state", "attempt_id", "retry_count", "acceptance", "required_test_ids"):
            self.assertIn(field, node)
        for edge in dag["edges"]:
            self.assertIn(edge["from"], {item["id"] for item in dag["nodes"]})
            self.assertIn("revalidation", edge)

    def test_duplicate_run_is_conflict(self):
        plan_id, run = self._start_run("TASK-RUN-T05")
        status, _ = self.call("POST", "/api/task-runs", {"plan_id": plan_id, "run_id": run["run_id"]})
        self.assertEqual(status, 409)

    def test_run_without_plan_id_is_bad_request(self):
        self.assertEqual(self.call("POST", "/api/task-runs", {})[0], 400)

    def test_unknown_run_is_404(self):
        self.assertEqual(self.call("GET", "/api/task-runs/TASK-RUN-NOPE")[0], 404)

    def test_invalid_max_steps_is_bad_request(self):
        _, run = self._start_run("TASK-RUN-T06")
        self.assertEqual(self.call("POST", f"/api/task-runs/{run['run_id']}/run", {"max_steps": 0})[0], 400)

    def test_invalid_event_limit_is_bad_request(self):
        _, run = self._start_run("TASK-RUN-T07")
        status, _ = self.call("GET", f"/api/task-runs/{run['run_id']}/events?limit=999999")
        self.assertEqual(status, 400)

    def test_health_reports_both_controllers(self):
        status, body = self.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertIn("discussion_controller", body["controllers"])
        self.assertIn("task_orchestrator", body["controllers"])
        self.assertEqual(body["task_api"]["execution_mode"], "mock")

    # ---------- 跨源（B05 在不同端口） ----------

    def _raw(self, method: str, path: str, origin: str | None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            method=method,
            headers={"Origin": origin} if origin else {},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.headers

    def test_cors_allows_local_origins(self):
        _, run = self._start_run("TASK-RUN-CORS")
        for origin in ("http://127.0.0.1:4321", "http://localhost:5173"):
            status, headers = self._raw("GET", f"/api/task-runs/{run['run_id']}", origin)
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("Access-Control-Allow-Origin"), origin)
            self.assertIn("GET", headers.get("Access-Control-Allow-Methods", ""))

    def test_cors_rejects_foreign_origin(self):
        _, headers = self._raw("GET", "/api/health", "https://evil.example.com")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_options_preflight_is_handled(self):
        status, headers = self._raw("OPTIONS", "/api/task-runs", "http://127.0.0.1:4321")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:4321")
        self.assertIn("POST", headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("Content-Type", headers.get("Access-Control-Allow-Headers", ""))


if __name__ == "__main__":
    unittest.main()
