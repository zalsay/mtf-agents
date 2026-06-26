#!/usr/bin/env python3
import argparse
import json
from http.client import RemoteDisconnected
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
ACTUAL_CLOSE_SOURCE = "a_stock_data_tencent_kline"
DEFAULT_CALENDAR = "XSHG"
PRICE_DECIMALS = 4
DEVIATION_DECIMALS = 4
NEGATIVE_DEVIATION_REJECT_POINTS = -5.0
NEGATIVE_DEVIATION_DOWNGRADE_POINTS = -3.0


class NormalizeError(ValueError):
    pass


def parse_args():
    parser = argparse.ArgumentParser(
        description="Normalize MTF ETF future archives to close-price-only predicted paths."
    )
    parser.add_argument("input", help="Path to YYYY-MM-DD-mtf-future.json")
    parser.add_argument("--output", help="Write normalized JSON to this path")
    parser.add_argument("--in-place", action="store_true", help="Overwrite the input file")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print a summary without writing")
    parser.add_argument("--calendar", default=DEFAULT_CALENDAR, help="exchange-calendars calendar name")
    parser.add_argument(
        "--target-anchor",
        choices=["base", "request-end", "latest-data"],
        default="request-end",
        help="Date after which target trading dates are generated when rebuilding paths",
    )
    parser.add_argument(
        "--keep-existing-base-close",
        action="store_true",
        help="Use existing base_close.close/change_base_value instead of fetching Tencent actual close",
    )
    parser.add_argument(
        "--skip-path-actuals",
        action="store_true",
        help="Do not fetch actual closes for reached predicted_close_path target dates",
    )
    parser.add_argument(
        "--negative-deviation-reject-points",
        type=float,
        default=NEGATIVE_DEVIATION_REJECT_POINTS,
        help="Reject a prediction path when actual_change_percent - expected_change_percent is at or below this value",
    )
    parser.add_argument(
        "--negative-deviation-downgrade-points",
        type=float,
        default=NEGATIVE_DEVIATION_DOWNGRADE_POINTS,
        help="Downgrade a prediction path when actual_change_percent - expected_change_percent is at or below this value",
    )
    return parser.parse_args()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_archive(
    archive,
    calendar_name=DEFAULT_CALENDAR,
    target_anchor="base",
    fetch_actual=True,
    fetch_path_actuals=True,
    negative_deviation_reject_points=NEGATIVE_DEVIATION_REJECT_POINTS,
    negative_deviation_downgrade_points=NEGATIVE_DEVIATION_DOWNGRADE_POINTS,
):
    data = deepcopy(archive)
    items = data.get("items")
    if not isinstance(items, list):
        raise NormalizeError("archive must contain an items list")

    normalized_items = [
        normalize_item(
            item,
            calendar_name,
            target_anchor=target_anchor,
            fetch_actual=fetch_actual,
            fetch_path_actuals=fetch_path_actuals,
            archive_as_of_date=data.get("market_data_date") or data.get("report_date"),
            negative_deviation_reject_points=negative_deviation_reject_points,
            negative_deviation_downgrade_points=negative_deviation_downgrade_points,
        )
        for item in items
    ]
    data["items"] = normalized_items
    data["price_basis"] = "close_price_only"
    data["predicted_close_calculation"] = "base_close.close * (1 + expected_change_percent / 100)"
    data["predicted_close_basis"] = "actual close on base_close.date"
    data["actual_base_close_source"] = ACTUAL_CLOSE_SOURCE if fetch_actual else "existing_archive_value"
    data["path_date_semantics"] = (
        "predicted_close_path points use target_date; each point is calculated from "
        "base_close.date/base_close.close, not from target_date close."
    )
    data["same_day_deviation_control"] = {
        "formula": "actual_change_percent - expected_change_percent",
        "actual_change_percent_formula": "(actual_close_on_target_date / base_close - 1) * 100",
        "reject_at_or_below_points": negative_deviation_reject_points,
        "downgrade_at_or_below_points": negative_deviation_downgrade_points,
        "note": "Only compare actual change percent with expected_change_percent when actual close date equals target_date.",
    }
    validate_archive(data)
    return data


