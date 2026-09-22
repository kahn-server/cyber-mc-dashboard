#!/bin/bash
# =====================================================================
# Cyberpunk MC Dashboard 启动脚本（通用版）
# 用法: ./dashboard.sh start|stop
#
# 可用环境变量覆盖（不设置则自动）:
#   DASH_DIR            面板目录（默认 $HOME/.dashboard）
#   PANEL_DIR           MC 面板目录（默认 $HOME/.mc_panel）
#   DISPLAY_NUM         X display 编号（默认 :1）
#   DASH_CPU_AFFINITY   CPU 亲和核心（默认自动取末两位核心，1 核则 0）
#   DASH_VNC_PASS       VNC 密码（默认 123456，建议修改）
#   WEBSOCKIFY_BIN      websockify 可执行文件路径（默认自动探测）
# =====================================================================
DASH_DIR="${DASH_DIR:-$HOME/.dashboard}"
PANEL_DIR="${PANEL_DIR:-$HOME/.mc_panel}"
DISPLAY_NUM="${DISPLAY_NUM:-:1}"
VNC_PORT=5900
WS_PORT=6080
VNC_PASS="${DASH_VNC_PASS:-123456}"

# websockify 路径探测：环境变量 > $HOME/.local/bin > PATH
if [ -n "$WEBSOCKIFY_BIN" ]; then
    WEBSOCKIFY="$WEBSOCKIFY_BIN"
elif [ -x "$HOME/.local/bin/websockify" ]; then
    WEBSOCKIFY="$HOME/.local/bin/websockify"
else
    WEBSOCKIFY="$(command -v websockify 2>/dev/null || echo '')"
fi
if [ -z "$WEBSOCKIFY" ]; then
    echo "[!] 未找到 websockify，请先执行: pip install websockify"
    exit 1
fi

# CPU 亲和：自动取末两位核心（MC 服务占用前部核心），可用 DASH_CPU_AFFINITY 覆盖
NCORES="$(nproc 2>/dev/null || echo 1)"
if [ -n "$DASH_CPU_AFFINITY" ]; then
    CPU_AFFINITY="$DASH_CPU_AFFINITY"
elif [ "$NCORES" -ge 2 ]; then
    CPU_AFFINITY="$((NCORES-2)),$((NCORES-1))"
else
    CPU_AFFINITY="0"
fi
echo "[*] CPU 核心: ${NCORES}，面板亲和: ${CPU_AFFINITY}（可用 DASH_CPU_AFFINITY 覆盖）"

start() {
    if pgrep -f "dashboard_cn.py" > /dev/null 2>&1; then
        echo "[!] 已在运行"; exit 0
    fi
    echo "[*] 1/4 Xvfb..."
    rm -f "/tmp/.X${DISPLAY_NUM#:}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM#:}"
    nohup Xvfb "$DISPLAY_NUM" -screen 0 1920x1080x24 -ac > "$DASH_DIR/xvfb.log" 2>&1 &
    sleep 2
    echo "[*] 2/4 面板 (CPU ${CPU_AFFINITY})..."
    cd "$DASH_DIR"
    DISPLAY="$DISPLAY_NUM" nohup taskset -c "$CPU_AFFINITY" python3 -u dashboard_cn.py > "$DASH_DIR/dash.log" 2>&1 &
    sleep 5
    echo "[*] 3/4 x11vnc..."
    nohup x11vnc -display "$DISPLAY_NUM" -localhost -rfbport "$VNC_PORT" -forever -shared -passwd "$VNC_PASS" -o "$DASH_DIR/x11vnc.log" > /dev/null 2>&1 &
    sleep 2
    echo "[*] 4/4 websockify..."
    cd "$PANEL_DIR"
    nohup "$WEBSOCKIFY" 127.0.0.1:"$WS_PORT" 127.0.0.1:"$VNC_PORT" > websockify.log 2>&1 &
    sleep 1
    echo "[OK] VNC 127.0.0.1:${VNC_PORT} 密码:${VNC_PASS}  WS: ${WS_PORT}"
}

stop() {
    pkill -f websockify 2>/dev/null
    pkill -f dashboard_cn.py 2>/dev/null
    pkill -f x11vnc 2>/dev/null
    pkill -f "Xvfb $DISPLAY_NUM" 2>/dev/null
    sleep 2
    pkill -9 -f "Xvfb $DISPLAY_NUM" 2>/dev/null
    rm -f "/tmp/.X${DISPLAY_NUM#:}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM#:}"
    echo "[OK] 已停止"
}

case "$1" in
    start) start ;;
    stop) stop ;;
    *) echo "用法: $0 start|stop" ;;
esac
