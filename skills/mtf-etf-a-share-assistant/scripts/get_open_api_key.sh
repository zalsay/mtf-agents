#!/usr/bin/env bash
set -euo pipefail

base_url="${MTF_API_BASE_URL:-https://go-api.meetlife.com.cn/mtf-service}"
temp_token="${MTF_API_TEMP_TOKEN:-}"
username="${MTF_API_USERNAME:-}"
password="${MTF_API_PASSWORD:-}"
key_name="${MTF_API_KEY_NAME:-mtf-etf-a-share-assistant}"
v2=0
server_name="${MTF_API_V2_SERVER_NAME:-}"
external_user_id="${MTF_API_V2_USER_ID:-}"
env_file="${MTF_API_ENV_FILE:-.env.open-api}"
write_env=1

usage() {
  cat <<'USAGE' >&2
Usage:
  get_open_api_key.sh --v2 --server-name NAME --user-id USER_ID [--base-url URL] [--env-file PATH] [--no-write-env]
  get_open_api_key.sh --temp-token TOKEN [--base-url URL] [--name KEY_NAME] [--env-file PATH] [--no-write-env]
  get_open_api_key.sh [--base-url URL] [--username USER] [--password PASS] [--name KEY_NAME] [--env-file PATH] [--no-write-env]

Environment:
  MTF_API_BASE_URL   Default: https://go-api.meetlife.com.cn/mtf-service
  MTF_API_TEMP_TOKEN One-time token generated in FinTrack settings, valid for 5 minutes
  MTF_API_USERNAME   Legacy fallback: FinTrack username
  MTF_API_PASSWORD   Legacy fallback: FinTrack password
  MTF_API_KEY_NAME   Key name, default: mtf-etf-a-share-assistant
  MTF_API_V2_SERVER_NAME  v2 external caller name
  MTF_API_V2_USER_ID      v2 external caller user id
  MTF_API_ENV_FILE   Env output file, default: .env.open-api

By default this script writes MTF_API_BASE_URL and the selected API key variable
to .env.open-api, then prints the newly exchanged api_key once.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --v2)
      v2=1
      shift
      ;;
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
    --server-name)
      server_name="${2:-}"
      shift 2
      ;;
    --user-id)
      external_user_id="${2:-}"
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

if [[ -z "$base_url" ]]; then
  echo "base URL is required." >&2
  exit 2
fi

if [[ "$v2" == "1" && ( -z "$server_name" || -z "$external_user_id" ) ]]; then
  echo "v2 mode requires server name and user id." >&2
  exit 2
fi

if [[ "$write_env" == "1" && -z "$env_file" ]]; then
  echo "env file path is required when env writing is enabled." >&2
  exit 2
fi

base_url="${base_url%/}"

if [[ "$v2" == "1" ]]; then
  if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl is required for v2 API key creation." >&2
    exit 2
  fi
  tmp_dir="$(mktemp -d)"
  cleanup_v2() {
    rm -f "$tmp_dir/public.pem" "$tmp_dir/payload.json" "$tmp_dir/ciphertext.bin"
    rmdir "$tmp_dir" 2>/dev/null || true
  }
  trap cleanup_v2 EXIT

  public_response="$(curl -fsS "$base_url/api/open/v2/auth/public-key")"
  python3 - "$public_response" "$tmp_dir/public.pem" <<'PY'
import json
import sys

body = json.loads(sys.argv[1])
public_key = (body.get("data") or {}).get("public_key")
if not public_key:
    error = body.get("error") or {}
    raise SystemExit(f"{error.get('code', 'public_key_failed')}: {error.get('message', 'public key missing')}")
with open(sys.argv[2], "w", encoding="ascii") as output:
    output.write(public_key)
PY

  python3 - "$server_name" "$external_user_id" > "$tmp_dir/payload.json" <<'PY'
import json
import sys
import time

print(json.dumps({
    "server_name": sys.argv[1],
    "user_id": sys.argv[2],
    "timestamp": int(time.time()),
}, separators=(",", ":")))
PY
  openssl pkeyutl -encrypt \
    -pubin -inkey "$tmp_dir/public.pem" \
    -in "$tmp_dir/payload.json" -out "$tmp_dir/ciphertext.bin" \
    -pkeyopt rsa_padding_mode:oaep \
    -pkeyopt rsa_oaep_md:sha256 \
    -pkeyopt rsa_mgf1_md:sha256 \
    >/dev/null 2>&1
  encrypted_payload="$(base64 -w0 "$tmp_dir/ciphertext.bin" | tr '+/' '-_' | tr -d '=')"
  endpoint="/api/open/v2/auth/api-key"
  payload="$(python3 - "$encrypted_payload" <<'PY'
import json
import sys

print(json.dumps({"encrypted_payload": sys.argv[1]}, separators=(",", ":")))
PY
)"
elif [[ -n "$temp_token" ]]; then
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

python3 - "$response" "$write_env" "$env_file" "$base_url" "$v2" <<'PY'
import json
import os
import shlex
import sys

body = json.loads(sys.argv[1])
write_env = sys.argv[2] == "1"
env_file = sys.argv[3]
base_url = sys.argv[4]
v2_mode = sys.argv[5] == "1"

status = body.get("status")
if status not in ("ok", "success"):
    error = body.get("error") or {}
    code = error.get("code", "request_failed")
    message = error.get("message", "failed to create API key")
    raise SystemExit(f"{code}: {message}")

api_key = (body.get("data") or {}).get("api_key")
if not api_key:
    data = body.get("data") or {}
    raise SystemExit("response did not include data.api_key")

if write_env:
    updates = {
        "MTF_API_BASE_URL": base_url,
        ("MTF_OPEN_API_V2_KEY" if v2_mode else "FINTRACK_OPEN_API_KEY"): api_key,
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
