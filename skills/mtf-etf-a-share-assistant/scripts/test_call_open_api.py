#!/usr/bin/env python3
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import call_open_api


class CallOpenApiTests(unittest.TestCase):
    def test_predict_once_matches_contract_payload(self):
        args = argparse.Namespace(
            command="mtf-predict-once",
            stock_code="510300",
            stock_type=2,
            prediction_type="mtf-lite",
            horizon_len=7,
            context_len=256,
            prefer_cache=True,
        )

        method, path, params, payload = call_open_api.command_to_request(args)

        self.assertEqual("POST", method)
        self.assertEqual("/api/open/v1/mtf/predict-once", path)
        self.assertIsNone(params)
        self.assertTrue(payload["prefer_cache"])
        self.assertNotIn("best_max_age_days", payload)

    def test_strategy_save_posts_json_body(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            body_path = Path(tmp_dir) / "strategy.json"
            body_path.write_text(json.dumps({"name": "ETF trend"}), encoding="utf-8")
            args = argparse.Namespace(command="strategy-save", json=f"@{body_path}")

            method, path, params, payload = call_open_api.command_to_request(args)

        self.assertEqual("POST", method)
        self.assertEqual("/api/open/v1/strategy/params", path)
        self.assertIsNone(params)
        self.assertEqual({"name": "ETF trend"}, payload)

    def test_best_by_config_allows_aggregate_lookup(self):
        args = argparse.Namespace(
            command="mtf-best-by-config",
            symbol="510050",
            stock_type=2,
            horizon_len=None,
            context_len=None,
        )

        method, path, params, payload = call_open_api.command_to_request(args)

        self.assertEqual("GET", method)
        self.assertEqual("/api/open/v1/mtf/best/by-config", path)
        self.assertEqual({"symbol": "510050", "stock_type": 2, "horizon_len": None, "context_len": None}, params)
        self.assertIsNone(payload)

    def test_best_by_config_allows_partial_config_filter(self):
        args = argparse.Namespace(
            command="mtf-best-by-config",
            symbol="510050",
            stock_type=2,
            horizon_len=7,
            context_len=None,
        )

        method, path, params, payload = call_open_api.command_to_request(args)

        self.assertEqual("GET", method)
        self.assertEqual("/api/open/v1/mtf/best/by-config", path)
        self.assertEqual({"symbol": "510050", "stock_type": 2, "horizon_len": 7, "context_len": None}, params)
        self.assertIsNone(payload)

    def test_request_json_adds_optional_headers(self):
        captured = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"status":"ok","data":{}}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeResponse()

        with patch.object(call_open_api, "urlopen", fake_urlopen):
            status, body = call_open_api.request_json(
                "https://go-api.meetlife.com.cn:9001",
                "ftk_test",
                "POST",
                "/api/open/v1/etf/quotes",
                payload={"symbols": ["510300"]},
                extra_headers={
                    "X-FinTrack-User": "zalsay",
                    "X-Request-Id": "req-test",
                },
            )

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok", "data": {}}, body)
        self.assertEqual("https://go-api.meetlife.com.cn:9001/api/open/v1/etf/quotes", captured["url"])
        self.assertEqual("Bearer ftk_test", captured["headers"]["Authorization"])
        self.assertEqual("zalsay", captured["headers"]["X-fintrack-user"])
        self.assertEqual("req-test", captured["headers"]["X-request-id"])
        self.assertEqual("application/json", captured["headers"]["Content-type"])
        self.assertEqual(60, captured["timeout"])


if __name__ == "__main__":
    unittest.main()
