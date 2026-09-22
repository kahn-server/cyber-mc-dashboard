# Cyberpunk MC Dashboard

A cyberpunk-styled Minecraft server monitoring terminal (Python / pygame fullscreen rendering).

![Type](https://img.shields.io/badge/type-monitor-dashboard-ff2d95)
![Python](https://img.shields.io/badge/python-3.8+-00d4ff)

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
├── dashboard.py          # Main program (single file)
├── dashboard.sh          # Start/stop script (start|stop)
├── config.example.json   # Config template (copy to config.json)
├── config.json           # Your real config (contains password — do NOT commit to a public repo)
└── shots/                # Screenshot output (runtime)
```

## Installation

**System dependencies (APT)** — headless boxes need a virtual display and VNC forwarding (`dashboard.sh` relies on them):

```bash
sudo apt-get install -y xvfb x11vnc python3 python3-pip
```

**Python dependencies**:

```bash
pip install pygame psutil requests
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
