#!/usr/bin/env bash
set -euo pipefail

base_url="${MTF_API_BASE_URL:-https://go-api.meetlife.com.cn:9001}"
temp_token="${MTF_API_TEMP_TOKEN:-}"
username="${MTF_API_USERNAME:-}"
password="${MTF_API_PASSWORD:-}"
key_name="${MTF_API_KEY_NAME:-mtf-etf-a-share-assistant}"
env_file="${MTF_API_ENV_FILE:-.env.open-api}"
write_env=1

usage() {
  cat <<'USAGE' >&2
Usage:
  get_open_api_key.sh --temp-token TOKEN [--base-url URL] [--name KEY_NAME] [--env-file PATH] [--no-write-env]
  get_open_api_key.sh [--base-url URL] [--username USER] [--password PASS] [--name KEY_NAME] [--env-file PATH] [--no-write-env]

Environment:
  MTF_API_BASE_URL   Default: https://go-api.meetlife.com.cn:9001
  MTF_API_TEMP_TOKEN One-time token generated in FinTrack settings, valid for 5 minutes
  MTF_API_USERNAME   Legacy fallback: FinTrack username
  MTF_API_PASSWORD   Legacy fallback: FinTrack password
  MTF_API_KEY_NAME   Key name, default: mtf-etf-a-share-assistant
  MTF_API_ENV_FILE   Env output file, default: .env.open-api

By default this script writes MTF_API_BASE_URL and FINTRACK_OPEN_API_KEY
to .env.open-api, then prints the raw api_key once when a new key is created.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      base_url="${2:-}"
      shift 2
      ;;
    --temp-token)
      temp_token="${2:-}"
      shift 2
      ;;
    --username)
      username="${2:-}"
      shift 2
      ;;
    --password)
      password="${2:-}"
      shift 2
      ;;
    --name)
      key_name="${2:-}"
      shift 2
      ;;
    --env-file)
      env_file="${2:-}"
      shift 2
      ;;
    --no-write-env)
      write_env=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$base_url" || -z "$key_name" ]]; then
  echo "base URL and key name are required." >&2
  exit 2
fi

if [[ "$write_env" == "1" && -z "$env_file" ]]; then
  echo "env file path is required when env writing is enabled." >&2
  exit 2
fi

base_url="${base_url%/}"

if [[ -n "$temp_token" ]]; then
  endpoint="/api/open/v1/auth/api-key/from-token"
  payload="$(python3 - "$temp_token" "$key_name" <<'PY'
import json
import sys

print(json.dumps({
    "token": sys.argv[1],
    "name": sys.argv[2],
}, ensure_ascii=False))
PY
)"
else
  echo "No temporary token provided; falling back to legacy username/password API key creation." >&2
  if [[ -z "$username" ]]; then
    read -r -p "FinTrack username: " username
  fi

  if [[ -z "$password" ]]; then
    read -r -s -p "FinTrack password: " password
    echo >&2
  fi

  if [[ -z "$username" || -z "$password" ]]; then
    echo "temporary token, or username and password, are required." >&2
    exit 2
  fi

  endpoint="/api/open/v1/auth/api-key"
  payload="$(python3 - "$username" "$password" "$key_name" <<'PY'
import json
import sys

print(json.dumps({
    "username": sys.argv[1],
    "password": sys.argv[2],
    "name": sys.argv[3],
}, ensure_ascii=False))
PY
)"
fi

response="$(curl -fsS \
  -H 'Content-Type: application/json' \
  -X POST \
  --data "$payload" \
  "$base_url$endpoint")"

python3 - "$response" "$write_env" "$env_file" "$base_url" <<'PY'
import json
import os
import shlex
import sys

body = json.loads(sys.argv[1])
write_env = sys.argv[2] == "1"
env_file = sys.argv[3]
base_url = sys.argv[4]

status = body.get("status")
if status not in ("ok", "success"):
    error = body.get("error") or {}
    code = error.get("code", "request_failed")
    message = error.get("message", "failed to create API key")
    raise SystemExit(f"{code}: {message}")

api_key = (body.get("data") or {}).get("api_key")
if not api_key:
    data = body.get("data") or {}
    if data.get("has_existing_key"):
        name = data.get("name", "existing key")
        raise SystemExit(
            f"FinTrack already has an active Open API key ({name}), "
            "but raw keys are only shown when newly created. "
            "Set FINTRACK_OPEN_API_KEY to the existing key, or revoke it and redeem a new temporary token."
        )
    raise SystemExit("response did not include data.api_key")

if write_env:
    updates = {
        "MTF_API_BASE_URL": base_url,
        "FINTRACK_OPEN_API_KEY": api_key,
    }
    lines = []
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as existing:
            for line in existing:
                key = line.split("=", 1)[0].strip()
                if key not in updates:
                    lines.append(line.rstrip("\n"))
    for key, value in updates.items():
        lines.append(f"{key}={shlex.quote(value)}")
    parent = os.path.dirname(os.path.abspath(env_file))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(env_file, "w", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")
    print(f"Wrote {env_file}", file=sys.stderr)

print(api_key)
PY
