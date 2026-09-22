# -*- coding: utf-8 -*-
"""
Cyberpunk MC Server Dashboard —— 赛博朋克 MC 服务器监控终端（v3 旗舰版）
========================================================================
· 布局：以 1792x1024 参考图为基准，按实际屏幕分辨率等比计算坐标，
  自动适配 16:9 / 16:10 / 4:3 及任意特种比例（无法匹配时按 16:9 拉伸铺满）。
· 渲染：霓虹渐变面板 / 多层外发光 / 渐变发光环形仪表 / 刻度动画 /
  发光大标题 / CRT 扫描线 / 数据雨 / 移动扫描束 / 径向光晕背景 / 噪点。
· 数据：全部真实采集（psutil + RCON + Mojang API + 日志文件）。

运行：
    pip install pygame mcrcon psutil requests
    export MC_RCON_PASSWORD=你的rcon密码     # 可选
    python3 dashboard.py                      # 全屏（自动适配屏幕）
    MC_WINDOWED=1 MC_WIDTH=1792 MC_HEIGHT=1024 python3 dashboard.py   # 窗口模式

快捷键：
    ESC        退出
    T          主题循环：自动 → 白天 → 黑夜
    ↑ / ↓      日志手动翻页
    R          日志回到最新（LIVE）
    S          截图保存到 shots/
"""

import os
import sys
import time
import math
import json
import re
import io
import random
import socket
import struct
import glob as _glob
import threading
import subprocess
from collections import deque
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import pygame
import psutil
import requests


class RCONClient:
    """纯 socket 实现的 Minecraft RCON 客户端。

    不用第三方 mcrcon 库：该库用 signal.alarm 实现超时，
    在子线程调用会抛 "signal only works in main thread"。
    协议（SERVERDATA）：TCP + 4 字节包长 + (id, type, payload)。
    """

    def __init__(self, host, password, port=25575, timeout=3):
        self.host = host
        self.password = password
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port),
                                             timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self._send(3, self.password)          # SERVERDATA_AUTH
        _id, _type, _data = self._read()
        if _id == -1:
            raise RuntimeError("RCON 认证失败（密码错误）")
        return self

    def command(self, cmd):
        self._send(2, cmd)                    # SERVERDATA_EXECCOMMAND
        _id, _type, data = self._read()
        return data

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def _send(self, ptype, payload):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        body = struct.pack("<ii", 1, ptype) + payload + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(body)) + body)

    def _read(self):
        ln = struct.unpack("<i", self._recv_exact(4))[0]
        body = self._recv_exact(ln)
        _id, ptype = struct.unpack("<ii", body[:8])
        data = body[8:ln - 2].decode("utf-8", errors="replace")
        return _id, ptype, data

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("RCON 连接被服务器断开")
            buf += chunk
        return buf

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()
        return False

# ================= 配置加载 =================
def load_config():
    config = {
        "rcon_ip": os.environ.get("MC_RCON_IP", "127.0.0.1"),
        "rcon_port": int(os.environ.get("MC_RCON_PORT", 25575)),
        "rcon_password": os.environ.get("MC_RCON_PASSWORD", ""),
        "log_path": os.environ.get("MC_LOG_PATH", "/data/minecraft_server/logs/latest.log"),
        "width": int(os.environ.get("MC_WIDTH", 1792)),
        "height": int(os.environ.get("MC_HEIGHT", 1024)),
        "max_players": int(os.environ.get("MC_MAX_PLAYERS", 20)),
        "server_name": os.environ.get("MC_SERVER_NAME", "NIGHT CITY NODE"),
    }
    if os.path.exists("config.json"):
        with open("config.json", "r", encoding="utf-8") as f:
            config.update(json.load(f))
    return config

CONFIG = load_config()
BASE_W, BASE_H = 1792, 1024      # 参考图基准分辨率
FPS = 60
DEMO = os.environ.get("MC_DEMO", "") == "1"   # 演示模式：无 RCON 时模拟在线数据

# 截图输出目录（按 S 键保存一帧）
SHOT_DIR = os.environ.get("MC_SHOT_DIR", "shots")


def save_shot(screen):
    """保存当前屏幕一帧到 SHOT_DIR"""
    try:
        os.makedirs(SHOT_DIR, exist_ok=True)
        name = f"dash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path = os.path.join(SHOT_DIR, name)
        pygame.image.save(screen, path)
        print(f"[SHOT] saved -> {path}")
        return path
    except Exception as e:
        print(f"[SHOT] failed: {e}")
        return None


# ================= 配色（高对比版本：拉开明暗层次，VNC/低色深下依然清晰） =================
COLOR_BG        = (6, 10, 16)
COLOR_BG_DEEP   = (4, 7, 11)
COLOR_CYAN      = (0, 246, 255)
COLOR_CYAN_DIM  = (0, 190, 215)
COLOR_MAGENTA   = (255, 40, 140)
COLOR_MAG_DIM   = (205, 30, 120)
COLOR_GREEN     = (0, 255, 140)
COLOR_YELLOW    = (255, 205, 20)
COLOR_RED       = (255, 72, 66)
COLOR_DARK      = (52, 76, 100)
COLOR_DARKER    = (24, 42, 58)
COLOR_PANEL_BG  = (17, 36, 50)
COLOR_TEXT      = (240, 248, 255)
COLOR_DIM_TEXT  = (158, 178, 198)

# 主题定义
THEMES = {
    "night": {
        "COLOR_BG": (6, 10, 16), "COLOR_BG_DEEP": (4, 7, 11),
        "COLOR_CYAN": (0, 246, 255), "COLOR_CYAN_DIM": (0, 190, 215),
        "COLOR_MAGENTA": (255, 40, 140), "COLOR_MAG_DIM": (205, 30, 120),
        "COLOR_GREEN": (0, 255, 140), "COLOR_YELLOW": (255, 205, 20),
        "COLOR_RED": (255, 72, 66), "COLOR_DARK": (52, 76, 100),
        "COLOR_DARKER": (24, 42, 58), "COLOR_PANEL_BG": (17, 36, 50),
        "COLOR_TEXT": (240, 248, 255), "COLOR_DIM_TEXT": (158, 178, 198),
    },
    "day": {
        "COLOR_BG": (20, 34, 50), "COLOR_BG_DEEP": (14, 24, 36),
        "COLOR_CYAN": (0, 200, 235), "COLOR_CYAN_DIM": (40, 130, 165),
        "COLOR_MAGENTA": (225, 55, 130), "COLOR_MAG_DIM": (150, 45, 95),
        "COLOR_GREEN": (0, 210, 125), "COLOR_YELLOW": (225, 185, 10),
        "COLOR_RED": (235, 90, 78), "COLOR_DARK": (70, 96, 120),
        "COLOR_DARKER": (32, 52, 70), "COLOR_PANEL_BG": (30, 50, 68),
        "COLOR_TEXT": (245, 250, 255), "COLOR_DIM_TEXT": (150, 175, 195),
    },
}
THEME_MODE = "auto"          # auto / day / night
CURRENT_THEME = "night"


def apply_theme(name):
    """把主题色应用到全局 COLOR_* 变量"""
    global CURRENT_THEME, COLOR_BG, COLOR_BG_DEEP, COLOR_CYAN, COLOR_CYAN_DIM
    global COLOR_MAGENTA, COLOR_MAG_DIM, COLOR_GREEN, COLOR_YELLOW, COLOR_RED
    global COLOR_DARK, COLOR_DARKER, COLOR_PANEL_BG, COLOR_TEXT, COLOR_DIM_TEXT
    t = THEMES.get(name)
    if not t:
        return
    for k, v in t.items():
        globals()[k] = v
    CURRENT_THEME = name


def cycle_theme_mode():
    global THEME_MODE
    order = ["auto", "day", "night"]
    idx = (order.index(THEME_MODE) + 1) % len(order)
    THEME_MODE = order[idx]
    if THEME_MODE == "auto":
        apply_theme("day" if 6 <= datetime.now().hour < 18 else "night")
    else:
        apply_theme(THEME_MODE)


def auto_theme_check():
    global THEME_MODE
    if THEME_MODE != "auto":
        return
    target = "day" if 6 <= datetime.now().hour < 18 else "night"
    if target != CURRENT_THEME:
        apply_theme(target)


# ================= 全局状态 =================
class GlobalState:
    def __init__(self):
        self.system_stats = {}
        self.history = {                      # 历史曲线（最多120点）
            "CPU":   deque(maxlen=120),
            "内存":   deque(maxlen=120),
            "TPS":   deque(maxlen=120),
            "网络":   deque(maxlen=120),
        }
        self.mc_tps = 0.0
        self.mc_online = False
        self.mc_version = "--"
        self.mc_conn_t0 = None          # MC 服务器在线计时起点（重启自动重计）
        self.mc_server_uptime = None    # MC 服务器进程真实运行时长（秒），None=未知
        self.mc_off_since = None        # 最近一次 RCON 断开时刻（超过 60s 才重计）
        self.mc_players = 0
        self.mc_uptime = "--"
        self.demo = False
        self.log_lines = []
        self.player_list = []
        self.avatars = {}
        self.thermal = []      # [(名称, 当前温度℃), ...]
        self.fans = []         # [(名称, RPM), ...]
        self.data_lock = threading.Lock()
        self.log_lock = threading.Lock()
        self.sys_boot = 0.0

        # 日志速率计算变量
        self.last_log_lines = 0
        self.last_log_time = time.time()
        # 日志滚动状态（终端式：0 = 跟随最新，>0 = 向上看历史行数）
        self.log_scroll = 0
        self.log_wrap_key = None
        self.log_wrap_flat = []

