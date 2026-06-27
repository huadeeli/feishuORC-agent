from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orc_calc.ocr.cloud_paddle import CloudPaddleOCRProvider, _parse_official_jsonl  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _FakeRequests:
    def __init__(self, jsonl_text: str) -> None:
        self.jsonl_text = jsonl_text
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return _FakeResponse(200, {"data": {"jobId": "job-1"}})

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if url.endswith("/job-1"):
            return _FakeResponse(200, {"data": {"state": "done", "resultUrl": {"jsonUrl": "https://example.test/out.jsonl"}}})
        return _FakeResponse(200, text=self.jsonl_text)


class CloudPaddleTests(unittest.TestCase):
    def test_missing_token_status_is_not_ready(self) -> None:
        provider = CloudPaddleOCRProvider(token="")
        status = provider.status()
        self.assertFalse(status["cloud_ready"])
        self.assertIn("PADDLEOCR_ACCESS_TOKEN", status["last_cloud_error"])

    def test_parse_official_jsonl_rec_texts(self) -> None:
        jsonl = json.dumps(
            {
                "result": {
                    "ocrResults": [
                        {
                            "prunedResult": {
                                "rec_texts": ["毛重*", "48.29", "代办税额*", "894.05"],
                                "rec_scores": [0.98, 0.99, 0.97, 0.99],
                            }
                        }
                    ]
                }
            },
            ensure_ascii=False,
        )
        lines = _parse_official_jsonl(jsonl)
        self.assertEqual([line.text for line in lines], ["毛重*", "48.29", "代办税额*", "894.05"])

    def test_official_async_flow_uses_job_poll_and_jsonl(self) -> None:
        jsonl = json.dumps(
            {
                "result": {
                    "ocrResults": [
                        {"prunedResult": {"rec_texts": ["结算单价*", "1830"], "rec_scores": [0.96, 0.99]}}
                    ]
                }
            },
            ensure_ascii=False,
        )
        fake_requests = _FakeRequests(jsonl)
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "sample.jpg"
            image_path.write_bytes(b"fake-image")
            provider = CloudPaddleOCRProvider(token="test-token", request_timeout=1, poll_interval=0, max_wait=1)
            with patch("orc_calc.ocr.cloud_paddle._load_requests", return_value=fake_requests):
                lines = provider._recognize_lines(image_path, image_filename="sample.jpg")

        self.assertEqual([line.text for line in lines], ["结算单价*", "1830"])
        self.assertEqual(fake_requests.posts[0][0], "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs")
        self.assertIn("files", fake_requests.posts[0][1])
        self.assertEqual(fake_requests.gets[0][0], "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs/job-1")


if __name__ == "__main__":
    unittest.main()