def normalize_item(
    item,
    calendar_name,
    target_anchor="base",
    fetch_actual=True,
    fetch_path_actuals=True,
    archive_as_of_date=None,
    negative_deviation_reject_points=NEGATIVE_DEVIATION_REJECT_POINTS,
    negative_deviation_downgrade_points=NEGATIVE_DEVIATION_DOWNGRADE_POINTS,
):
    raw_data = extract_raw_data(item)
    symbol = require_text(item.get("symbol") or raw_data.get("stock_code"), "symbol")
    base_date = require_text(
        nested_get(item, "base_close", "date") or item.get("change_base_date") or raw_data.get("change_base_date"),
        f"{symbol} base date",
    )
    existing_base_close = (
        nested_get(item, "base_close", "close")
        or item.get("change_base_value")
        or raw_data.get("change_base_value")
    )
    base_close = fetch_tencent_close(symbol, base_date) if fetch_actual else require_float(
        existing_base_close, f"{symbol} base close"
    )
    base_source = ACTUAL_CLOSE_SOURCE if fetch_actual else (
        nested_get(item, "base_close", "source") or "existing_archive_value"
    )
    expected_path = extract_expected_change_path(item, raw_data, symbol)
    target_dates = resolve_target_dates(item, raw_data, base_date, len(expected_path), calendar_name, target_anchor)
    predicted_path = build_predicted_close_path(base_date, base_close, target_dates, expected_path)
    close_observation = normalize_close_observation(item)
    path_as_of_date = resolve_path_as_of_date(item, raw_data, close_observation, archive_as_of_date)
    predicted_path = enrich_predicted_close_path(
        symbol,
        predicted_path,
        close_observation=close_observation,
        as_of_date=path_as_of_date,
        fetch_actual=fetch_actual and fetch_path_actuals,
        reject_points=negative_deviation_reject_points,
        downgrade_points=negative_deviation_downgrade_points,
    )

    normalized = {
        "symbol": symbol,
        "name": item.get("name") or raw_data.get("short_name") or "",
        "theme": item.get("theme") or "",
        "horizon_days": int(item.get("horizon_days") or item.get("horizon_len") or raw_data.get("horizon_len") or len(expected_path)),
        "base_close": {
            "date": base_date,
            "close": round(base_close, PRICE_DECIMALS),
            "source": base_source,
            "note": "actual close on base_close.date",
        },
        "expected_change_percent_path": expected_path,
        "expected_change_percent_final": expected_path[-1],
        "predicted_close_path": predicted_path,
        "model_reference_range": build_model_reference_range(predicted_path),
    }

    if close_observation:
        normalized["close_observation"] = close_observation
        normalized["same_day_deviation_control"] = build_same_day_deviation_control(
            close_observation,
            predicted_path,
            negative_deviation_reject_points,
            negative_deviation_downgrade_points,
        )
    if item.get("validation_summary"):
        normalized["validation_summary"] = item["validation_summary"]
    normalized["predicted_close_calculation"] = "base_close.close * (1 + expected_change_percent / 100)"
    normalized["predicted_close_basis"] = "actual close on base_close.date"
    normalized["path_date_semantics"] = (
        "target_date is the prediction target date; base_date/base_close are the calculation anchor."
    )
    return normalized


def extract_raw_data(item):
    raw = item.get("raw_response")
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        return raw["data"]
    return {}


def extract_expected_change_path(item, raw_data, symbol):
    path = item.get("expected_change_percent_path") or item.get("predicted_change_percent") or raw_data.get(
        "predicted_change_percent"
    )
    if path is None:
        raise NormalizeError(f"{symbol} missing predicted change percent path")
    if not isinstance(path, list):
        path = [path]
    result = [round(require_float(value, f"{symbol} expected change percent"), 4) for value in path]
    if not result:
        raise NormalizeError(f"{symbol} expected change percent path is empty")
    return result


def resolve_anchor_date(item, raw_data, base_date, target_anchor):
    if target_anchor == "base":
        return base_date
    if target_anchor == "request-end":
        return require_text(raw_data.get("request_end_date") or item.get("request_end_date"), "request_end_date")
    if target_anchor == "latest-data":
        return require_text(raw_data.get("latest_data_date") or item.get("latest_data_date"), "latest_data_date")
    raise NormalizeError(f"unsupported target anchor: {target_anchor}")


