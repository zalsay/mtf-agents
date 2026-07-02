#!/usr/bin/env python3
import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_REPORT_ROOT = Path("reports/mtf-etf")
DEFAULT_TARGET_WEIGHT = 0.95
SWITCH_THRESHOLD_POINTS = 8.0
EXIT_THRESHOLD_PERCENT = -1.0
MARKET_CRASH_THRESHOLD_PERCENT = -3.0
FORBIDDEN_MARKDOWN_TERMS = [
    "API",
    "endpoint",
    "payload",
    "JSON",
    "trace",
    "unique_key",
    "request",
    "response",
    "raw",
    "watchlist",
    "skill",
    "workflow",
    "字段",
    "接口",
    "脚本",
    "Open API",
    "mtf-pro",
    "latest_close",
    "change_base",
    "future_dates",
    "predicted_change_percent",
    "日期对齐",
    "明日计划",
]


@dataclass
class AccountState:
    holding_symbol: str | None
    holding_name: str
    holding_amount: int
    holding_value: float
    available_cash: float
    total_value: float
    holding_weight: float


@dataclass
class Candidate:
    symbol: str
    name: str
    theme: str
    close_date: str
    close: float | None
    actual_change_percent: float | None
    same_day_expected_percent: float | None
    deviation_points: float | None
    deviation_status: str
    remaining_expected_percent: float | None
    reference_low: float | None
    reference_high: float | None
    market_risk_label: str
    rhythm: str = ""
    level: str = ""
    action: str = "不执行"
    account_note: str = ""
    target_weight: str = "0"
    target_amount: float = 0.0
    invalidation: str = "条件变化后重算"
    relative_to_holding: float | None = None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Render user-facing daily ETF research and trade-plan Markdown from normalized future archive."
    )
    parser.add_argument("report_date", help="Report date in YYYY-MM-DD")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--future-json", help="Path to normalized YYYY-MM-DD-mtf-future.json")
    parser.add_argument("--sim-report", help="Path to YYYY-MM-DD-sim-trade-report.json")
    parser.add_argument("--output-dir", help="Default: reports/mtf-etf/YYYY-MM-DD")
    parser.add_argument("--target-weight", type=float, default=DEFAULT_TARGET_WEIGHT)
    parser.add_argument("--switch-threshold-points", type=float, default=SWITCH_THRESHOLD_POINTS)
    parser.add_argument("--exit-threshold-percent", type=float, default=EXIT_THRESHOLD_PERCENT)
    parser.add_argument("--market-crash-threshold-percent", type=float, default=MARKET_CRASH_THRESHOLD_PERCENT)
    parser.add_argument("--write", action="store_true", help="Write suggested-ETF.md and trade-plan.md")
    parser.add_argument("--check-terms", action="store_true", help="Fail if user Markdown contains internal terms")
    return parser.parse_args()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_text(path, text):
    Path(path).write_text(text, encoding="utf-8")


def round4(value):
    return None if value is None else round(float(value), 4)


def fmt_percent(value):
    if value is None:
        return "暂无"
    return f"{value:+.4f}%"


def fmt_points(value):
    if value is None:
        return "暂无"
    return f"{value:+.4f} 个百分点"


def fmt_money(value):
    return f"`{value:.2f}`"


