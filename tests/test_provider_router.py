import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from provider_router import generate_story, parse_routing
from providers import ProviderHTTPError


class StoryRoutingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "providers.json"
        self.config = {
            "max_estimated_usd": 0.10,
            "providers": [
                {"name": name, "base_url": f"https://{name}.example/v1",
                 "model": "test", "key_env": "TEST_KEY", "priority": priority,
                 "estimated_usd": 0.05}
                for name, priority in [("secondary", 20), ("primary", 10)]
            ],
        }
        self.story = {"title": "Story", "description": "Description", "story": "Story",
                      "scenes": [{"visual_prompt": "Rain", "dialogue": "", "caption": ""}]}
        self.response = ({"choices": [{"message": {"content": json.dumps(self.story)}}]}, {})
        environment = patch.dict("os.environ", {"TEST_KEY": "fixture"})
        environment.start()
        self.addCleanup(environment.stop)

    def run_router(self):
        self.path.write_text(json.dumps(self.config), encoding="utf-8")
        return generate_story(parse_routing(self.path.read_text(encoding="utf-8")), {"scene_count": 1}, "Return JSON.")

    @patch("provider_router.request")
    def test_primary(self, request):
        request.return_value = self.response
        self.assertEqual(self.run_router(), self.story)
        self.assertIn("primary.example", request.call_args.args[0])

    @patch("provider_router.request")
    def test_manual(self, request):
        self.config.update(policy="manual", manual_provider="secondary")
        request.return_value = self.response
        self.assertEqual(self.run_router(), self.story)
        self.assertIn("secondary.example", request.call_args.args[0])

    @patch("provider_router.request")
    def test_outage_falls_back(self, request):
        request.side_effect = [ProviderHTTPError("primary.example", 503), self.response]
        self.assertEqual(self.run_router(), self.story)
        self.assertIn("secondary.example", request.call_args.args[0])

    @patch("provider_router.request")
    def test_budget_prevents_fallback(self, request):
        self.config["max_estimated_usd"] = 0.05
        request.side_effect = ProviderHTTPError("primary.example", 503)
        with self.assertRaisesRegex(RuntimeError, "estimated budget exceeded"):
            self.run_router()
        self.assertEqual(request.call_count, 1)

    @patch("provider_router.time.sleep")
    @patch("provider_router.request")
    def test_rate_limit_retries(self, request, sleep):
        request.side_effect = [ProviderHTTPError("primary.example", 429, 2), self.response]
        self.assertEqual(self.run_router(), self.story)
        sleep.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
