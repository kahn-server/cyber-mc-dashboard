# Cyberpunk MC Dashboard

> A cyberpunk-styled **Minecraft server monitoring terminal** — fullscreen neon HUD rendered in Python/pygame, with real RCON data, CRT scanlines and live log feed.

**English** | [Chinese](README_cn.md)

![Type](https://img.shields.io/badge/type-monitor-dashboard-ff2d95)
![Python](https://img.shields.io/badge/python-3.8+-00d4ff)
![RCON](https://img.shields.io/badge/rcon-native--socket-00d4ff)
![License](https://img.shields.io/badge/license-MIT-ff2d95)

**Highlights**

- 🌆 Fullscreen neon cyberpunk HUD (auto-scales to any resolution, incl. 16:9 / 16:10 / 4:3 / ultra-tall)
- 📊 Real data, not simulation: system load / CPU / RAM, MC players (native RCON), server status, live log tail
- 🎛️ Demo mode (`MC_DEMO=1`) for showcasing without RCON
- 🖥️ Headless-ready: `dashboard.sh start` brings up Xvfb + x11vnc + websockify (CPU affinity auto-assigned)
- 🧩 Companion screen for [MCPanel](https://github.com/kahn-server/mc-panel) web panel (in-page VNC)

## Features

- **Fullscreen neon dashboard**: designed at 1792×1024 baseline, coordinates scale proportionally to your actual screen resolution — auto-adapts to 16:9 / 16:10 / 4:3 and arbitrary aspect ratios.
- **Cyberpunk visuals**: neon gradient panels, multi-layer glow, gradient ring gauges, tick animations, glowing titles, CRT scanlines, digital rain, moving scan beam, radial glow background, noise.
- **Real data collection** (not simulated):
  - System load / memory / CPU (psutil)
  - MC online players / player list (**native RCON**, hand-written pure-socket client, no mcrcon dependency)
  - Server status (Mojang API)
  - Log stream (live tail of MC `latest.log`)
- **Demo mode**: set `MC_DEMO=1` to simulate online data without RCON, handy for showcasing.

## Directory Layout

```
.
├── dashboard.py          # Main program (English version)
├── dashboard_cn.py       # Main program (Chinese version, see README_cn.md)
├── dashboard.sh          # Start/stop script, launches dashboard.py (English)
├── dashboard_cn.sh       # Start/stop script for Chinese version (launches dashboard_cn.py)
├── config.example.json   # Config template (copy to config.json)
├── config.json           # Your real config (contains password — do NOT commit to a public repo)
└── shots/                # Screenshot output (runtime)
```

> 🇨🇳 **Chinese users**: use `dashboard_cn.py` + `dashboard_cn.sh` — see [README_cn.md](README_cn.md) for Chinese instructions.

## Installation

**System dependencies (APT)** — headless boxes need a virtual display and VNC forwarding (`dashboard.sh` relies on them):

```bash
sudo apt-get install -y xvfb x11vnc python3 python3-pip
```

**Python dependencies**:

A virtual environment is **recommended — and required on newer Python releases** (PEP 668 blocks global installs on Debian 12+ / Ubuntu 23.10+):

```bash
python3 -m venv ~/.dashboard/venv
~/.dashboard/venv/bin/pip install pygame psutil requests websockify
```

`dashboard.sh` auto-detects `~/.dashboard/venv/bin/python` and the venv's `websockify`, so no extra flags are needed.

On older systems the plain install still works:

```bash
pip install --user pygame psutil requests websockify
```

> No mcrcon needed: the project ships a pure-socket `RCONClient` (some mcrcon builds use `signal.alarm` for timeouts, which throws in worker threads, hence the custom client).

## Configuration

### Option 1: config.json (recommended)

```bash
cp config.example.json config.json
```

Edit `config.json`:

```json
{
  "rcon_ip": "127.0.0.1",
  "rcon_port": 25575,
  "rcon_password": "YOUR_RCON_PASSWORD",
  "log_path": "/YOUR/MC/dir/logs/latest.log",
  "server_name": "Your Server Name",
  "width": 1792,
  "height": 1024,
  "max_players": 100
}
```

### Option 2: Environment variables (higher priority than config.json)

| Variable | Description | Default |
|---|---|---|
| `MC_RCON_IP` | RCON address | `127.0.0.1` |
| `MC_RCON_PORT` | RCON port | `25575` |
| `MC_RCON_PASSWORD` | RCON password | empty (required) |
| `MC_LOG_PATH` | MC log file path | empty |
| `MC_SERVER_NAME` | Dashboard title | `Cyberpunk MC Dashboard` |
| `MC_WIDTH` / `MC_HEIGHT` | Window size | `1792` / `1024` |
| `MC_MAX_PLAYERS` | Server max players | `20` |
| `MC_DEMO` | `1` for demo mode | empty |
| `MC_WINDOWED` | `1` for windowed mode (else fullscreen) | empty |

## Run

```bash
# Fullscreen
python3 dashboard.py

# Windowed
MC_WINDOWED=1 MC_WIDTH=1792 MC_HEIGHT=1024 python3 dashboard.py

# Or via the start script (virtual display + VNC + web terminal, for headless boxes)
./dashboard.sh start     # start
./dashboard.sh stop      # stop
```

> The start script auto-detects CPU core count for affinity (`DASH_CPU_AFFINITY` overrides it) and auto-probes websockify; `DASH_DIR / PANEL_DIR / DASH_VNC_PASS / WEBSOCKIFY_BIN / DISPLAY_NUM` are all overridable via environment variables — no script editing needed.

## Hotkeys

| Key | Action |
|---|---|
| `ESC` | Quit |
| `T` | Theme cycle: auto → day → night |
| `↑ / ↓` | Manual log paging |
| `R` | Jump log back to live (LIVE) |
| `S` | Save screenshot to `shots/` |

## Security Notes

- `config.json` contains the **RCON password** — sensitive data. Do not commit your `config.json` to a public repository.
- The RCON password default in the code is empty; it must be supplied via `config.json` or environment variables.

## License

MIT