def next_calendar_day(date_text):
    return (datetime.strptime(date_text, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()


def default_paths(args):
    root = Path(args.report_root)
    output_dir = Path(args.output_dir) if args.output_dir else root / args.report_date
    future_json = Path(args.future_json) if args.future_json else output_dir / f"{args.report_date}-mtf-future.json"
    sim_report = Path(args.sim_report) if args.sim_report else output_dir / f"{args.report_date}-sim-trade-report.json"
    return output_dir, future_json, sim_report


def latest_account_state(sim_report):
    if not sim_report.exists():
        return AccountState(None, "", 0, 0.0, 0.0, 0.0, 0.0)
    data = load_json(sim_report)
    rows = data.get("rows") or []
    if not rows:
        return AccountState(None, "", 0, 0.0, 0.0, 0.0, 0.0)
    row = rows[-1]
    positions = row.get("current_position_snapshot") or []
    position = positions[0] if positions else {}
    total_value = float(row.get("total_value") or 0.0)
    holding_value = float(row.get("positions_value") or position.get("value") or 0.0)
    return AccountState(
        holding_symbol=position.get("symbol"),
        holding_name=position.get("name") or "",
        holding_amount=int(position.get("amount") or 0),
        holding_value=holding_value,
        available_cash=float(row.get("available_cash") or 0.0),
        total_value=total_value,
        holding_weight=(holding_value / total_value) if total_value else 0.0,
    )


def same_day_point(item, report_date):
    return next((point for point in item.get("predicted_close_path", []) if point.get("target_date") == report_date), None)


def build_candidate(item, report_date, market_risk_label):
    control = item.get("same_day_deviation_control") or {}
    observation = item.get("close_observation") or {}
    final_expected = item.get("expected_change_percent_final")
    same_expected = control.get("expected_change_percent")
    remaining = None
    if final_expected is not None and same_expected is not None:
        remaining = round4(float(final_expected) - float(same_expected))
    reference = item.get("model_reference_range") or {}
    return Candidate(
        symbol=item.get("symbol", ""),
        name=item.get("name", ""),
        theme=item.get("theme", ""),
        close_date=observation.get("date") or report_date,
        close=round4(observation.get("close")) if observation.get("close") is not None else None,
        actual_change_percent=round4(control.get("actual_change_percent")),
        same_day_expected_percent=round4(same_expected),
        deviation_points=round4(control.get("deviation_percentage_points")),
        deviation_status=control.get("status") or "unknown",
        remaining_expected_percent=remaining,
        reference_low=round4(reference.get("low")),
        reference_high=round4(reference.get("high")),
        market_risk_label=market_risk_label,
    )


def is_buy_allowed(candidate):
    return (
        candidate.remaining_expected_percent is not None
        and candidate.remaining_expected_percent > 0
        and candidate.deviation_status == "pass"
    )


def classify_candidates(candidates, account, market_triggered, args):
    holding = next((candidate for candidate in candidates if candidate.symbol == account.holding_symbol), None)
    holding_remaining = holding.remaining_expected_percent if holding else None

    for candidate in candidates:
        if holding_remaining is not None and candidate.remaining_expected_percent is not None:
            candidate.relative_to_holding = round4(candidate.remaining_expected_percent - holding_remaining)

    buyable = [candidate for candidate in candidates if is_buy_allowed(candidate)]
    buyable.sort(key=lambda candidate: candidate.remaining_expected_percent or -999, reverse=True)
    top_buyable = buyable[0] if buyable else None

    should_clear_holding = False
    if holding:
        should_clear_holding = (
            market_triggered
            or holding.deviation_status == "reject"
            or (
                holding.remaining_expected_percent is not None
                and holding.remaining_expected_percent < args.exit_threshold_percent
            )
        )

    switch_target = None
    if not market_triggered and top_buyable and account.holding_symbol:
        advantage = top_buyable.relative_to_holding
        if advantage is not None and advantage >= args.switch_threshold_points:
            switch_target = top_buyable
        elif should_clear_holding and advantage is not None and advantage >= 5.0:
            switch_target = top_buyable
    elif not market_triggered and top_buyable and not account.holding_symbol:
        switch_target = top_buyable

    for candidate in candidates:
        fill_candidate_labels(candidate)
        candidate.market_risk_label = "触发" if market_triggered else "未触发"
        candidate.target_weight = "0"
        candidate.target_amount = 0.0
        candidate.account_note = "不作为买入方向"
        candidate.invalidation = "条件变化后重算"

    if holding:
        if should_clear_holding:
            holding.action = "清仓"
            holding.level = "退出"
            holding.target_weight = "0"
            holding.account_note = "当前持仓有效"
            holding.invalidation = "后续预计涨跌重新回到退出线以上时重算"
        else:
            holding.action = "持有"
            holding.level = "持仓有效"
            holding.target_weight = "维持现有仓位"
            holding.account_note = "当前持仓有效"
            holding.invalidation = "负向偏差转弱或后续空间低于退出线"

    if switch_target:
        switch_target.action = "买入"
        switch_target.level = "主候选"
        switch_target.account_note = "清仓后额度可承接" if account.holding_symbol else "账户有买入额度"
        switch_target.target_weight = f"{int(args.target_weight * 100)}%"
        switch_target.target_amount = round(account.total_value * args.target_weight, 2)
        switch_target.invalidation = "后续优势低于 5 个百分点或触发负向偏差风控"

    for candidate in candidates:
        if candidate is switch_target or candidate is holding:
            continue
        candidate.action = "不执行"
        candidate.target_weight = "0"
        candidate.target_amount = 0.0
        if candidate.deviation_status == "reject":
            candidate.level = "暂不采纳"
            candidate.account_note = "不作为买入方向"
            candidate.invalidation = "负向偏差解除前不买入"
        elif candidate.deviation_status == "downgrade":
            candidate.level = "降级观察"
            candidate.account_note = "不作为买入方向"
            candidate.invalidation = "降级未解除前不切换"
        elif candidate.remaining_expected_percent is None:
            candidate.level = "待确认"
            candidate.account_note = "缺少同日对照"
            candidate.invalidation = "同日对照补齐后再重算"
        elif candidate.remaining_expected_percent <= 0:
            candidate.level = "观察" if candidate.remaining_expected_percent == 0 else "回避"
            candidate.account_note = "空间不足"
            candidate.invalidation = "后续空间重新转正且优势达标"
        elif switch_target:
            candidate.level = "备选"
            candidate.account_note = "优先级低于主候选"
            candidate.invalidation = "主候选失效后再重算"
        else:
            candidate.level = "候选观察"
            candidate.account_note = "优势不足"
            candidate.invalidation = "优势扩大后再重算"

    return sorted(candidates, key=candidate_sort_key)


def fill_candidate_labels(candidate):
    if candidate.deviation_status == "reject":
        candidate.rhythm = "实际表现明显弱于同日预计"
    elif candidate.deviation_status == "downgrade":
        candidate.rhythm = "实际表现低于同日预计，已降级"
    elif candidate.remaining_expected_percent is None:
        candidate.rhythm = "缺少同日对照"
    elif candidate.remaining_expected_percent < 0:
        candidate.rhythm = "后续空间转负"
    elif candidate.remaining_expected_percent == 0:
        candidate.rhythm = "后续空间已走完"
    elif candidate.deviation_points is not None and candidate.deviation_points > 0:
        candidate.rhythm = "同日节奏未触发负向偏差风控"
    else:
        candidate.rhythm = "同日偏差未触发硬风控"
    if not candidate.level:
        candidate.level = "可采纳" if candidate.deviation_status == "pass" else "观察"


def candidate_sort_key(candidate):
    status_rank = {"pass": 0, "downgrade": 1, "reject": 2}.get(candidate.deviation_status, 3)
    remaining = candidate.remaining_expected_percent if candidate.remaining_expected_percent is not None else -999
    return (status_rank, -remaining)


def market_risk(data, args):
    risk = data.get("market_index_risk") or {}
    expected = risk.get("expected_change_percent")
    triggered = bool(risk.get("triggered"))
    if expected is not None and float(expected) <= args.market_crash_threshold_percent:
        triggered = True
    return risk, triggered


def trade_summary(sorted_candidates, account):
    holding = next((candidate for candidate in sorted_candidates if candidate.symbol == account.holding_symbol), None)
    buy = next((candidate for candidate in sorted_candidates if candidate.action == "买入"), None)
    if holding and buy:
        return f"清仓 `{holding.symbol}`，切换到 `{buy.symbol}`"
    if holding and holding.action == "清仓":
        return f"清仓 `{holding.symbol}`，不新增、不换仓"
    if holding and holding.action == "持有":
        return f"继续持有 `{holding.symbol}`，不新增、不换仓"
    if buy:
        return f"买入 `{buy.symbol}`"
    return "不新增、不换仓"


def render_suggested(report_date, data, sorted_candidates, account, market, market_triggered):
    buy = next((candidate for candidate in sorted_candidates if candidate.action == "买入"), None)
    holding = next((candidate for candidate in sorted_candidates if candidate.symbol == account.holding_symbol), None)
    lines = [
        f"# {report_date} ETF 研究结论",
        "",
        "## 核心结论",
        "",
        f"- 上证指数同日预计涨跌为 `{fmt_percent(market.get('expected_change_percent'))}`，{'触发大盘大跌风控' if market_triggered else '未触发大盘大跌风控'}。",
    ]
    if account.holding_symbol:
        holding_close = f"，今天收盘价 `{holding.close:.3f}`" if holding and holding.close is not None else ""
        lines.append(
            f"- 当前模拟账户持有 `{account.holding_symbol}`{holding_close}，账户总权益约 `{account.total_value:.2f}`。"
        )
    else:
        lines.append(f"- 当前模拟账户无持仓，账户总权益约 `{account.total_value:.2f}`。")
    if holding and buy:
        lines.append(
            f"- `{holding.symbol}` 后续预计涨跌约 `{fmt_percent(holding.remaining_expected_percent)}`；"
            f"`{buy.symbol}` 后续预计涨跌约 `{fmt_percent(buy.remaining_expected_percent)}`，且同日节奏未触发负向偏差风控。"
        )
    elif holding:
        lines.append(f"- `{holding.symbol}` 后续预计涨跌约 `{fmt_percent(holding.remaining_expected_percent)}`。")
    elif buy:
        lines.append(f"- `{buy.symbol}` 后续预计涨跌约 `{fmt_percent(buy.remaining_expected_percent)}`。")
    lines.append(f"- 本轮明确结果：{trade_summary(sorted_candidates, account)}。")
    lines.extend(["", "## 证据表", ""])
    lines.append(
        "| ETF | 主题 | 收盘日期 | 收盘价 | 实际涨跌幅 | 同日预计 | 偏差 | 后续预计涨跌 | 趋势节奏 | 观察级别 | 操作建议 |"
    )
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |")
    for candidate in sorted_candidates:
        lines.append(
            f"| `{candidate.symbol}` {candidate.name} | {candidate.theme or '-'} | {candidate.close_date} | "
            f"{candidate.close:.3f} | {fmt_percent(candidate.actual_change_percent)} | "
            f"{fmt_percent(candidate.same_day_expected_percent)} | {fmt_points(candidate.deviation_points)} | "
            f"{fmt_percent(candidate.remaining_expected_percent)} | {candidate.rhythm} | {candidate.level} | {suggest_action(candidate)} |"
        )
    lines.extend(
        [
            "",
            "## 市场风控",
            "",
            f"- 上证指数同日预计涨跌为 `{fmt_percent(market.get('expected_change_percent'))}`，"
            f"{'低于或等于 -3%，本轮以清仓防守为先' if market_triggered else '未低于 `-3%`，因此没有触发清仓防守'}。",
            "",
            "## 交易判断",
            "",
        ]
    )
    for candidate in sorted_candidates:
        if candidate.action in ("买入", "清仓", "持有") or candidate.deviation_status in ("reject", "downgrade"):
            lines.append(f"- `{candidate.symbol}`：{candidate.rhythm}，{suggest_action(candidate)}。")
    lines.extend(
        [
            "",
            "## 风险提示",
            "",
            "- 今日判断只基于收盘价和同日对照后的涨跌幅差异，不使用盘中价格判断预测是否有效。",
            "- 上证指数风控未触发不代表可以追高，仍需遵守 ETF 自身偏差和换仓优势规则。",
            "",
        ]
    )
    return "\n".join(lines)


def suggest_action(candidate):
    if candidate.action == "买入":
        return "切换买入"
    if candidate.action == "清仓":
        return "清仓"
    if candidate.action == "持有":
        return "继续持有"
    if candidate.deviation_status == "reject":
        return "回避，不买入"
    if candidate.deviation_status == "downgrade":
        return "不切换"
    if candidate.level == "备选":
        return "不新增"
    return candidate.action


def render_trade_plan(report_date, sorted_candidates, account, market, market_triggered):
    plan_date = next_calendar_day(report_date)
    summary = trade_summary(sorted_candidates, account)
    buy = next((candidate for candidate in sorted_candidates if candidate.action == "买入"), None)
    holding = next((candidate for candidate in sorted_candidates if candidate.symbol == account.holding_symbol), None)
    lines = [
        f"# {plan_date} ETF 交易计划",
        "",
        "## 计划摘要",
        "",
        f"本计划基于 {report_date} 收盘价和上证指数风控给出 {plan_date} 的明确执行结果：{summary}。",
    ]
    if holding and buy:
        lines.append(
            f"上证指数同日预计涨跌为 `{fmt_percent(market.get('expected_change_percent'))}`，未触发大盘大跌风控；"
            f"`{holding.symbol}` 后续预计涨跌已低于退出线，`{buy.symbol}` 相对当前持仓优势约 "
            f"`{fmt_points(buy.relative_to_holding)}`，满足切换条件。"
        )
    elif market_triggered:
        lines.append("上证指数同日预计跌幅触发大盘风控，本轮不新增买入。")
    lines.extend(["", "## 账户状态", ""])
    holding_text = "无持仓"
    if account.holding_symbol:
        holding_text = f"`{account.holding_symbol}`，`{account.holding_amount}` 份"
    lines.extend(
        [
            "| 项目 | 数值 |",
            "| --- | ---: |",
            f"| 当前持仓 | {holding_text} |",
            f"| 持仓市值 | {fmt_money(account.holding_value)} |",
            f"| 剩余现金 | {fmt_money(account.available_cash)} |",
            f"| 总权益 | {fmt_money(account.total_value)} |",
            f"| 当前持仓占比 | `{account.holding_weight * 100:.2f}%` |",
            f"| 当前可用现金 | {fmt_money(account.available_cash)} |",
            f"| 清仓后可承接额度 | {fmt_money(account.total_value * DEFAULT_TARGET_WEIGHT)} |",
            "",
            "## 执行结果",
            "",
            "| 顺序 | ETF | 后续预计涨跌 | 相对当前持仓 | 市场风控 | 同日偏差风控 | 账户检查 | 执行结果 | 目标仓位 | 目标金额 | 失效条件 |",
            "| ---: | --- | ---: | ---: | --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for index, candidate in enumerate(sorted_candidates, start=1):
        lines.append(
            f"| {index} | `{candidate.symbol}` {candidate.name} | {fmt_percent(candidate.remaining_expected_percent)} | "
            f"{fmt_points(candidate.relative_to_holding)} | {candidate.market_risk_label} | "
            f"{risk_text(candidate)} | {candidate.account_note} | {candidate.action} | "
            f"{candidate.target_weight} | {fmt_money(candidate.target_amount)} | {candidate.invalidation} |"
        )
    lines.extend(["", "## 执行顺序", ""])
    step = 1
    if holding and holding.action == "清仓":
        lines.append(f"{step}. 卖出 `{holding.symbol}` 当前 `{account.holding_amount}` 份，目标仓位降为 0。")
        step += 1
    if buy:
        amount = buy.target_amount
        lines.append(
            f"{step}. 用清仓后资金买入 `{buy.symbol}`，目标仓位 `{buy.target_weight}`，"
            f"目标金额约 `{amount:.2f}`；实际成交按执行日开盘价计算，买入数量按 `100` 份整手向下取整。"
        )
        step += 1
    excluded = [candidate.symbol for candidate in sorted_candidates if candidate.action == "不执行"]
    if excluded:
        lines.append(f"{step}. 不买入 {join_symbols(excluded)}。")
        step += 1
    lines.append(f"{step}. 下一个交易日继续先检查上证指数市场风控，再判断 ETF 动作。")
    lines.extend(
        [
            "",
            "## 风控备注",
            "",
            "- 动作优先级为：上证指数大跌风控、ETF 负向偏差硬风控、当前持仓退出线、后续预计涨跌与换仓优势、账户额度。",
        ]
    )
    if holding and buy:
        lines.append(
            f"- 当前没有触发上证指数大跌风控；`{holding.symbol}` 清仓原因是后续预计涨跌已低于退出线，"
            f"`{buy.symbol}` 买入原因是后续空间和换仓优势均满足本轮切换条件。"
        )
    lines.append("")
    return "\n".join(lines)


def risk_text(candidate):
    if candidate.deviation_status == "reject":
        return f"暂不采纳，偏差 {fmt_points(candidate.deviation_points)}"
    if candidate.deviation_status == "downgrade":
        return f"降级观察，偏差 {fmt_points(candidate.deviation_points)}"
    if candidate.deviation_status == "pass":
        return f"可采纳，偏差 {fmt_points(candidate.deviation_points)}"
    return "待确认"


def join_symbols(symbols):
    return "、".join(f"`{symbol}`" for symbol in symbols)


def check_forbidden_terms(*texts):
    combined = "\n".join(texts)
    return [term for term in FORBIDDEN_MARKDOWN_TERMS if term in combined]


def main():
    args = parse_args()
    output_dir, future_json, sim_report = default_paths(args)
    data = load_json(future_json)
    account = latest_account_state(sim_report)
    market, market_triggered = market_risk(data, args)
    market_label = "触发" if market_triggered else "未触发"
    candidates = [build_candidate(item, args.report_date, market_label) for item in data.get("items", [])]
    sorted_candidates = classify_candidates(candidates, account, market_triggered, args)
    suggested = render_suggested(args.report_date, data, sorted_candidates, account, market, market_triggered)
    trade_plan = render_trade_plan(args.report_date, sorted_candidates, account, market, market_triggered)

    if args.check_terms:
        hits = check_forbidden_terms(suggested, trade_plan)
        if hits:
            raise SystemExit(f"user markdown contains forbidden terms: {', '.join(hits)}")

    if args.write:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_text(output_dir / f"{args.report_date}-suggested-ETF.md", suggested)
        write_text(output_dir / f"{args.report_date}-trade-plan.md", trade_plan)
    else:
        print(suggested)
        print(trade_plan)


if __name__ == "__main__":
    main()