def resolve_target_dates(item, raw_data, base_date, expected_count, calendar_name, target_anchor):
    raw_future_dates = raw_data.get("future_dates")
    if isinstance(raw_future_dates, list) and len(raw_future_dates) == expected_count:
        return [require_text(value, "future target date") for value in raw_future_dates]

    existing_path = item.get("predicted_close_path")
    if isinstance(existing_path, list) and len(existing_path) == expected_count:
        existing_dates = [point.get("target_date") for point in existing_path if isinstance(point, dict)]
        if len(existing_dates) == expected_count and all(existing_dates):
            return [require_text(value, "existing target date") for value in existing_dates]

    anchor_date = resolve_anchor_date(item, raw_data, base_date, target_anchor)
    return future_trading_dates(anchor_date, expected_count, calendar_name)


def build_predicted_close_path(base_date, base_close, target_dates, expected_path):
    if len(target_dates) != len(expected_path):
        raise NormalizeError("target date count must match expected change percent count")
    result = []
    for index, (target_date, expected_change) in enumerate(zip(target_dates, expected_path), start=1):
        predicted_close = round(base_close * (1 + expected_change / 100), PRICE_DECIMALS)
        result.append(
            {
                "step": index,
                "base_date": base_date,
                "base_close": round(base_close, PRICE_DECIMALS),
                "target_date": target_date,
                "expected_change_percent": expected_change,
                "predicted_close": predicted_close,
                "actual_close": None,
                "actual_close_source": None,
                "actual_change_percent": None,
                "deviation_percentage_points": None,
                "deviation_status": "pending",
            }
        )
    return result


def build_model_reference_range(predicted_path):
    low = min(predicted_path, key=lambda point: point["predicted_close"])
    high = max(predicted_path, key=lambda point: point["predicted_close"])
    return {
        "low": low["predicted_close"],
        "low_target_date": low["target_date"],
        "high": high["predicted_close"],
        "high_target_date": high["target_date"],
        "note": "仅作研究参考，不是交易价格。",
    }


def normalize_close_observation(item):
    existing = item.get("close_observation")
    if isinstance(existing, dict) and existing.get("date") and existing.get("close") is not None:
        return existing
    latest_close = item.get("latest_close")
    latest_date = item.get("latest_data_date")
    if latest_close is None or not latest_date:
        return None
    return {
        "date": latest_date,
        "close": require_float(latest_close, "latest close"),
        "source": "close_price",
    }


def resolve_path_as_of_date(item, raw_data, close_observation, archive_as_of_date):
    if close_observation and close_observation.get("date"):
        return close_observation["date"]
    return (
        item.get("market_data_date")
        or item.get("report_date")
        or item.get("latest_data_date")
        or raw_data.get("latest_data_date")
        or archive_as_of_date
    )


def enrich_predicted_close_path(
    symbol,
    predicted_path,
    close_observation=None,
    as_of_date=None,
    fetch_actual=True,
    reject_points=NEGATIVE_DEVIATION_REJECT_POINTS,
    downgrade_points=NEGATIVE_DEVIATION_DOWNGRADE_POINTS,
):
    observation_by_date = {}
    if close_observation and close_observation.get("date") and close_observation.get("close") is not None:
        observation_by_date[close_observation["date"]] = {
            "close": require_float(close_observation["close"], "actual close"),
            "source": close_observation.get("source") or "close_observation",
        }

    result = []
    as_of = parse_date(as_of_date) if as_of_date else None
    for point in predicted_path:
        enriched = deepcopy(point)
        target_date = point["target_date"]
        if as_of is None or parse_date(target_date) > as_of:
            result.append(enriched)
            continue

        actual = observation_by_date.get(target_date)
        if actual is None and fetch_actual:
            try:
                actual = {
                    "close": fetch_tencent_close(symbol, target_date),
                    "source": ACTUAL_CLOSE_SOURCE,
                }
            except NormalizeError:
                actual = None
        if actual is None:
            enriched["deviation_status"] = "actual_unavailable"
            result.append(enriched)
            continue

        enriched.update(
            calculate_path_point_deviation(
                actual["close"],
                actual.get("source"),
                point,
                reject_points=reject_points,
                downgrade_points=downgrade_points,
            )
        )
        result.append(enriched)
    return result


