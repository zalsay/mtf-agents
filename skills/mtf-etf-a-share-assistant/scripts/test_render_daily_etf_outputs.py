#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import render_daily_etf_outputs as renderer


def candidate(symbol, remaining, status="pass", deviation=0.0):
    return renderer.Candidate(
        symbol=symbol,
        name=f"{symbol} ETF",
        theme="主题",
        close_date="2026-06-30",
        close=1.0,
        actual_change_percent=10.0,
        same_day_expected_percent=8.0,
        deviation_points=deviation,
        deviation_status=status,
        remaining_expected_percent=remaining,
        reference_low=0.9,
        reference_high=1.1,
        market_risk_label="未触发",
    )


class RenderDailyETFOutputsTests(unittest.TestCase):
    def test_switches_when_holding_is_below_exit_and_candidate_advantage_is_large(self):
        args = argparse.Namespace(
            target_weight=0.95,
            switch_threshold_points=8.0,
            exit_threshold_percent=-1.0,
        )
        account = renderer.AccountState("515880", "持仓", 5403, 9703.79, 501.53, 10205.32, 0.9508)
        holding = candidate("515880", -3.4869, "pass", -2.981)
        target = candidate("588170", 28.6966, "pass", 38.0431)
        downgraded = candidate("159259", -0.7285, "downgrade", -4.0852)

        result = renderer.classify_candidates([holding, target, downgraded], account, False, args)
        by_symbol = {item.symbol: item for item in result}

        self.assertEqual("清仓", by_symbol["515880"].action)
        self.assertEqual("买入", by_symbol["588170"].action)
        self.assertEqual(9695.05, by_symbol["588170"].target_amount)
        self.assertEqual(32.1835, by_symbol["588170"].relative_to_holding)
        self.assertEqual("不执行", by_symbol["159259"].action)

    def test_reject_candidate_is_never_buy_target(self):
        args = argparse.Namespace(
            target_weight=0.95,
            switch_threshold_points=8.0,
            exit_threshold_percent=-1.0,
        )
        account = renderer.AccountState("515880", "持仓", 100, 100.0, 0.0, 100.0, 1.0)
        holding = candidate("515880", -2.0, "pass", -1.0)
        rejected = candidate("515220", 30.0, "reject", -6.0)

        result = renderer.classify_candidates([holding, rejected], account, False, args)
        by_symbol = {item.symbol: item for item in result}

        self.assertEqual("清仓", by_symbol["515880"].action)
        self.assertEqual("不执行", by_symbol["515220"].action)
        self.assertEqual("暂不采纳", by_symbol["515220"].level)

    def test_forbidden_term_scan_catches_internal_terms(self):
        hits = renderer.check_forbidden_terms("这里不应出现 API 和 workflow")

        self.assertIn("API", hits)
        self.assertIn("workflow", hits)


if __name__ == "__main__":
    unittest.main()