state = GlobalState()

# 线程池：避免频繁创建线程导致内存爆炸
executor = ThreadPoolExecutor(max_workers=5)


# ================= 字体工具 =================
try:
    from fontTools.ttLib import TTCollection as _TTCollection
except Exception:
    _TTCollection = None

_CJK_SC_TTF = "/tmp/noto_sans_cjk_sc.ttf"
_CJK_MONO_SC_TTF = "/tmp/noto_mono_cjk_sc.ttf"
_font_file_cache = {}


def _extract_cjk_font(face_index, out_path):
    """从 NotoSansCJK-Regular.ttc 提取指定 face 为独立 TTF（pygame 不支持 ttc face 索引）"""
    if os.path.exists(out_path):
        return out_path
    if _TTCollection is None:
        return None
    for pat in ("/usr/share/fonts/**/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/**/NotoSansCJK-Medium.ttc"):
        for p in sorted(_glob.glob(pat, recursive=True)):
            try:
                _TTCollection(p).fonts[face_index].save(out_path)
                return out_path
            except Exception:
                continue
    return None


def _cjk_font_file():
    """简体中文字体 TTF（face 2 = Noto Sans CJK SC）"""
    if "sc" not in _font_file_cache:
        _font_file_cache["sc"] = _extract_cjk_font(2, _CJK_SC_TTF)
    return _font_file_cache["sc"]


def _cjk_mono_font_file():
    """等宽+简体中文字体 TTF（face 7 = Noto Sans Mono CJK SC）"""
    if "mono_sc" not in _font_file_cache:
        _font_file_cache["mono_sc"] = _extract_cjk_font(7, _CJK_MONO_SC_TTF)
    return _font_file_cache["mono_sc"]


def load_font(size, mono=False):
    """动态探测系统字体；优先简体中文（等宽/普通）"""
    if mono:
        p = _cjk_mono_font_file()
        if not p:
            # 等宽中文字体提取失败时，回退到 SC 黑体（保证中文绝不变成方块）
            p = _cjk_font_file()
        if p:
            try:
                return pygame.font.Font(p, size)
            except Exception:
                pass
        for n in ["dejavusansmono", "wqy-microhei", "notosanscjk"]:
            try:
                f = pygame.font.SysFont(n, size)
                if f is not None:
                    return f
            except Exception:
                continue
        return pygame.font.Font(None, size)

    p = _cjk_font_file()
    if p:
        try:
            return pygame.font.Font(p, size)
        except Exception:
            pass
    for n in ["wqy-microhei", "simhei", "notosanscjk", "dejavusansmono"]:
        try:
            f = pygame.font.SysFont(n, size)
            if f is not None:
                return f
        except Exception:
            continue
    return pygame.font.Font(None, size)


def wrap_text(text, font, max_w, half_w, full_w):
    """按可用宽度把一行文本折成多行（等宽字体快速估算 + 超宽段二分校正）"""
    if font.size(text)[0] <= max_w:
        return [text]
    out = []
    cur = ""
    curw = 0
    for ch in text:
        w = full_w if ord(ch) > 0x2E80 else half_w
        if curw + w > max_w and cur:
            out.append(cur)
            cur = ch
            curw = w
        else:
            cur += ch
            curw += w
    if cur:
        out.append(cur)
    # 校正：估算有偏差时把仍超宽的段用二分切掉
    final = []
    for seg in out:
        while seg and font.size(seg)[0] > max_w:
            lo, hi = 1, len(seg)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if font.size(seg[:mid])[0] <= max_w:
                    lo = mid
                else:
                    hi = mid - 1
            final.append(seg[:lo])
            seg = seg[lo:]
        if seg:
            final.append(seg)
    return final


def fmt_uptime(seconds):
    seconds = max(0, int(seconds))
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    if d:
        return f"{d}d{h}h"
    if h:
        return f"{h}h{m}m"
    return f"{m}m"


def ratio_tag(w, h):
    """根据真实分辨率计算显示比例标识（16:9 / 16:10 / 4:3 / 21:9 / 未知→WxH）"""
    r = w / h
    for tag, v in (("21:9", 21 / 9), ("16:9", 16 / 9),
                   ("16:10", 1.6), ("4:3", 4 / 3)):
        if abs(r - v) < 0.05:
            return tag
    return f"{w}x{h}"


# ================= 布局计算（按实际分辨率等比缩放，基准 1792x1024） =================
class Layout:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.sx = w / BASE_W
        self.sy = h / BASE_H
        self.fs = min(self.sx, self.sy)   # 字体按最小缩放，防止 4:3 等屏幕溢出

    def xy(self, x, y):
        return (int(x * self.sx), int(y * self.sy))

    def rect(self, x, y, w, h):
        return (int(x * self.sx), int(y * self.sy),
                max(1, int(w * self.sx)), max(1, int(h * self.sy)))

    def r(self, r):
        return max(1, int(r * self.fs))

    def font(self, size):
        return load_font(max(8, int(size * self.fs)))

    def fontm(self, size):
        return load_font(max(8, int(size * self.fs)), mono=True)


# ================= 工具与 API 模块 =================
def fetch_player_avatar(username):
    """真实 Mojang API 与头像拉取 (带防重复请求锁)"""
    if username in state.avatars:
        return
    try:
        res_uuid = requests.get(f"https://api.mojang.com/users/profiles/minecraft/{username}", timeout=5)
        if res_uuid.status_code == 200:
            uuid = res_uuid.json().get("id")
            img_url = f"https://minotar.net/helm/{uuid}/100.png"
            img_data = requests.get(img_url, timeout=5).content
            img_surf = pygame.image.load(io.BytesIO(img_data)).convert_alpha()
            with state.data_lock:
                state.avatars[username] = img_surf
            return
    except Exception:
        pass
    with state.data_lock:
        state.avatars[username] = None


# ================= 真实数据采集线程 =================
def get_system_stats():
    """真实系统数据（CPU/内存/磁盘/网络/日志速率/线程）"""
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net = psutil.net_io_counters()

    log_lines_per_sec = 0
    try:
        if os.path.exists(CONFIG["log_path"]):
            with open(CONFIG["log_path"], 'rb') as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 102400))
                lines = f.readlines()
                current_lines = len(lines)
            now = time.time()
            time_delta = now - state.last_log_time
            if time_delta > 0:
                line_delta = current_lines - state.last_log_lines
                if line_delta > 0:
                    log_lines_per_sec = round(line_delta / time_delta, 1)
            state.last_log_lines = current_lines
            state.last_log_time = now
    except Exception:
        pass

    # 网络速率（真实差值）
    net_speed = 0.0
    now = time.time()
    if getattr(state, "_net_last", None) is not None:
        dt = now - state._net_last_t
        if dt > 0:
            net_speed = max(0.0, (net.bytes_recv - state._net_last) / (1024 ** 2) / dt)
    state._net_last = net.bytes_recv
    state._net_last_t = now

    with state.data_lock:
        state.system_stats = {
            "CPU": (f"{cpu:.0f}%", cpu),
            "内存": (f"{mem.used / (1024 ** 3):.1f}G", mem.percent),
            "磁盘": (f"{disk.used / (1024 ** 3):.1f}G", disk.percent),
            "网络↓": (f"{net_speed:.1f}", min(100.0, net_speed * 4)),
            "TPS": (f"{state.mc_tps:.1f}", min(100.0, (state.mc_tps / 20) * 100)),
            "在线": (str(state.mc_players), min(100.0, state.mc_players / max(1, CONFIG["max_players"]) * 100)),
            "日志": (f"{log_lines_per_sec}/s", min(100.0, log_lines_per_sec * 2)),
            "线程": (str(threading.active_count()), min(100.0, threading.active_count() * 2)),
        }
        state.history["CPU"].append(cpu)
        state.history["内存"].append(mem.percent)
        state.history["TPS"].append(min(100.0, state.mc_tps / 20 * 100))
        state.history["网络"].append(min(100.0, net_speed * 4))


def parse_list_response(resp):
    """宽松解析 /list 输出：兼容英文/中文/无玩家/颜色码（插件改写也能兜底）"""
    if not resp:
        return [], None
    clean = re.sub(r"§[0-9a-fk-or]", "", resp)
    # 玩家名：中英文冒号后的部分
    players = []
    sep = ": " if ": " in clean else ("：" if "：" in clean else None)
    if sep is not None:
        rest = clean.split(sep, 1)[1].strip()
        if rest:
            players = [p.strip() for p in rest.split(",") if p.strip()]
    # 总人数：英文 "There are X of a max of Y" / "X/Y" / 中文 "在线 X/共 Y"
    total = None
    m = re.search(r"(\d+)\s+of\s+a\s+max\s+of\s+(\d+)", clean)
    if not m:
        m = re.search(r"(\d+)\s*/\s*(\d+)", clean)
    if not m:
        m = re.search(r"在线\s*(\d+)[^0-9]{0,8}(\d+)", clean)
    if m:
        total = int(m.group(2))
    if total is None and players:
        total = len(players)
    return players, total


