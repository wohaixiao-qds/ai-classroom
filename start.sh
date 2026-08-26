#!/bin/bash
# 一键启动 AI 课堂(先杀旧进程再重启,幂等)
# 用法: ./start.sh          前后端都起
#       ./start.sh api      只重启后端
#       ./start.sh web      只重启前端
set -euo pipefail
cd "$(dirname "$0")"

API_PORT=8100
WEB_PORT=5273
LOG_DIR=.run
mkdir -p "$LOG_DIR"

kill_by_port() { # 端口上有进程就杀(含 -9 兜底),没有则静默
  local pids
  pids=$(lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "→ 端口 $1 已有进程($pids),先关掉"
    kill $pids 2>/dev/null || true
    sleep 1
    kill -9 $pids 2>/dev/null || true
  fi
}

wait_http() { # $1=url $2=名称 $3=超时秒
  local i=0
  until curl -sS -o /dev/null --max-time 2 "$1" 2>/dev/null; do
    i=$((i + 1))
    [ $i -ge "$3" ] && { echo "⚠️ $2 在 $3 秒内没就绪,看日志:$LOG_DIR/"; exit 1; }
    sleep 1
  done
  echo "✅ $2 就绪"
}

start_api() {
  kill_by_port $API_PORT
  echo "→ 启动 API(uvicorn :$API_PORT,日志 $LOG_DIR/api.log)"
  nohup sh -c 'cd apps/api && exec uv run uvicorn app.main:app --port '"$API_PORT"' --reload' \
    >"$LOG_DIR/api.log" 2>&1 &
  wait_http "http://127.0.0.1:$API_PORT/openapi.json" "API" 30
}

start_web() {
  kill_by_port $WEB_PORT
  echo "→ 启动前端(vite :$WEB_PORT,日志 $LOG_DIR/web.log)"
  nohup pnpm -C apps/web dev >"$LOG_DIR/web.log" 2>&1 &
  wait_http "http://localhost:$WEB_PORT/" "前端" 30  # vite 绑 ::1,127.0.0.1 探不通
}

case "${1:-all}" in
  api) start_api ;;
  web) start_web ;;
  all) start_api && start_web ;;
  *) echo "用法: $0 [all|api|web]"; exit 2 ;;
esac

echo ""
echo "🎯 AI 课堂:http://localhost:$WEB_PORT   (API :$API_PORT)"
[ "${1:-all}" = "all" ] && echo "   日志: $LOG_DIR/api.log / $LOG_DIR/web.log   停止: 再跑一次本脚本选对应项后 kill,或 lsof -ti:$API_PORT,$WEB_PORT | xargs kill"
