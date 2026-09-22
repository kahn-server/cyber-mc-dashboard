#!/bin/bash
# ============================================================
# Cyberpunk MC Dashboard 启动脚本（start / stop）
# ------------------------------------------------------------
# 【使用前必改】以下 7 个变量按你的环境修改：
#   DASH_DIR    面板代码所在目录（含 dashboard.py）
#   PANEL_DIR   你的 MC 网页面板目录（用于启动 websockify，
#               不需要网页终端可留空）
#   DISPLAY_NUM Xvfb 虚拟显示编号
#   VNC_PORT    VNC 端口
#   WS_PORT     websockify 网页终端端口
#   VNC_PASS    VNC 连接密码
#   WEBSOCKIFY  websockify 可执行文件路径（无则留空跳过）
# ============================================================
DASH_DIR=/home/mcserver/.dashboard
PANEL_DIR=/home/mcserver/.mc_panel
DISPLAY_NUM=:1
VNC_PORT=5900
WS_PORT=6080
VNC_PASS=123456
WEBSOCKIFY=/home/mcserver/.local/bin/websockify

start() {
    if pgrep -f "dashboard.py" > /dev/null; then
        echo "[!] 已在运行"; exit 0
    fi
    echo "[*] 1/4 Xvfb..."
    rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
    nohup Xvfb $DISPLAY_NUM -screen 0 1920x1080x24 -ac > $DASH_DIR/xvfb.log 2>&1 &
    sleep 2
    echo "[*] 2/4 面板 (CPU 6,7)..."
    cd $DASH_DIR
    DISPLAY=$DISPLAY_NUM nohup taskset -c 6,7 python3 -u dashboard.py > $DASH_DIR/dash.log 2>&1 &
    sleep 5
    echo "[*] 3/4 x11vnc..."
    nohup x11vnc -display $DISPLAY_NUM -localhost -rfbport $VNC_PORT -forever -shared -passwd $VNC_PASS -o $DASH_DIR/x11vnc.log > /dev/null 2>&1 &
    sleep 2
    echo "[*] 4/4 websockify..."
    cd $PANEL_DIR
    nohup $WEBSOCKIFY 127.0.0.1:$WS_PORT 127.0.0.1:$VNC_PORT > websockify.log 2>&1 &
    sleep 1
    echo "[OK] VNC 127.0.0.1:5900 密码:123456  WS: 6080"
}

stop() {
    pkill -f websockify 2>/dev/null
    pkill -f dashboard.py 2>/dev/null
    pkill -f x11vnc 2>/dev/null
    pkill -f "Xvfb :1" 2>/dev/null
    sleep 2
    pkill -9 -f "Xvfb :1" 2>/dev/null
    rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
    echo "[OK] 已停止"
}

case "$1" in
    start) start ;;
    stop) stop ;;
    *) echo "用法: $0 start|stop" ;;
esac
