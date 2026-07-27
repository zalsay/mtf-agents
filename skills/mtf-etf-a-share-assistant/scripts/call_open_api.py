#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://go-api.meetlife.com.cn/mtf-service"
DEFAULT_ENV_FILE = ".env.open-api"


def load_env_file(path):
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), unquote_env(value.strip()))


def unquote_env(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_json_arg(value):
    if not value:
        return None
    if value.startswith("@"):
        return json.loads(Path(value[1:]).read_text(encoding="utf-8"))
    return json.loads(value)


def clean_params(params):
    return {key: value for key, value in params.items() if value is not None}


def request_json(base_url, api_key, method, path, params=None, payload=None, extra_headers=None):
    base = base_url.rstrip("/")
    url = base + path
    params = clean_params(params or {})
    if params:
        url += "?" + urlencode(params)
    body = None
    headers = {"Authorization": f"Bearer {api_key}"}
    headers.update(clean_params(extra_headers or {}))
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=60) as response:
            data = response.read().decode("utf-8")
            return response.status, json.loads(data) if data else {}
    except HTTPError as exc:
        data = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(data)
        except json.JSONDecodeError:
            body = {"error": data}
        return exc.code, body
    except URLError as exc:
        raise SystemExit(f"request failed: {exc}") from exc


def build_parser():
    parser = argparse.ArgumentParser(description="Call FinTrack Open API endpoints for the MTF ETF skill.")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key")
    parser.add_argument("--env-file", default=os.environ.get("MTF_API_ENV_FILE", DEFAULT_ENV_FILE))
    parser.add_argument("--fintrack-user", help="Optional X-FinTrack-User external user alias")
    parser.add_argument("--request-id", help="Optional X-Request-Id for caller-side tracing")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("etf-hot")
    quotes = sub.add_parser("etf-quotes")
    quotes.add_argument("symbols", nargs="+")
    lookup = sub.add_parser("etf-lookup")
    lookup.add_argument("--symbol", required=True)

    best = sub.add_parser("mtf-best")
    best.add_argument("--symbol")
    best.add_argument("--stock-type", type=int)
    best.add_argument("--horizon-len", type=int)
    best.add_argument("--include-validation", choices=["true", "false"], default="true")

    by_config = sub.add_parser("mtf-best-by-config")
    by_config.add_argument("--symbol", required=True)
    by_config.add_argument("--stock-type", type=int, default=2)
    by_config.add_argument("--horizon-len", type=int)
    by_config.add_argument("--context-len", type=int)

    future = sub.add_parser("mtf-future")
    future.add_argument("--unique-key", required=True)
    future.add_argument("--predict-date", help="Only query the cached future chunk containing YYYY-MM-DD")

    predict_once = sub.add_parser("mtf-predict-once")
    add_predict_args(predict_once)
    predict_once.add_argument("--predict-date", help="Treat YYYY-MM-DD as the prediction date")
    predict_once.add_argument("--prefer-cache", action="store_true")

    predict_best = sub.add_parser("mtf-predict-best")
    add_predict_args(predict_best)
    predict_best.add_argument("--years", type=int, default=15)

    backtest = sub.add_parser("mtf-backtest")
    backtest.add_argument("--json", help="JSON body string, or @path/to/body.json")

    job = sub.add_parser("mtf-job")
    job.add_argument("--job-id", required=True)

    sub.add_parser("strategy-list")
    strategy_save = sub.add_parser("strategy-save")
    strategy_save.add_argument("--json", required=True, help="JSON body string, or @path/to/body.json")

    sub.add_parser("watchlist")
    watch_add = sub.add_parser("watchlist-add")
    watch_add.add_argument("--symbol", required=True)
    watch_add.add_argument("--stock-type", type=int, default=2)
    watch_add.add_argument("--notes")
    bind = sub.add_parser("watchlist-bind-strategy")
    bind.add_argument("--symbol", required=True)
    bind.add_argument("--stock-type", type=int, default=2)
    bind.add_argument("--strategy-unique-key", required=True)

    raw = sub.add_parser("raw")
    raw.add_argument("--method", choices=["GET", "POST"], required=True)
    raw.add_argument("--path", required=True)
    raw.add_argument("--params")
    raw.add_argument("--json")
    return parser


