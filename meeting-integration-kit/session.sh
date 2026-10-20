# 在工具包目录执行 source ./session.sh；先配置 MEETING_REPO、MEETING_BASE_URL。
umask 077
mkdir -p private evidence
chmod 700 private evidence
admin() { python3 tools/call.py --auth-file private/backend-a.token "$@"; }
member() { python3 tools/call.py --auth-file private/gateway-a.token "$@"; }
