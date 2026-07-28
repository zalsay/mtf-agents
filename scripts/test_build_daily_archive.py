import unittest
from unittest import mock

import build_daily_archive


class BuildDailyArchiveTests(unittest.TestCase):
    def setUp(self):
        build_daily_archive.NAME_MAP.clear()

    def test_candidates_come_from_etf_hot_items(self):
        response = {
            "data": {
                "items": [
                    {"code": "sh510300", "name": "沪深300ETF"},
                    {"code": "159919", "name": "沪深300ETF基金"},
                    {"code": "000001", "name": "上证指数"},
                    {"code": "600000", "name": "非ETF股票"},
                ]
            }
        }

        candidates = build_daily_archive.get_candidates(response)

        self.assertEqual({"510300": 2, "159919": 2}, candidates)
        self.assertEqual("沪深300ETF", build_daily_archive.get_candidate_name("510300"))
        self.assertEqual("沪深300ETF基金", build_daily_archive.get_candidate_name("159919"))

    def test_candidates_reject_non_list_items(self):
        with self.assertRaises(build_daily_archive.OpenAPIError):
            build_daily_archive.get_candidates({"data": {"items": {}}})

    def test_cache_miss_predicts_and_queries_same_target_date(self):
        calls = []
        future_calls = 0

        def fake_call_api(command, *args):
            nonlocal future_calls
            calls.append((command, args))
            if command == "mtf-v2-future":
                future_calls += 1
                if future_calls == 1:
                    raise build_daily_archive.OpenAPIError(
                        "cache miss",
                        {"error": {"code": "prediction_cache_not_found"}},
                    )
                return {"data": {"future_dates": ["2026-07-24"]}}
            if command == "mtf-v2-best":
                return {
                    "data": {
                        "unique_key": "512800_best_hlen_8_clen_2048_v_2.5_mtf-pro",
                        "horizon_len": 8,
                        "context_len": 2048,
                    }
                }
            if command == "mtf-v2-predict-once":
                return {"status": "accepted"}
            raise AssertionError(command)

        with mock.patch.object(build_daily_archive, "call_api", side_effect=fake_call_api):
            result = build_daily_archive.fetch_mtf_future(
                "2026-07-24",
                "512800",
                stock_type=2,
                horizon_len=8,
                context_len=2048,
                allow_predict=True,
            )

        self.assertEqual(["2026-07-24"], result["future_dates"])
        predict_calls = [args for command, args in calls if command == "mtf-v2-predict-once"]
        self.assertEqual(1, len(predict_calls))
        self.assertIn(("--predict-date", "2026-07-24"), zip(predict_calls[0], predict_calls[0][1:]))
        future_args = [args for command, args in calls if command == "mtf-v2-future"]
        self.assertTrue(all("--predict-date" in args for args in future_args))
        self.assertTrue(all("2026-07-24" in args for args in future_args))


if __name__ == "__main__":
    unittest.main()
