#!/usr/bin/env python3
import argparse
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_REPORT_ROOT = Path("reports/mtf-etf")
DEFAULT_INITIAL_CASH = 10000
DEFAULT_TARGET_WEIGHT = 0.95
DEFAULT_LOT_SIZE = 100
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
PRICE_SOURCE = "a-stock-data actual daily open"


class SimTradeError(ValueError):
    pass


def parse_args():
    parser = argparse.ArgumentParser(
        description="Apply a daily ETF trade plan to the simulated account using execution-day open prices."
    )
    parser.add_argument("execution_date", help="Execution date in YYYY-MM-DD")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    parser.add_argument("--source-date", help="Plan/account date. Default: latest report date before execution_date.")
    parser.add_argument("--plan", help="Path to source YYYY-MM-DD-trade-plan.md")
    parser.add_argument("--previous-sim-report", help="Path to source YYYY-MM-DD-sim-trade-report.json")
    parser.add_argument("--output", help="Path to write execution-date sim-trade-report.json")
    parser.add_argument("--target-weight", type=float, default=DEFAULT_TARGET_WEIGHT)
    parser.add_argument("--lot-size", type=int, default=DEFAULT_LOT_SIZE)
    parser.add_argument("--write", action="store_true", help="Write output file. Otherwise print a summary only.")
    return parser.parse_args()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_paths(args):
    root = Path(args.report_root)
    source_date = args.source_date or latest_source_date(root, args.execution_date)
    plan = Path(args.plan) if args.plan else root / source_date / f"{source_date}-trade-plan.md"
    previous = (
        Path(args.previous_sim_report)
        if args.previous_sim_report
        else root / source_date / f"{source_date}-sim-trade-report.json"
    )
    output = (
        Path(args.output)
        if args.output
        else root / args.execution_date / f"{args.execution_date}-sim-trade-report.json"
    )
    return source_date, plan, previous, output


def latest_source_date(root, execution_date):
    dates = [
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name < execution_date and (path / f"{path.name}-trade-plan.md").exists()
    ]
    if not dates:
        raise SimTradeError(f"no source trade plan found before {execution_date}")
    return sorted(dates)[-1]


def parse_trade_plan(path):
    text = Path(path).read_text(encoding="utf-8")
    actions = []
    in_table = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("| 顺序 |"):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            if actions:
                break
            continue
        if re.match(r"^\|\s*-", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 10:
            continue
        symbol, name = parse_etf_cell(cells[1])
        action = cells[7]
        target_weight = parse_target_weight(cells[8])
        if action in {"买入", "清仓", "持有", "减仓", "加仓", "不执行"}:
            actions.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "action": action,
                    "target_weight": target_weight,
                }
            )
    if not actions:
        raise SimTradeError(f"no executable action rows found in {path}")
    return actions


def parse_etf_cell(cell):
    match = re.search(r"`([^`]+)`\s*(.*)", cell)
    if not match:
        raise SimTradeError(f"cannot parse ETF cell: {cell}")
    return match.group(1), match.group(2).strip()


def parse_target_weight(cell):
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)%", cell)
    if match:
        return float(match.group(1)) / 100
    return None


def latest_account_row(report):
    rows = report.get("rows") or []
    if not rows:
        raise SimTradeError("previous sim report has no rows")
    return rows[-1]


def first_position(row):
    positions = row.get("current_position_snapshot") or []
    return deepcopy(positions[0]) if positions else None