def calculate_path_point_deviation(
    actual_close,
    actual_close_source,
    point,
    reject_points=NEGATIVE_DEVIATION_REJECT_POINTS,
    downgrade_points=NEGATIVE_DEVIATION_DOWNGRADE_POINTS,
):
    base_close = require_float(point["base_close"], "base close")
    if base_close == 0:
        raise NormalizeError("base close cannot be zero when calculating path point deviation")
    expected_change_percent = require_float(point["expected_change_percent"], "expected change percent")
    actual_close = require_float(actual_close, "actual close")
    actual_change_percent = round((actual_close / base_close - 1) * 100, DEVIATION_DECIMALS)
    deviation_points = round(actual_change_percent - expected_change_percent, DEVIATION_DECIMALS)
    return {
        "actual_close": round(actual_close, PRICE_DECIMALS),
        "actual_close_source": actual_close_source or "actual_close",
        "actual_change_percent": actual_change_percent,
        "deviation_percentage_points": deviation_points,
        "deviation_status": classify_deviation_status(deviation_points, reject_points, downgrade_points),
    }


def classify_deviation_status(deviation_points, reject_points, downgrade_points):
    if deviation_points <= reject_points:
        return "reject"
    if deviation_points <= downgrade_points:
        return "downgrade"
    return "pass"


def build_same_day_deviation_control(
    close_observation,
    predicted_path,
    reject_points=NEGATIVE_DEVIATION_REJECT_POINTS,
    downgrade_points=NEGATIVE_DEVIATION_DOWNGRADE_POINTS,
):
    observation_date = close_observation["date"]
    actual_close = require_float(close_observation["close"], "actual close")
    matched_point = next(
        (point for point in predicted_path if point.get("target_date") == observation_date),
        None,
    )
    if matched_point is None:
        return {
            "status": "no_same_day_match",
            "observation_date": observation_date,
            "actual_close": round(actual_close, PRICE_DECIMALS),
            "adoptable": None,
            "buy_allowed": False,
            "add_allowed": False,
            "clear_if_held": False,
            "note": "No target_date matches the actual close date; do not compare actual change percent with expected_change_percent.",
        }

    point_deviation = calculate_path_point_deviation(
        actual_close,
        close_observation.get("source") or "close_observation",
        matched_point,
        reject_points=reject_points,
        downgrade_points=downgrade_points,
    )
    control = {
        "status": "pass",
        "observation_date": observation_date,
        "matched_target_date": matched_point["target_date"],
        "base_close": matched_point["base_close"],
        "actual_close": point_deviation["actual_close"],
        "actual_change_percent": point_deviation["actual_change_percent"],
        "expected_change_percent": matched_point["expected_change_percent"],
        "deviation_percentage_points": point_deviation["deviation_percentage_points"],
        "reject_at_or_below_points": reject_points,
        "downgrade_at_or_below_points": downgrade_points,
        "adoptable": True,
        "buy_allowed": True,
        "add_allowed": True,
        "clear_if_held": False,
        "note": "Actual change percent is not below expected_change_percent by the negative-deviation risk threshold.",
    }
    if point_deviation["deviation_status"] == "reject":
        control.update(
            {
                "status": "reject",
                "adoptable": False,
                "buy_allowed": False,
                "add_allowed": False,
                "clear_if_held": True,
                "note": "Actual change percent is materially below same-day expected_change_percent; reject this prediction path.",
            }
        )
    elif point_deviation["deviation_status"] == "downgrade":
        control.update(
            {
                "status": "downgrade",
                "adoptable": True,
                "buy_allowed": False,
                "add_allowed": False,
                "clear_if_held": False,
                "reduce_if_held": True,
                "note": "Actual change percent is below same-day expected_change_percent enough to downgrade; do not buy or add.",
            }
        )
    elif point_deviation["deviation_percentage_points"] > 0:
        control["note"] = (
            "Actual change percent is above same-day expected_change_percent; this is not a chase signal."
        )
    return control


