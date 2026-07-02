#!/usr/bin/env python3
from pathlib import Path
import sys
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

        prices = {("515880", "2026-07-01"): 1.796, ("588170", "2026-07-01"): 4.179}
        with patch.object(sim_trade, "fetch_tencent_daily_price", side_effect=lambda symbol, date, price_field="open": prices[(symbol, date)]):
            result, row, trades = sim_trade.apply_plan(previous, actions, "2026-07-01", 0.95, 100)

        self.assertEqual(2, row["trade_count"])
        self.assertEqual(2300, row["current_position_snapshot"][0]["amount"])
        self.assertEqual(4.179, row["current_position_snapshot"][0]["price"])
        self.assertEqual(9611.7, row["positions_value"])
        self.assertEqual(593.62, row["available_cash"])
        self.assertEqual(10205.32, row["total_value"])
        self.assertEqual("sell", trades[0]["side"])
        self.assertEqual(5403, trades[0]["amount"])
        self.assertEqual(1.796, trades[0]["price"])
        self.assertEqual("buy", trades[1]["side"])
        self.assertEqual(2300, trades[1]["amount"])
        self.assertEqual("open", result["price_source_detail"]["price_field"])
        self.assertEqual(100, result["price_source_detail"]["lot_size"])

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


if __name__ == "__main__":
    unittest.main()
