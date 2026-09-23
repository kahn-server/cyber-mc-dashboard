#!/bin/bash
# =====================================================================
# Cyberpunk MC Dashboard start script (universal)
# Usage: ./dashboard.sh start|stop
#
# Overridable env vars (auto if unset):
#   DASH_DIR            panel dir (default $HOME/.dashboard)
#   PANEL_DIR           MC panel dir (default $HOME/.mc_panel)
#   DISPLAY_NUM         X display number (default :1)
#   DASH_CPU_AFFINITY   CPU affinity cores (default: last two cores, 0 on 1-core)
#   DASH_VNC_PASS       VNC password (default 123456, change it)
#   WEBSOCKIFY_BIN      websockify binary path (default: auto-probed)
#   DASH_PY             python binary (default: \$DASH_DIR/venv/bin/python if exists, else python3)
# =====================================================================
DASH_DIR="${DASH_DIR:-$HOME/.dashboard}"
PANEL_DIR="${PANEL_DIR:-$HOME/.mc_panel}"
DISPLAY_NUM="${DISPLAY_NUM:-:1}"
VNC_PORT=5900
WS_PORT=6080
VNC_PASS="${DASH_VNC_PASS:-123456}"

# websockify probe: env var > venv > $HOME/.local/bin > PATH
if [ -n "$WEBSOCKIFY_BIN" ]; then
    WEBSOCKIFY="$WEBSOCKIFY_BIN"
elif [ -x "$DASH_DIR/venv/bin/websockify" ]; then
    WEBSOCKIFY="$DASH_DIR/venv/bin/websockify"
elif [ -x "$HOME/.local/bin/websockify" ]; then
    WEBSOCKIFY="$HOME/.local/bin/websockify"
else
    WEBSOCKIFY="$(command -v websockify 2>/dev/null || echo '')"
fi
if [ -z "$WEBSOCKIFY" ]; then
    echo "[!] websockify not found. Create a venv and install it (see README):"
    echo "    python3 -m venv \$HOME/.dashboard/venv && \$HOME/.dashboard/venv/bin/pip install websockify"
    exit 1
fi

# python probe: DASH_PY > \$DASH_DIR/venv/bin/python (venv) > python3
if [ -n "$DASH_PY" ]; then
    DASH_PYTHON="$DASH_PY"
elif [ -x "$DASH_DIR/venv/bin/python" ]; then
    DASH_PYTHON="$DASH_DIR/venv/bin/python"
else
    DASH_PYTHON="$(command -v python3 2>/dev/null || echo python3)"
fi

# CPU affinity: last two cores by default (MC server owns the front cores), override with DASH_CPU_AFFINITY
NCORES="$(nproc 2>/dev/null || echo 1)"
if [ -n "$DASH_CPU_AFFINITY" ]; then
    CPU_AFFINITY="$DASH_CPU_AFFINITY"
elif [ "$NCORES" -ge 2 ]; then
    CPU_AFFINITY="$((NCORES-2)),$((NCORES-1))"
else
    CPU_AFFINITY="0"
fi
echo "[*] CPU cores: ${NCORES}, panel affinity: ${CPU_AFFINITY} (override with DASH_CPU_AFFINITY)"

start() {
    if pgrep -f "dashboard.py" > /dev/null 2>&1; then
        echo "[!] already running"; exit 0
    fi
    echo "[*] 1/4 Xvfb..."
    rm -f "/tmp/.X${DISPLAY_NUM#:}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM#:}"
    nohup Xvfb "$DISPLAY_NUM" -screen 0 1920x1080x24 -ac > "$DASH_DIR/xvfb.log" 2>&1 &
    sleep 2
    echo "[*] 2/4 dashboard (CPU ${CPU_AFFINITY})..."
    cd "$DASH_DIR"
    DISPLAY="$DISPLAY_NUM" nohup taskset -c "$CPU_AFFINITY" "$DASH_PYTHON" -u dashboard.py > "$DASH_DIR/dash.log" 2>&1 &
    sleep 5
    echo "[*] 3/4 x11vnc..."
    nohup x11vnc -display "$DISPLAY_NUM" -localhost -rfbport "$VNC_PORT" -forever -shared -passwd "$VNC_PASS" -o "$DASH_DIR/x11vnc.log" > /dev/null 2>&1 &
    sleep 2
    echo "[*] 4/4 websockify..."
    cd "$PANEL_DIR"
    nohup "$WEBSOCKIFY" 127.0.0.1:"$WS_PORT" 127.0.0.1:"$VNC_PORT" > websockify.log 2>&1 &
    sleep 1
    echo "[OK] VNC 127.0.0.1:${VNC_PORT} pass:${VNC_PASS}  WS: ${WS_PORT}"
}

stop() {
    pkill -f websockify 2>/dev/null
    pkill -f dashboard.py 2>/dev/null
    pkill -f x11vnc 2>/dev/null
    pkill -f "Xvfb $DISPLAY_NUM" 2>/dev/null
    sleep 2
    pkill -9 -f "Xvfb $DISPLAY_NUM" 2>/dev/null
    rm -f "/tmp/.X${DISPLAY_NUM#:}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM#:}"
    echo "[OK] stopped"
}

case "$1" in
    start) start ;;
    stop) stop ;;
    *) echo "Usage: $0 start|stop" ;;
esac