def future_trading_dates(anchor_date, count, calendar_name=DEFAULT_CALENDAR):
    try:
        import exchange_calendars as xcals
        import pandas as pd
    except ImportError as exc:
        raise NormalizeError(
            "missing trading calendar dependency: run `python3 -m pip install exchange-calendars`"
        ) from exc

    start_date = parse_date(anchor_date) + timedelta(days=1)
    end_date = start_date + timedelta(days=max(30, count * 5 + 30))
    calendar = xcals.get_calendar(calendar_name)
    sessions = calendar.sessions_in_range(pd.Timestamp(start_date), pd.Timestamp(end_date))
    dates = [session.date().isoformat() for session in sessions[:count]]
    if len(dates) < count:
        raise NormalizeError(f"calendar {calendar_name} returned only {len(dates)} sessions after {anchor_date}")
    return dates


def fetch_tencent_close(symbol, trading_date):
    quote_code = tencent_quote_code(symbol)
    params = {
        "param": f"{quote_code},day,{trading_date},{trading_date},1",
    }
    url = TENCENT_KLINE_URL + "?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, RemoteDisconnected, TimeoutError, OSError) as exc:
        raise NormalizeError(f"{symbol} Tencent daily close request failed for {trading_date}: {exc}") from exc
    day_rows = nested_get(payload, "data", quote_code, "day") or []
    for row in day_rows:
        if len(row) >= 3 and row[0] == trading_date:
            return require_float(row[2], f"{symbol} Tencent close on {trading_date}")
    raise NormalizeError(f"{symbol} missing Tencent daily close for {trading_date}")


def tencent_quote_code(symbol):
    code = str(symbol)
    return tencent_market_prefix(code) + code


def tencent_market_prefix(symbol):
    code = str(symbol)
    if code.startswith(("5", "6", "9")):
        return "sh"
    if code.startswith(("4", "8")):
        return "bj"
    return "sz"


def validate_archive(data):
    forbidden = {"reference_buy", "reference_sell", "latest_close", "latest_price", "raw_response", "date"}
    for item in data.get("items", []):
        symbol = item.get("symbol", "<unknown>")
        for key in ("reference_buy", "reference_sell", "latest_close", "latest_price", "raw_response"):
            if key in item:
                raise NormalizeError(f"{symbol} still contains forbidden field {key}")
        base = nested_get(item, "base_close", "close")
        for point in item.get("predicted_close_path", []):
            extra = forbidden.intersection(point.keys())
            if extra:
                raise NormalizeError(f"{symbol} predicted_close_path contains forbidden field(s): {sorted(extra)}")
            expected = round(base * (1 + point["expected_change_percent"] / 100), PRICE_DECIMALS)
            if point["predicted_close"] != expected:
                raise NormalizeError(f"{symbol} formula mismatch at step {point.get('step')}")


def nested_get(data, *keys):
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise NormalizeError(f"missing {label}")
    return value.strip()


def require_float(value, label):
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise NormalizeError(f"invalid {label}: {value!r}") from exc


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def summarize(data):
    lines = []
    for item in data.get("items", []):
        path = item["predicted_close_path"]
        lines.append(
            f"{item['symbol']}: base={item['base_close']['date']} {item['base_close']['close']}, "
            f"targets={path[0]['target_date']}..{path[-1]['target_date']}, "
            f"range={item['model_reference_range']['low']}..{item['model_reference_range']['high']}"
        )
    return "\n".join(lines)


def main():
    args = parse_args()
    if args.in_place and args.output:
        raise SystemExit("--in-place and --output cannot be used together")
    input_path = Path(args.input)
    output_path = input_path if args.in_place else Path(args.output) if args.output else None
    try:
        normalized = normalize_archive(
            load_json(input_path),
            calendar_name=args.calendar,
            target_anchor=args.target_anchor,
            fetch_actual=not args.keep_existing_base_close,
            fetch_path_actuals=not args.skip_path_actuals,
            negative_deviation_reject_points=args.negative_deviation_reject_points,
            negative_deviation_downgrade_points=args.negative_deviation_downgrade_points,
        )
    except NormalizeError as exc:
        raise SystemExit(str(exc)) from exc
    print(summarize(normalized))
    if args.dry_run:
        return
    if output_path is None:
        raise SystemExit("choose --in-place, --output, or --dry-run")
    write_json(output_path, normalized)


if __name__ == "__main__":
    main()
