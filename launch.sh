#!/usr/bin/env bash
# ============================================================================
# launch.sh — nodeskclaw-meeting 源码启动器（api + worker），不依赖 docker
#
# 用法：
#   bash launch.sh start      # 停 docker 容器 → 迁移 → 启动 api+worker → 健康检查
#   bash launch.sh stop       # 停止 api+worker
#   bash launch.sh restart    # stop + start
#   bash launch.sh status     # 进程/端口/健康/DB 连通性
#   bash launch.sh logs       # tail -f api 与 worker 日志
#   bash launch.sh migrate    # 只跑 alembic upgrade head
#   bash launch.sh dbcheck    # 只验证数据库连通/认证/表数量/迁移版本（不起服务）
#   bash launch.sh docker-stop# 只停 docker compose 服务（保留容器与数据卷，可回滚）
#
# 可选环境变量：
#   API_PORT=4522  API_BIND=127.0.0.1  PYTHON_BIN=/usr/bin/python3.12
#   SKIP_MIGRATE=1        跳过 alembic 迁移
#   NO_STOP_DOCKER=1      不自动停 docker（端口冲突时自行处理）
#   SKIP_DEPS=1           跳过依赖安装（venv 已就绪时自动跳过）
# ============================================================================
set -uo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")"
REPO="$(cd "$(dirname "$SELF")" && pwd)"
chmod +x "$SELF" 2>/dev/null

VENV="$REPO/.venv"
PY="$VENV/bin/python"
LOGDIR="$REPO/logs"
RUNDIR="$REPO/run"
ENVF="$REPO/.env"
COMPOSE="$REPO/deploy/compose.yaml"
PROJECT=nodeskclaw-meeting