def add_predict_args(parser):
    parser.add_argument("--stock-code", required=True)
    parser.add_argument("--stock-type", type=int, default=2)
    parser.add_argument("--prediction-type", choices=["mtf-lite", "mtf-pro"], default="mtf-lite")
    parser.add_argument("--horizon-len", type=int, default=7)
    parser.add_argument("--context-len", type=int, default=512)


def command_to_request(args):
    if args.command == "etf-hot":
        return "GET", "/api/open/v1/etf/hot", None, None
    if args.command == "etf-quotes":
        return "POST", "/api/open/v1/etf/quotes", None, {"symbols": args.symbols}
    if args.command == "etf-lookup":
        return "GET", "/api/open/v1/etf/lookup", {"symbol": args.symbol}, None
    if args.command == "mtf-best":
        return "GET", "/api/open/v1/mtf/best", {
            "symbol": args.symbol,
            "stock_type": args.stock_type,
            "horizon_len": args.horizon_len,
            "include_validation": args.include_validation,
        }, None
    if args.command == "mtf-best-by-config":
        return "GET", "/api/open/v1/mtf/best/by-config", {
            "symbol": args.symbol,
            "stock_type": args.stock_type,
            "horizon_len": args.horizon_len,
            "context_len": args.context_len,
        }, None
    if args.command == "mtf-future":
        return "GET", "/api/open/v1/mtf/future", {
            "unique_key": args.unique_key,
            "predict_date": args.predict_date,
        }, None
    if args.command in ("mtf-predict-once", "mtf-predict-best"):
        payload = {
            "stock_code": args.stock_code,
            "stock_type": args.stock_type,
            "prediction_type": args.prediction_type,
            "horizon_len": args.horizon_len,
            "context_len": args.context_len,
        }
        if args.command == "mtf-predict-once":
            predict_date = getattr(args, "predict_date", None)
            if predict_date is not None:
                payload["predict_date"] = predict_date
            payload["prefer_cache"] = args.prefer_cache
            return "POST", "/api/open/v1/mtf/predict-once", None, payload
        payload["years"] = args.years
        return "POST", "/api/open/v1/mtf/predict-best", None, payload
    if args.command == "mtf-backtest":
        return "POST", "/api/open/v1/mtf/backtest", None, parse_json_arg(args.json) or {}
    if args.command == "mtf-job":
        return "GET", f"/api/open/v1/mtf/jobs/{args.job_id}", None, None
    if args.command == "strategy-list":
        return "GET", "/api/open/v1/strategy/list", None, None
    if args.command == "strategy-save":
        return "POST", "/api/open/v1/strategy/params", None, parse_json_arg(args.json)
    if args.command == "watchlist":
        return "GET", "/api/open/v1/watchlist", None, None
    if args.command == "watchlist-add":
        return "POST", "/api/open/v1/watchlist", None, {
            "symbol": args.symbol,
            "stock_type": args.stock_type,
            "notes": args.notes,
        }
    if args.command == "watchlist-bind-strategy":
        return "POST", "/api/open/v1/watchlist/bind-strategy", None, {
            "symbol": args.symbol,
            "stock_type": args.stock_type,
            "strategy_unique_key": args.strategy_unique_key,
        }
    if args.command == "raw":
        path = args.path if args.path.startswith("/") else "/" + args.path
        return args.method, path, parse_json_arg(args.params) or {}, parse_json_arg(args.json)
    raise SystemExit(f"unsupported command: {args.command}")


def main():
    parser = build_parser()
    args = parser.parse_args()
    load_env_file(args.env_file)
    args.base_url = args.base_url or os.environ.get("MTF_API_BASE_URL", DEFAULT_BASE_URL)
    args.api_key = args.api_key or os.environ.get("FINTRACK_OPEN_API_KEY") or os.environ.get("MTF_OPEN_API_KEY")
    if not args.api_key:
        raise SystemExit("missing API key: set FINTRACK_OPEN_API_KEY or run get_open_api_key.sh first")
    method, path, params, payload = command_to_request(args)
    extra_headers = {
        "X-FinTrack-User": args.fintrack_user,
        "X-Request-Id": args.request_id,
    }
    status, body = request_json(args.base_url, args.api_key, method, path, params, payload, extra_headers)
    print(json.dumps(body, ensure_ascii=False, indent=2))
    if status >= 400:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
