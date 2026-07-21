#!/usr/bin/env python3
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_daily_trade_plan as sim_trade


class ApplyDailyTradePlanTests(unittest.TestCase):
    def test_applies_clear_and_buy_with_open_price_and_lot_size(self):
        previous = {
            "report_date": "2026-06-30",
            "rows": [
                {
                    "date": "2026-06-30",
                    "initial_cash": 10000,
                    "total_value": 10205.32,
                    "available_cash": 501.53,
                    "positions_value": 9703.79,
                    "current_position_snapshot": [
                        {
                            "symbol": "515880",
                            "name": "国泰中证全指通信设备ETF",
                            "amount": 5403,
                            "price": 1.796,
                            "value": 9703.79,
                        }
                    ],
                }
            ],
            "trades": [],
        }
        actions = [
            {"symbol": "515880", "name": "国泰中证全指通信设备ETF", "action": "清仓", "target_weight": None},
            {"symbol": "588170", "name": "华夏上证科创板半导体材料设备主题ETF", "action": "买入", "target_weight": 0.95},
        ]

        prices = {
            ("515880", "2026-07-01", "open"): 1.796,
            ("588170", "2026-07-01", "open"): 4.179,
            ("588170", "2026-07-01", "close"): 4.176,
        }
        with patch.object(sim_trade, "fetch_easy_tdx_daily_price", side_effect=lambda symbol, date, price_field="open": prices[(symbol, date, price_field)]):
            result, row, trades = sim_trade.apply_plan(previous, actions, "2026-07-01", 0.95, 100)

        self.assertEqual(2, row["trade_count"])
        self.assertEqual(2300, row["current_position_snapshot"][0]["amount"])
        self.assertEqual(4.176, row["current_position_snapshot"][0]["price"])
        self.assertEqual(9604.8, row["positions_value"])
        self.assertEqual(593.62, row["available_cash"])
        self.assertEqual(10198.42, row["total_value"])
        self.assertEqual("sell", trades[0]["side"])
        self.assertEqual(5403, trades[0]["amount"])
        self.assertEqual(1.796, trades[0]["price"])
        self.assertEqual("buy", trades[1]["side"])
        self.assertEqual(2300, trades[1]["amount"])
        self.assertEqual("open", result["price_source_detail"]["trade_price_field"])
        self.assertEqual("close", result["price_source_detail"]["valuation_price_field"])
        self.assertEqual("easy_tdx", result["price_source_detail"]["provider"])
        self.assertEqual("DAILY", result["price_source_detail"]["period"])
        self.assertEqual("QFQ", result["price_source_detail"]["adjust"])
        self.assertEqual(100, result["price_source_detail"]["lot_size"])
        self.assertEqual("current_fund_performance", next(iter(result)))
        summary = result["current_fund_performance"]
        self.assertEqual("2026-07-01", summary["date"])
        self.assertEqual(10000, summary["initial_cash"])
        self.assertEqual(10198.42, summary["total_value"])
        self.assertEqual(593.62, summary["available_cash"])
        self.assertEqual(9604.8, summary["positions_value"])
        self.assertEqual(-6.9, summary["daily_profit"])
        self.assertEqual(198.42, summary["cumulative_profit"])
        self.assertEqual(row["daily_return_rate"], summary["daily_return_rate"])
        self.assertEqual(row["cumulative_return_rate"], summary["cumulative_return_rate"])
        self.assertEqual(2, summary["trade_count"])
        self.assertEqual(row["current_position_snapshot"], summary["current_position_snapshot"])

    def test_parse_trade_plan_reads_table_actions(self):
        text = """# 2026-07-01 ETF 交易计划

| 顺序 | ETF | 后续预计涨跌 | 相对当前持仓 | 市场风控 | 同日偏差风控 | 账户检查 | 执行结果 | 目标仓位 | 目标金额 | 失效条件 |
| ---: | --- | ---: | ---: | --- | --- | --- | --- | --- | ---: | --- |
| 1 | `588170` 华夏上证科创板半导体材料设备主题ETF | +28.0000% | +30.0000 个百分点 | 未触发 | 可采纳 | 清仓后额度可承接 | 买入 | 95% | `9695.05` | 失效 |
| 2 | `515880` 国泰中证全指通信设备ETF | -3.0000% | +0.0000 个百分点 | 未触发 | 可采纳 | 当前持仓有效 | 清仓 | 0 | `0.00` | 失效 |
"""
        with patch.object(Path, "read_text", return_value=text):
            actions = sim_trade.parse_trade_plan(Path("fake.md"))

        self.assertEqual("588170", actions[0]["symbol"])
        self.assertEqual("买入", actions[0]["action"])
        self.assertEqual(0.95, actions[0]["target_weight"])
        self.assertEqual("515880", actions[1]["symbol"])
        self.assertEqual("清仓", actions[1]["action"])

    def test_applies_share_split_before_valuation(self):
        previous = {
            "rows": [
                {
                    "date": "2026-07-03",
                    "initial_cash": 10000,
                    "total_value": 8825.32,
                    "available_cash": 593.62,
                    "current_position_snapshot": [
                        {
                            "symbol": "588170",
                            "name": "华夏上证科创板半导体材料设备主题ETF",
                            "amount": 2300,
                            "price": 3.579,
                            "value": 8231.7,
                        }
                    ],
                }
            ],
            "trades": [],
        }

        with patch.object(sim_trade, "fetch_easy_tdx_daily_price", return_value=1.192):
            result, row, trades = sim_trade.apply_plan(previous, [], "2026-07-06", 0.95, 100)

        position = row["current_position_snapshot"][0]
        self.assertEqual(6900, position["amount"])
        self.assertEqual(8224.8, row["positions_value"])
        self.assertEqual(8818.42, row["total_value"])
        self.assertEqual(0, len(trades))
        adjustment = result["price_source_detail"]["share_adjustments"][0]
        self.assertEqual("588170", adjustment["symbol"])
        self.assertEqual(3.0, adjustment["factor"])
        self.assertEqual(2300, adjustment["amount_before"])
        self.assertEqual(6900, adjustment["amount_after"])

    def test_fetches_easy_tdx_daily_price_with_qfq_adjust(self):
        class FakeFrame:
            def to_dict(self, mode):
                return [{"datetime": "2026-07-01T00:00:00.000", "open": 4.179, "close": 4.176}]

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
            price = sim_trade.fetch_easy_tdx_daily_price("588170", "2026-07-01", "open")

        self.assertEqual(4.179, price)
        self.assertEqual("SH", context.client.call["market"])
        self.assertEqual("588170", context.client.call["code"])
        self.assertEqual("DAILY", context.client.call["period"])
        self.assertEqual("QFQ", context.client.call["adjust"])


if __name__ == "__main__":
    unittest.main()
