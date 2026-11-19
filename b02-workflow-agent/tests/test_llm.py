from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.adapters import RequirementGateway
from backend.llm import LLMConfig, OpenAICompatibleClient


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class LlmAdapterTests(unittest.TestCase):
    def test_openai_compatible_json_response_is_parsed(self):
        client = OpenAICompatibleClient(LLMConfig(base_url="https://example.test", model="demo", api_key="secret", enabled=True))
        payload = {"choices": [{"message": {"content": '{"requirements": []}'}}]}
        with patch("backend.llm.urlopen", return_value=FakeResponse(payload)):
            self.assertEqual({"requirements": []}, client.complete_json(system="system", user="user"))

    def test_public_config_never_exposes_api_key(self):
        client = OpenAICompatibleClient(LLMConfig(api_key="secret", enabled=True))
        public = client.config.public()
        self.assertTrue(public["key_configured"])
        self.assertNotIn("secret", json.dumps(public))

    def test_local_fallback_changes_requirements_by_idea(self):
        gateway = RequirementGateway(OpenAICompatibleClient(LLMConfig(enabled=False)))
        common = {"constraints": "", "problem": "", "proposal_draft": "", "claims": [], "objections": [], "open_questions": [], "decisions": []}
        chat = gateway.prepare_draft({**common, "idea": "我想制作一个聊天社交系统"})
        lost = gateway.prepare_draft({**common, "idea": "我想制作一个校园失物招领系统"})
        self.assertNotEqual(
            [item["description"] for item in chat["requirements"]],
            [item["description"] for item in lost["requirements"]],
        )
        self.assertNotEqual(len(chat["requirements"]), len(lost["requirements"]))
        self.assertEqual("local-heuristic", chat["generation_source"])
        self.assertEqual("local-heuristic", lost["generation_source"])


if __name__ == "__main__":
    unittest.main()