API_PORT="${API_PORT:-4522}"
API_BIND="${API_BIND:-127.0.0.1}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3.12}"
SKIP_MIGRATE="${SKIP_MIGRATE:-0}"
NO_STOP_DOCKER="${NO_STOP_DOCKER:-0}"
SKIP_DEPS="${SKIP_DEPS:-0}"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  \033[32mPASS\033[0m %s\n' "$*"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; }
info() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
die()  { printf '\n\033[31mFATAL\033[0m %s\n' "$*" >&2; exit 1; }

mkdir -p "$LOGDIR" "$RUNDIR"

api_pid()    { [ -f "$RUNDIR/api.pid" ] && cat "$RUNDIR/api.pid" 2>/dev/null; }
worker_pid() { [ -f "$RUNDIR/worker.pid" ] && cat "$RUNDIR/worker.pid" 2>/dev/null; }
alive()      { local p="${1:-}"; [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
port_pids()  { ss -ltnp 2>/dev/null | awk -v p=":$API_PORT" '$4 ~ p"$" {print}' | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u | tr '\n' ' '; }
mask_url()   { sed -E 's#//[^:/@]+:[^@]*@#//***:***@#g' <<<"${1:-}"; }

# ---------------------------------------------------------------- 1. .env/DB
load_database_url() {
  [ -f "$ENVF" ] || die ".env 不存在：$ENVF"
  local raw
  raw="$(grep -E '^[[:space:]]*DATABASE_URL=' "$ENVF" | head -1 | cut -d= -f2-)"
  raw="${raw%\"}"; raw="${raw#\"}"; raw="${raw%\'}"; raw="${raw#\'}"
  raw="$(printf '%s' "$raw" | tr -d '\r' | sed -E 's/[[:space:]]+$//')"
  [ -n "$raw" ] || die ".env 里没有 DATABASE_URL"

  # 已知笔误：scheme 重复了两次
  #   postgresql+asyncpg://postgresql+asyncpg://user:pass@host:5432/db
  if [[ "$raw" == *"://postgresql+asyncpg://"* ]]; then
    warn "DATABASE_URL 的 scheme 重复（'postgresql+asyncpg://' 出现两次），本次已自动纠正"
    warn "建议你把 .env 里那一行手动改成：$(mask_url "${raw/:\/\/postgresql+asyncpg:\/\//:\/\/}")"
    raw="${raw/:\/\/postgresql+asyncpg:\/\//:\/\/}"
  fi

  # 校验：必须能被 SQLAlchemy 解析，且带 host/port/dbname
  DB_URL="$("$PY" - "$raw" <<'PY' 2>/dev/null
import sys
from urllib.parse import urlsplit
raw = sys.argv[1]
p = urlsplit(raw)
assert p.scheme == "postgresql+asyncpg", f"scheme={p.scheme}"
assert p.hostname, "no hostname"
assert p.port, "no port"
assert p.path and p.path.strip("/"), "no database name"
print(raw)
PY
)" || die "DATABASE_URL 无法解析（原始值：$(mask_url "$raw")）"

  DB_HOST="$(printf '%s' "$DB_URL" | sed -E 's#^[a-z+]+://([^@]*@)?([^:/]+).*#\2#')"
  DB_PORT="$(printf '%s' "$DB_URL" | sed -E 's#^[a-z+]+://([^@]*@)?[^:/]+:([0-9]+).*#\2#')"
  DB_NAME="$(printf '%s' "$DB_URL" | sed -E 's#^[a-z+]+://[^/]+/([^?]+).*#\1#')"
  export DATABASE_URL="$DB_URL"
  ok "DATABASE_URL 有效 → $(mask_url "$DB_URL")"
}

check_db_tcp() {
  if timeout 5 bash -c "cat < /dev/null > /dev/tcp/$DB_HOST/$DB_PORT" 2>/dev/null; then
    ok "数据库端口可达 $DB_HOST:$DB_PORT"
  else
    die "数据库不可达 $DB_HOST:$DB_PORT —— 检查网络/防火墙/pg_hba"
  fi
}

# 真实认证 + 库存在性 + 版本（需要 venv 已装 asyncpg）
check_db_auth() {
  local out
  if out="$("$PY" - "$DB_URL" <<'PY' 2>&1
import asyncio, sys
from urllib.parse import urlsplit, unquote
import asyncpg

raw = sys.argv[1]
p = urlsplit(raw)
async def main():
    conn = await asyncpg.connect(
        user=unquote(p.username or ""), password=unquote(p.password or ""),
        host=p.hostname, port=p.port or 5432, database=p.path.lstrip("/"),
        timeout=8,
    )
    try:
        db = await conn.fetchval("select current_database()")
        ver = await conn.fetchval("show server_version")
        tables = await conn.fetchval(
            "select count(*) from information_schema.tables "
            "where table_schema='public' and table_type='BASE TABLE'")
        alv = await conn.fetchval(
            "select version_num from alembic_version") if await conn.fetchval(
            "select to_regclass('public.alembic_version') is not null") else None
        print(f"db={db} server={ver} tables={tables} alembic={alv or 'NONE'}")
    finally:
        await conn.close()
asyncio.run(main())
PY
)"; then
    ok "数据库认证成功 → $out"
  else
    printf '%s\n' "$out" | tail -12
    die "数据库认证失败（用户名/密码/库名/pg_hba 任一不符）"
  fi
}

# ---------------------------------------------------------------- 2. venv/依赖
ensure_venv() {
  if [ -x "$PY" ]; then ok "venv 已存在（$("$PY" -V 2>&1)）"; return; fi
  [ -x "$PYTHON_BIN" ] || die "找不到 $PYTHON_BIN（pyproject 要求 Python>=3.12,<3.15）"
  command -v uv >/dev/null || die "找不到 uv"
  uv venv --python "$PYTHON_BIN" "$VENV" >/dev/null 2>&1 || die "uv venv 创建失败"
  [ -x "$PY" ] || die "venv 创建后仍无 python"
  ok "venv 创建完成 $("$PY" -V 2>&1)"
}

deps_ok() { "$PY" -c 'import fastapi,uvicorn,asyncpg,sqlalchemy,pydantic_settings,alembic,httpx,multipart' >/dev/null 2>&1; }

ensure_deps() {
  [ "$SKIP_DEPS" = "1" ] && { warn "SKIP_DEPS=1，跳过依赖检查"; return; }
  if deps_ok; then ok "依赖已就绪"; return; fi
  cd "$REPO" || die "cd $REPO 失败"

  if curl -fsS -m 8 -o /dev/null https://pypi.org/simple/ 2>/dev/null; then
    info "安装依赖（uv pip install -e .）"
    uv pip install --python "$PY" -e "$REPO" 2>&1 | tail -12
    deps_ok && ok "依赖安装完成" || die "依赖安装后仍缺包（看上面的 pip 输出）"
    return
  fi

  warn "PyPI 不可达，改用离线路径：从现有 docker 镜像复制 site-packages"
  local img
  img="$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "^$PROJECT:" | head -1)"
  [ -n "$img" ] || die "离线安装需要镜像 $PROJECT:xxx，但本地没有；请先联网装依赖"
  local tmp="mg_dep_$$"
  docker create --name "$tmp" "$img" >/dev/null || die "创建临时容器失败"
  local site="$VENV/lib/python3.12/site-packages"
  mkdir -p "$site"
  docker cp "$tmp:/usr/local/lib/python3.12/site-packages/." "$site/" || { docker rm -f "$tmp" >/dev/null; die "复制 site-packages 失败"; }
  docker rm -f "$tmp" >/dev/null
  deps_ok && ok "离线依赖就绪（来源镜像 $img）" || die "离线依赖仍缺包"
}

preflight_config() {
  cd "$REPO" || die "cd $REPO 失败"
  local out
  if out="$("$PY" -c 'from app.core.config import Settings; Settings()' 2>&1)"; then
    ok "Settings 校验通过（ENVIRONMENT / KEYRING / 腾讯 webhook / URL 均为生产合法）"
  else
    printf '%s\n' "$out" | tail -15
    die "Settings 校验失败 —— 上面的 ValueError 就是 .env 里要改的字段"
  fi
  "$PY" -c 'from app.main import create_app' >/dev/null 2>&1 \
    && ok "app.main 可导入" || die "app.main 导入失败，跑：$PY -c 'from app.main import create_app'"
}

# ---------------------------------------------------------------- 3. docker
docker_stop() {
  [ "$NO_STOP_DOCKER" = "1" ] && { warn "NO_STOP_DOCKER=1，不停 docker"; return; }
  command -v docker >/dev/null || { warn "本机无 docker，跳过"; return; }
  local running
  running="$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null)"
  if [ -z "$running" ]; then ok "docker 项目 $PROJECT 已无运行容器"; return; fi

  info "停用 docker 部署（保留容器与数据卷，可回滚）"
  docker ps --filter "label=com.docker.compose.project=$PROJECT" \
    --format '  {{.Names}}\t{{.Image}}\t{{.Status}}'
  if [ -f "$COMPOSE" ]; then
    if ! docker compose --env-file "$ENVF" -f "$COMPOSE" stop 2>&1 | tail -8; then
      warn "compose stop 未成功，改用 docker stop"
      docker stop $running >/dev/null 2>&1
    fi
    # 双保险：compose 静默失败时按容器 id 再停一次
    local still
    still="$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null)"
    [ -n "$still" ] && docker stop $still >/dev/null 2>&1
  else
    warn "找不到 $COMPOSE，改用 docker stop"
    docker stop $running >/dev/null 2>&1
  fi
  local left
  left="$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null | wc -l)"
  [ "$left" -eq 0 ] && ok "docker 容器已全部停止（数据卷保留）" || bad "仍有 $left 个容器在运行"
}

stop_legacy_source() {
  # 上一轮用过 systemd --user unit（meeting-gateway.service）+ mg-run-source.sh 包装器，
  # 那个包装器会把 DATABASE_URL 改写成 docker postgres 的地址，与现在的 .env 冲突。
  local changed=0
  if command -v systemctl >/dev/null && systemctl --user list-unit-files 2>/dev/null | grep -q '^meeting-gateway\.service'; then
    if systemctl --user is-active --quiet meeting-gateway.service 2>/dev/null; then
      systemctl --user stop meeting-gateway.service 2>/dev/null && changed=1
      ok "已停止旧 systemd unit meeting-gateway.service"
    fi
    systemctl --user disable meeting-gateway.service >/dev/null 2>&1 && \
      ok "已 disable 旧 unit（否则重启机器会抢回 4522）" || true
  fi
  if pkill -f 'mg-run-source\.sh' 2>/dev/null; then ok "已清理旧包装器 mg-run-source.sh"; changed=1; fi
  # 只清理本项目起出来的 uvicorn/worker，避免误杀别的服务
  local strays
  strays="$(pgrep -af "uvicorn app\.main:create_app" 2>/dev/null | grep -F "$REPO" | awk '{print $1}')"
  if [ -n "$strays" ]; then
    kill -TERM $strays 2>/dev/null
    for _ in $(seq 1 10); do pgrep -f "uvicorn app\.main:create_app" >/dev/null 2>&1 || break; sleep 1; done
    ok "已终止遗留 uvicorn pid=$(echo $strays | tr '\n' ' ')"
    changed=1
  fi
  local stw
  stw="$(pgrep -af "python.*-m app\.worker" 2>/dev/null | grep -F "$REPO" | awk '{print $1}')"
  [ -n "$stw" ] && { kill -TERM $stw 2>/dev/null; ok "已终止遗留 worker pid=$(echo $stw | tr '\n' ' ')"; changed=1; }
  [ "$changed" = "0" ] && ok "无遗留源码进程"
}

# ---------------------------------------------------------------- 4. 迁移
run_migrate() {
  [ "$SKIP_MIGRATE" = "1" ] && { warn "SKIP_MIGRATE=1，跳过迁移"; return; }
  cd "$REPO" || die "cd $REPO 失败"
  info "数据库迁移 alembic upgrade head"
  local out
  if out="$("$PY" -m alembic upgrade head 2>&1)"; then
    printf '%s\n' "$out" | tail -10
    ok "迁移完成（或已是最新）"
  else
    printf '%s\n' "$out" | tail -25
    bad "迁移失败"
  fi
}

# ---------------------------------------------------------------- 5. 启动
start_api() {
  cd "$REPO" || die "cd $REPO 失败"
  nohup "$PY" -m uvicorn app.main:create_app --factory \
    --host "$API_BIND" --port "$API_PORT" --no-access-log \
    >>"$LOGDIR/api.log" 2>&1 &
  echo $! > "$RUNDIR/api.pid"
  sleep 3
  alive "$(api_pid)" && ok "api 已启动 pid=$(api_pid) → $API_BIND:$API_PORT" \
    || { bad "api 启动即退出"; tail -25 "$LOGDIR/api.log"; }
}

start_worker() {
  cd "$REPO" || die "cd $REPO 失败"
  nohup "$PY" -m app.worker >>"$LOGDIR/worker.log" 2>&1 &
  echo $! > "$RUNDIR/worker.pid"
  sleep 3
  alive "$(worker_pid)" && ok "worker 已启动 pid=$(worker_pid)" \
    || { bad "worker 启动即退出"; tail -25 "$LOGDIR/worker.log"; }
}

wait_health() {
  local i
  for i in $(seq 1 40); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' -m 2 "http://$API_BIND:$API_PORT/health/live" 2>/dev/null)" = "200" ] && return 0
    sleep 2
  done
  return 1
}

verify() {
  wait_health && ok "/health/live = 200" || { bad "/health/live 80s 内未就绪"; tail -30 "$LOGDIR/api.log"; }
  local ready; ready="$(curl -s -m 5 "http://$API_BIND:$API_PORT/health/ready" 2>/dev/null)"
  if grep -q '"database":true' <<<"$ready"; then ok "ready database=true → $DB_NAME@$DB_HOST:$DB_PORT"
  else bad "ready 未连上库 → ${ready:-无响应}"; fi

  local owner; owner="$(port_pids)"
  if [ -n "$owner" ]; then ok "端口 $API_PORT 属主 pid=$owner（应为 $PY 的子进程，不是 docker-proxy）"
  else warn "未能解析端口属主"; fi

  local code
  code="$(curl -sk -m 10 --resolve "copilot.superic.com:9999:127.0.0.1" -o /dev/null -w '%{http_code}' \
    -G 'https://copilot.superic.com:9999/api/v1/oauth/authorizations' \
    --data-urlencode 'continue_to=https://copilot.superic.com:9999/meeting/done' 2>/dev/null)"
  [ "$code" = "200" ] && ok "经 nginx 签发授权 URL = 200" || warn "经 nginx = ${code:-失败}（若 nginx 未运行可忽略）"

  printf '\n  日志：%s\n  API  %s  %s\n' "$LOGDIR/{api,worker}.log" "$(api_pid)" "$(worker_pid)"
}

do_stop() {
  info "停止源码进程"
  for name in api worker; do
    local p; p="$([ "$name" = api ] && api_pid || worker_pid)"
    if alive "$p"; then
      kill -TERM "$p" 2>/dev/null
      for _ in $(seq 1 15); do alive "$p" || break; sleep 1; done
      alive "$p" && { kill -9 "$p" 2>/dev/null; warn "$name 强制杀掉 pid=$p"; } || ok "$name 已停止 pid=$p"
    else
      ok "$name 未运行"
    fi
    rm -f "$RUNDIR/$name.pid"
  done
}

# ---------------------------------------------------------------- 6. status
do_status() {
  info "进程"
  alive "$(api_pid)"    && ok "api    running pid=$(api_pid)"    || bad "api    not running"
  alive "$(worker_pid)" && ok "worker running pid=$(worker_pid)" || bad "worker not running"
  info "端口"
  ss -ltnp 2>/dev/null | awk -v p=":$API_PORT" '$4 ~ p"$"' || echo "  $API_PORT 未监听"
  info "健康"
  printf '  live=%s  ready=%s\n' \
    "$(curl -s -o /dev/null -w '%{http_code}' -m 3 "http://$API_BIND:$API_PORT/health/live" 2>/dev/null)" \
    "$(curl -s -m 3 "http://$API_BIND:$API_PORT/health/ready" 2>/dev/null)"
  info "数据库"
  [ -n "${DB_HOST:-}" ] && printf '  target=%s:%s/%s  tcp=%s\n' "$DB_HOST" "$DB_PORT" "$DB_NAME" \
    "$(timeout 3 bash -c "cat < /dev/null > /dev/tcp/$DB_HOST/$DB_PORT" 2>/dev/null && echo ok || echo unreachable)"
  info "docker（应为空）"
  docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '  {{.Names}} {{.Status}}' 2>/dev/null || true
  info "日志尾部"
  tail -5 "$LOGDIR/api.log" 2>/dev/null | sed 's/^/  api | /'
  tail -5 "$LOGDIR/worker.log" 2>/dev/null | sed 's/^/  worker | /'
}

# ---------------------------------------------------------------- main
CMD="${1:-start}"
cd "$REPO" || die "cd $REPO 失败"

case "$CMD" in
  start)
    info "0. 载入配置"
    ensure_venv
    load_database_url
    check_db_tcp
    info "1. 依赖"
    ensure_deps
    info "2. 数据库认证"
    check_db_auth
    info "3. 配置校验"
    preflight_config
    info "4. 停用 docker 与旧源码进程"
    docker_stop
    stop_legacy_source
    if [ -n "$(port_pids)" ]; then
      bad "端口 $API_PORT 仍被占用 pid=$(port_pids)"
      die "先释放端口。若是 docker：docker ps --filter label=com.docker.compose.project=$PROJECT"
    fi
    ok "端口 $API_PORT 空闲"
    run_migrate
    info "5. 启动"
    start_api
    start_worker
    info "6. 验证"
    verify
    printf '\n\033[1mPASS=%d FAIL=%d\033[0m\n' "$PASS" "$FAIL"
    [ "$FAIL" -eq 0 ] && printf '\033[32m启动成功。\033[0m nginx 无需改动（upstream 仍是 127.0.0.1:%s）\n' "$API_PORT" || printf '\033[31m有 %d 项失败，看上面的日志路径。\033[0m\n' "$FAIL"
    [ "$FAIL" -eq 0 ]
    ;;
  stop)       do_stop ;;
  restart)    do_stop; exec bash "$SELF" start ;;
  status)     load_database_url 2>/dev/null; do_status ;;
  logs)       tail -n 50 -f "$LOGDIR/api.log" "$LOGDIR/worker.log" ;;
  migrate)    ensure_venv; load_database_url; check_db_tcp; ensure_deps; check_db_auth; run_migrate ;;
  docker-stop) docker_stop ;;
  dbcheck)    ensure_venv; load_database_url; check_db_tcp; ensure_deps; check_db_auth ;;
  *)          sed -n '2,20p' "$SELF"; exit 1 ;;
esac
