#!/usr/bin/env python3
import json
from datetime import datetime
from pathlib import Path


DEFAULT_ADJUSTMENT_FILE = Path(__file__).with_name("split_adjustments.json")


def load_adjustments(path=DEFAULT_ADJUSTMENT_FILE):
    adjustment_path = Path(path)
    if not adjustment_path.exists():
        return {}
    return json.loads(adjustment_path.read_text(encoding="utf-8"))


def adjustments_between(symbol, start_date, end_date, adjustments=None):
    if not start_date or not end_date:
        return []
    data = adjustments if adjustments is not None else load_adjustments()
    start = parse_date(start_date)
    end = parse_date(end_date)
    if end < start:
        start, end = end, start
    result = []
    for item in data.get(str(symbol), []):
        effective = parse_date(item["effective_date"])
        if start < effective <= end:
            result.append(item)
    return result


def share_factor_between(symbol, start_date, end_date, adjustments=None):
    factor = 1.0
    for item in adjustments_between(symbol, start_date, end_date, adjustments):
        factor *= float(item["factor"])
    return factor


def comparable_price_factor(symbol, base_date, target_date, adjustments=None):
    return share_factor_between(symbol, base_date, target_date, adjustments)


def adjust_expected_change_path(
    symbol,
    base_date,
    target_dates,
    expected_change_path,
    adjustments=None,
):
    if len(target_dates) != len(expected_change_path):
        raise ValueError("target date count must match expected change percent count")
    factors = [
        share_factor_between(symbol, base_date, target_date, adjustments)
        for target_date in target_dates
    ]
    adjusted = [
        round(((1 + float(expected) / 100) * factor - 1) * 100, 4)
        for expected, factor in zip(expected_change_path, factors)
    ]
    return adjusted, factors


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()
