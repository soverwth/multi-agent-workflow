"""B02/B05 single-port static bundle checks."""

from __future__ import annotations

import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend.app import ApplicationService, RequestHandler


class StaticBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        base = Path(cls.temporary.name)
        cls.frontend = base / "frontend" / "dist"
        (cls.frontend / "assets").mkdir(parents=True)
        (cls.frontend / "index.html").write_text("<main>B05 bundle</main>", encoding="utf-8")
        (cls.frontend / "assets" / "app.js").write_text("console.log('B05');", encoding="utf-8")
        RequestHandler.service = ApplicationService(base / "b02", base / "task.db", cls.frontend)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temporary.cleanup()

    def get(self, path: str):
        try:
            with urllib.request.urlopen(self.base_url + path, timeout=5) as response:
                return response.status, response.headers.get_content_type(), response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get_content_type(), error.read()

    def test_root_and_nested_assets_are_served_by_b02(self):
        status, content_type, body = self.get("/")
        self.assertEqual((200, "text/html"), (status, content_type))
        self.assertIn(b"B05 bundle", body)

        status, content_type, body = self.get("/assets/app.js")
        self.assertEqual((200, "text/javascript"), (status, content_type))
        self.assertIn(b"B05", body)

    def test_spa_route_falls_back_to_b05_index(self):
        status, content_type, body = self.get("/task-runs/demo")
        self.assertEqual((200, "text/html"), (status, content_type))
        self.assertIn(b"B05 bundle", body)

    def test_missing_asset_does_not_fall_back_to_index(self):
        status, _, _ = self.get("/assets/missing.js")
        self.assertEqual(404, status)


if __name__ == "__main__":
    unittest.main()
