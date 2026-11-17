import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.websocket import WorkflowEventHub, encode_frame, websocket_accept


class WebSocketTests(unittest.TestCase):
    def test_rfc6455_handshake_accept(self):
        self.assertEqual("s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", websocket_accept("dGhlIHNhbXBsZSBub25jZQ=="))

    def test_server_frame_lengths(self):
        self.assertEqual(b"\x81\x05hello", encode_frame(b"hello"))
        medium = encode_frame(b"x" * 126)
        self.assertEqual(126, medium[1])
        self.assertEqual(126, int.from_bytes(medium[2:4], "big"))
        large = encode_frame(b"x" * 65_536)
        self.assertEqual(127, large[1])
        self.assertEqual(65_536, int.from_bytes(large[2:10], "big"))

    def test_hub_fans_out_event_and_full_snapshot(self):
        class FakeClient:
            def __init__(self):
                self.messages = []

            def send_json(self, value):
                self.messages.append(value)

        hub = WorkflowEventHub()
        client = FakeClient()
        hub.register("RUN-TEST", client)
        run = {"run_id": "RUN-TEST", "stage": "DIVERGE"}
        event = {"sequence": 2, "type": "IDEA_FRAMED"}
        hub.publish(run, event)
        self.assertEqual(1, hub.client_count("RUN-TEST"))
        self.assertEqual("event", client.messages[0]["type"])
        self.assertIs(run, client.messages[0]["run"])
        hub.unregister("RUN-TEST", client)
        self.assertEqual(0, hub.client_count("RUN-TEST"))


if __name__ == "__main__":
    unittest.main()
