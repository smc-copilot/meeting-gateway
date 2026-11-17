#!/usr/bin/env bash
# Print the public egress IP this host uses toward Tencent Meeting.
# Usage (on the gateway host):
#   bash scripts/tencent-egress-ip.sh
#   bash scripts/tencent-egress-ip.sh --host api.meeting.qq.com
set -euo pipefail

TARGET_HOST="${1:-meeting.tencent.com}"
if [[ "${1:-}" == "--host" ]]; then
  TARGET_HOST="${2:?usage: $0 [--host hostname]}"
fi
TARGET_HOST="${TARGET_HOST#https://}"
TARGET_HOST="${TARGET_HOST%%/*}"

echo "=== proxy env ==="
echo "http_proxy=${http_proxy-}"
echo "https_proxy=${https_proxy-}"
echo "HTTP_PROXY=${HTTP_PROXY-}"
echo "HTTPS_PROXY=${HTTPS_PROXY-}"
echo "no_proxy=${no_proxy-}"
echo "NO_PROXY=${NO_PROXY-}"

echo
echo "=== resolve ${TARGET_HOST} ==="
if command -v getent >/dev/null 2>&1; then
  getent ahostsv4 "${TARGET_HOST}" | awk '{print $1}' | sort -u | head -5
elif command -v dig >/dev/null 2>&1; then
  dig +short A "${TARGET_HOST}" | head -5
else
  python3 - <<PY
import socket
print("\n".join(sorted({ai[4][0] for ai in socket.getaddrinfo("${TARGET_HOST}", 443, type=socket.SOCK_STREAM)})))
PY
fi

echo
echo "=== probe https://${TARGET_HOST}/ ==="
if curl -sS -o /dev/null -w "http_code=%{http_code} time=%{time_total}s remote_ip=%{remote_ip}\n" \
  --connect-timeout 8 --max-time 15 "https://${TARGET_HOST}/"; then
  :
else
  echo "WARN: HTTPS probe to ${TARGET_HOST} failed (exit $?)" >&2
fi

fetch_ip() {
  local label="$1"
  shift
  local ip=""
  local url
  for url in \
    "https://api.ipify.org" \
    "https://ifconfig.me/ip" \
    "https://myip.ipip.net"
  do
    if ip=$(curl -sS --connect-timeout 5 --max-time 10 "$@" "$url" 2>/dev/null | tr -d '\r' | head -1); then
      # ipip.net returns prose; extract first IPv4
      if [[ "$ip" =~ ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+) ]]; then
        ip="${BASH_REMATCH[1]}"
      fi
      if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "${label}=${ip}  (via ${url})"
        return 0
      fi
    fi
  done
  echo "${label}=UNAVAILABLE"
  return 1
}

echo
echo "=== public egress IP (same proxy env as this shell) ==="
fetch_ip "egress_with_env" || true

echo
echo "=== public egress IP (force direct, no proxy) ==="
(
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
  fetch_ip "egress_direct" || true
)

echo
echo "Put the IP that reaches Tencent (usually egress_with_env if the gateway process uses the same proxy) into the app IP whitelist."
echo "Tencent Meeting console: https://meeting.tencent.com/  (开放平台 → 应用安全 → 全局白名单)"
