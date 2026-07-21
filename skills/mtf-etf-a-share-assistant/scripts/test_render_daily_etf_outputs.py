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

    def test_unknown_market_risk_blocks_buy_without_forcing_clear(self):
        args = argparse.Namespace(
            target_weight=0.95,
            switch_threshold_points=8.0,
            exit_threshold_percent=-1.0,
        )
        account = renderer.AccountState("588170", "持仓", 100, 100.0, 0.0, 100.0, 1.0)
        holding = candidate("588170", 2.0, "pass", 1.0)
        target = candidate("159667", 20.0, "pass", 1.0)

        result = renderer.classify_candidates([holding, target], account, False, args, market_blocked=True)
        by_symbol = {item.symbol: item for item in result}

        self.assertEqual("持有", by_symbol["588170"].action)
        self.assertEqual("不执行", by_symbol["159667"].action)
        self.assertEqual("待确认", by_symbol["159667"].market_risk_label)
        self.assertEqual("市场风控待确认", by_symbol["159667"].account_note)

    def test_forward_remaining_overrides_expired_same_day_window(self):
        item = {
            "symbol": "588170",
            "name": "588170 ETF",
            "theme": "主题",
            "expected_change_percent_final": 45.0,
            "forward_remaining_expected_percent": 6.25,
            "close_observation": {"date": "2026-07-08", "close": 1.27},
            "same_day_deviation_control": {
                "status": "pass",
                "actual_change_percent": 42.0,
                "expected_change_percent": 45.0,
                "deviation_percentage_points": -3.0,
            },
        }

        result = renderer.build_candidate(item, "2026-07-08", "未触发")

        self.assertEqual(6.25, result.remaining_expected_percent)

    def test_forward_remaining_without_same_day_match_stays_pending(self):
        args = argparse.Namespace(
            target_weight=0.95,
            switch_threshold_points=8.0,
            exit_threshold_percent=-1.0,
        )
        account = renderer.AccountState("588170", "持仓", 100, 100.0, 0.0, 100.0, 1.0)
        holding = candidate("588170", 0.0, "pass", 0.0)
        pending = candidate("159259", 5.0, "no_same_day_match", None)

        result = renderer.classify_candidates([holding, pending], account, False, args)
        by_symbol = {item.symbol: item for item in result}

        self.assertEqual("不执行", by_symbol["159259"].action)
        self.assertEqual("待确认", by_symbol["159259"].level)
        self.assertEqual("缺少同日对照", by_symbol["159259"].rhythm)

    def test_forbidden_term_scan_catches_internal_terms(self):
        hits = renderer.check_forbidden_terms("这里不应出现 API 和 workflow")

        self.assertIn("API", hits)
        self.assertIn("workflow", hits)

    def test_trade_plan_uses_next_trading_day_for_friday(self):
        account = renderer.AccountState("588170", "持仓", 100, 100.0, 0.0, 100.0, 1.0)
        holding = candidate("588170", 10.0, "pass", 1.0)

        text = renderer.render_trade_plan(
            "2026-07-03",
            renderer.classify_candidates(
                [holding],
                account,
                False,
                argparse.Namespace(target_weight=0.95, switch_threshold_points=8.0, exit_threshold_percent=-1.0),
            ),
            account,
            {"expected_change_percent": 0.5},
            False,
        )

        self.assertIn("# 2026-07-06 ETF 交易计划", text)

    def test_expired_holding_window_requires_next_morning_refresh(self):
        args = argparse.Namespace(
            target_weight=0.95,
            switch_threshold_points=8.0,
            exit_threshold_percent=-1.0,
        )
        account = renderer.AccountState("513050", "持仓", 8800, 9653.6, 539.82, 10193.42, 0.947)
        holding = candidate("513050", 0.0, "pass", 1.5746)
        classified = renderer.classify_candidates([holding], account, False, args)

        suggested = renderer.render_suggested(
            "2026-07-17",
            {},
            classified,
            account,
            {"expected_change_percent": -0.1468},
            False,
        )
        plan = renderer.render_trade_plan(
            "2026-07-17",
            classified,
            account,
            {"expected_change_percent": -0.1468},
            False,
        )

        self.assertIn("本段预测窗口已到期，但到期本身不作为清仓信号", suggested)
        self.assertIn("2026-07-20 早上先刷新 `513050` 的下一批预测", plan)


if __name__ == "__main__":
    unittest.main()
