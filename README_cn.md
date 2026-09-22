# Cyberpunk MC Dashboard

赛博朋克风格的 Minecraft 服务器监控终端（Python / pygame 全屏渲染）。

**[English](README.md) | 简体中文**

![类型](https://img.shields.io/badge/type-monitor-dashboard-ff2d95)
![Python](https://img.shields.io/badge/python-3.8+-00d4ff)

## 功能

- **全屏霓虹仪表盘**：以 1792×1024 为基准，按实际屏幕分辨率等比计算坐标，自动适配 16:9 / 16:10 / 4:3 及任意特种比例。
- **赛博朋克视觉**：霓虹渐变面板、多层外发光、渐变发光环形仪表、刻度动画、发光大标题、CRT 扫描线、数据雨、移动扫描束、径向光晕背景、噪点。
- **真实数据采集**（非演示模拟）：
  - 系统负载 / 内存 / CPU（psutil）
  - MC 在线人数 / 玩家列表（**原生 RCON**，纯 socket 手搓客户端，不依赖 mcrcon）
  - 服务器状态（Mojang API）
  - 日志流（实时读取 MC `latest.log`）
- **演示模式**：无 RCON 时可设 `MC_DEMO=1` 模拟在线数据，方便展示。

## 目录结构

```
.
├── dashboard.py          # 主程序（英文版，供海外用户）
├── dashboard_cn.py       # 主程序（中文版，国内用户请使用这个）
├── dashboard.sh          # 启动/停止脚本（英文版，启动 dashboard.py）
├── dashboard_cn.sh       # 启动/停止脚本（中文版，启动 dashboard_cn.py）
├── config.example.json   # 配置模板（复制为 config.json 使用）
├── config.json           # 你的实际配置（含密码，请勿提交到公开仓库）
└── shots/                # 截图输出目录（运行时生成）
```

> ⚠️ **中文用户请使用 `dashboard_cn.py` + `dashboard_cn.sh`**（界面与提示均为中文）；英文版仅供海外用户。

## 安装

**系统依赖（APT）**——无显示器环境需要虚拟屏与 VNC 转发（`dashboard.sh` 依赖）：

```bash
sudo apt-get install -y xvfb x11vnc python3 python3-pip
```

**Python 依赖**：

```bash
pip install pygame psutil requests
```

> 不需要 mcrcon：项目内置纯 socket 实现的 `RCONClient`（部分发行版 mcrcon 用 `signal.alarm` 实现超时，在子线程会抛异常，故自研）。

## 配置

### 方式一：config.json（推荐）

```bash
cp config.example.json config.json
```

编辑 `config.json`：

```json
{
  "rcon_ip": "127.0.0.1",
  "rcon_port": 25575,
  "rcon_password": "你的RCON密码",
  "log_path": "/你的/MC服务器目录/logs/latest.log",
  "server_name": "你的服务器名",
  "width": 1792,
  "height": 1024,
  "max_players": 100
}
```

### 方式二：环境变量（优先级高于 config.json）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `MC_RCON_IP` | RCON 地址 | `127.0.0.1` |
| `MC_RCON_PORT` | RCON 端口 | `25575` |
| `MC_RCON_PASSWORD` | RCON 密码 | 空（必须配置） |
| `MC_LOG_PATH` | MC 日志文件路径 | 空 |
| `MC_SERVER_NAME` | 面板标题 | `Cyberpunk MC Dashboard` |
| `MC_WIDTH` / `MC_HEIGHT` | 窗口尺寸 | `1792` / `1024` |
| `MC_MAX_PLAYERS` | 服务器最大人数 | `20` |
| `MC_DEMO` | 置 `1` 进入演示模式 | 空 |
| `MC_WINDOWED` | 置 `1` 窗口模式（否则全屏） | 空 |

## 运行（中文版）

```bash
# 全屏运行（中文版）
python3 dashboard_cn.py

# 窗口模式
MC_WINDOWED=1 MC_WIDTH=1792 MC_HEIGHT=1024 python3 dashboard_cn.py

# 或使用启动脚本（带虚拟屏 + VNC + 网页终端，无显示器环境）
./dashboard_cn.sh start     # 启动
./dashboard_cn.sh stop      # 停止
```

> 启动脚本自动检测 CPU 核心数分配亲和（`DASH_CPU_AFFINITY` 可覆盖），自动探测 websockify；`DASH_DIR / PANEL_DIR / DASH_VNC_PASS / WEBSOCKIFY_BIN / DISPLAY_NUM` 等均可用环境变量覆盖，无需改脚本。

## 快捷键

| 键 | 功能 |
|---|---|
| `ESC` | 退出 |
| `T` | 主题循环：自动 → 白天 → 黑夜 |
| `↑ / ↓` | 日志手动翻页 |
| `R` | 日志回到最新（LIVE） |
| `S` | 截图保存到 `shots/` |

## 安全说明

- `config.json` 包含 **RCON 密码**，属于敏感信息——请勿将你的 `config.json` 提交到公开仓库。
- 代码中的 RCON 密码默认值为空，必须通过 `config.json` 或环境变量提供。

## License

MIT
