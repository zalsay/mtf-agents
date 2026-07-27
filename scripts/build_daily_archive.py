#!/usr/bin/env python3
"""构建当日 MTF future 归档 (reports/mtf-etf/YYYY-MM-DD/YYYY-MM-DD-mtf-future.json)。

该脚本供每日自动化工作流第 1 步调用: 自动从 Open API 拉取
- etf-hot 热门 ETF 雷达, 持久化为本地快照 YYYY-MM-DD-etf-hot.json (候选"发现源")
- watchlist 候选与每只标的的 mtf-future 预测 (含异步 job 轮询)
用 easy-tdx(QFQ) 回填当日实际收盘, 组装成
normalize_mtf_future_archive.py 能吃掉的归档 JSON。

关键约束:
- close_observation.source 必须为 'easy_tdx_qfq_daily_kline' (前复权口径),
  与 easy-tdx 拉取的路径点一致, 避免 split_adjustments.json 的份额拆分因子被重复计算。
- ETF 预测只用 mtf-pro; 若 mtf-future 返回 job, 用 mtf-job 轮询至 succeeded 后重拉。

用法:
    python3 scripts/build_daily_archive.py [--date YYYY-MM-DD] [--dry-run]
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
INDEX_KEY = "idx000001_best_hlen_7_clen_2048_v_2.5_mtf-pro"
CRASH_THRESHOLD = -3.0
# ETF 代码特征: 沪市 5xxxxx / 深市 1xxxxx
ETF_RE = re.compile(r"^(5|1)\d{5}$")
# 规整 symbol -> 名称 (来自 watchlist 的 company_name)
NAME_MAP = {}


def call_api(sub, *args):
    cmd = [
        sys.executable, str(SCRIPTS / "call_open_api.py"),
        "--env-file", str(ENV), sub, *args,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"call_open_api {sub} 失败 rc={r.returncode}: {r.stderr[:500]}")
    return json.loads(r.stdout)


def get_candidates():
    """返回 {规整symbol: unique_key}，仅含 ETF/基金类标的。

    watchlist 的 symbol 带交易所前缀 (sh/sz/bj)，需先去掉；并用 stock_type==2
    或 ETF 代码特征 (5xxxxx 沪市 / 1xxxxx 深市) 过滤。上证指数不在 watchlist 内，
    由 build_index_risk 单独处理。
    """
    d = call_api("watchlist")
    wl = (d.get("data") or {}).get("watchlist", [])
    out = {}
    for w in wl:
        st = w.get("stock") or {}
        raw_sym = str(st.get("symbol", "") or "")
        uk = w.get("unique_key") or ""
        if not raw_sym or not uk:
            continue
        sym = re.sub(r"^(sh|sz|bj)", "", raw_sym, flags=re.I) or raw_sym
        stype = w.get("stock_type")
        is_etf = (str(stype) == "2") or bool(ETF_RE.match(sym))
        if is_etf:
            out[sym] = uk
            NAME_MAP[sym] = st.get("company_name", "") or ""
            print(f"[cand] {raw_sym} -> {sym} ({NAME_MAP[sym]})")
    return out


def get_watchlist_name(sym):
    return NAME_MAP.get(sym, "")


def fetch_and_save_etf_hot(report_date, out_dir, dry_run=False):
    """拉取 etf-hot 热门 ETF 雷达并持久化为本地 JSON 快照 (best-effort, 非致命)。

    这是候选"发现源"的本地落盘：etf-hot 只给热门雷达元数据（不给 MTF 预测），
    MTF 预测按权限只能在 watchlist 内拉取。上游偶发不可用时不影响主归档，仅记录错误。
    返回写出路径；失败时返回 None。
    """
    try:
        raw = call_api("etf-hot")
    except Exception as e:
        print(f"[etf-hot][warn] 拉取失败, 跳过快照: {e}")
        return None
    envelope_err = (raw.get("status") == "error") or bool(raw.get("error"))
    payload = {
        "report_date": report_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "GET /api/open/v1/etf/hot",
        "ok": not envelope_err,
        "data": (raw.get("data") or {}),
        "error": raw.get("error") if envelope_err else None,
        "raw_response": raw,
    }
    out_path = out_dir / f"{report_date}-etf-hot.json"
    if dry_run:
        print(f"[dry-run] 将写入 {out_path} (etf-hot 快照, ok={not envelope_err})")
        return out_path
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    hot = (raw.get("data") or {})
    print(f"[etf-hot] 已保存 {out_path} (ok={not envelope_err}, data keys={list(hot.keys())})")
    return out_path


def build_index_risk(report_date):
    resp = fetch_mtf_future(INDEX_KEY)
    fdates = resp.get("future_dates") or []
    pct = resp.get("predicted_change_percent") or []
    target = report_date if report_date in fdates else (fdates[-1] if fdates else report_date)
    expected = pct[fdates.index(report_date)] if report_date in fdates else (pct[-1] if pct else 0.0)
    triggered = expected <= CRASH_THRESHOLD
    return {
        "name": "上证指数",
        "symbol": "idx000001",
        "target_date": target,
        "expected_change_percent": round(expected, 4),
        "crash_threshold_percent": CRASH_THRESHOLD,
        "triggered": triggered,
        "buy_blocked": False,
        "status": "pass" if not triggered else "reject",
        "note": ("上证指数同日预计涨跌未触发大盘大跌风控"
                 if not triggered else "上证指数同日预计涨跌触发大盘大跌风控"),
    }


def fetch_mtf_future(key):
    d = call_api("mtf-future", "--unique-key", key)
    data = (d.get("data") or {})
    job_id = data.get("job_id")
    if job_id and not data.get("success"):
        for _ in range(40):  # 最多等 ~10 分钟
            j = call_api("mtf-job", "--job-id", job_id).get("data") or {}
            if j.get("status") == "succeeded" or j.get("success"):
                break
            time.sleep(15)
        else:
            raise RuntimeError(f"mtf-future job {job_id} 轮询超时")
        d = call_api("mtf-future", "--unique-key", key)
        data = (d.get("data") or {})
    if not data.get("predicted_change_percent") and not data.get("future_dates"):
        raise RuntimeError(f"{key} 未返回有效预测")
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


def build(report_date, dry_run=False):
    out_dir = ROOT / "reports" / "mtf-etf" / report_date
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 候选"发现源"快照: etf-hot 热门 ETF 雷达落盘 (best-effort, 失败不影响主归档)
    try:
        fetch_and_save_etf_hot(report_date, out_dir, dry_run=dry_run)
    except Exception as e:
        print(f"[warn] etf-hot 快照写入失败 (不影响 mtf-future 主归档): {e}")

    # 2) 操作边界: watchlist 候选 -> mtf-future 预测归档
    cands = get_candidates()
    print(f"[build] {report_date}: {len(cands)} 个 ETF 候选")

    items = []
    for sym, key in cands.items():
        try:
            resp = fetch_mtf_future(key)
            name = (get_watchlist_name(sym) or resp.get("short_name")
                    or resp.get("name") or sym)
            actual, actual_date = fetch_close_best_effort(sym, report_date)
        except Exception as e:
            print(f"[warn] ETF {sym} 跳过 (预测/行情获取失败): {e}")
            continue
        items.append({
            "symbol": sym,
            "name": name,
            "theme": "",
            "horizon_days": resp.get("horizon_len", 7),
            "raw_response": {"data": resp},
            "close_observation": {
                "date": actual_date,
                "close": round(actual, 4),
                "source": "easy_tdx_qfq_daily_kline",
            },
        })
        print(f"[build] ETF {sym} {name}: {report_date} 实际收盘 = {actual} (obs {actual_date})")

    try:
        index_risk = build_index_risk(report_date)
        print(f"[build] 上证指数同日预计 {index_risk['expected_change_percent']:+.4f}% "
              f"triggered={index_risk['triggered']}")
    except Exception as e:
        print(f"[warn] 上证指数风控获取失败: {e}")
        index_risk = {
            "name": "上证指数", "symbol": "idx000001", "target_date": report_date,
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
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    build(args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