def get_real_mc_data():
    """通过 RCON 获取真实 MC 数据：自研 socket 客户端（无 signal 坑）+ 原版指令 + 宽松解析"""
    if not CONFIG["rcon_password"]:
        return
    try:
        with RCONClient(CONFIG["rcon_ip"], CONFIG["rcon_password"],
                        port=CONFIG["rcon_port"], timeout=3) as rcon:
            # RCON 通道通 = 服务器在线（即使输出格式特殊也能点亮 ONLINE）
            with state.data_lock:
                # 从离线→在线：仅当首次连接、或断开超过 60 秒（真重启）时才重计
                if not state.mc_online:
                    if state.mc_conn_t0 is None or (
                            state.mc_off_since is not None
                            and time.time() - state.mc_off_since > 60):
                        state.mc_conn_t0 = time.time()
                    state.mc_off_since = None
                state.mc_online = True

            # ---- 玩家列表：优先原版指令，插件接管 /list 时回退解析 ----
            list_resp = rcon.command("minecraft:list")
            if any(k in list_resp.lower() for k in ("unknown", "未知的", "错误", "unrecognized")):
                list_resp = rcon.command("list")
            players, _ = parse_list_response(list_resp)
            with state.data_lock:
                state.player_list = players
                state.mc_players = len(players)

            # ---- TPS：spigot/paper 指令（原版无 /tps，失败静默保持旧值） ----
            try:
                tps_resp = rcon.command("tps")
                tps_m = re.search(r"([0-9]+\.[0-9]+)", tps_resp)
                if tps_m:
                    with state.data_lock:
                        state.mc_tps = float(tps_m.group(1))
            except Exception:
                pass

            # ---- 版本：RCON version 指令（原版/Paper 均支持） ----
            try:
                ver_resp = rcon.command("version")
                vm = re.search(r"(\d+\.\d+(?:\.\d+)?)", ver_resp)
                if vm:
                    with state.data_lock:
                        state.mc_version = vm.group(1)
            except Exception:
                pass

        for p in state.player_list:
            if p not in state.avatars:
                executor.submit(fetch_player_avatar, p)
    except Exception as e:
        print(f"[RCON] 获取失败: {type(e).__name__}: {e}")
        with state.data_lock:
            state.mc_online = False
            if state.mc_off_since is None:
                state.mc_off_since = time.time()


def parse_logs():
    """真实日志读取与正则解析（保留最近 1000 行，终端式滚动查看）"""
    if not os.path.exists(CONFIG["log_path"]):
        return [(f"[WARN] 日志文件不存在: {CONFIG['log_path']}", COLOR_MAGENTA)]
    try:
        # 尾部读取（最多 ~600KB 的尾巴，约几千行），再截断保留 1000 行
        with open(CONFIG["log_path"], 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 600000))
            if size > 600000:
                f.readline()  # 丢弃可能被截断的半行
            lines = f.readlines()[-1000:]
        parsed = []
        join_re = re.compile(r"\[.*?\] \[Server thread/INFO\]: (.*?) joined the game")
        left_re = re.compile(r"\[.*?\] \[Server thread/INFO\]: (.*?) left the game")
        err_re = re.compile(r"\[.*?\] \[Server thread/ERROR\]:")
        chat_re = re.compile(r"\[.*?\] \[Server thread/INFO\]: <(.*?)> (.*)")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if "RCON" in line.upper():
                continue  # 过滤 RCON 相关行，不显示在面板日志里
            if err_re.search(line):
                parsed.append(("[ERR] " + line, COLOR_MAGENTA))
            elif join_re.search(line):
                parsed.append((f"[+] {join_re.search(line).group(1)} 加入游戏", COLOR_GREEN))
            elif left_re.search(line):
                parsed.append((f"[-] {left_re.search(line).group(1)} 离开游戏", COLOR_YELLOW))
            elif chat_re.search(line):
                p, msg = chat_re.search(line).groups()
                parsed.append((f"<{p}> {msg}", COLOR_TEXT))
            else:
                parsed.append((line, COLOR_DIM_TEXT))
        return parsed[-1000:]
    except Exception as e:
        return [(f"[ERR] 日志读取失败: {e}", COLOR_MAGENTA)]