def apply_plan(previous_report, actions, execution_date, target_weight, lot_size):
    previous_row = latest_account_row(previous_report)
    position = first_position(previous_row)
    cash = float(previous_row.get("available_cash") or 0.0)
    previous_total = float(previous_row.get("total_value") or 0.0)
    trades = []
    open_prices = {}

    clear_symbols = {action["symbol"] for action in actions if action["action"] == "清仓"}
    buy_actions = [action for action in actions if action["action"] == "买入"]

    if position and position.get("symbol") in clear_symbols:
        symbol = position["symbol"]
        amount = int(position.get("amount") or 0)
        price = get_open_price(open_prices, symbol, execution_date)
        value = round(amount * price, 3)
        cash += value
        trades.append(build_trade(execution_date, symbol, position.get("name") or "", "sell", amount, price, value))
        position = None

    total_after_sells = cash + position_value(position, open_prices, execution_date)

    for action in buy_actions:
        symbol = action["symbol"]
        price = get_open_price(open_prices, symbol, execution_date)
        desired_weight = action.get("target_weight") or target_weight
        desired_value = min(cash, total_after_sells * desired_weight)
        amount = floor_to_lot(desired_value / price, lot_size)
        if amount <= 0:
            continue
        value = round(amount * price, 3)
        cash -= value
        position = {
            "symbol": symbol,
            "name": action.get("name") or "",
            "amount": amount,
            "price": price,
            "value": round(value, 2),
        }
        trades.append(build_trade(execution_date, symbol, action.get("name") or "", "buy", amount, price, value))

    if position:
        symbol = position["symbol"]
        price = get_open_price(open_prices, symbol, execution_date)
        amount = int(position.get("amount") or 0)
        value = round(amount * price, 3)
        position.update({"price": price, "value": round(value, 2)})
    else:
        value = 0.0

    total = cash + value
    positions = []
    if position:
        position["weight"] = value / total if total else 0.0
        positions.append(position)

    row = {
        "date": execution_date,
        "quote_date": execution_date,
        "initial_cash": previous_row.get("initial_cash") or DEFAULT_INITIAL_CASH,
        "total_value": round(total, 2),
        "available_cash": round(cash, 2),
        "positions_value": round(value, 2),
        "daily_profit": clean_round(total - previous_total, 2),
        "cumulative_profit": clean_round(total - DEFAULT_INITIAL_CASH, 2),
        "daily_return_rate": (total - previous_total) / previous_total if previous_total else 0,
        "cumulative_return_rate": (total - DEFAULT_INITIAL_CASH) / DEFAULT_INITIAL_CASH,
        "trade_count": len(trades),
        "current_position_snapshot": positions,
    }

    result = deepcopy(previous_report)
    result["report_date"] = execution_date
    result["valuation_source"] = PRICE_SOURCE
    result["price_source_detail"] = {
        "provider": "tencent_kline",
        "trade_date": execution_date,
        "price_field": "open",
        "lot_size": lot_size,
        "executed_trades": [
            {"symbol": t["security"], "open": t["price"], "side": t["side"], "amount": t["amount"]}
            for t in trades
        ],
    }
    result["rows"] = replace_by_date(result.get("rows") or [], execution_date, row)
    result["trades"] = replace_trades_by_date(result.get("trades") or [], execution_date, trades)
    return result, row, trades


def position_value(position, open_prices, execution_date):
    if not position:
        return 0.0
    price = get_open_price(open_prices, position["symbol"], execution_date)
    return int(position.get("amount") or 0) * price


def get_open_price(cache, symbol, execution_date):
    key = (symbol, execution_date)
    if key not in cache:
        cache[key] = fetch_tencent_daily_price(symbol, execution_date, price_field="open")
    return cache[key]


def fetch_tencent_daily_price(symbol, trading_date, price_field="open"):
    quote_code = tencent_quote_code(symbol)
    url = TENCENT_KLINE_URL + "?" + urlencode({"param": f"{quote_code},day,{trading_date},{trading_date},1"})
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SimTradeError(f"{symbol} Tencent daily price request failed for {trading_date}: {exc}") from exc
    rows = nested_get(payload, "data", quote_code, "day") or []
    index = {"open": 1, "close": 2}[price_field]
    for row in rows:
        if len(row) > index and row[0] == trading_date:
            return float(row[index])
    raise SimTradeError(f"{symbol} missing Tencent {price_field} for {trading_date}")


def tencent_quote_code(symbol):
    code = str(symbol)
    if code.startswith(("5", "6", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def nested_get(data, *keys):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def floor_to_lot(amount, lot_size):
    return int(amount // lot_size) * lot_size


def clean_round(value, digits):
    rounded = round(value, digits)
    return 0 if rounded == 0 else rounded


def build_trade(date, symbol, name, side, amount, price, value):
    return {
        "date": date,
        "trade_id": f"sim-{date}-{symbol}-{side}",
        "order_id": f"sim-{date}-{symbol}-{side}",
        "security": symbol,
        "security_name": name,
        "side": side,
        "amount": int(amount),
        "price": price,
        "value": round(value, 2),
        "commission": 0,
        "note": f"Simulated execution using a-stock-data actual daily open price for {date}.",
    }


def replace_by_date(rows, execution_date, new_row):
    kept = [row for row in rows if row.get("date") != execution_date]
    kept.append(new_row)
    return sorted(kept, key=lambda row: datetime.strptime(row["date"], "%Y-%m-%d"))


def replace_trades_by_date(trades, execution_date, new_trades):
    kept = [trade for trade in trades if trade.get("date") != execution_date]
    return kept + new_trades


def main():
    args = parse_args()
    if args.lot_size <= 0:
        raise SystemExit("--lot-size must be positive")
    try:
        source_date, plan_path, previous_path, output_path = resolve_paths(args)
        actions = parse_trade_plan(plan_path)
        result, row, trades = apply_plan(load_json(previous_path), actions, args.execution_date, args.target_weight, args.lot_size)
    except SimTradeError as exc:
        raise SystemExit(str(exc)) from exc

    print(
        f"{args.execution_date}: source={source_date}, trades={len(trades)}, "
        f"total={row['total_value']:.2f}, cash={row['available_cash']:.2f}, positions={row['positions_value']:.2f}"
    )
    if args.write:
        write_json(output_path, result)


if __name__ == "__main__":
    main()
