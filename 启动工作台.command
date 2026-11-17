#!/bin/zsh
# 双击启动原有工作台；只监听本机，继续使用 data/platform.sqlite。
set -u
cd "${0:A:h}" || exit 1
URL='http://127.0.0.1:8766/'
LOG_FILE="$PWD/data/studioflow-start.log"

fail() {
  echo "$1"
  if [[ -t 0 && "${STUDIOFLOW_NO_PAUSE:-0}" != 1 ]]; then
    read -r "reply?按回车关闭窗口…"
  fi
  exit 1
}

command -v python3 >/dev/null || fail '未找到 Python，请安装 Python 3.11 或以上版本。'
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || fail '需要 Python 3.11 或以上版本。'

ready() {
  curl --noproxy '*' -fsS --max-time 2 "${URL}api/runtime" 2>/dev/null |
    python3 -c 'import json,sys; sys.exit(json.load(sys.stdin).get("mode") != "team")' 2>/dev/null
}

show_page() {
  echo "工作台地址：$URL"
  if [[ "${STUDIOFLOW_OPEN_BROWSER:-1}" == 1 ]]; then
    open "$URL"
  fi
}

if ready; then
  echo 'StudioFlow 已在运行，直接打开。'
  show_page
  exit 0
fi

if lsof -nP -iTCP:8766 -sTCP:LISTEN >/dev/null 2>&1; then
  fail '8766 端口已被占用，且未检测到可用的团队工作台。请先检查占用程序。'
fi

mkdir -p data || fail '无法创建日志目录。'
# 只锁启动阶段，避免连续双击启动多份服务。
LOCK_DIR="$PWD/data/.workbench-start.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  fail '已有启动操作正在进行。若上次启动被强制中断，请删除 data/.workbench-start.lock 后重试。'
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT
echo '正在启动 StudioFlow…'
echo "启动日志：$LOG_FILE"
umask 077
SERVER_PID=$(python3 - "$LOG_FILE" <<'PY'
import subprocess
import sys

with open(sys.argv[1], 'ab') as log:
    process = subprocess.Popen(
        [sys.executable, '-u', '-m', 'server.app', '--mode', 'team',
         '--host', '127.0.0.1', '--port', '8766', '--database', 'data/platform.sqlite'],
        stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
    )
print(process.pid)
PY
) || fail "无法创建服务进程，请查看：$LOG_FILE"

for attempt in {1..30}; do
  if ready; then
    echo 'StudioFlow 已启动，关闭此终端窗口不会停止服务。'
    show_page
    exit 0
  fi
  kill -0 "$SERVER_PID" 2>/dev/null || fail "服务启动失败，请查看：$LOG_FILE"
  sleep 1
done
fail "30 秒内尚未就绪；进程可能仍在启动，请查看日志后再试：$LOG_FILE"
