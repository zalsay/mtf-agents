#!/usr/bin/env python3
import unittest
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import normalize_mtf_future_archive as normalizer


class NormalizeMTFFutureArchiveTests(unittest.TestCase):
    def test_rebuilds_path_from_actual_base_close_and_trading_dates(self):
        archive = {
            "report_date": "2026-06-22",
            "items": [
                {
                    "symbol": "159259",
                    "name": "易方达国证成长100ETF",
                    "theme": "成长100",
                    "change_base_date": "2026-06-12",
                    "change_base_value": 1.4589,
                    "predicted_change_percent": [1.6432, 20.8726],
                    "price_path": [1.4829, 1.7634],
                    "reference_buy": {"price": 1.4829},
                    "reference_sell": {"price": 1.7634},
                    "latest_close": 1.763,
                }
            ],
        }

        with patch.object(normalizer, "fetch_actual_close", return_value=1.521):
            with patch.object(
                normalizer,
                "future_trading_dates",
                return_value=["2026-06-15", "2026-06-16"],
            ) as future_dates:
                result = normalizer.normalize_archive(archive, fetch_path_actuals=False)

        item = result["items"][0]
        self.assertEqual("close_price_only", result["price_basis"])
        self.assertEqual(
            {
                "date": "2026-06-12",
                "close": 1.521,
                "source": "easy_tdx_qfq_daily_kline",
                "adjust": "QFQ",
                "note": "actual close on base_close.date",
            },
            item["base_close"],
        )
        self.assertEqual("QFQ", result["actual_daily_kline_adjust"])
        self.assertEqual([1.6432, 20.8726], item["expected_change_percent_path"])
        self.assertEqual(
            {
                "step": 1,
                "base_date": "2026-06-12",
                "base_close": 1.521,
                "target_date": "2026-06-15",
                "expected_change_percent": 1.6432,
                "predicted_close": 1.546,
                "actual_close": None,
                "actual_close_source": None,
                "actual_change_percent": None,
                "deviation_percentage_points": None,
                "deviation_status": "actual_unavailable",
            },
            item["predicted_close_path"][0],
        )
        self.assertEqual(1.8385, item["predicted_close_path"][1]["predicted_close"])
        self.assertNotIn("raw_response", item)
        self.assertNotIn("reference_buy", item)
        self.assertNotIn("latest_close", item)
        self.assertNotIn("date", item["predicted_close_path"][0])
        future_dates.assert_called_once_with("2026-06-12", 2, "XSHG")

    def test_prefers_raw_future_dates_over_base_date_calendar(self):
        archive = {
            "items": [
                {
                    "symbol": "515880",
                    "base_close": {"date": "2026-06-12", "close": 1.584},
                    "expected_change_percent_path": [2.1445, 5.2105, 11.015],
                    "raw_response": {
                        "data": {
                            "future_dates": ["2026-06-24", "2026-06-25", "2026-06-26"],
                        }
                    },
                }
            ]
        }

        with patch.object(normalizer, "future_trading_dates") as future_dates:
            result = normalizer.normalize_archive(archive, fetch_actual=False, fetch_path_actuals=False)

        target_dates = [point["target_date"] for point in result["items"][0]["predicted_close_path"]]
        self.assertEqual(["2026-06-24", "2026-06-25", "2026-06-26"], target_dates)
        future_dates.assert_not_called()

    def test_marks_rejected_when_actual_close_is_below_same_day_threshold(self):
        archive = {
            "items": [
                {
                    "symbol": "515220",
                    "base_close": {"date": "2026-06-12", "close": 1.1},
                    "expected_change_percent_path": [20.0],
                    "close_observation": {"date": "2026-06-15", "close": 1.18},
                }
            ]
        }

        with patch.object(
            normalizer,
            "future_trading_dates",
            return_value=["2026-06-15"],
        ):
            result = normalizer.normalize_archive(archive, fetch_actual=False)

        control = result["items"][0]["same_day_deviation_control"]
        self.assertEqual("reject", control["status"])
        self.assertEqual(7.2727, control["actual_change_percent"])
        self.assertEqual(20.0, control["expected_change_percent"])
        self.assertEqual(-12.7273, control["deviation_percentage_points"])
        self.assertFalse(control["adoptable"])
        self.assertFalse(control["buy_allowed"])
        self.assertFalse(control["add_allowed"])
        self.assertTrue(control["clear_if_held"])
        path_point = result["items"][0]["predicted_close_path"][0]
        self.assertEqual(1.18, path_point["actual_close"])
        self.assertEqual(7.2727, path_point["actual_change_percent"])
        self.assertEqual(-12.7273, path_point["deviation_percentage_points"])
        self.assertEqual("reject", path_point["deviation_status"])

    def test_leaves_future_path_point_deviation_blank(self):
        archive = {
            "items": [
                {
                    "symbol": "159259",
                    "base_close": {"date": "2026-06-12", "close": 1.0},
                    "expected_change_percent_path": [5.0, 10.0],
                    "close_observation": {"date": "2026-06-15", "close": 1.04},
                }
            ]
        }

        with patch.object(
            normalizer,
            "future_trading_dates",
            return_value=["2026-06-15", "2026-06-16"],
        ):
            result = normalizer.normalize_archive(archive, fetch_actual=False)

        first, second = result["items"][0]["predicted_close_path"]
        self.assertEqual(4.0, first["actual_change_percent"])
        self.assertEqual(-1.0, first["deviation_percentage_points"])
        self.assertEqual("pass", first["deviation_status"])
        self.assertIsNone(second["actual_close"])
        self.assertIsNone(second["actual_change_percent"])
        self.assertIsNone(second["deviation_percentage_points"])
        self.assertEqual("pending", second["deviation_status"])

    def test_downgrades_between_warning_and_reject_thresholds(self):
        control = normalizer.build_same_day_deviation_control(
            {"date": "2026-06-15", "close": 97.0},
            [
                {
                    "target_date": "2026-06-15",
                    "base_close": 100.0,
                    "predicted_close": 100.0,
                    "expected_change_percent": 1.0,
                }
            ],
        )

        self.assertEqual("downgrade", control["status"])
        self.assertEqual(-3.0, control["actual_change_percent"])
        self.assertEqual(1.0, control["expected_change_percent"])
        self.assertEqual(-4.0, control["deviation_percentage_points"])
        self.assertTrue(control["adoptable"])
        self.assertFalse(control["buy_allowed"])
        self.assertFalse(control["add_allowed"])
        self.assertFalse(control["clear_if_held"])
        self.assertTrue(control["reduce_if_held"])

    def test_does_not_compare_actual_close_without_same_day_match(self):
        control = normalizer.build_same_day_deviation_control(
            {"date": "2026-06-16", "close": 96.0},
            [
                {
                    "target_date": "2026-06-15",
                    "base_close": 100.0,
                    "predicted_close": 100.0,
                    "expected_change_percent": 1.0,
                }
            ],
        )

        self.assertEqual("no_same_day_match", control["status"])
        self.assertIsNone(control["adoptable"])
        self.assertFalse(control["buy_allowed"])
        self.assertFalse(control["add_allowed"])
        self.assertFalse(control["clear_if_held"])

    def test_qfq_actual_close_does_not_apply_split_factor_again(self):
        result = normalizer.calculate_path_point_deviation(
            1.232,
            "easy_tdx_qfq_daily_kline",
            {
                "base_date": "2026-06-12",
                "target_date": "2026-07-07",
                "base_close": 0.889,
                "expected_change_percent": 34.7701,
            },
            symbol="588170",
        )

        self.assertEqual(38.5827, result["actual_change_percent"])
        self.assertEqual(3.8126, result["deviation_percentage_points"])
        self.assertNotIn("actual_close_comparable", result)
        self.assertNotIn("corporate_action_adjustment_factor", result)

    def test_adjusts_raw_expected_change_percent_to_qfq_split_basis(self):
        archive = {
            "report_date": "2026-07-15",
            "items": [
                {
                    "symbol": "588170",
                    "raw_response": {
                        "data": {
                            "change_base_date": "2026-06-12",
                            "change_base_value": 2.6935,
                            "future_dates": ["2026-07-15"],
                            "predicted_change_percent": [-55.8365],
                        }
                    },
                    "close_observation": {
                        "date": "2026-07-15",
                        "close": 1.122,
                        "source": "easy_tdx_qfq_daily_kline",
                    },
                }
            ],
        }

        with patch.object(normalizer, "fetch_actual_close", return_value=0.889):
            result = normalizer.normalize_archive(archive, fetch_path_actuals=False)

        item = result["items"][0]
        control = item["same_day_deviation_control"]
        self.assertEqual([-55.8365], item["raw_expected_change_percent_path"])
        self.assertEqual([3.0], item["corporate_action_expected_change_factors"])
        self.assertEqual("qfq_comparable_base", item["expected_change_percent_basis"])
        self.assertEqual([32.4905], item["expected_change_percent_path"])
        self.assertEqual(1.1778, item["predicted_close_path"][0]["predicted_close"])
        self.assertEqual(26.2092, control["actual_change_percent"])
        self.assertEqual(32.4905, control["expected_change_percent"])
        self.assertEqual(-6.2813, control["deviation_percentage_points"])
        self.assertEqual("reject", control["status"])

    def test_expected_change_split_factor_starts_on_effective_date(self):
        adjusted, factors = normalizer.adjust_expected_change_path(
            "588170",
            "2026-06-12",
            ["2026-07-03", "2026-07-06", "2026-07-07"],
            [10.0, -55.0, -50.0],
        )

        self.assertEqual([1.0, 3.0, 3.0], factors)
        self.assertEqual([10.0, 35.0, 50.0], adjusted)

    def test_split_adjusted_expected_path_is_idempotent(self):
        archive = {
            "report_date": "2026-07-15",
            "items": [
                {
                    "symbol": "588170",
                    "base_close": {
                        "date": "2026-06-12",
                        "close": 0.889,
                        "source": "easy_tdx_qfq_daily_kline",
                        "adjust": "QFQ",
                    },
                    "expected_change_percent_basis": "qfq_comparable_base",
                    "raw_expected_change_percent_path": [-55.8365],
                    "corporate_action_expected_change_factors": [3.0],
                    "expected_change_percent_path": [32.4905],
                    "predicted_close_path": [
                        {
                            "target_date": "2026-07-15",
                            "expected_change_percent": 32.4905,
                        }
                    ],
                    "close_observation": {
                        "date": "2026-07-15",
                        "close": 1.122,
                        "source": "easy_tdx_qfq_daily_kline",
                    },
                }
            ],
        }

        result = normalizer.normalize_archive(
            archive,
            fetch_actual=False,
            fetch_path_actuals=False,
        )

        item = result["items"][0]
        self.assertEqual([32.4905], item["expected_change_percent_path"])
        self.assertEqual([-55.8365], item["raw_expected_change_percent_path"])
        self.assertEqual([3.0], item["corporate_action_expected_change_factors"])
        self.assertEqual("qfq_comparable_base", item["expected_change_percent_basis"])
        self.assertEqual(-6.2813, item["same_day_deviation_control"]["deviation_percentage_points"])

    def test_unadjusted_actual_close_applies_split_factor_for_comparable_price(self):
        result = normalizer.calculate_path_point_deviation(
            1.192,
            "a_stock_data_tencent_kline",
            {
                "base_date": "2026-06-12",
                "target_date": "2026-07-06",
                "base_close": 2.666,
                "expected_change_percent": 30.6775,
            },
            symbol="588170",
        )

        self.assertEqual(34.1335, result["actual_change_percent"])
        self.assertEqual(3.456, result["deviation_percentage_points"])
        self.assertEqual(3.576, result["actual_close_comparable"])
        self.assertEqual(3.0, result["corporate_action_adjustment_factor"])

    def test_uses_existing_normalized_shape_without_forbidden_path_date(self):
        archive = {
            "items": [
                {
                    "symbol": "515880",
                    "name": "国泰中证全指通信设备ETF",
                    "theme": "通信设备",
                    "horizon_days": 2,
                    "base_close": {"date": "2026-06-12", "close": 1.584},
                    "expected_change_percent_path": [4.4075, 6.843],
                    "predicted_close_path": [
                        {
                            "step": 1,
                            "base_date": "2026-06-12",
                            "base_close": 1.584,
                            "target_date": "2026-06-17",
                            "expected_change_percent": 4.4075,
                            "predicted_close": 1.6538,
                        }
                    ],
                    "validation_summary": {"mae": 0.0076},
                }
            ]
        }

        with patch.object(
            normalizer,
            "future_trading_dates",
            return_value=["2026-06-15", "2026-06-16"],
        ):
            result = normalizer.normalize_archive(archive, fetch_actual=False)

        item = result["items"][0]
        self.assertEqual("existing_archive_value", item["base_close"]["source"])
        self.assertEqual("2026-06-15", item["predicted_close_path"][0]["target_date"])
        self.assertEqual("2026-06-16", item["predicted_close_path"][1]["target_date"])
        self.assertEqual({"mae": 0.0076}, item["validation_summary"])
        for point in item["predicted_close_path"]:
            self.assertNotIn("date", point)
            self.assertIn("deviation_percentage_points", point)

    def test_rejects_archive_without_items(self):
        with self.assertRaises(normalizer.NormalizeError):
            normalizer.normalize_archive({})

    def test_tencent_quote_code_matches_etf_exchange_codes(self):
        self.assertEqual("sz159259", normalizer.tencent_quote_code("159259"))
        self.assertEqual("sh515880", normalizer.tencent_quote_code("515880"))
        self.assertEqual("sh588170", normalizer.tencent_quote_code("588170"))

    def test_parses_easy_tdx_daily_close_response_with_qfq_adjust(self):
        class FakeFrame:
            def to_dict(self, mode):
                return [{"datetime": "2026-06-12T00:00:00.000", "open": 1.539, "close": 1.521}]

        class FakeClient:
            def get_stock_kline(self, market, code, period, start, count, adjust):
                self.call = {
                    "market": market,
                    "code": code,
                    "period": period,
                    "start": start,
                    "count": count,
                    "adjust": adjust,
                }
                return FakeFrame()

        class FakeContext:
            def __init__(self):
                self.client = FakeClient()

            def __enter__(self):
                return self.client

            def __exit__(self, exc_type, exc, traceback):
                return False

        conn_module = ModuleType("easy_tdx.cli.conn")
        parsers_module = ModuleType("easy_tdx.cli.parsers")
        context = FakeContext()
        conn_module.get_mac_client = lambda: context
        parsers_module.parse_adjust = lambda value: value
        parsers_module.parse_market = lambda value: value
        parsers_module.parse_period = lambda value: value
        with patch.dict(
            "sys.modules",
            {
                "easy_tdx": ModuleType("easy_tdx"),
                "easy_tdx.cli": ModuleType("easy_tdx.cli"),
                "easy_tdx.cli.conn": conn_module,
                "easy_tdx.cli.parsers": parsers_module,
            },
        ):
            close = normalizer.fetch_easy_tdx_close("159259", "2026-06-12")

        self.assertEqual(1.521, close)
        self.assertEqual("SZ", context.client.call["market"])
        self.assertEqual("159259", context.client.call["code"])
        self.assertEqual("DAILY", context.client.call["period"])
        self.assertEqual("QFQ", context.client.call["adjust"])

    def test_uses_split_adjusted_comparable_close_for_deviation(self):
        point = {
            "base_date": "2026-06-12",
            "base_close": 2.666,
            "target_date": "2026-07-06",
            "expected_change_percent": 30.6775,
        }

        result = normalizer.calculate_path_point_deviation(
            1.192,
            "test",
            point,
            symbol="588170",
        )

        self.assertEqual(1.192, result["actual_close"])
        self.assertEqual(3.576, result["actual_close_comparable"])
        self.assertEqual(3.0, result["corporate_action_adjustment_factor"])
        self.assertEqual(34.1335, result["actual_change_percent"])
        self.assertEqual(3.456, result["deviation_percentage_points"])
        self.assertEqual("pass", result["deviation_status"])


if __name__ == "__main__":
    unittest.main()
