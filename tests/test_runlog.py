from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

from halyk_agent.runlog import JsonlRunLogger, RecordingTransport


class FakeTransport:
    def post_json(self, url, headers, payload, timeout):
        return {"id": "response-1", "echo": payload}


class RunLogTests(unittest.TestCase):
    def test_records_ordered_request_and_response_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            logger = JsonlRunLogger(Path(temporary))
            transport = RecordingTransport(FakeTransport(), logger, "openai")
            transport.set_context(scenario="P1", attempt=1)
            response = transport.post_json(
                "https://example.test/responses",
                {
                    "Authorization": "Bearer real-secret",
                    "Content-Type": "application/json",
                },
                {"input": "hello"},
                30,
            )

            self.assertEqual(response["id"], "response-1")
            request = json.loads(
                (Path(temporary) / "api" / "0001-request.json").read_text(
                    encoding="utf-8"
                )
            )
            recorded_response = json.loads(
                (Path(temporary) / "api" / "0001-response.json").read_text(
                    encoding="utf-8"
                )
            )
            events = [
                json.loads(line)
                for line in (Path(temporary) / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

            self.assertEqual(request["headers"]["Authorization"], "[REDACTED]")
            self.assertNotIn("real-secret", json.dumps(request))
            self.assertEqual(recorded_response["body"]["id"], "response-1")
            self.assertEqual([event["sequence"] for event in events], [1, 2])
            self.assertEqual(
                [event["event"] for event in events],
                ["api_request", "api_response"],
            )

    def test_concurrent_transports_keep_unique_request_ids_and_valid_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            logger = JsonlRunLogger(Path(temporary))

            def send(index: int) -> None:
                transport = RecordingTransport(FakeTransport(), logger, "anthropic")
                transport.set_context(scenario=f"P{index}", attempt=1)
                transport.post_json(
                    "https://example.test/messages",
                    {"x-api-key": "real-secret"},
                    {"index": index},
                    30,
                )

            with ThreadPoolExecutor(max_workers=7) as executor:
                list(executor.map(send, range(1, 13)))

            api_dir = Path(temporary) / "api"
            requests = sorted(api_dir.glob("*-request.json"))
            responses = sorted(api_dir.glob("*-response.json"))
            events = [
                json.loads(line)
                for line in (Path(temporary) / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

            self.assertEqual(len(requests), 12)
            self.assertEqual(len(responses), 12)
            self.assertEqual(len({path.name[:4] for path in requests}), 12)
            self.assertEqual([event["sequence"] for event in events], list(range(1, 25)))
            self.assertTrue(all("elapsed_minutes" in json.loads(path.read_text(encoding="utf-8")) for path in responses))


if __name__ == "__main__":
    unittest.main()