def get_mc_server_uptime():
    """获取 MC 服务器进程真实运行时长（秒）。

    方案 1（最准，跨天/跨重启正确）：读取 java 服务器进程的启动时间
    （/proc/<pid>/stat 的 starttime + 系统启动时刻），纯系统级、不依赖任何插件。
    方案 2（回退）：日志启动完成行 "Done (" 的时间戳估算（当天时间，跨天尽力回推）。
    失败返回 None。
    """
    # 1) 进程级：java -jar server.jar 的启动时刻
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", r"server\.jar"], timeout=3).decode().strip()
        pid = out.split("\n")[0]
        with open("/proc/%s/stat" % pid, "r") as f:
            parts = f.read().split()
        start_ticks = float(parts[21])
        boot = psutil.boot_time()
        ticks = float(os.sysconf("SC_CLK_TCK"))
        start_ts = boot + start_ticks / ticks
        if start_ts > 0:
            return max(0, time.time() - start_ts)
    except Exception:
        pass
    # 2) 回退：日志启动完成行 "Done ("（取最后一条）
    try:
        with open(CONFIG["log_path"], 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(200000)
        m = re.findall(r"\[(\d{1,2}:\d{2}:\d{2})\].*?Done \(", head)
        if m:
            hh, mm, ss = map(int, m[-1].split(":"))
            now = datetime.now()
            start = now.replace(hour=hh, minute=mm, second=ss, microsecond=0)
            days = 0
            while start > now and days < 30:
                start -= timedelta(days=1)
                days += 1
            return max(0, (now - start).total_seconds())
    except Exception:
        pass
    return None


def background_worker():
    _demo_t0 = time.time()
    _demo_msgs = [
        "<Steve> 服务器真不错！",
        "<Alex> 我去下界挖石英了",
        "<Herobrine> 谁把出生点的箱子搬走了？",
        "[Server thread/INFO]: Saved the game",
        "[Server thread/INFO]: Autosave complete",
        "<Steve> 家里的自动熔炉又满了",
        "[Server thread/WARN]: Can't keep up! Is the server overloaded?",
        "<Alex> 今晚打凋灵吗？",
        "[Server thread/INFO]: Done (4.213s)! For help, type \"help\"",
        "<Herobrine> 末地传送门位置在 x=120 z=340",
    ]
    _uptime_tick = 0
    while True:
        get_system_stats()
        get_real_mc_data()
        # 每 ~10 秒刷新 MC 服务器进程真实运行时长（不依赖插件）
        if _uptime_tick % 5 == 0:
            with state.data_lock:
                state.mc_server_uptime = get_mc_server_uptime()
        _uptime_tick += 1
        # 演示模式：无真实 RCON 数据时模拟在线服务器
        if DEMO:
            with state.data_lock:
                if not state.mc_online:
                    state.demo = True
                    state.mc_online = True
                    state.mc_version = "1.21.1"
                    state.mc_players = 3
                    state.player_list = ["Steve", "Alex", "Herobrine"]
                    state.mc_uptime = fmt_uptime(time.time() - _demo_t0)
                state.mc_tps = round(19.6 + random.uniform(-0.5, 0.5), 1)
                state.mc_uptime = fmt_uptime(time.time() - _demo_t0)
            for p in state.player_list:
                if p not in state.avatars:
                    executor.submit(fetch_player_avatar, p)
            with state.log_lock:
                if not state.log_lines:
                    state.log_lines = [
                        (f"[{datetime.now().strftime('%H:%M:%S')}] "
                         f"{random.choice(_demo_msgs)}", COLOR_TEXT)
                        for _ in range(12)
                    ]
                else:
                    state.log_lines.append(
                        (f"[{datetime.now().strftime('%H:%M:%S')}] "
                         f"{random.choice(_demo_msgs)}", COLOR_TEXT))
                    state.log_lines = state.log_lines[-16:]
        logs = parse_logs()
        if not DEMO:
            with state.log_lock:
                state.log_lines = logs
        time.sleep(2)


# ================= 高级 UI 渲染引擎（v3：发光 / 渐变 / 弧度 / 动画） =================
class CyberpunkRenderer:
    def __init__(self, screen, layout):
        self.screen = screen
        self.L = layout
        self.font_tiny   = layout.fontm(16)
        self.font_small  = layout.font(18)
        self.font_med    = layout.font(28)
        self.font_big    = layout.font(52)
        self.font_huge   = layout.font(96)
        self.font_mono   = layout.fontm(18)
        self.font_mono_l = layout.fontm(22)
        self.glow_cache = {}
        self.panel_bg_cache = {}

        self.grid_surf = None
        self.scanline_surf = None
        self.bg_glow_surf = None

        self.glitch_until = 0
        self.glitch_off = 0

        # 数据雨列
        self.rain_cols = []
        self._init_rain()

    # ---------- 通用工具 ----------
    def lerp(self, c1, c2, t):
        return (int(c1[0] + (c2[0] - c1[0]) * t),
                int(c1[1] + (c2[1] - c1[1]) * t),
                int(c1[2] + (c2[2] - c1[2]) * t))

    def text_glow(self, text, font, color, pos, glow_color=None, radius=3):
        """发光文字：低透明度多位移叠加 + 主体"""
        g = glow_color or color
        surf = font.render(text, True, color)
        x, y = pos
        for dy in (-radius, radius):
            self.screen.blit(surf, (x, y + dy))
            for dx in (-radius, radius):
                s = surf.copy()
                s.set_alpha(60)
                self.screen.blit(s, (x + dx, y + dy))
        self.screen.blit(surf, (x, y))

    def text_stroke(self, text, font, color, pos, stroke=2,
                    stroke_color=(0, 0, 0)):
        """抢救公式：纯色文字 + 纯黑描边（不发光），任何亮/暗背景上都清晰"""
        surf = font.render(text, True, color)
        bsurf = font.render(text, True, stroke_color)
        x, y = pos
        for dx in range(-stroke, stroke + 1):
            for dy in range(-stroke, stroke + 1):
                if dx or dy:
                    self.screen.blit(bsurf, (x + dx, y + dy))
        self.screen.blit(surf, (x, y))

    def blur_glow(self, text, font, color, pos, radius=6):
        """模糊光晕（大标题/TPS 用）：缩小再放大模拟高斯模糊"""
        base = font.render(text, True, color)
        x, y = pos
        w, h = base.get_size()
        try:
            small = pygame.transform.smoothscale(base, (max(4, w // 4), max(4, h // 4)))
            glow = pygame.transform.smoothscale(
                small, (w + radius * 2, h + radius * 2))
            glow.set_alpha(75)
            self.screen.blit(glow, (x - radius, y - radius),
                             special_flags=pygame.BLEND_RGBA_ADD)
        except Exception:
            pass
        self.screen.blit(base, (x, y))

    def _init_rain(self):
        chars = "01<>/\\|_+=*#ABCDEFアイウ"
        for i in range(12):
            self.rain_cols.append({
                "x": self.L.w - 20 - i * 24,
                "y": random.randint(-self.L.h, 0),
                "speed": random.uniform(1.4, 3.4),
                "len": random.randint(10, 28),
                "chars": [random.choice(chars) for _ in range(44)],
            })

    # ---------- 背景层（预渲染 + 径向霓虹光晕） ----------
    def build_background_layers(self):
        W, H = self.L.w, self.L.h
        if self.grid_surf is None or self.grid_surf.get_size() != (W, H):
            grid = pygame.Surface((W, H), pygame.SRCALPHA)
            for i in range(0, W, 80):
                pygame.draw.aaline(grid, (24, 44, 62, 95), (i, 0), (i, H))
            for j in range(0, H, 80):
                pygame.draw.aaline(grid, (24, 44, 62, 95), (0, j), (W, j))
            for k in range(1, 8):
                alpha = 14 - k
                if alpha > 0:
                    pygame.draw.aaline(grid, (0, 200, 220, alpha),
                                       (0, H - k * 60), (W, H - k * 60))
            self.grid_surf = grid

        if self.scanline_surf is None or self.scanline_surf.get_size() != (W, H):
            sl = pygame.Surface((W, H), pygame.SRCALPHA)
            for y in range(0, H, 4):
                pygame.draw.line(sl, (0, 0, 0, 40), (0, y), (W, y))
            self.scanline_surf = sl

        # 径向光晕：左上青 + 右下品红（呼吸）
        pulse = 0.5 + 0.5 * math.sin(time.time() * 0.8)
        bg = pygame.Surface((W, H), pygame.SRCALPHA)
        c1 = COLOR_CYAN
        c2 = COLOR_MAGENTA
        for i in range(220, 0, -1):
            a = int((0.5 + 0.4 * pulse) * i / 220 * 9)
            if a <= 0:
                continue
            pygame.draw.circle(bg, (*c1, a), (int(W * 0.12), int(H * 0.22)), i + 40)
            pygame.draw.circle(bg, (*c2, a), (int(W * 0.92), int(H * 0.85)), i + 60)
        self.bg_glow_surf = bg

    def draw_background(self):
        self.screen.fill(COLOR_BG)
        self.screen.blit(self.bg_glow_surf, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
        self.screen.blit(self.grid_surf, (0, 0))
        self.screen.blit(self.scanline_surf, (0, 0))
        self.draw_data_rain()

    # ---------- 数据雨 ----------
    def draw_data_rain(self):
        for col in self.rain_cols:
            cy = col["y"]
            for i in range(col["len"]):
                y = int(cy - i * 22)
                if 0 <= y < self.L.h:
                    ch = col["chars"][i % len(col["chars"])]
                    head = (i == 0)
                    c = COLOR_CYAN if head else (14, 42, 62)
                    s = self.font_tiny.render(ch, True, c)
                    self.screen.blit(s, (int(col["x"]), y))
            col["y"] += col["speed"]
            if col["y"] - col["len"] * 22 > self.L.h:
                col["y"] = random.randint(-self.L.h, -30)

    # ---------- 面板（渐变底 + 多层发光 + 弧形角 + 顶部亮条） ----------
    def get_panel_bg(self, w, h):
        key = (w, h, CURRENT_THEME)
        if key not in self.panel_bg_cache:
            surf = pygame.Surface((w, h), pygame.SRCALPHA)
            # 竖向渐变：顶亮底暗
            top = (*COLOR_PANEL_BG, 216)
            bot = (*COLOR_BG_DEEP, 236)
            for y in range(h):
                t = y / max(1, h - 1)
                c = self.lerp(top, bot, t)
                pygame.draw.line(surf, c, (0, y), (w, y))
            # 顶部内侧亮条（高光）
            for y in range(min(10, h)):
                a = int(70 * (1 - y / 10))
                pygame.draw.line(surf, (*COLOR_CYAN, a), (0, y), (w, y))
            self.panel_bg_cache[key] = surf
        return self.panel_bg_cache[key]

    def get_glow_surface(self, w, h, color=COLOR_CYAN, radius=14):
        key = (w, h, color, radius)
        if key not in self.glow_cache:
            pad = radius + 12
            surf = pygame.Surface((w + pad * 2, h + pad * 2), pygame.SRCALPHA)
            for i in range(8, 0, -1):
                alpha = int(30 * (8 - i + 1) / 9)
                d = pad + i
                pygame.draw.rect(surf, (*color, alpha),
                                 (pad - i, pad - i, w + i * 2, h + i * 2),
                                 border_radius=radius + 4)
            self.glow_cache[key] = surf
        return self.glow_cache[key]

    def draw_panel(self, x, y, w, h, title="", accent=COLOR_CYAN, pulse=True):
        """霓虹呼吸面板：渐变底 + 外发光 + 描边 + 弧形角 + 标题"""
        breath = abs(math.sin(time.time() * 1.6)) * 0.5 + 0.5 if pulse else 0.8
        glow = self.get_glow_surface(w, h, accent)
        glow.set_alpha(int(120 * breath))
        self.screen.blit(glow, (x - 26, y - 26), special_flags=pygame.BLEND_RGBA_ADD)

        self.screen.blit(self.get_panel_bg(w, h), (x, y))

        # 主描边（降亮不抢戏）+ 内描边
        pygame.draw.rect(self.screen, self.lerp(accent, COLOR_BG_DEEP, 0.5),
                         (x, y, w, h), 2, border_radius=12)
        pygame.draw.rect(self.screen, self.lerp(COLOR_PANEL_BG, accent, 0.5),
                         (x + 5, y + 5, w - 10, h - 10), 1, border_radius=9)

        # 顶部发光条（透明层叠加）
        tw = int(w * 0.55)
        top_s = pygame.Surface((tw, 5), pygame.SRCALPHA)
        for i in range(4):
            a = int(60 * (1 - i / 4))
            pygame.draw.line(top_s, (*accent, a), (0, i), (tw, i), 1)
        self.screen.blit(top_s, (x + 18, y + 1),
                         special_flags=pygame.BLEND_RGBA_ADD)

        # 四角弧形括号
        Lc, off = int(w * 0.028), 10
        corners = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
        for cx, cy in corners:
            sgx = 1 if cx > x + w // 2 else -1
            sgy = 1 if cy > y + h // 2 else -1
            pygame.draw.line(self.screen, accent, (cx + sgx * off, cy),
                             (cx + sgx * (off + Lc), cy), 2)
            pygame.draw.line(self.screen, accent, (cx, cy + sgy * off),
                             (cx, cy + sgy * (off + Lc)), 2)
            # 弧
            if sgx == 1 and sgy == -1:
                rect = pygame.Rect(cx - Lc - off, cy - Lc - off, Lc * 2, Lc * 2)
                pygame.draw.arc(self.screen, accent, rect, 0, math.pi / 2, 2)
            elif sgx == -1 and sgy == -1:
                rect = pygame.Rect(cx - off, cy - Lc - off, Lc * 2, Lc * 2)
                pygame.draw.arc(self.screen, accent, rect, math.pi / 2, math.pi, 2)
            elif sgx == -1 and sgy == 1:
                rect = pygame.Rect(cx - off, cy - off, Lc * 2, Lc * 2)
                pygame.draw.arc(self.screen, accent, rect, math.pi, math.pi * 1.5, 2)
            else:
                rect = pygame.Rect(cx - Lc - off, cy - off, Lc * 2, Lc * 2)
                pygame.draw.arc(self.screen, accent, rect, math.pi * 1.5, math.pi * 2, 2)

        if title:
            ts = self.font_small.render("/// " + title, True, accent)
            self.text_glow(title, self.font_small, accent, (x + 30, y - 16),
                           glow_color=accent, radius=2)
            pygame.draw.circle(self.screen, COLOR_GREEN if state.mc_online else COLOR_RED,
                               (x + w - 24, y - 8), 5)
            pygame.draw.circle(self.screen, COLOR_GREEN if state.mc_online else COLOR_RED,
                               (x + w - 24, y - 8), 9, 1)

    # ---------- 环形仪表（外光晕 + 渐变发光弧 + 刻度动画） ----------
    def draw_ring_gauge(self, cx, cy, radius, percent, value_str, label,
                        accent=COLOR_CYAN):
        # 外光晕（半透明：先画到 SRCALPHA 层再叠加，避免 alpha 失效变成实心大圆）
        breath = abs(math.sin(time.time() * 2.2 + cx * 0.01)) * 0.5 + 0.5
        glow_r = radius + 36
        gs = pygame.Surface((glow_r * 2, glow_r * 2), pygame.SRCALPHA)
        for i in range(4, 0, -1):
            a = int(22 * breath * (5 - i) / 5)
            pygame.draw.circle(gs, (*accent, a), (glow_r, glow_r),
                               radius + 20 + i * 4)
        self.screen.blit(gs, (cx - glow_r, cy - glow_r),
                         special_flags=pygame.BLEND_RGBA_ADD)

        # 暗底环
        rect = pygame.Rect(cx - radius, cy - radius, radius * 2, radius * 2)
        pygame.draw.arc(self.screen, COLOR_DARKER, rect,
                        math.radians(-135), math.radians(135), radius and 12)

        # 渐变发光弧（辉光层先画到透明面再叠加 + 主弧）
        pct = max(0.0, min(100.0, percent))
        if pct > 0:
            gs2 = pygame.Surface((radius * 2 + 30, radius * 2 + 30), pygame.SRCALPHA)
            rect2 = pygame.Rect(15, 15, radius * 2, radius * 2)
            steps = max(2, int(pct / 2.5))
            for i in range(steps):
                a0 = math.radians(-135 + i * 270 / steps)
                a1 = math.radians(-135 + (i + 1) * 270 / steps)
                ratio = i / max(1, steps - 1)
                c = self.lerp(accent, COLOR_MAGENTA, ratio * 0.85)
                pygame.draw.arc(gs2, (*c, 70), rect2, a0, a1, 20)      # 辉光
            self.screen.blit(gs2, (cx - radius - 15, cy - radius - 15),
                             special_flags=pygame.BLEND_RGBA_ADD)
            for i in range(steps):
                a0 = math.radians(-135 + i * 270 / steps)
                a1 = math.radians(-135 + (i + 1) * 270 / steps)
                ratio = i / max(1, steps - 1)
                c = self.lerp(accent, COLOR_MAGENTA, ratio * 0.85)
                pygame.draw.arc(self.screen, c, rect, a0, a1, 9)       # 主弧
            end_ang = math.radians(-135 + pct * 2.7)
            ex = cx + math.cos(end_ang) * radius
            ey = cy + math.sin(end_ang) * radius
            pygame.draw.circle(self.screen, (245, 250, 255), (int(ex), int(ey)), 4)

        # 刻度（旋转动画，主刻度改暗色不抢戏）
        offset = time.time() * 30
        for i in range(48):
            ang = math.radians(i * (360 / 48) + (offset % 360))
            r1 = radius + 14
            r2 = radius + 19 if i % 6 == 0 else radius + 17
            x1 = cx + math.cos(ang) * r1
            y1 = cy + math.sin(ang) * r1
            x2 = cx + math.cos(ang) * r2
            y2 = cy + math.sin(ang) * r2
            c = self.lerp(accent, COLOR_BG_DEEP, 0.62) if i % 6 == 0 else COLOR_DARK
            pygame.draw.line(self.screen, c, (x1, y1), (x2, y2), 2)

        # 内圈细环（半透明改不透明暗色，避免 alpha 失效）
        pygame.draw.arc(self.screen, self.lerp(COLOR_DARKER, accent, 0.45),
                        pygame.Rect(cx - radius + 6, cy - radius + 6,
                                    (radius - 6) * 2, (radius - 6) * 2),
                        0, math.pi * 2, 1)

        # 中心数值（纯白 + 粗黑描边，下移避开圆环顶部）+ 百分比 + 标签（环外，黑边）
        vs = self.font_med.render(value_str, True, (255, 255, 255))
        self.text_stroke(value_str, self.font_med, (255, 255, 255),
                         (cx - vs.get_width() // 2, cy - 12), stroke=3)
        psc = accent if pct >= 1 else COLOR_DIM_TEXT
        ps = self.font_tiny.render(f"{percent:.0f}%", True, psc)
        self.text_stroke(f"{percent:.0f}%", self.font_tiny, psc,
                         (cx - ps.get_width() // 2, cy + radius - 2), stroke=2)
        ls = self.font_small.render(label, True, accent)
        self.text_stroke(label, self.font_small, accent,
                         (cx - ls.get_width() // 2, cy + radius + 22), stroke=2)

    # ---------- 内存含量 + TPS 面板 ----------
    def draw_mem_tps_panel(self, x, y, w, h):
        try:
            vm = psutil.virtual_memory()
            used_gb = vm.used / (1024 ** 3)
            total_gb = vm.total / (1024 ** 3)
            pct = vm.percent
        except Exception:
            used_gb = total_gb = 0.0
            pct = 0.0

        lw = int(w * 0.62)
        # 分隔线（发光：透明层叠加）
        pygame.draw.line(self.screen, COLOR_DARK, (x + lw + 8, y + 24),
                         (x + lw + 8, y + h - 24), 1)
        dline = pygame.Surface((3, h - 48), pygame.SRCALPHA)
        pygame.draw.line(dline, (*COLOR_MAGENTA, 70), (1, 0), (1, h - 48), 2)
        self.screen.blit(dline, (x + lw + 9, y + 24),
                         special_flags=pygame.BLEND_RGBA_ADD)

        self.text_glow("内 存 含 量", self.font_small, COLOR_CYAN, (x + 24, y + 16),
                       glow_color=COLOR_CYAN, radius=2)

        # 大字：已用 XG / 共 YG（纯白 + 黑描边，去发光）
        big = self.font_big.render(f"{used_gb:.0f}G / {total_gb:.0f}G", True, (255, 255, 255))
        self.text_stroke(f"{used_gb:.0f}G / {total_gb:.0f}G", self.font_big,
                         (255, 255, 255), (x + 24, y + 50), stroke=3)
        sub = self.font_small.render(f"已用 {used_gb:.1f}G   共 {total_gb:.0f}G",
                                     True, (196, 214, 232))
        self.screen.blit(sub, (x + 24, y + 122))

        # 发光进度条（辉光画透明层）
        bar_x, bar_y, bar_w, bar_h = x + 24, y + 164, lw - 60, 16
        pygame.draw.rect(self.screen, COLOR_DARKER, (bar_x, bar_y, bar_w, bar_h),
                         border_radius=8)
        fill = int(bar_w * min(100, pct) / 100)
        bar_c = (57, 255, 20) if pct < 70 else ((255, 225, 60) if pct < 90 else (255, 60, 60))
        if fill > 0:
            gs = pygame.Surface((fill + 16, bar_h + 14), pygame.SRCALPHA)
            pygame.draw.rect(gs, (*bar_c, 80), (8, 5, fill, bar_h), border_radius=9)
            self.screen.blit(gs, (bar_x - 8, bar_y - 5),
                             special_flags=pygame.BLEND_RGBA_ADD)
            pygame.draw.rect(self.screen, bar_c, (bar_x, bar_y, fill, bar_h),
                             border_radius=8)
            # 前端亮点
            pygame.draw.circle(self.screen, (245, 250, 255),
                               (bar_x + fill, bar_y + bar_h // 2), 4)
        pct_s = self.font_med.render(f"{pct:.0f}%", True, bar_c)
        self.screen.blit(pct_s, (bar_x + bar_w + 18, bar_y - 6))
        for k in range(0, 101, 25):
            gx = bar_x + int(bar_w * k / 100)
            pygame.draw.line(self.screen, COLOR_BG, (gx, bar_y - 4),
                             (gx, bar_y + bar_h + 4), 1)

        # 内存历史折线（发光双层：辉光透明层 + 主细线）
        with state.data_lock:
            mem_hist = list(state.history["内存"])[-60:]
        wx, wy, ww, wh = x + 24, y + 204, lw - 60, h - 234
        pygame.draw.rect(self.screen, COLOR_DARKER, (wx, wy, ww, wh), border_radius=6)
        for gy in range(0, wh + 1, max(1, wh // 4)):
            pygame.draw.line(self.screen, (22, 42, 60), (wx, wy + gy), (wx + ww, wy + gy))
        if len(mem_hist) > 1:
            # 动态范围缩放：按数据实际 min-max 归一化，避免高占用时曲线一直顶格
            lo, hi = min(mem_hist), max(mem_hist)
            if hi - lo < 1.0:
                lo, hi = hi - 5.0, hi + 5.0
            lo = max(0.0, lo - (hi - lo) * 0.15)
            hi = min(100.0, hi + (hi - lo) * 0.15)
            span = max(1.0, hi - lo)
            pts = []
            for i, v in enumerate(mem_hist):
                px = wx + i * (ww / (len(mem_hist) - 1))
                py = wy + wh - ((min(100.0, v) - lo) / span) * wh
                pts.append((px, py))
            gs = pygame.Surface((ww, wh), pygame.SRCALPHA)
            rel = [(px - wx, py - wy) for px, py in pts]
            pygame.draw.lines(gs, (*COLOR_MAGENTA, 90), False, rel, 7)
            self.screen.blit(gs, (wx, wy), special_flags=pygame.BLEND_RGBA_ADD)
            pygame.draw.lines(self.screen, COLOR_MAGENTA, False, pts, 2)
            lx, ly = pts[-1]
            pygame.draw.circle(self.screen, (245, 250, 255), (int(lx), int(ly)), 3)
        tip = self.font_tiny.render("MEM % HISTORY", True, (176, 196, 220))
        self.text_stroke("MEM % HISTORY", self.font_tiny, (176, 196, 220),
                         (wx + 8, wy + 6), stroke=1)

        # 右半：TPS 圆环
        tps = state.mc_tps
        tps_pct = min(100.0, (tps / 20.0) * 100.0) if tps > 0 else 0.0
        cx = x + lw + 10 + (w - lw - 20) // 2
        cy = y + h // 2
        self.draw_ring_gauge(cx, cy, 74, tps_pct, f"{tps:.1f}", "TPS",
                             accent=COLOR_GREEN)
        if tps >= 19:
            note = "SMOOTH 20.0"
            nc = COLOR_GREEN
        elif tps >= 15:
            note = "LAGGING"
            nc = COLOR_YELLOW
        elif tps > 0:
            note = "CRITICAL"
            nc = COLOR_RED
        else:
            note = "NO SIGNAL"
            nc = COLOR_DIM_TEXT
        nt = self.font_small.render(note, True, nc)
        self.screen.blit(nt, (cx - nt.get_width() // 2, cy + 126))

    # ---------- glitch 标题（发光） ----------
    def draw_glitch_title(self, text, cx, top, font=None):
        font = font or self.font_huge
        now = time.time()
        if now > self.glitch_until and random.random() < 0.014:
            self.glitch_until = now + 0.2
            self.glitch_off = random.randint(-9, 9)
        base = font.render(text, True, COLOR_CYAN)
        x = cx - base.get_width() // 2

        # 光晕
        try:
            small = pygame.transform.smoothscale(base, (max(4, base.get_width() // 5),
                                                        max(4, base.get_height() // 5)))
            glow = pygame.transform.smoothscale(small, (base.get_width() + 20,
                                                        base.get_height() + 20))
            glow.set_alpha(70)
            self.screen.blit(glow, (x - 10, top - 10),
                             special_flags=pygame.BLEND_RGBA_ADD)
        except Exception:
            pass

        r = font.render(text, True, COLOR_MAGENTA)
        self.screen.blit(r, (x + 3, top + 2))
        g = font.render(text, True, COLOR_CYAN)
        self.screen.blit(g, (x - 3, top - 2))
        wsurf = font.render(text, True, (245, 250, 255))
        self.screen.blit(wsurf, (x, top))

        if now < self.glitch_until:
            step = 8
            for ry in range(0, wsurf.get_height(), step):
                if random.random() < 0.35:
                    shard = wsurf.subsurface(
                        (0, ry, wsurf.get_width(),
                         min(step, wsurf.get_height() - ry))).copy()
                    self.screen.blit(shard, (x + self.glitch_off, top + ry))
            for _ in range(3):
                sy = top + random.randint(0, wsurf.get_height())
                pygame.draw.line(self.screen, COLOR_CYAN,
                                 (x - 40, sy), (x + wsurf.get_width() + 40, sy), 1)

    # ---------- 顶部状态条 ----------
    def draw_status_bar(self):
        now = datetime.now()
        clock_s = now.strftime("%H:%M:%S")
        date_s = now.strftime("%Y.%m.%d")
        sys_up = fmt_uptime(time.time() - state.sys_boot)
        if state.demo and state.mc_uptime != "--":
            mc_up = state.mc_uptime
        else:
            up = state.mc_server_uptime
            mc_up = fmt_uptime(up) if up is not None else "--"
        mode_txt = {"auto": "AUTO", "day": "DAY", "night": "NIGHT"}[THEME_MODE]

        # 右上角：真实比例标识 + 主题 + 时间 + 运行时长 + RCON
        right = self.L.w - 24
        if state.demo:
            rcon_txt = "RCON SIM"
            rcon_c = COLOR_YELLOW
        else:
            rcon_txt = "RCON " + ("ON" if state.mc_online else "OFF")
            rcon_c = COLOR_GREEN if state.mc_online else COLOR_RED
        items = [
            (f"[{ratio_tag(self.L.w, self.L.h)}]", COLOR_CYAN),
            (f"[THEME:{mode_txt}]", COLOR_MAGENTA if mode_txt != "AUTO" else COLOR_YELLOW),
            (f"[{date_s} {clock_s}]", COLOR_CYAN_DIM),
            (f"[SYS-UP {sys_up}]", COLOR_CYAN_DIM),
            (f"[MC-UP {mc_up}]", COLOR_CYAN_DIM),
            (rcon_txt, rcon_c),
        ]
        x = right
        for it, c in reversed(items):
            s = self.font_mono.render(it, True, c)
            x -= s.get_width() + 24
            pygame.draw.line(self.screen, self.lerp(COLOR_BG, c, 0.3),
                             (x + 2, 12), (x + 2, 34), 1)
            self.screen.blit(s, (x + 8, 14))

        # 左下角节点名（暗色小字，远离边缘避免裁切）
        nm = self.font_small.render(CONFIG["server_name"], True, (44, 68, 92))
        self.screen.blit(nm, (56, 16))

    # ---------- MC 状态面板 ----------
    def draw_mc_status(self, x, y, w):
        sx, sy = x, y
        pw = w
        st = "ONLINE" if state.mc_online else "OFFLINE"
        stc = (255, 255, 255) if state.mc_online else (255, 72, 66)
        stw = self.font_big.render(st, True, stc)
        self.text_stroke(st, self.font_big, stc, (sx, sy), stroke=3)
        pulse_d = int(6 + math.sin(time.time() * 3) * 3)
        pygame.draw.circle(self.screen, stc, (sx + 190, sy + 26), pulse_d)
        pygame.draw.circle(self.screen, self.lerp(COLOR_BG_DEEP, stc, 0.5),
                           (sx + 190, sy + 26), 16, 1)

        # 超大 TPS（纯白 + 粗黑描边，去发光——亮底上必须黑边才浮得出来）
        tps_txt = f"{state.mc_tps:.1f}"
        tps_color = COLOR_GREEN if state.mc_tps >= 19 else \
            (COLOR_YELLOW if state.mc_tps >= 15 else
             (COLOR_RED if state.mc_tps > 0 else COLOR_DIM_TEXT))
        self.text_stroke(tps_txt, self.font_huge, (255, 255, 255),
                         (sx, sy + 64), stroke=3)
        tps_label = self.font_med.render("TPS", True, COLOR_CYAN)
        self.text_stroke("TPS", self.font_med, COLOR_CYAN,
                         (sx + 210, sy + 118), stroke=2)
        # TPS 底部刻度条
        tw = min(200, int(pw * 0.35))
        pygame.draw.rect(self.screen, COLOR_DARKER, (sx, sy + 186, tw, 8), border_radius=4)
        tps_pct = min(1.0, state.mc_tps / 20.0)
        pygame.draw.rect(self.screen, tps_color, (sx, sy + 186, int(tw * tps_pct), 8),
                         border_radius=4)

        # 信息行（白字 + 细黑边；用黑体渲染，中文绝不方块）
        if state.demo and state.mc_uptime != "--":
            mc_up = state.mc_uptime
        else:
            up = state.mc_server_uptime
            mc_up = fmt_uptime(up) if up is not None else "--"
        infos = [
            (f"运行时长: {mc_up}", (255, 255, 255)),
            (f"版本: {state.mc_version}", (255, 255, 255)),
            (f"玩家: {state.mc_players}/{CONFIG['max_players']}", (255, 255, 255)),
            (f"日志: {CONFIG['log_path'][-30:]}", (176, 196, 220)),
        ]
        for i, (line, c) in enumerate(infos):
            s = self.font_small.render(line, True, c)
            self.text_stroke(line, self.font_small, c, (sx, sy + 218 + i * 30), stroke=1)
            pygame.draw.line(self.screen, COLOR_DARK,
                             (sx, sy + 208 + i * 30),
                             (sx + pw - 60, sy + 208 + i * 30))

    # ---------- 玩家卡片 ----------
    def draw_player_card(self, x, y, name, avatar_surf, online=True):
        Lc = self.L
        size = Lc.r(100)
        # 发光边框（透明层叠加）
        glow_s = pygame.Surface((size + 14, size + 14), pygame.SRCALPHA)
        for i in range(3, 0, -1):
            a = int(46 / (4 - i))
            pygame.draw.rect(glow_s, (*COLOR_CYAN, a),
                             (7 - i, 7 - i, size + i * 2, size + i * 2),
                             2, border_radius=6)
        self.screen.blit(glow_s, (x - 7, y - 7),
                         special_flags=pygame.BLEND_RGBA_ADD)
        pygame.draw.rect(self.screen, COLOR_DARKER, (x, y, size, size), border_radius=6)
        pygame.draw.rect(self.screen, COLOR_CYAN, (x, y, size, size), 2, border_radius=6)
        if avatar_surf:
            try:
                self.screen.blit(pygame.transform.smoothscale(avatar_surf, (size, size)), (x, y))
            except Exception:
                avatar_surf = None
        if not avatar_surf:
            # 赛博风占位：发光头影 + 面罩 + 扫描线
            cxm, cym = x + size // 2, y + int(size * 0.38)
            hr = int(size * 0.26)
            head = pygame.Surface((hr * 2 + 8, hr * 2 + 8), pygame.SRCALPHA)
            for i in range(3, 0, -1):
                pygame.draw.circle(head, (*COLOR_MAGENTA, 34 // i),
                                   (hr + 4, hr + 4), hr + i * 2)
            self.screen.blit(head, (cxm - hr - 4, cym - hr - 4),
                             special_flags=pygame.BLEND_RGBA_ADD)
            pygame.draw.circle(self.screen, COLOR_DARKER, (cxm, cym), hr)
            pygame.draw.circle(self.screen, COLOR_MAGENTA, (cxm, cym), hr, 2)
            # 面罩
            mw, mh = int(hr * 1.3), int(hr * 0.5)
            pygame.draw.rect(self.screen, COLOR_CYAN,
                             (cxm - mw // 2, cym + int(hr * 0.25), mw, mh),
                             border_radius=4)
            pygame.draw.line(self.screen, (0, 60, 70),
                             (cxm - mw // 2 + 3, cym + int(hr * 0.25) + mh // 2),
                             (cxm + mw // 2 - 3, cym + int(hr * 0.25) + mh // 2), 1)
            # 底部轮廓
            pygame.draw.arc(self.screen, COLOR_DARK,
                            (cxm - hr, cym - hr, hr * 2, int(hr * 1.9)),
                            0, math.pi, 2)
        # 在线点 + 名字
        pygame.draw.circle(self.screen, COLOR_GREEN if online else COLOR_RED,
                           (x + size - 12, y + 12), 5)
        ns = self.font_small.render(name, True, COLOR_TEXT)
        self.screen.blit(ns, (x + size // 2 - ns.get_width() // 2, y + size + 10))

    # ---------- 日志（终端式：整行显示自动折行 + 跟随/滚动） ----------
    def draw_logs(self, x, y, logs, rows=5, pw=0):
        Lc = self.L
        pw = pw or (x and self.L.w - x - 30)
        if not logs:
            return
        # 折行缓存（日志内容变化才重建，避免每帧重复计算）
        if state.log_wrap_key != id(logs):
            state.log_wrap_key = id(logs)
            max_w = pw - 36          # 文字从左边铺到面板右缘留 20px
            half_w = self.font_mono.size("M")[0]
            full_w = self.font_mono.size("中")[0]
            flat = []
            for line, color in logs:
                for seg in wrap_text(line, self.font_mono, max_w, half_w, full_w):
                    flat.append((seg, color))
            state.log_wrap_flat = flat
        flat = state.log_wrap_flat
        total = len(flat)
        if total == 0:
            return
        line_h = Lc.r(38)
        max_scroll = max(0, total - rows)
        scroll = max(0, min(state.log_scroll, max_scroll))
        state.log_scroll = scroll
        start = total - rows - scroll
        shown = flat[start:start + rows]
        for i, (line, color) in enumerate(shown):
            ly = y + i * line_h
            s = self.font_mono.render(line, True, color)
            self.screen.blit(s, (x + 16, ly))
            pygame.draw.line(self.screen, (16, 30, 44), (x + 10, ly + line_h - 2),
                             (x + 10, ly + line_h - 2))
        if scroll > 0:
            ind = f"[↑{scroll}行  {max_scroll - scroll + 1}/{max_scroll + 1}]  R/↓=回最新"
            ic = COLOR_YELLOW
        else:
            ind = "[LIVE] 新日志自动跟随  ↑/滚轮=查看历史"
            ic = COLOR_GREEN
        s = self.font_tiny.render(ind, True, ic)
        self.screen.blit(s, (x + pw - 50 - s.get_width(), y + rows * line_h + 6))

    # ---------- 鼠标悬停提示框 ----------
    def draw_tooltip(self, lines, mx, my):
        """半透明黑底圆角框 + 白字黑边，跟随鼠标显示"""
        f = self.font_tiny
        heights = f.get_height()
        w = max(f.render(l, True, (255, 255, 255)).get_width() for l in lines) + 26
        h = len(lines) * (heights + 6) + 16
        x, y = mx + 20, my + 20
        if x + w > self.L.w - 8:
            x = mx - w - 20
        if y + h > self.L.h - 8:
            y = my - h - 20
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        surf.fill((3, 7, 11, 215))
        pygame.draw.rect(surf, (*COLOR_CYAN, 255), (0, 0, w, h), 1, border_radius=6)
        pygame.draw.line(surf, (*COLOR_MAGENTA, 220), (8, 6), (8, h - 6), 2)
        self.screen.blit(surf, (x, y))
        for i, line in enumerate(lines):
            self.text_stroke(line, f, (255, 255, 255),
                             (x + 14, y + 9 + i * (heights + 6)), stroke=1)

    # ---------- 全局噪点 ----------
    def draw_noise(self):
        for _ in range(70):
            nx = random.randint(0, self.L.w)
            ny = random.randint(0, self.L.h)
            c = random.choice([(255, 255, 255, 26), (0, 240, 255, 22), (255, 0, 127, 18)])
            self.screen.set_at((nx, ny), c)

    # ---------- 移动扫描亮线 ----------
    def draw_scan_beam(self):
        y = int((time.time() * 90) % (self.L.h + 200)) - 100
        surf = pygame.Surface((self.L.w, 3), pygame.SRCALPHA)
        surf.fill((*COLOR_CYAN, 120))
        self.screen.blit(surf, (0, y), special_flags=pygame.BLEND_RGBA_ADD)


# ================= 主程序 =================
def pick_sdl_driver():
    """无图形会话时选择可用的视频驱动（返回诊断字符串列表）"""
    diag = []
    if os.environ.get('SDL_VIDEODRIVER'):
        diag.append(f"SDL_VIDEODRIVER 已显式指定: {os.environ['SDL_VIDEODRIVER']}")
        return diag
    if os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
        diag.append("检测到图形会话，交给 SDL 自动选择驱动")
        return diag
    # 无 DISPLAY / Wayland：尝试内核直驱
    if sys.platform.startswith('linux') and os.path.exists('/dev/dri/card0'):
        os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
        diag.append("使用 kmsdrm（内核 DRM/KMS 直驱，无需图形桌面）")
        diag.append("提示: kmsdrm 需要在本地 tty 运行并拥有 /dev/dri 权限，SSH 会话通常拿不到 DRM master")
    else:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["MC_WINDOWED"] = "1"
        diag.append("未检测到 /dev/dri/card0，服务器没有可用的真实显示设备")
        diag.append("已用 dummy 驱动兜底（可运行、可 S 键截图，但屏幕上看不到画面）")
        diag.append("想要真实画面：① 接 HDMI 显示器/GPU 真机运行；② 安装 Xvfb 虚拟显示；③ 用 SDL_VIDEODRIVER=dummy 仅预览截图")
    return diag


def init_display():
    """初始化显示，返回 (screen, W, H)；失败时打印诊断并用 dummy 兜底"""
    diag = pick_sdl_driver()
    for line in diag:
        print("[DIAG]", line)

    # 无音频设备（无头服务器）时用 dummy 音频驱动，避免 ALSA 刷屏报错
    if "SDL_AUDIODRIVER" not in os.environ:
        os.environ["SDL_AUDIODRIVER"] = "dummy"

    pygame.init()

    windowed = os.environ.get("MC_WINDOWED", "") == "1"
    try:
        if windowed:
            W = int(os.environ.get("MC_WIDTH", CONFIG["width"]))
            H = int(os.environ.get("MC_HEIGHT", CONFIG["height"]))
            screen = pygame.display.set_mode((W, H))
        else:
            try:
                screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            except Exception:
                screen = pygame.display.set_mode((CONFIG["width"], CONFIG["height"]))
        W, H = screen.get_size()
        pygame.mouse.set_visible(False)
        return screen, W, H
    except pygame.error as e:
        print(f"[ERROR] 显示初始化失败: {e}")
        print("[DIAG] 排查步骤：")
        print("  · ls -l /dev/dri/    → 是否存在 card0（GPU 直驱的前提）")
        print("  · groups              → 当前用户是否在 video 组（不在则 sudo usermod -aG video $USER）")
        print("  · 是否在本地 tty 运行 → kmsdrm 需要 DRM master，SSH 远程会话拿不到")
        print("  · 无显示设备方案：接 HDMI 真机 / 装 Xvfb / SDL_VIDEODRIVER=dummy 预览")
        print("[DIAG] 已降级为 dummy 驱动兜底（可运行、可 S 键截图，但无真实画面）")
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["MC_WINDOWED"] = "1"
        screen = pygame.display.set_mode((CONFIG["width"], CONFIG["height"]))
        pygame.mouse.set_visible(False)
        return screen, screen.get_width(), screen.get_height()


def main():
    screen, W, H = init_display()
    layout = Layout(W, H)
    renderer = CyberpunkRenderer(screen, layout)
    renderer.build_background_layers()
    clock = pygame.time.Clock()

    # 系统开机时间基准
    try:
        state.sys_boot = psutil.boot_time()
    except Exception:
        state.sys_boot = time.time() - 600

    threading.Thread(target=background_worker, daemon=True).start()
    last_theme_check = 0.0

    running = True
    while running:
        mx, my = pygame.mouse.get_pos()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_t:
                    cycle_theme_mode()
                    renderer.panel_bg_cache = {}
                    renderer.bg_glow_surf = None
                elif event.key == pygame.K_s:
                    save_shot(screen)
                elif event.key == pygame.K_UP:
                    with state.log_lock:
                        state.log_scroll += 1
                elif event.key == pygame.K_DOWN:
                    with state.log_lock:
                        state.log_scroll = max(0, state.log_scroll - 1)
                elif event.key == pygame.K_r:
                    with state.log_lock:
                        state.log_scroll = 0
            elif event.type == pygame.MOUSEWHEEL:
                # 鼠标停在日志面板内时，滚轮滚动历史（上滚=看更早 3 行，下滚=回最新）
                p5r = layout.rect(960, 760, 792, 220)
                if (p5r[0] <= mx <= p5r[0] + p5r[2]
                        and p5r[1] <= my <= p5r[1] + p5r[3]):
                    with state.log_lock:
                        state.log_scroll = max(0, state.log_scroll + event.y * 3)

        # 主题自动切换
        if time.time() - last_theme_check > 5:
            auto_theme_check()
            last_theme_check = time.time()
            renderer.build_background_layers()

        renderer.build_background_layers()
        renderer.draw_background()

        # ---- 标题 + 状态条 ----
        renderer.draw_glitch_title("服 务 器 监 控", layout.w // 2, 16, renderer.font_big)
        renderer.draw_status_bar()

        # ---- 面板（参考图同款布局） ----
        p1 = layout.rect(40, 100, 900, 520)
        p2 = layout.rect(40, 640, 900, 340)
        p3 = layout.rect(960, 100, 792, 330)
        p4 = layout.rect(960, 450, 792, 290)
        p5 = layout.rect(960, 760, 792, 220)
        renderer.draw_panel(*p1, "SYSTEM MONITOR")
        renderer.draw_panel(*p2, "MEMORY & TPS", accent=COLOR_MAGENTA)
        renderer.draw_panel(*p3, "MC SERVER STATUS")
        renderer.draw_panel(*p4,
                            f"ONLINE PLAYERS ({state.mc_players}/{CONFIG['max_players']})",
                            accent=COLOR_MAGENTA)
        renderer.draw_panel(*p5, "SYSTEM LOGS")

        # ---- 八大仪表（2 行 x 4 列） ----
        with state.data_lock:
            stats_copy = dict(state.system_stats)
        labels = list(stats_copy.keys())
        accent_map = {
            "CPU": COLOR_CYAN, "内存": COLOR_CYAN, "磁盘": COLOR_CYAN,
            "网络↓": COLOR_GREEN, "TPS": COLOR_GREEN,
            "在线": COLOR_MAGENTA, "日志": COLOR_YELLOW, "线程": COLOR_MAGENTA,
        }
        for i, label in enumerate(labels):
            row, col = i // 4, i % 4
            cx, cy = layout.xy(40 + 70 + col * 215, 100 + 140 + row * 210)
            val, pct = stats_copy.get(label, ("--", 0))
            renderer.draw_ring_gauge(cx, cy, layout.r(58), pct, str(val), label,
                                     accent_map.get(label, COLOR_CYAN))

        # ---- 内存含量 + TPS 面板 ----
        renderer.draw_mem_tps_panel(*p2)

        # ---- MC 状态面板 ----
        sx, sy = layout.xy(990, 135)
        renderer.draw_mc_status(sx, sy, p3[2])

        # ---- 玩家卡片（2 行 x 4） ----
        with state.data_lock:
            players_copy = list(state.player_list)
            avatars_copy = dict(state.avatars)
        for i, pname in enumerate(players_copy[:8]):
            row, col = i // 4, i % 4
            ax, ay = layout.xy(990 + col * 178, 480 + row * 128)
            renderer.draw_player_card(ax, ay, pname, avatars_copy.get(pname))
        rpct = (state.mc_players / CONFIG["max_players"] * 100.0) if CONFIG["max_players"] else 0
        rn = renderer.font_med.render(f"{state.mc_players}/{CONFIG['max_players']}",
                                      True, COLOR_MAGENTA)
        rx, ry = layout.xy(1670, 592)
        renderer.text_stroke(f"{state.mc_players}/{CONFIG['max_players']}",
                             renderer.font_med, COLOR_MAGENTA, (rx, ry), stroke=2)
        rt = renderer.font_tiny.render(f"{rpct:.0f}%", True, COLOR_DIM_TEXT)
        renderer.screen.blit(rt, (rx, layout.xy(0, 645)[1]))
        if not players_copy:
            tip_txt = "AWAITING PLAYERS // NO SIGNAL"
            tip = renderer.font_med.render(tip_txt, True, (255, 225, 60))
            tx, ty = layout.xy(990 + 100, 600)
            renderer.text_stroke(tip_txt, renderer.font_med, (255, 225, 60),
                                 (tx, ty), stroke=2)

        # ---- 日志 ----
        with state.log_lock:
            logs_copy = list(state.log_lines)
        lx, ly = layout.xy(975, 780)
        renderer.draw_logs(lx, ly, logs_copy, rows=5, pw=p5[2])

        # ---- 鼠标交互：悬停仪表/玩家卡 → 信息提示 ----
        hover_tip = None
        for i, label in enumerate(labels):
            row, col = i // 4, i % 4
            gcx, gcy = layout.xy(40 + 70 + col * 215, 100 + 140 + row * 210)
            if (mx - gcx) ** 2 + (my - gcy) ** 2 <= (layout.r(58) + 12) ** 2:
                val, pct = stats_copy.get(label, ("--", 0))
                unit = "" if label in ("在线", "线程", "日志") else (
                    "G" if label in ("内存", "磁盘") else (
                        "MB/s" if label == "网络↓" else (
                            "TPS" if label == "TPS" else "%")))
                hover_tip = [f"{label}  {val} {unit}".strip(),
                             f"负载 {pct:.0f}%"]
                break
        if hover_tip is None and players_copy:
            for i, pname in enumerate(players_copy[:8]):
                row, col = i // 4, i % 4
                ax2, ay2 = layout.xy(990 + col * 178, 480 + row * 128)
                if (ax2 <= mx <= ax2 + layout.r(100)
                        and ay2 <= my <= ay2 + layout.r(100)):
                    hover_tip = [f"玩家: {pname}", "ONLINE"]
                    break
        if hover_tip:
            renderer.draw_tooltip(hover_tip, mx, my)

        # ---- 特效叠加 ----
        renderer.draw_scan_beam()
        renderer.draw_noise()

        # ---- 演示模式水印（诚实标注，避免被误认为真实数据） ----
        if state.demo:
            wm = renderer.font_small.render("DEMO SIMULATION · 模拟数据预览",
                                            True, COLOR_YELLOW)
            wx0 = layout.w - wm.get_width() - 24
            wy0 = layout.h - wm.get_height() - 18
            pygame.draw.line(renderer.screen, COLOR_YELLOW, (wx0 - 8, wy0 + 9),
                             (wx0 + wm.get_width() + 8, wy0 + 9), 1)
            pygame.draw.line(renderer.screen, (*COLOR_YELLOW, 80),
                             (wx0 - 8, wy0 + 12), (wx0 + wm.get_width() + 8, wy0 + 12), 1)
            renderer.screen.blit(wm, (wx0, wy0))
            # 中央大号半透明 DEMO 水印
            big_wm = renderer.font_big.render("D E M O", True, (255, 200, 0))
            wms = pygame.Surface(big_wm.get_size(), pygame.SRCALPHA)
            wms.blit(big_wm, (0, 0))
            wms.set_alpha(46)
            renderer.screen.blit(wms, (layout.w // 2 - big_wm.get_width() // 2,
                                       int(layout.h * 0.82)))

        # ---- 鼠标准星 ----
        pygame.draw.aaline(renderer.screen, COLOR_CYAN, (mx - 16, my), (mx + 16, my))
        pygame.draw.aaline(renderer.screen, COLOR_CYAN, (mx, my - 16), (mx, my + 16))
        pygame.draw.circle(renderer.screen, COLOR_MAGENTA, (mx, my), 6, 1)
        pygame.draw.circle(renderer.screen, COLOR_MAGENTA, (mx, my), 2)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
