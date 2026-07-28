#!/usr/bin/env python3
"""构建当日 MTF future 归档 (reports/mtf-etf/YYYY-MM-DD/YYYY-MM-DD-mtf-future.json)。

该脚本供每日自动化工作流第 1 步调用: 自动从 Open API 拉取
- v2 etf-hot 热门 ETF 雷达, 持久化为本地快照 YYYY-MM-DD-etf-hot.json, 并作为预测目标列表
- 每个热门 ETF 的指定日期 mtf-future 缓存查询
用 easy-tdx(QFQ) 回填当日实际收盘, 组装成
normalize_mtf_future_archive.py 能吃掉的归档 JSON。

关键约束:
- close_observation.source 必须为 'easy_tdx_qfq_daily_kline' (前复权口径),
  与 easy-tdx 拉取的路径点一致, 避免 split_adjustments.json 的份额拆分因子被重复计算。
- ETF 预测只用 mtf-pro，并通过 v2 客户端先选择 512/1024/2048 的 best key。
  v2 future 先读取指定日期的已有缓存；缓存未命中自动触发同配置补算并轮询 future。
  如需只读缓存，显式传入 --cache-only。

用法:
    python3 scripts/build_daily_archive.py [--date YYYY-MM-DD] [--horizon-len 8|16|32|64]
        [--context-len 512|1024|2048] [--cache-only] [--dry-run]
默认日期 = 今天。
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import easy_tdx
from easy_tdx.cli.conn import get_mac_client
from easy_tdx.cli.parsers import parse_adjust, parse_market, parse_period

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/mtf-etf-a-share-assistant/scripts"
ENV = SCRIPTS / ".env.open-api"
INDEX_SYMBOL = "000001"
CRASH_THRESHOLD = -3.0
SUPPORTED_CONTEXT_LENS = (512, 1024, 2048)
SUPPORTED_HORIZON_LENS = (8, 16, 32, 64)
# ETF 代码特征: 沪市 5xxxxx / 深市 1xxxxx
ETF_RE = re.compile(r"^(5|1)\d{5}$")
# 规整 symbol -> 名称 (来自 etf-hot 的 name)
NAME_MAP = {}
PREDICTION_POLL_ATTEMPTS = 24
PREDICTION_POLL_INTERVAL_SECONDS = 5
TRAIN_POLL_ATTEMPTS = 120
TRAIN_POLL_INTERVAL_SECONDS = 10
DEFAULT_TRAIN_CONTEXT_LEN = 2048


class OpenAPIError(RuntimeError):
    def __init__(self, message, body=None):
        super().__init__(message)
        self.body = body if isinstance(body, dict) else {}


def call_api(sub, *args):
    cmd = [
        sys.executable, str(SCRIPTS / "call_open_api.py"),
        "--env-file", str(ENV), sub, *args,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0 or not r.stdout.strip():
        body = {}
        if r.stdout.strip():
            try:
                body = json.loads(r.stdout)
            except json.JSONDecodeError:
                pass
        detail = r.stderr.strip() or json.dumps(body, ensure_ascii=False)
        raise OpenAPIError(
            f"call_open_api {sub} 失败 rc={r.returncode}: {detail[:500]}",
            body,
        )
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as exc:
        raise OpenAPIError(f"call_open_api {sub} 返回非法 JSON: {exc}") from exc


def response_data(response):
    data = response.get("data") if isinstance(response, dict) else None
    return data if isinstance(data, dict) else {}


def is_prediction_cache_miss(error):
    if not isinstance(error, OpenAPIError):
        return False
    error_body = error.body.get("error")
    if isinstance(error_body, dict) and error_body.get("code") == "prediction_cache_not_found":
        return True
    return "prediction_cache_not_found" in json.dumps(error.body, ensure_ascii=False)


def is_best_missing(error):
    if not isinstance(error, OpenAPIError):
        return False
    error_body = error.body.get("error")
    code = error_body.get("code") if isinstance(error_body, dict) else None
    return code in {"not_found", "mtf_pro_best_not_found"}


def future_contains_date(data, predict_date):
    dates = data.get("future_dates") if isinstance(data, dict) else None
    return isinstance(dates, list) and predict_date in {str(value) for value in dates}


def wait_for_prediction_cache(v2_args):
    """Poll the dated future cache after an async prediction trigger."""
    last_error = "prediction cache is still unavailable"
    target_date = v2_args[v2_args.index("--predict-date") + 1]
    for attempt in range(PREDICTION_POLL_ATTEMPTS):
        try:
            response = call_api("mtf-v2-future", *v2_args)
            data = response_data(response)
            if future_contains_date(data, target_date):
                return data
            last_error = f"prediction response did not contain target future date {target_date}"
        except OpenAPIError as exc:
            if not is_prediction_cache_miss(exc):
                raise
            last_error = str(exc)
        if attempt < PREDICTION_POLL_ATTEMPTS - 1:
            time.sleep(PREDICTION_POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"v2 预测缓存轮询超时: {last_error}")


def wait_for_training_job(job_id):
    """Wait until the best-model training job has persisted its result."""
    last_status = "queued"
    for attempt in range(TRAIN_POLL_ATTEMPTS):
        response = call_api("mtf-v2-job", "--job-id", job_id)
        data = response_data(response)
        status = str(data.get("status") or "").strip().lower()
        last_status = status or last_status
        if status == "succeeded":
            return data
        if status == "failed":
            error = data.get("error") or "training job failed"
            raise RuntimeError(f"best 训练失败: {error}")
        if status not in {"queued", "running"}:
            raise RuntimeError(f"best 训练返回未知 job 状态: {status or '<empty>'}")
        if attempt < TRAIN_POLL_ATTEMPTS - 1:
            time.sleep(TRAIN_POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"best 训练 job 轮询超时: {job_id}, last_status={last_status}")


def train_missing_best(stock_code, stock_type, horizon_len, context_len):
    train_context_len = context_len or DEFAULT_TRAIN_CONTEXT_LEN
    response = call_api(
        "mtf-v2-train",
        "--stock-code", stock_code,
        "--stock-type", str(stock_type),
        "--horizon-len", str(horizon_len),
        "--context-len", str(train_context_len),
        "--years", "15",
    )
    data = response_data(response)
    job_id = str(data.get("job_id") or response.get("job_id") or "").strip()
    if not job_id:
        raise RuntimeError(f"best 训练未返回 job_id: {response}")
    print(
        f"[train] {stock_code} best 缺失，启动训练 job={job_id} "
        f"(horizon={horizon_len}, context={train_context_len})"
    )
    result = wait_for_training_job(job_id)
    print(f"[train] {stock_code} job={job_id} 成功，重新查询 best")
    return result


def get_candidates(hot_response):
    """返回 {规整symbol: stock_type}，目标直接来自 etf-hot.items。"""
    payload = (hot_response.get("data") or {}) if isinstance(hot_response, dict) else {}
    items = payload.get("items")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise OpenAPIError("etf-hot 返回的 items 不是列表", hot_response)

    out = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_sym = str(item.get("code", "") or item.get("symbol", "") or "")
        if not raw_sym:
            continue
        sym = re.sub(r"^(sh|sz|bj)", "", raw_sym, flags=re.I) or raw_sym
        if not ETF_RE.match(sym):
            continue
        out[sym] = 2
        NAME_MAP[sym] = str(item.get("name", "") or "")
        print(f"[cand] {raw_sym} -> {sym} ({NAME_MAP[sym]})")
    return out


def get_candidate_name(sym):
    return NAME_MAP.get(sym, "")


def fetch_and_save_etf_hot(report_date, out_dir, dry_run=False):
    """拉取 v2 etf-hot 并持久化快照；返回原始 Open API 响应作为候选源。"""
    try:
        raw = call_api("mtf-v2-etf-hot")
    except Exception as e:
        raise OpenAPIError(f"etf-hot 拉取失败: {e}") from e
    envelope_err = (raw.get("status") == "error") or bool(raw.get("error"))
    payload = {
        "report_date": report_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "GET /api/open/v2/etf/hot",
        "ok": not envelope_err,
        "data": (raw.get("data") or {}),
        "error": raw.get("error") if envelope_err else None,
        "raw_response": raw,
    }
    out_path = out_dir / f"{report_date}-etf-hot.json"
    if dry_run:
        print(f"[dry-run] 将写入 {out_path} (etf-hot 快照, ok={not envelope_err})")
        return raw
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    hot = (raw.get("data") or {})
    print(f"[etf-hot] 已保存 {out_path} (ok={not envelope_err}, data keys={list(hot.keys())})")
    return raw


def build_index_risk(report_date, horizon_len, context_len, allow_predict=False):
    resp = fetch_mtf_future(
        report_date,
        INDEX_SYMBOL,
        stock_type=3,
        horizon_len=horizon_len,
        context_len=context_len,
        allow_predict=allow_predict,
    )
    fdates = resp.get("future_dates") or []
    pct = resp.get("predicted_change_percent") or []
    target = report_date if report_date in fdates else (fdates[-1] if fdates else report_date)
    expected = pct[fdates.index(report_date)] if report_date in fdates else (pct[-1] if pct else 0.0)
    triggered = expected <= CRASH_THRESHOLD
    return {
        "name": "上证指数",
        "symbol": INDEX_SYMBOL,
        "target_date": target,
        "expected_change_percent": round(expected, 4),
        "crash_threshold_percent": CRASH_THRESHOLD,
        "triggered": triggered,
        "buy_blocked": False,
        "status": "pass" if not triggered else "reject",
        "note": ("上证指数同日预计涨跌未触发大盘大跌风控"
                 if not triggered else "上证指数同日预计涨跌触发大盘大跌风控"),
    }


def fetch_mtf_future(
    predict_date,
    stock_code,
    stock_type,
    horizon_len=8,
    context_len=None,
    allow_predict=False,
):
    v2_args = [
        "--symbol", stock_code,
        "--stock-type", str(stock_type),
        "--horizon-len", str(horizon_len),
    ]
    if context_len is not None:
        v2_args.extend(["--context-len", str(context_len)])
    v2_args.extend(["--predict-date", predict_date])
    best_args = list(v2_args)
    predict_date_index = best_args.index("--predict-date")
    best_args = best_args[:predict_date_index]
    cache_miss = False
    try:
        d = call_api("mtf-v2-future", *v2_args)
        if not future_contains_date(response_data(d), predict_date):
            cache_miss = True
    except OpenAPIError as exc:
        if is_best_missing(exc):
            if not allow_predict:
                raise
            train_missing_best(stock_code, stock_type, horizon_len, context_len)
            try:
                d = call_api("mtf-v2-future", *v2_args)
            except OpenAPIError as retried:
                if not is_prediction_cache_miss(retried):
                    raise
                cache_miss = True
            else:
                cache_miss = not future_contains_date(response_data(d), predict_date)
        elif is_prediction_cache_miss(exc):
            if not allow_predict:
                raise
            cache_miss = True
        else:
            raise

    if cache_miss:
        if not allow_predict:
            raise RuntimeError(f"{stock_code} future 缓存缺少 {predict_date}")
        selected = response_data(call_api("mtf-v2-best", *best_args))
        key = selected["unique_key"]
        selected_horizon = int(selected["horizon_len"])
        selected_context = int(selected["context_len"])
        print(
            f"[cache-miss] future={key} contains={predict_date}; "
            f"触发 mtf-v2-predict-once predict_date={predict_date} "
            f"(horizon={selected_horizon}, context={selected_context}, type=mtf-pro)"
        )
        trigger = call_api(
            "mtf-v2-predict-once",
            "--stock-code", stock_code,
            "--stock-type", str(stock_type),
            "--prediction-type", "mtf-pro",
            "--horizon-len", str(selected_horizon),
            "--context-len", str(selected_context),
            "--predict-date", predict_date,
            "--prefer-cache",
        )
        del trigger
        wait_for_prediction_cache(v2_args)
        d = call_api("mtf-v2-future", *v2_args)
    data = response_data(d)
    if not future_contains_date(data, predict_date):
        raise RuntimeError(f"{stock_code} 未返回包含 {predict_date} 的有效 future")
    return data


def market_code(symbol):
    if symbol == INDEX_SYMBOL:
        return "SH", "000001"
    if symbol.startswith(("5", "6", "9")):
        return "SH", symbol
    if symbol.startswith(("4", "8")):
        return "BJ", symbol
    return "SZ", symbol


def fetch_close(symbol, trading_date):
    market, code = market_code(symbol)
    with get_mac_client() as client:
        frame = client.get_stock_kline(
            parse_market(market), code, period=parse_period("DAILY"),
            start=0, count=1200, adjust=parse_adjust("QFQ"),
        )
    for row in frame.to_dict("records"):
        dt = str(row.get("datetime"))
        if dt.startswith(trading_date):
            return float(row["close"]), trading_date
    raise RuntimeError(f"{symbol} 在 {trading_date} 无 easy-tdx 收盘")


def fetch_close_best_effort(symbol, preferred):
    for i in range(6):
        cand = preferred if i == 0 else _back_days(preferred, i)
        try:
            return fetch_close(symbol, cand)
        except Exception:
            continue
    raise RuntimeError(f"{symbol} 近 6 个交易日均无 easy-tdx 收盘")


def _back_days(date_text, n):
    from datetime import timedelta
    return (datetime.strptime(date_text, "%Y-%m-%d") - timedelta(days=n)).strftime("%Y-%m-%d")


def build(
    report_date,
    horizon_len=8,
    context_len=None,
    allow_predict=True,
    dry_run=False,
):
    out_dir = ROOT / "reports" / "mtf-etf" / report_date
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    # 1) etf-hot 是候选发现源，同时落盘雷达快照
    try:
        hot_response = fetch_and_save_etf_hot(report_date, out_dir, dry_run=dry_run)
    except Exception as e:
        raise RuntimeError(f"etf-hot 候选发现失败，停止构建: {e}") from e

    # 2) 操作边界: etf-hot 候选 -> v2 mtf-future 预测归档
    cands = get_candidates(hot_response)
    print(f"[build] {report_date}: {len(cands)} 个 ETF 候选")

    items = []
    for sym, stock_type in cands.items():
        try:
            resp = fetch_mtf_future(
                report_date,
                sym,
                stock_type=stock_type,
                horizon_len=horizon_len,
                context_len=context_len,
                allow_predict=allow_predict,
            )
            name = (get_candidate_name(sym) or resp.get("short_name")
                    or resp.get("name") or sym)
            actual, actual_date = fetch_close_best_effort(sym, report_date)
        except Exception as e:
            print(f"[warn] ETF {sym} 跳过 (预测/行情获取失败): {e}")
            continue
        items.append({
            "symbol": sym,
            "name": name,
            "theme": "",
            "horizon_days": resp.get("horizon_len", 8),
            "raw_response": {"data": resp},
            "close_observation": {
                "date": actual_date,
                "close": round(actual, 4),
                "source": "easy_tdx_qfq_daily_kline",
            },
        })
        print(f"[build] ETF {sym} {name}: {report_date} 实际收盘 = {actual} (obs {actual_date})")

    try:
        index_risk = build_index_risk(
            report_date,
            horizon_len=horizon_len,
            context_len=context_len,
            allow_predict=allow_predict,
        )
        print(f"[build] 上证指数同日预计 {index_risk['expected_change_percent']:+.4f}% "
              f"triggered={index_risk['triggered']}")
    except Exception as e:
        print(f"[warn] 上证指数风控获取失败: {e}")
        index_risk = {
            "name": "上证指数", "symbol": INDEX_SYMBOL, "target_date": report_date,
            "expected_change_percent": None, "crash_threshold_percent": CRASH_THRESHOLD,
            "triggered": False, "buy_blocked": False, "status": "unknown",
            "note": "上证指数同日预测获取失败，风控状态未知",
        }

    archive = {
        "report_date": report_date,
        "market_data_date": report_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "price_basis": "raw_api_response",
        "market_index_risk": index_risk,
        "items": items,
    }
    out_path = out_dir / f"{report_date}-mtf-future.json"
    if dry_run:
        print(f"[dry-run] 将写入 {out_path} ({len(items)} ETF items)")
        print(json.dumps(archive, ensure_ascii=False, indent=2)[:800])
        return
    out_path.write_text(json.dumps(archive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {out_path} with {len(items)} ETF items; index triggered={index_risk.get('triggered') if index_risk else None}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--horizon-len", type=int, choices=SUPPORTED_HORIZON_LENS, default=8)
    ap.add_argument("--context-len", type=int, choices=SUPPORTED_CONTEXT_LENS)
    predict_mode = ap.add_mutually_exclusive_group()
    predict_mode.add_argument(
        "--allow-predict",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    predict_mode.add_argument(
        "--cache-only",
        action="store_true",
        help="只查询已有 future 缓存，不触发补算",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    build(
        args.date,
        horizon_len=args.horizon_len,
        context_len=args.context_len,
        allow_predict=not args.cache_only,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
