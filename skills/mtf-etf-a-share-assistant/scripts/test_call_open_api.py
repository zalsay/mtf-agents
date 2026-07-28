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
            prediction_type="mtf-pro",
            horizon_len=7,
            context_len=512,
            predict_date="2026-07-28",
            prefer_cache=True,
        )

        method, path, params, payload = call_open_api.command_to_request(args)

        self.assertEqual("POST", method)
        self.assertEqual("/api/open/v1/mtf/predict-once", path)
        self.assertIsNone(params)
        self.assertTrue(payload["prefer_cache"])
        self.assertEqual("2026-07-28", payload["predict_date"])
        self.assertNotIn("best_max_age_days", payload)

    def test_future_query_targets_requested_cached_date(self):
        args = argparse.Namespace(
            command="mtf-future",
            unique_key="515880_best_hlen_7_clen_2048_v_2.5_mtf-pro",
            predict_date="2026-07-28",
        )

        method, path, params, payload = call_open_api.command_to_request(args)

        self.assertEqual("GET", method)
        self.assertEqual("/api/open/v1/mtf/future", path)
        self.assertEqual(
            {
                "unique_key": "515880_best_hlen_7_clen_2048_v_2.5_mtf-pro",
                "predict_date": "2026-07-28",
            },
            params,
        )
        self.assertIsNone(payload)

    def test_predict_commands_default_to_context_len_512(self):
        parser = call_open_api.build_parser()

        args = parser.parse_args([
            "mtf-predict-once",
            "--stock-code", "510300",
        ])

        self.assertEqual(512, args.context_len)
        self.assertEqual("mtf-pro", args.prediction_type)
        self.assertEqual(7, args.horizon_len)

    def test_v2_commands_reject_unsupported_horizon(self):
        parser = call_open_api.build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args([
                "mtf-v2-predict-once",
                "--stock-code", "510300",
                "--horizon-len", "7",
            ])

    def test_v2_commands_accept_extended_horizon(self):
        parser = call_open_api.build_parser()
        args = parser.parse_args([
            "mtf-v2-predict-once",
            "--stock-code", "510300",
            "--horizon-len", "16",
        ])

        _, _, _, payload = call_open_api.command_to_request(args)
        self.assertEqual(16, payload["horizon_len"])

    def test_v2_best_command_uses_aggregate_endpoint_and_supported_defaults(self):
        parser = call_open_api.build_parser()
        args = parser.parse_args([
            "mtf-v2-best",
            "--symbol", "510300",
        ])

        method, path, params, payload = call_open_api.command_to_request(args)

        self.assertEqual("GET", method)
        self.assertEqual("/api/open/v2/mtf/best/by-config", path)
        self.assertEqual(
            {"symbol": "510300", "stock_type": 2, "horizon_len": 8, "context_len": None},
            params,
        )
        self.assertIsNone(payload)

    def test_v2_predict_once_uses_v2_endpoint_and_pro_payload(self):
        parser = call_open_api.build_parser()
        args = parser.parse_args([
            "mtf-v2-predict-once",
            "--stock-code", "510300",
            "--horizon-len", "8",
            "--context-len", "1024",
            "--predict-date", "2026-07-28",
            "--prefer-cache",
        ])

        method, path, params, payload = call_open_api.command_to_request(args)

        self.assertEqual("POST", method)
        self.assertEqual("/api/open/v2/mtf/predict-once", path)
        self.assertIsNone(params)
        self.assertEqual("mtf-pro", payload["prediction_type"])
        self.assertEqual(8, payload["horizon_len"])
        self.assertEqual(1024, payload["context_len"])
        self.assertTrue(payload["prefer_cache"])

    def test_v2_selects_pro_key_and_prefers_largest_context_when_omitted(self):
        response = {
            "data": {
                "symbol": "510300",
                "items": [
                    {
                        "symbol": "510300",
                        "horizon_len": 8,
                        "context_len": 512,
                        "mtf_version": "v_2.5",
                        "mtf_lite_unique_key": "lite-512",
                        "mtf_pro_unique_key": "pro-512",
                    },
                    {
                        "symbol": "510300",
                        "horizon_len": 8,
                        "context_len": 2048,
                        "mtf_version": "v_2.5",
                        "mtf_lite_unique_key": "lite-2048",
                        "mtf_pro_unique_key": "pro-2048",
                    },
                ],
            }
        }

        selected = call_open_api.select_v2_mtf_pro_config(response)

        self.assertEqual("pro-2048", selected["unique_key"])
        self.assertEqual(2048, selected["context_len"])
        self.assertEqual("mtf-pro", selected["prediction_type"])

    def test_v2_can_select_requested_horizon_and_context_without_lite_fallback(self):
        response = {
            "data": {
                "items": [
                    {
                        "symbol": "510300",
                        "horizon_len": 8,
                        "context_len": 1024,
                        "mtf_pro_unique_key": "pro-8-1024",
                    },
                    {
                        "symbol": "510300",
                        "horizon_len": 8,
                        "context_len": 2048,
                        "mtf_lite_unique_key": "lite-8-2048",
                    },
                ]
            }
        }

        selected = call_open_api.select_v2_mtf_pro_config(response, 8, 1024)
        self.assertEqual("pro-8-1024", selected["unique_key"])

        with self.assertRaises(LookupError):
            call_open_api.select_v2_mtf_pro_config(response, 8, 2048)

    def test_v2_future_queries_selected_key_and_requested_date(self):
        parser = call_open_api.build_parser()
        args = parser.parse_args([
            "mtf-v2-future",
            "--symbol", "510300",
            "--context-len", "1024",
            "--predict-date", "2026-07-28",
        ])
        responses = [
            {
                "request_id": "best-req",
                "status": "ok",
                "data": {
                    "symbol": "510300",
                    "items": [{
                        "symbol": "510300",
                        "horizon_len": 8,
                        "context_len": 1024,
                        "mtf_version": "v_2.5",
                        "mtf_pro_unique_key": "pro-8-1024",
                    }],
                },
            },
            {
                "request_id": "future-req",
                "status": "ok",
                "data": {"future_dates": ["2026-07-28"], "predicted_change_percent": [1.2]},
            },
        ]
        captured = []

        def fake_request_json(base_url, api_key, method, path, params=None, payload=None, extra_headers=None):
            captured.append((method, path, params, payload))
            return 200, responses.pop(0)

        with patch.object(call_open_api, "request_json", fake_request_json):
            status, body = call_open_api.request_v2_future(
                "https://example.test", "ftk_test", args,
            )

        self.assertEqual(200, status)
        self.assertEqual("pro-8-1024", body["data"]["unique_key"])
        self.assertEqual(2, len(captured))
        self.assertEqual("/api/open/v2/mtf/best/by-config", captured[0][1])
        self.assertEqual("/api/open/v2/mtf/future", captured[1][1])
        self.assertEqual("2026-07-28", captured[1][2]["predict_date"])
        self.assertEqual("pro-8-1024", captured[1][2]["unique_key"])

    def test_public_key_request_does_not_add_bearer_header(self):
        captured = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"status":"ok","data":{"public_key":"pem"}}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            return FakeResponse()

        with patch.object(call_open_api, "urlopen", fake_urlopen):
            status, body = call_open_api.request_json(
                "https://example.test",
                None,
                "GET",
                "/api/open/v2/auth/public-key",
            )

        self.assertEqual(200, status)
        self.assertEqual("pem", body["data"]["public_key"])
        self.assertEqual("https://example.test/api/open/v2/auth/public-key", captured["url"])
        self.assertNotIn("Authorization", captured["headers"])

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
                "https://go-api.meetlife.com.cn/mtf-service",
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
        self.assertEqual("https://go-api.meetlife.com.cn/mtf-service/api/open/v1/etf/quotes", captured["url"])
        self.assertEqual("Bearer ftk_test", captured["headers"]["Authorization"])
        self.assertEqual("zalsay", captured["headers"]["X-fintrack-user"])
        self.assertEqual("req-test", captured["headers"]["X-request-id"])
        self.assertEqual("application/json", captured["headers"]["Content-type"])
        self.assertEqual(60, captured["timeout"])


if __name__ == "__main__":
    unittest.main()
