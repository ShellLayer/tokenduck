"""TokenDuck —— Windows 任务栏内嵌显示 Codex CLI 用量额度 + Kimi 用量额度 + ZCode 用量额度。

数据来源：
- codex：~/.codex/auth.json 的 ChatGPT 登录态（支持 CODEX_HOME）+ wham/usage 接口。
- kimi：kimi.com 网页登录态（优先从桌面端导入并建立独立会话，
  见 fetch_kimi_quota）+ 订阅页“额度”接口（5 小时/每周窗口 + 月总额度）。
  绑定账号保持固定；换号时使用右键菜单“账户与登录…”。
- zcode：ZCode 桌面端（bigmodel/GLM）~/.zcode/v2/credentials.json 的加密凭证
  （AES-256-GCM，密钥为本机推导）+ 官方 MCP 额度接口（月总额度）。
纯标准库实现（tkinter + ctypes + urllib），零第三方依赖。
本工具的凭证由 Windows 当前用户加密；新安装存放在 %APPDATA%/tokenduck/，
已有用户原地复用旧目录。卸载和数据清理见 docs/USAGE.md。
调试：python tokenduck.py --once 单次拉取三家数据并打印。
"""

import base64
import ctypes
import getpass
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone

from secure_store import CredentialStore, CredentialStoreError, protect_bytes, unprotect_bytes

APP_VERSION = "0.3.0"
RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else RESOURCE_DIR
# 敏感数据（登录令牌）统一放 %APPDATA%，避免桌面目录被 OneDrive 等网盘同步上云
def select_data_directory(appdata):
    """新安装使用 TokenDuck 目录；已有用户原地复用旧数据，不复制或解密凭证。"""
    current = os.path.join(appdata, "tokenduck")
    legacy = os.path.join(appdata, "codexbar")
    known_files = ("accounts.dat", "config.json", "kimi_web.json", "usage_cache.json")
    populated = lambda directory: any(os.path.isfile(os.path.join(directory, name))
                                      for name in known_files)
    return legacy if populated(legacy) and not populated(current) else current


DATA_DIR = select_data_directory(
    os.environ.get("APPDATA", os.path.expanduser("~/AppData/Roaming")))
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LEGACY_CONFIG_PATH = os.path.join(APP_DIR, "config.json")
CACHE_PATH = os.path.join(DATA_DIR, "usage_cache.json")
ACCOUNT_STORE = CredentialStore(os.path.join(DATA_DIR, "accounts.dat"))
AUTH_PATH = os.path.join(
    os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex")), "auth.json")
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

DEFAULT_CONFIG = {
    "interval_minutes": 5,   # 自动刷新间隔
    "offset_x": 8,           # 与托盘图标区间的像素间距
    "font_size": 9,          # 上限；任务栏放不下三行时会自动缩小
    "data_font_size": 8,     # 常驻额度文字大小，按任务栏高度自动缩小
    "text_color": "",        # 留空 = 跟随系统主题自动
    "background": "",        # 留空 = 透明背景；可填 "#202020" 等变为纯色卡片
    "chip": True,            # 透明模式下垫一层极淡圆角色块（整块可点击；false = 纯浮字）
    "allow_browser_import": False,  # 仅在连接窗口中主动选择后启用浏览器导入
}

# 调试日志：TOKENDUCK_DEBUG=1 记录详情；未开启时也限频记录意外回调异常
DEBUG = bool(os.environ.get("TOKENDUCK_DEBUG") or os.environ.get("CODEXBAR_DEBUG"))
LOG_PATH = os.path.join(os.environ.get("TEMP", APP_DIR), "tokenduck_debug.log")
_last_forced_log = 0.0


def _dbg(msg, force=False):
    global _last_forced_log
    if not DEBUG:
        if not force:
            return
        now = time.monotonic()
        if now - _last_forced_log < 60:
            return
        _last_forced_log = now
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (
                datetime.now().strftime("%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def migrate_data_files():
    """迁移配置与旧凭证；先加密并校验，再移除旧明文。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    for old in (os.path.join(DATA_DIR, "kimi_web.json"), os.path.join(APP_DIR, "kimi_web.json")):
        if os.path.isfile(old):
            with open(old, "r", encoding="utf-8-sig") as f:
                cred = json.load(f)
            user = cred.get("_user") or _jwt_user(cred.get("access_token", ""))
            ACCOUNT_STORE.migrate_json(old, "kimi_web", {"kimi_account_id": user} if user else {})
    if not os.path.exists(CONFIG_PATH) and os.path.isfile(LEGACY_CONFIG_PATH):
        with open(LEGACY_CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            legacy = json.load(f)
        if isinstance(legacy, dict):
            _migrate_config_key(legacy, LEGACY_CONFIG_PATH)
            save_config(legacy)
    elif os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
                current = json.load(f)
        except (OSError, ValueError):
            current = None
        if isinstance(current, dict) and current.get("kimi_api_key"):
            _migrate_config_key(current, CONFIG_PATH)


def _migrate_config_key(config, source):
    key = config.get("kimi_api_key")
    if isinstance(key, str) and key.strip():
        existing = ACCOUNT_STORE.get("kimi_api_key")
        if existing and existing != key.strip():
            raise CredentialStoreError("新旧 Kimi key 不一致，未覆盖原配置")
        ACCOUNT_STORE.update({"kimi_api_key": key.strip()})
        if ACCOUNT_STORE.get("kimi_api_key") != key.strip():
            raise CredentialStoreError("key 加密校验失败，已保留原配置")
        clean = dict(config)
        clean.pop("kimi_api_key", None)
        temporary = source + ".tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        os.replace(temporary, source)
    config.pop("kimi_api_key", None)


def save_config(config):
    """公开设置不保存 key 或令牌。"""
    safe = {k: config.get(k, value) for k, value in DEFAULT_CONFIG.items()}
    os.makedirs(DATA_DIR, exist_ok=True)
    temporary = CONFIG_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(safe, f, ensure_ascii=False, indent=2)
    os.replace(temporary, CONFIG_PATH)

def select_startup_path(appdata):
    directory = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    current = os.path.join(directory, "tokenduck.vbs")
    legacy = os.path.join(directory, "codexbar.vbs")
    # 原地更新已有自启，避免更名后重复启动；不删除其他程序的启动项。
    return legacy if os.path.isfile(legacy) and not os.path.isfile(current) else current


STARTUP_VBS = select_startup_path(os.environ.get("APPDATA", ""))


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    cfg.update(raw)
        except (OSError, ValueError, TypeError):
            _dbg("配置文件不可读，使用默认配置", force=True)
    else:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    for key, lo, hi in (("interval_minutes", 1, 1440),
                        ("offset_x", -1000, 10000), ("font_size", 6, 24),
                        ("data_font_size", 6, 14)):
        try:
            n = int(cfg[key])
            cfg[key] = n if lo <= n <= hi else DEFAULT_CONFIG[key]
        except (TypeError, ValueError, OverflowError):
            cfg[key] = DEFAULT_CONFIG[key]
    for key in ("background", "text_color"):
        value = cfg.get(key)
        if not isinstance(value, str) or (value and not re.fullmatch(r"#[0-9a-fA-F]{6}", value)):
            cfg[key] = DEFAULT_CONFIG[key]
    if not isinstance(cfg.get("chip"), bool):
        cfg["chip"] = DEFAULT_CONFIG["chip"]
    cfg.pop("kimi_api_key", None)
    if not isinstance(cfg.get("allow_browser_import"), bool):
        cfg["allow_browser_import"] = False
    return cfg


_QUOTA_HOSTS = {"chatgpt.com", "www.kimi.com", "auth.kimi.com", "api.kimi.com",
                "zcode.z.ai", "open.bigmodel.cn", "api.z.ai"}


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        before, after = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (after.scheme != "https" or after.netloc.casefold() != before.netloc.casefold()):
            raise urllib.error.HTTPError(req.full_url, code, "已阻止跨站或不安全的重定向", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _urlopen(request, timeout=15):
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in _QUOTA_HOSTS or
            parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443)):
        raise RuntimeError("已阻止向非官方或不安全的地址发送凭证")
    try:
        return urllib.request.build_opener(_SameOriginRedirect()).open(request, timeout=timeout)
    except urllib.error.HTTPError as e:
        e.close()
        raise


def _blend(c1, c2, t):
    """颜色 c1 向 c2 混合 t(0~1)。"""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _rr_points(x1, y1, x2, y2, r):
    """圆角矩形多边形顶点（配合 canvas smooth 使用）。"""
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1, x1 + r, y1]


def _system_uses_light_theme():
    """读取系统任务栏深浅设置；读取失败时返回 None。"""
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "SystemUsesLightTheme")[0])
    except Exception:
        return None


def _contrast_text_color(bg):
    r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return "#1b1b1b" if lum >= 128 else "#ffffff"


def _theme_palette(bg, fg):
    return bg, fg, _blend(fg, bg, 0.55), _blend(fg, bg, 0.12)


def detect_theme_colors(exclude_rect=None):
    """采样任务栏实际像素，返回 (背景色, 文字色, 弱化色, 进度条底色)。

    exclude_rect 用于排除悬浮窗自身，避免把上次渲染结果当成任务栏颜色。
    明确偏深/偏浅的采样支持自定义任务栏；中间亮度以系统主题稳定文字色。
    """
    colors = []
    dc = None
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        shell = user32.FindWindowW("Shell_TrayWnd", None)
        if shell:
            rect = RECT()
            user32.GetWindowRect(shell, ctypes.byref(rect))
            # 只采样停靠位置附近的一段（任务栏有渐变，全局中位色会有色差）
            x0, x1 = rect.left + 100, rect.right - 100
            tray = user32.FindWindowExW(shell, None, "TrayNotifyWnd", None)
            if tray:
                trect = RECT()
                user32.GetWindowRect(tray, ctypes.byref(trect))
                x0 = max(rect.left + 20, trect.left - 450)
                x1 = max(x0 + 20, trect.left - 200)
            dc = user32.GetDC(0)
            y = (rect.top + rect.bottom) // 2
            x = x0
            while x < x1:
                excluded = (exclude_rect is not None and
                            exclude_rect[0] <= x < exclude_rect[2] and
                            exclude_rect[1] <= y < exclude_rect[3])
                if not excluded:
                    c = gdi32.GetPixel(dc, x, y)
                    if c != -1:
                        colors.append((c & 0xFF, (c >> 8) & 0xFF,
                                       (c >> 16) & 0xFF))
                x += 8
    except Exception:
        colors = []
    finally:
        if dc:
            try:
                ctypes.windll.user32.ReleaseDC(0, dc)
            except Exception:
                pass
    light = _system_uses_light_theme()
    if colors:
        rs = sorted(c[0] for c in colors)
        gs = sorted(c[1] for c in colors)
        bs = sorted(c[2] for c in colors)
        mid = len(colors) // 2
        bg = "#%02x%02x%02x" % (rs[mid], gs[mid], bs[mid])
        lum = 0.299 * rs[mid] + 0.587 * gs[mid] + 0.114 * bs[mid]
        if lum <= 80:
            light = False
        elif lum >= 180:
            light = True
        elif light is None:
            light = lum >= 128
    else:
        if light is None:
            light = False
        bg = "#f2f2f2" if light else "#1c1c1c"
    fg = "#1b1b1b" if light else "#ffffff"
    return _theme_palette(bg, fg)


def fetch_usage(timeout=15):
    """读取 auth.json 并请求用量接口，返回响应 dict。失败抛 RuntimeError。"""
    if not os.path.exists(AUTH_PATH):
        raise RuntimeError("未找到 ~/.codex/auth.json，请先运行 codex 登录")
    try:
        with open(AUTH_PATH, "r", encoding="utf-8") as f:
            auth = json.load(f)
        tokens = auth["tokens"]
        access_token = tokens["access_token"]
        account_id = tokens["account_id"]
    except (KeyError, json.JSONDecodeError):
        raise RuntimeError("auth.json 格式异常，请重新运行 codex 登录")

    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": "Bearer " + access_token,
            "ChatGPT-Account-Id": account_id,
            "User-Agent": "tokenduck",
            "Accept": "application/json",
        },
    )
    try:
        with _urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError("登录已过期 (401)，请在终端运行一次 codex")
        raise RuntimeError("HTTP %s" % e.code)
    except Exception as e:
        raise RuntimeError("网络错误：%s" % e)


# ---------- kimi：网页登录态 + 订阅额度（5h/每周窗口 + 月总额度） ----------

KIMI_WEB_CRED_PATH = os.path.join(DATA_DIR, "kimi_web.json")
# 网页版“订阅-额度”页的数据接口（connect-RPC，JSON over POST）。
# 鉴权用 kimi.com 网页登录态（浏览器 localStorage 的 access_token / refresh_token）；
# kimi CLI 的 OAuth token 与此网关不兼容（签名算法不同，401），不能混用。
KIMI_QUOTA_URL = ("https://www.kimi.com/apiv2/kimi.gateway.membership.v2"
                  ".MembershipService/GetSubscriptionStats")
# 以下 RPC 都在 auth.kimi.com（网页版 AuthService；字段用蛇形命名也能解析）
KIMI_WEB_REFRESH_URL = ("https://auth.kimi.com/api/account.gateway.v1"
                        ".AuthService/RefreshToken")
KIMI_QR_CREATE_URL = ("https://auth.kimi.com/api/account.gateway.v1"
                      ".AuthService/CreateLoginQRCode")
KIMI_QR_SCAN_URL = ("https://auth.kimi.com/api/account.gateway.v1"
                    ".AuthService/ScanLoginQRCode")
KIMI_QR_CONFIRM_URL = ("https://auth.kimi.com/api/account.gateway.v1"
                       ".AuthService/ConfirmLoginQRCode")
KIMI_QR_STATUS_URL = ("https://auth.kimi.com/api/account.gateway.v1"
                      ".AuthService/GetLoginQRCodeStatus")


def _connect_post(url, obj, token=None, timeout=15):
    """connect-RPC 一元调用（JSON）。HTTP/网络错误原样抛出。"""
    headers = {
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
        "Accept": "application/json",
        "User-Agent": "tokenduck",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers=headers)
    with _urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _read_kimi_web_cred():
    """只读本工具的加密会话；解密失败须报错，不能悄悄覆盖原凭证。"""
    cred = ACCOUNT_STORE.get("kimi_web")
    if isinstance(cred, dict) and isinstance(cred.get("access_token"), str) and cred["access_token"]:
        return cred
    return None


def _save_kimi_web_cred(cred):
    user = cred.get("_user") or _jwt_user(cred.get("access_token", ""))
    changes = {"kimi_web": cred}
    changes["kimi_auth_mode"] = "web"
    if user:
        changes["kimi_account_id"] = user
    ACCOUNT_STORE.update(changes)


def _jwt_claims(tok):
    """不解签名地取 JWT 的 claims dict；取不到返回 {}。"""
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        c = json.loads(base64.urlsafe_b64decode(p))
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _jwt_exp(tok):
    """不解签名地取 JWT 的 exp；取不到返回 0（视为过期）。"""
    try:
        return float(_jwt_claims(tok).get("exp", 0))
    except Exception:
        return 0.0


def _jwt_user(tok):
    """取 JWT 里的账号身份（abstract_user_id 优先），取不到返回 None。"""
    c = _jwt_claims(tok)
    return c.get("abstract_user_id") or c.get("sub") or c.get("user_id")


# 本机可能存有 kimi.com 登录态的 localStorage leveldb 位置（只读扫描）
_BROWSER_LS_BASES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""),
                 r"Google\Chrome\User Data"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""),
                 r"Microsoft\Edge\User Data"),
]
_KIMI_DESKTOP_LS = os.path.join(os.environ.get("APPDATA", ""),
                                r"kimi-desktop\Local Storage\leveldb")
_KIMI_DESKTOP_DIR = os.path.join(os.environ.get("APPDATA", ""), "kimi-desktop")
_LS_KEY_RE = re.compile(
    rb"_https://(?:www\.|auth\.)?kimi\.(?:com|ai)\x00\x01(access_token|refresh_token)")
_JWT_RE = re.compile(rb"eyJ[A-Za-z0-9_.\-]+")


def _scan_leveldb_tokens(path):
    """分块扫描一个 LevelDB 文件，返回按写入位置倒序排列的令牌记录。"""
    recs = {}
    carry = b""
    offset = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            offset += len(chunk)
            data = carry + chunk
            base = offset - len(data)
            for m in _LS_KEY_RE.finditer(data):
                j = _JWT_RE.search(data, m.end(), m.end() + 800)  # 值紧跟键名
                if j:
                    recs[(base + m.start(), m.group(1))] = j.group()
            carry = data[-65536:]
    return [(pos, kind, tok) for (pos, kind), tok in sorted(
        recs.items(), key=lambda item: item[0][0], reverse=True)]


def import_kimi_web_from_desktop(expected_user=None):
    """只读桌面端的结构化登录；不导入、续期其 refresh_token。"""
    share = os.path.join(_KIMI_DESKTOP_DIR, "daimon-share")
    try:
        with open(os.path.join(_KIMI_DESKTOP_DIR, "daimon-storage.json"), encoding="utf-8-sig") as f:
            target = json.load(f).get("shareDir")
        if isinstance(target, str) and os.path.isabs(target):
            share = target
    except (OSError, ValueError, AttributeError):
        pass
    path = os.path.join(share, "daimon", "config.json")
    try:
        if os.path.getsize(path) > 8 * 1024 * 1024:
            return None
        with open(path, encoding="utf-8-sig") as f:
            web = (json.load(f).get("credentials") or {}).get("kimiWeb") or {}
        access = web.get("accessToken")
        user = _jwt_user(access) if isinstance(access, str) else None
        if (not user or _jwt_exp(access) <= time.time() + 60 or
                expected_user and user != expected_user):
            return None
        return {"_来源": "本机 Kimi 桌面端（只读）", "_user": user,
                "access_token": access, "refresh_token": ""}
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def import_kimi_web_from_browser(expected_user=None):
    """从本机浏览器 / kimi 桌面端的 localStorage 里提取 kimi.com 登录令牌
    （只读原文件，不复制浏览器数据库，不导入浏览器的续期令牌）。
    仅在用户主动启用浏览器导入后使用。"""
    def newest_valid(seq, margin):
        seen = set()
        for t in seq:
            if t not in seen:
                seen.add(t)
                user = _jwt_user(t)
                if (user and (not expected_user or user == expected_user) and
                        _jwt_exp(t) > time.time() + margin):
                    return t
        return None

    entries = []
    for lv in _iter_leveldb_dirs():
        for path in glob.glob(os.path.join(lv, "*.log")) + \
                   glob.glob(os.path.join(lv, "*.ldb")):
            try:
                entries.append((os.path.getmtime(path), path))
            except OSError:
                pass

    for _, path in sorted(entries, reverse=True):
        try:
            records = _scan_leveldb_tokens(path)
        except OSError:
            continue
        access = newest_valid([tok.decode("ascii") for _, kind, tok in records
                               if kind == b"access_token"], 60)
        if access:
            return {"_来源": "本机浏览器（只读）", "_user": _jwt_user(access),
                    "access_token": access, "refresh_token": ""}
    return None


def _iter_leveldb_dirs():
    for base in _BROWSER_LS_BASES:
        for prof in glob.glob(os.path.join(base, "*")):
            lv = os.path.join(prof, "Local Storage", "leveldb")
            if os.path.isdir(lv):
                yield lv
    if os.path.isdir(_KIMI_DESKTOP_LS):
        yield _KIMI_DESKTOP_LS


class KimiAuthError(RuntimeError):
    """已确认凭证失效；与断网、超时等可重试故障分开处理。"""


def _kimi_own_session(cred):
    return bool(cred and str(cred.get("_来源", "")).startswith("独立会话"))


def _kimi_web_refresh(cred, timeout=15):
    """access_token 过期后用 refresh_token 换新并写回（令牌会轮换）。
    失败抛 RuntimeError。"""
    rt = cred.get("refresh_token")
    if not rt:
        raise KimiAuthError("kimi 网页令牌已过期且缺少 refresh_token，"
                           "请在浏览器里打开 kimi.com 后刷新")
    try:
        data = _connect_post(KIMI_WEB_REFRESH_URL, {"refresh_token": rt},
                             timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            raise KimiAuthError("kimi 网页登录已失效：请在浏览器里打开并登录 "
                               "kimi.com 后左键刷新（或右键菜单手动设置）")
        raise RuntimeError("kimi 网页令牌刷新 HTTP %s" % e.code)
    except Exception as e:
        raise RuntimeError("kimi 网页令牌刷新网络错误：%s" % e)
    at = data.get("accessToken") or data.get("access_token")
    if not at:
        raise RuntimeError("kimi 网页令牌刷新响应异常，请重新设置")
    old_user = cred.get("_user") or _jwt_user(cred.get("access_token", ""))
    if (_jwt_exp(at) <= time.time() or not _jwt_user(at) or
            old_user and _jwt_user(at) != old_user):
        raise RuntimeError("kimi 续期返回的账号或有效期不符，未覆盖已绑定账号")
    new = dict(cred)
    new["access_token"] = at
    new_rt = data.get("refreshToken") or data.get("refresh_token")
    if new_rt:
        new["refresh_token"] = new_rt
    try:
        _save_kimi_web_cred(new)
    except Exception as e:
        raise RuntimeError("kimi 网页令牌写回失败：%s" % e)
    return new


def _kimi_web_bootstrap(access_token, timeout=15):
    """借一份新鲜的网页 access_token，走扫码登录 RPC 为 tokenduck 建立一个
    **独立会话**（自己的 refresh_token 链，续期不会影响浏览器/桌面端的登录态）。
    成功返回新凭证 dict，任何一步失败都返回 None（调用方回退到直接借用）。"""
    try:
        code = (_connect_post(KIMI_QR_CREATE_URL, {}, timeout=timeout)
                or {}).get("code")
        if not code:
            return None
        _connect_post(KIMI_QR_SCAN_URL, {"code": code},
                      token=access_token, timeout=timeout)
        _connect_post(KIMI_QR_CONFIRM_URL, {"code": code},
                      token=access_token, timeout=timeout)
        st = _connect_post(KIMI_QR_STATUS_URL, {"code": code},
                           timeout=timeout) or {}
        at = st.get("accessToken") or st.get("access_token")
        if not at:
            return None
        return {"_来源": "独立会话（自动绑定）",
                "access_token": at,
                "refresh_token": st.get("refreshToken")
                                 or st.get("refresh_token") or ""}
    except Exception:
        return None


def _num(x):
    if isinstance(x, bool):
        return None
    try:
        n = float(x)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    """解析接口的 ISO 时间或秒/毫秒时间戳；缺失和非法值保持未知。"""
    if value is None or isinstance(value, bool):
        return None
    n = _num(value)
    if n is not None:
        return n / 1000.0 if n > 1e12 else n
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _kimi_level(tok):
    """从会话 JWT 的 membership 类 claim 取会员等级字符串；取不到返回 None。
    claim 可能是字符串（LEVEL_XXX）或 dict（{"level": 25}，数值档）。"""
    c = _jwt_claims(tok)
    for k in ("code_membership", "membership"):
        v = c.get(k)
        if isinstance(v, str) and v:
            return v.replace("LEVEL_", "")
        if isinstance(v, dict):
            n = v.get("level")
            if isinstance(n, (int, float)):
                return {25: "INTERMEDIATE"}.get(int(n), "Lv.%d" % n)
    return None


def fetch_kimi_quota(timeout=15):
    """优先用本地加密保存的 API key，
    否则用网页登录态。两条路径都隔离错误。"""
    key = (ACCOUNT_STORE.get("kimi_api_key") or "").strip()
    mode = ACCOUNT_STORE.get("kimi_auth_mode")
    if key and mode != "web":
        return _fetch_kimi_by_api_key(key, timeout)
    if mode == "key" and not key:
        raise RuntimeError("已选择 Kimi Code key，请在账户与登录中设置有效 key")
    return _fetch_kimi_by_web(timeout)


def _fetch_kimi_by_api_key(key, timeout=15):
    """读取 coding/v1/usages，兼容计数版和新版 usages 比例格式。"""
    req = urllib.request.Request(
        "https://api.kimi.com/coding/v1/usages",
        headers={"Authorization": "Bearer " + key,
                 "Accept": "application/json", "User-Agent": "tokenduck"})
    try:
        with _urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError("kimi API key 无效或已过期")
        raise RuntimeError("kimi 额度 HTTP %s" % e.code)
    except Exception as e:
        raise RuntimeError("kimi 网络错误：%s" % e)

    return _parse_kimi_api_quota(data)


def _parse_kimi_api_quota(data):
    if not isinstance(data, dict):
        raise RuntimeError("kimi API key 额度响应格式异常")
    # 兼容网关包裹的响应；不把错误响应或未知结构当成零用量。
    if isinstance(data.get("data"), dict):
        data = data["data"]
    if isinstance(data.get("quota"), dict):
        data = data["quota"]
    usages = data.get("usages") or {}
    if not isinstance(usages, dict):
        usages = {}

    def ratio_entry(*keys):
        entry = next((usages[k] for k in keys if isinstance(usages.get(k), dict)), {})
        ratio = _num(entry.get("used_ratio", entry.get("usedRatio")))
        reset = _timestamp(entry.get("reset_time") or entry.get("resetAt"))
        return ratio, reset

    wins = {}
    for keys, tag, secs in ((("limit_5h", "limit5h"), "5h", 18000),
                             (("limit_7d", "limit7d"), "w", 604800)):
        ratio, reset = ratio_entry(*keys)
        if ratio is not None:
            wins[tag] = {"tag": tag, "used_percent": round(ratio * 100),
                         "reset_at": reset, "secs": secs}

    def counter_window(detail, tag, secs):
        if not isinstance(detail, dict):
            return None
        total = _num(detail.get("limit"))
        used, left = _num(detail.get("used")), _num(detail.get("remaining"))
        if total is None or total <= 0:
            return None
        if used is None and left is not None:
            used = total - left
        if used is None:
            return None
        return {"tag": tag, "used_percent": round(used / total * 100),
                "reset_at": _timestamp(detail.get("resetTime") or
                                        detail.get("reset_at")),
                "secs": secs, "amount": total,
                "amount_left": left if left is not None else total - used}

    # 旧计数字段仍返回时优先使用它，避免某些响应中的汇总比例固定为 0。
    for lim in data.get("limits") or []:
        if not isinstance(lim, dict):
            continue
        window = lim.get("window") or {}
        if not isinstance(window, dict):
            continue
        dur = _num(window.get("duration"))
        unit = str(window.get("timeUnit") or "HOUR").upper()
        factors = (("MINUTE", 60), ("HOUR", 3600), ("DAY", 86400),
                   ("WEEK", 604800), ("SECOND", 1))
        factor = next((n for name, n in factors if name in unit), None)
        if dur is None or dur <= 0 or factor is None:
            continue
        secs = dur * factor
        if secs == 604800:
            tag = "w"
        elif secs % 3600 == 0:
            tag = "%gh" % (secs / 3600)
        else:
            tag = "%gm" % (secs / 60)
        win = counter_window(lim.get("detail") or window, tag, secs)
        if win:
            wins[tag] = win

    monthly, month_reset = ratio_entry("limit_month_total", "month_total", "monthTotal")
    code_monthly, _ = ratio_entry("limit_month_code", "month_code", "monthCode")
    # usage 是旧套餐的周额度；即使 limits 已有短窗口，也必须单独读取。
    if monthly is None or "w" in wins:
        weekly = counter_window(data.get("usage"), "w", 604800)
        if weekly:
            wins["w"] = weekly
    if not wins and monthly is None:
        raise RuntimeError("kimi API key 未返回额度数据")
    return {"windows": sorted(wins.values(), key=lambda w: w["secs"]),
            "level": None, "used_ratio": monthly,
            "amount": None, "amount_left": None,
            "code_used_ratio": code_monthly, "reset_at": month_reset,
            "source": "API key"}


def _discard_kimi_web_cred():
    # 保留绑定的账号身份，防止下次失败恢复时导入另一个账号。
    ACCOUNT_STORE.update(remove=("kimi_web",))


def _bind_kimi_web(timeout=15, expected_user=None, *, replace_account=False,
                   persist=True, allow_browser=None):
    """优先只读桌面端，以新鲜访问令牌建立工具自己的续期链。"""
    if not replace_account:
        expected_user = expected_user or ACCOUNT_STORE.get("kimi_account_id")
    imported = import_kimi_web_from_desktop(expected_user)
    if allow_browser is None:
        allow_browser = load_config().get("allow_browser_import", False)
    if not imported and allow_browser:
        imported = import_kimi_web_from_browser(expected_user)
    if not imported or not imported.get("access_token"):
        message = ("未找到已绑定账号的有效登录；请在 Kimi 桌面端登录原账号，"
                   "或通过“连接账户”主动切换账号" if expected_user else
                   "请在 Kimi 桌面端登录一次，再选择“连接账户”；也可主动启用浏览器导入")
        raise KimiAuthError(message)
    cred = _kimi_web_bootstrap(imported["access_token"], timeout) or imported
    user = _jwt_user(cred["access_token"])
    source_user = imported.get("_user") or _jwt_user(imported["access_token"])
    if not user or user != source_user or expected_user and user != expected_user:
        raise KimiAuthError("Kimi 登录账号不一致，未保存或切换账号")
    # 若独立会话创建失败，只借用访问令牌；绝不消费桌面端/浏览器的续期令牌。
    if not _kimi_own_session(cred):
        cred = dict(cred, refresh_token="")
    cred["_user"] = user
    if persist:
        _save_kimi_web_cred(cred)
    return cred


def _fetch_kimi_by_web(timeout=15):
    """请求订阅页“额度”接口：kimi 5h/每周用量窗口 + 会员月总额度。

    凭证策略（互不影响他人登录态为前提）：
    - 加密保存的独立会话自动续期，不修改其他客户端的续期链；
    - 账号保持绑定，失败恢复只接受同一账号；用户可主动重新绑定；
    - 只读桌面端为首选，浏览器导入需主动开启。
    返回规整 dict：{windows, level, used_ratio(0~1), amount, amount_left,
    code_used_ratio, reset_at}。失败抛 RuntimeError。"""
    cred = _read_kimi_web_cred()
    now = time.time()
    expected_user = (cred or {}).get("_user") or _jwt_user((cred or {}).get("access_token", ""))
    expected_user = expected_user or ACCOUNT_STORE.get("kimi_account_id")
    if cred is not None and _jwt_exp(cred["access_token"]) < now + 60:
        if _kimi_own_session(cred) and cred.get("refresh_token"):
            try:
                cred = _kimi_web_refresh(cred, timeout)
            except KimiAuthError:
                # 仅在服务端明确拒绝凭证时重绑；断网/超时不能清除有效会话。
                _discard_kimi_web_cred()
                cred = None
        else:
            cred = None                         # 借来的令牌不刷新，重新导入
    if cred is None:
        cred = _bind_kimi_web(timeout, expected_user)
    try:
        data = _connect_post(KIMI_QUOTA_URL, {}, cred["access_token"], timeout)
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise RuntimeError("kimi 额度 HTTP %s" % e.code)
        # 新绑定的会话也需要按其真实来源处理，不能沿用绑定前的 own 标志。
        if _kimi_own_session(cred) and cred.get("refresh_token"):
            try:
                cred = _kimi_web_refresh(cred, timeout)
            except KimiAuthError:
                _discard_kimi_web_cred()
                cred = _bind_kimi_web(timeout, expected_user)
        else:
            _discard_kimi_web_cred()
            cred = _bind_kimi_web(timeout, expected_user)
        try:
            data = _connect_post(KIMI_QUOTA_URL, {}, cred["access_token"], timeout)
        except urllib.error.HTTPError as retry_error:
            if retry_error.code == 401:
                _discard_kimi_web_cred()
                raise KimiAuthError("kimi 登录已失效：请登录 kimi.com 后重新绑定账号")
            raise RuntimeError("kimi 额度 HTTP %s" % retry_error.code)
        except Exception as retry_error:
            raise RuntimeError("kimi 网络错误：%s" % retry_error)
    except Exception as e:
        raise RuntimeError("kimi 网络错误：%s" % e)

    return _parse_kimi_web_quota(data, cred["access_token"])


def connect_kimi_account(allow_browser=None, timeout=15):
    """主动连接：先验证新账号额度，全部成功后才替换加密绑定。"""
    candidate = _bind_kimi_web(timeout, replace_account=True, persist=False,
                               allow_browser=allow_browser)
    response = _connect_post(KIMI_QUOTA_URL, {}, candidate["access_token"], timeout)
    data = _parse_kimi_web_quota(response, candidate["access_token"])
    _save_kimi_web_cred(candidate)
    return data


def _parse_kimi_web_quota(data, access_token=""):
    if not isinstance(data, dict):
        raise RuntimeError("kimi 网页额度响应格式异常")

    # 5h / 每周用量窗口（coding 额度，与 CLI usages 接口的数据同源）
    wins = []
    for key, snake_key, tag, secs in (
            ("ratelimitCode5h", "ratelimit_code_5h", "5h", 18000),
            ("ratelimitCode7d", "ratelimit_code_7d", "w", 604800)):
        rl = data.get(key, data.get(snake_key))
        if not isinstance(rl, dict) or rl.get("enabled") is False:
            continue
        wreset = _timestamp(rl.get("resetTime") or rl.get("reset_time"))
        ratio = _num(rl.get("ratio"))
        # Connect/ProtoJSON 默认省略数值 0。已启用的窗口仍然是已用 0%，
        # 不能因此跳过整行；空对象、显式 null 和非法比例继续按未知处理。
        if "ratio" not in rl and (rl.get("enabled") is True or wreset is not None):
            ratio = 0.0
        if ratio is None:
            continue
        wins.append({"tag": tag, "used_percent": round(ratio * 100),
                     "reset_at": wreset, "secs": secs})

    bal = data.get("subscriptionBalance") or data.get("subscription_balance")
    if not isinstance(bal, dict):
        bal = {}
    used_ratio = _num(bal.get("amountUsedRatio", bal.get("amount_used_ratio")))
    amount = _num(bal.get("amount"))
    left = _num(bal.get("amountLeft", bal.get("amount_left")))
    if used_ratio is None and amount and left is not None and amount > 0:
        used_ratio = (amount - left) / amount
    et = bal.get("expireTime") or bal.get("expire_time")
    reset_at = _timestamp(et)
    if (used_ratio is None and "amountUsedRatio" not in bal and
            "amount_used_ratio" not in bal and reset_at is not None and
            reset_at > time.time()):
        # 有明确有效期的订阅余额同样可能省略默认的零比例。
        used_ratio = 0.0
    if not wins and used_ratio is None:
        raise RuntimeError("无订阅额度数据（可能未开通会员）")
    return {
        "windows": wins,                 # [{tag, used_percent, reset_at, secs}]
        "level": _kimi_level(access_token),
        "used_ratio": used_ratio,        # 月总额度已用比例（0~1，可能 None）
        "amount": amount,                # 总额度（可能为 None）
        "amount_left": left,             # 剩余额度（可能为 None）
        "code_used_ratio": _num(bal.get("kimiCodeUsedRatio",
                                        bal.get("kimi_code_used_ratio"))),
        "reset_at": reset_at,
    }


# ---------- zcode：ZCode 桌面端（bigmodel/GLM）订阅额度 ----------

ZCODE_HOME = os.path.expanduser(os.environ.get("ZCODE_HOME", "~/.zcode"))
ZCODE_CRED_PATH = os.path.join(ZCODE_HOME, "v2", "credentials.json")
ZCODE_CFG_PATH = os.path.join(ZCODE_HOME, "v2", "config.json")
ZCODE_USAGE_URL = "https://zcode.z.ai/api/v1/mcp/usage"   # 回退：月度总额度
# monitor 接口（与 ZCode 客户端/magpie 一致）：5h + 周窗口、剩余量、重置时间
ZCODE_MONITOR_PATH = "/api/monitor/usage/quota/limit"
ZCODE_SUB_PATH = "/api/biz/subscription/list"             # 订阅到期时间


# ---- 纯标准库 AES-256-GCM（解 ZCode 桌面端凭证用，免第三方依赖） ----

def _gf_mul128(x, y):
    """GCM GF(2^128) 乘法（NIST SP800-38D）：x 的位从 MSB 起参与，R=E1||0^120。"""
    r = 0xE1 << 120
    z = 0
    v = y
    for i in range(128):
        if (x >> (127 - i)) & 1:
            z ^= v
        lsb = v & 1
        v >>= 1
        if lsb:
            v ^= r
    return z


def _aes_sbox():
    def mul(a, b):
        def xt(x):
            return ((x << 1) ^ 0x1B) & 0xFF if x & 0x80 else x << 1
        r = 0
        for _ in range(8):
            if b & 1:
                r ^= a
            b >>= 1
            a = xt(a)
        return r

    def inv(a):
        if a == 0:
            return 0
        for b in range(1, 256):
            if mul(a, b) == 1:
                return b
        return 0

    sbox = [0] * 256
    for i in range(256):
        x = inv(i)
        for _ in range(4):
            x = ((x << 1) | (x >> 7)) & 0xFF ^ inv(i)
        sbox[i] = x ^ 0x63
    return sbox


_AES_SBOX = None   # 延迟生成（约 100ms，只在首次解密 zcode 凭证时初始化）


def _aes_gcm_decrypt(key, iv, cipher, tag):
    """AES-256-GCM 解密（验证 tag）。仅用于 12 字节 IV / 16 字节 tag 场景。"""
    global _AES_SBOX
    if _AES_SBOX is None:
        _AES_SBOX = _aes_sbox()
    sbox = _AES_SBOX

    def mul(a, b):
        def xt(x):
            return ((x << 1) ^ 0x1B) & 0xFF if x & 0x80 else x << 1
        r = 0
        for _ in range(8):
            if b & 1:
                r ^= a
            b >>= 1
            a = xt(a)
        return r

    # 密钥扩展（FIPS-197）
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [sbox[b] for b in t]
            t[0] ^= rcon
            rcon = mul(rcon, 2)
        elif nk > 6 and i % nk == 4:
            t = [sbox[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])

    def block(blk):
        s = [[blk[4 * c + r] for c in range(4)] for r in range(4)]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[c][r]
        for rnd in range(1, nr + 1):
            for r in range(4):
                for c in range(4):
                    s[r][c] = sbox[s[r][c]]
            for r in range(1, 4):
                s[r] = s[r][r:] + s[r][:r]
            if rnd != nr:
                for c in range(4):
                    a = [s[r][c] for r in range(4)]
                    s[0][c] = mul(a[0], 2) ^ mul(a[1], 3) ^ a[2] ^ a[3]
                    s[1][c] = a[0] ^ mul(a[1], 2) ^ mul(a[2], 3) ^ a[3]
                    s[2][c] = a[0] ^ a[1] ^ mul(a[2], 2) ^ mul(a[3], 3)
                    s[3][c] = mul(a[0], 3) ^ a[1] ^ a[2] ^ mul(a[3], 2)
            for c in range(4):
                for r in range(4):
                    s[r][c] ^= w[rnd * 4 + c][r]
        out = bytearray(16)
        for c in range(4):
            for r in range(4):
                out[4 * c + r] = s[r][c]
        return bytes(out)

    h = int.from_bytes(block(b"\0" * 16), "big")
    j0 = int.from_bytes(iv + b"\x00\x00\x00\x01", "big")
    # CTR 解密（从 inc32(J0) 起）
    out = bytearray()
    ctr = j0
    for i in range(0, len(cipher), 16):
        ctr = (ctr + 1) & ((1 << 128) - 1)
        ks = block(ctr.to_bytes(16, "big"))
        out += bytes(a ^ b for a, b in zip(cipher[i:i + 16], ks))
    # GHASH(AAD 空)：C 块 + 位长度块（注意是对密文 C，不是明文）
    def pad16(b):
        return b + b"\0" * ((16 - len(b) % 16) % 16)

    data = pad16(cipher) + (len(cipher) * 8).to_bytes(16, "big")
    s = 0
    for i in range(0, len(data), 16):
        s = _gf_mul128(s ^ int.from_bytes(data[i:i + 16], "big"), h)
    ek = block(j0.to_bytes(16, "big"))
    calc = (s ^ int.from_bytes(ek, "big")).to_bytes(16, "big")[:len(tag)]
    if calc != tag:
        raise ValueError("auth tag mismatch")
    return bytes(out)


def _zcode_secret():
    """复现 ZCode 桌面端的凭证加密密钥：
    环境变量 ZCODE_CREDENTIAL_SECRET 优先，否则用本机可推导的 fallback
    （与 ZCode app.asar 中 createCredentialCipherProvider 的逻辑一致）。"""
    env = os.environ.get("ZCODE_CREDENTIAL_SECRET")
    if env:
        return env
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    return "zcode-credential-fallback:win32:%s:%s" % (
        os.path.expanduser("~"), user)


def _zcode_decrypt(value):
    """解密 ZCode credentials.json 里的 enc:v1: 字段（AES-256-GCM）。
    格式：enc:v1:<iv12(b64url)>.<tag16(b64url)>.<ciphertext(b64url)>。
    密钥 = sha256(secret)。返回明文字符串；失败抛 RuntimeError。"""
    prefix = "enc:v1:"
    if not value.startswith(prefix):
        return value                       # 兼容未加密的明文
    parts = value[len(prefix):].split(".")
    if len(parts) != 3:
        raise RuntimeError("zcode 凭证密文格式非法")

    def b64url_dec(s):
        s = s + "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s)

    iv, tag, cipher = (b64url_dec(p) for p in parts)
    if len(iv) != 12 or len(tag) != 16:
        raise RuntimeError("zcode 凭证 IV/AuthTag 长度非法")
    key = hashlib.sha256(_zcode_secret().encode("utf-8")).digest()
    try:
        return _aes_gcm_decrypt(key, iv, cipher, tag).decode("utf-8")
    except Exception:
        raise RuntimeError("zcode 凭证解密失败（密钥不匹配或数据损坏）")


def fetch_zcode_quota(timeout=15):
    """读 ZCode 桌面端凭证，查 GLM Coding Plan 额度。

    优先路径（与 ZCode 客户端/magpie 一致）：~/.zcode/v2/config.json 里
    coding-plan 的 apiKey 是明文，直接调 monitor 接口拿 5h + 周双窗口
    （含剩余量/重置时间）+ 订阅到期。
    回退路径：解密 credentials.json 调官方 MCP 额度接口（仅月度总额度）。
    返回 {windows, level, plan_name, until} 或月度版。失败抛 RuntimeError。"""
    # ---- 优先：monitor 接口（明文 apiKey，无需解密） ----
    wins, level, plan_name, until = _fetch_zcode_monitor(timeout)
    if wins is not None:
        return {"windows": wins, "level": level,
                "plan_name": plan_name, "until": until}

    # ---- 回退：官方 MCP 接口（解密凭证） ----
    if not os.path.exists(ZCODE_CRED_PATH):
        raise RuntimeError("未找到 %s（请先登录 ZCode 桌面端）" % ZCODE_CRED_PATH)
    try:
        with open(ZCODE_CRED_PATH, "r", encoding="utf-8") as f:
            cred = json.load(f)
        zjwt = _zcode_decrypt(cred["zcodejwttoken"])
        at = _zcode_decrypt(cred["oauth:bigmodel:access_token"])
    except (KeyError, json.JSONDecodeError):
        raise RuntimeError("zcode credentials.json 格式异常，请重新登录 ZCode")

    req = urllib.request.Request(
        ZCODE_USAGE_URL,
        headers={
            "Authorization": "Bearer " + zjwt,
            "X-Bigmodel-Authorization": "Bearer " + at,
            "Bigmodel-Target-Type": "PERSONAL",
            "Accept": "application/json",
            "User-Agent": "tokenduck",
        })
    try:
        with _urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError("zcode 登录已过期 (401)，请打开 ZCode 桌面端重新登录")
        raise RuntimeError("zcode 额度 HTTP %s" % e.code)
    except Exception as e:
        raise RuntimeError("zcode 网络错误：%s" % e)
    if data.get("code") not in (0, "0"):
        raise RuntimeError("zcode 接口错误：%s" % data.get("msg", "?"))
    d = data.get("data") or {}
    tu = d.get("total_usage") or {}
    used, limit = _num(tu.get("used")), _num(tu.get("limit"))
    remaining = _num(tu.get("remaining"))
    if used is not None and limit:
        used_percent = round(used / limit * 100)
        if remaining is None:
            remaining = limit - used
    else:
        used_percent = None
    return {
        "windows": ([{"tag": "月", "used_percent": used_percent,
                      "reset_at": _num(d.get("next_refresh_at")),
                      "amount": limit, "amount_left": remaining}]
                    if used_percent is not None else []),
        "level": d.get("level"),
        "plan_name": None, "until": None,
        # 兼容字段
        "used": used, "limit": limit, "remaining": remaining,
        "used_percent": used_percent,
    }


def _zcode_api_key():
    """从 ~/.zcode/v2/config.json 取 coding-plan 的明文 apiKey 及其站点。
    返回 (key, root_url)，找不到返回 (None, None)。"""
    manual = ACCOUNT_STORE.get("zcode_key")
    if isinstance(manual, dict) and manual.get("key"):
        site = manual.get("site")
        if site not in ("bigmodel", "zai"):
            raise RuntimeError("ZCode key 的站点无效，请重新连接")
        return manual["key"], ("https://open.bigmodel.cn" if site == "bigmodel" else "https://api.z.ai")
    try:
        with open(ZCODE_CFG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return None, None
    provs = cfg.get("provider") or {}
    # bigmodel-coding-plan（国内）/ zai-coding-plan（国际）优先于 start-plan
    for pid in sorted(provs):
        if "coding-plan" not in pid or "start" in pid:
            continue
        opts = (provs[pid].get("options") or {})
        key = opts.get("apiKey")
        if isinstance(key, str) and key:
            if key.startswith("enc:"):
                key = _zcode_decrypt(key)
            base = opts.get("baseURL") or opts.get("baseUrl")
            if base:
                parsed = urllib.parse.urlsplit(base)
                if (parsed.scheme != "https" or parsed.hostname not in ("open.bigmodel.cn", "api.z.ai") or
                        parsed.username is not None or parsed.port not in (None, 443)):
                    raise RuntimeError("ZCode 配置中的站点不是受支持的官方地址，未发送 key")
                root = "https://" + parsed.hostname
            else:
                root = "https://api.z.ai" if "zai" in pid else "https://open.bigmodel.cn"
            return key, root
    return None, None


def _fetch_zcode_monitor(timeout=15, credential=None):
    """用明文 apiKey 调 monitor 接口。返回 (windows, level, plan_name, until)。
    windows 为 None 表示不可用（回退旧路径）。"""
    key, root = credential if credential is not None else _zcode_api_key()
    if not key:
        return None, None, None, None
    headers = {"Authorization": "Bearer " + key,
               "Accept": "application/json", "User-Agent": "ZCode/3.14.4"}
    try:
        with _urlopen(urllib.request.Request(
                root + ZCODE_MONITOR_PATH, headers=headers), timeout=timeout) as r:
            data = json.load(r)
        if data.get("code") not in (0, "0", 200, "200"):
            return None, None, None, None
        limits = (data.get("data") or {}).get("limits") or []
    except Exception:
        return None, None, None, None

    level = (data.get("data") or {}).get("level")
    wins = []
    for x in limits:
        # unit: 3=小时(number=小时数)， 6=周(number=周数)——与 magpie 的 zcodeSpan 一致
        unit, n = x.get("unit"), x.get("number") or 0
        if unit == 3:
            tag = "%dh" % max(1, n)
            secs = max(1, n) * 3600
        elif unit == 6:
            tag = "w"
            secs = max(1, n) * 604800
        else:
            continue           # 其他（如月度 TIME_LIMIT）不展示
        pct = _num(x.get("percentage"))
        usage = _num(x.get("usage"))
        remaining = _num(x.get("remaining"))
        current = _num(x.get("currentValue"))
        if pct is None and usage and current is not None:
            pct = round(current / usage * 100)
        if pct is None:
            continue
        reset = _num(x.get("nextResetTime"))
        if reset and reset > 1e12:      # 毫秒时间戳
            reset /= 1000.0
        wins.append({"tag": tag, "used_percent": pct, "reset_at": reset,
                     "amount": usage, "amount_left": remaining})
    if not wins:
        return None, None, None, None

    # 订阅到期（尽力而为，失败不影响额度）
    until = None
    plan_name = None
    try:
        with _urlopen(urllib.request.Request(
                root + ZCODE_SUB_PATH, headers=headers), timeout=timeout) as r:
            subs = json.load(r).get("data") or []
        for s in subs:
            if str(s.get("status", "")).upper() == "VALID":
                plan_name = s.get("productName")
                # valid: "2027-01-07 10:00:00-2027-04-07 10:00:00"（北京时间）
                # 取末尾的完整日期时间（rfind 从后往前找第二个日期块）
                m = re.search(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}:\d{2}))?\s*$",
                              (s.get("valid") or "").strip())
                if m:
                    ds = m.group(1) + ("T" + m.group(2) if m.group(2) else "")
                    try:
                        until = datetime.fromisoformat(ds).replace(
                            tzinfo=timezone(timedelta(hours=8))).timestamp()
                    except ValueError:
                        pass
                break
    except Exception:
        pass
    return wins, level, plan_name, until


def window_tag(win):
    """按窗口时长给个短标签：5 小时窗口 / 每周窗口。"""
    secs = (win or {}).get("limit_window_seconds", 0)
    return "5h" if secs and secs <= 18000 else "w"


def fmt_countdown(reset_at):
    secs = max(0, int(reset_at - time.time()))
    d, secs = divmod(secs, 86400)
    h, secs = divmod(secs, 3600)
    m = secs // 60
    if d:
        return "%dd%dh" % (d, h)
    if h:
        return "%dh%dm" % (h, m)
    return "%dm" % m


def fmt_countdown_short(reset_at):
    """精确到分钟：≤1h→45m，≤1d→2h30m，>1d→5d12h。"""
    secs = max(0, int(reset_at - time.time()))
    d, secs = divmod(secs, 86400)
    h, secs = divmod(secs, 3600)
    m = secs // 60
    if d:
        return "%dd%dh" % (d, h) if h else "%dd" % d
    if h:
        return "%dh%dm" % (h, m)
    return "%dm" % m


def _remain(used_percent):
    """已用% → 余量%；数据缺失时返回 '?'。"""
    n = _num(used_percent)
    if n is not None:
        return max(0, min(100, int(round(100 - n))))
    return "?"


def _fmt_amount(n):
    """额度数值缩写显示：>=10000 用“万”。"""
    if n is None:
        return "?"
    if abs(n) >= 10000:
        return ("%.1f" % (n / 10000.0)).rstrip("0").rstrip(".") + "万"
    return "%d" % n if n == int(n) else "%.1f" % n


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _display_windows(provider, data):
    """统一文字、进度条与倒计时的数据，过滤缺失值时保持三者对齐。"""
    if not isinstance(data, dict):
        return []
    if provider == "codex":
        rl = data.get("rate_limit") or {}
        windows = [rl.get("primary_window"), rl.get("secondary_window")]
    else:
        windows = list(data.get("windows") or [])
    valid = []
    for win in windows:
        if not isinstance(win, dict):
            continue
        pct = _num(win.get("used_percent"))
        if pct is None:
            continue
        w = dict(win, used_percent=pct)
        w.setdefault("tag", window_tag(w) if provider == "codex" else "月")
        valid.append(w)
    # 普通会员或新套餐可能只返回月余额；仍在任务栏中显示，而不是留空。
    monthly = _num(data.get("used_ratio")) if provider == "kimi" else None
    if monthly is not None and len(valid) < 2 and not any(w["tag"] == "月" for w in valid):
        valid.append({"tag": "月", "used_percent": monthly * 100,
                      "reset_at": data.get("reset_at")})
    if not valid and provider == "zcode":
        pct = _num(data.get("used_percent"))
        if pct is not None:
            valid.append({"tag": "月", "used_percent": pct,
                          "reset_at": data.get("reset_at")})
    return valid


_CACHE_FIELDS = {
    "codex": ("plan_type", "rate_limit", "credits"),
    "kimi": ("windows", "level", "used_ratio", "amount", "amount_left",
             "code_used_ratio", "reset_at", "source"),
    "zcode": ("windows", "level", "plan_name", "until", "used", "limit",
              "remaining", "used_percent", "reset_at"),
}


def load_usage_cache():
    """加载上次成功额度；缓存永远以待刷新状态显示，不代表当前实时额度。"""
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        entries = {}
        for name in _CACHE_FIELDS:
            entry = raw.get(name)
            if not isinstance(entry, dict):
                continue
            saved_at = _num(entry.get("saved_at"))
            data = entry.get("data")
            if (saved_at is not None and 0 < saved_at <= time.time() + 60 and
                    _display_windows(name, data)):
                entries[name] = {"saved_at": saved_at, "data": data}
        return entries
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def save_usage_cache(entries):
    # 仅保存需要显示的额度字段，不保存 access_token、refresh_token 或 API key。
    safe = {}
    for name, fields in _CACHE_FIELDS.items():
        entry = entries.get(name) or {}
        data = entry.get("data")
        if isinstance(data, dict) and _num(entry.get("saved_at")) is not None:
            safe[name] = {"saved_at": entry["saved_at"],
                          "data": {k: data[k] for k in fields if k in data}}
    tmp = CACHE_PATH + ".tmp"
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False, allow_nan=False)
        os.replace(tmp, CACHE_PATH)
    except (OSError, ValueError, TypeError) as e:
        _dbg("保存额度缓存失败: %s" % e)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


class TokenDuck:
    def __init__(self, cfg, hidden=False):
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.fetch_lock = threading.Lock()
        cached = {} if hidden else load_usage_cache()
        self.data = cached.get("codex", {}).get("data")
        self.error = "上次记录，等待刷新" if self.data else None
        self.kimi_data = cached.get("kimi", {}).get("data")
        self.kimi_error = "上次记录，等待刷新" if self.kimi_data else None
        self.zcode_data = cached.get("zcode", {}).get("data")
        self.zcode_error = "上次记录，等待刷新" if self.zcode_data else None
        self.last_success = {name: entry["saved_at"] for name, entry in cached.items()}
        self.last_refresh = None
        self.width = 120
        self._tip = None
        self.screen_x = 0
        self.screen_y = 0
        self.tb_h = 48                # 最近一次探测到的任务栏高（anchor 里更新）

        self.root = tk.Tk()
        if hidden:
            self.root.withdraw()
        self.root.title("TokenDuck")
        self._account_window = None
        self._settings_window = None
        self._account_status_vars = {}
        self._codex_login_running = False
        icon = os.path.join(RESOURCE_DIR, "assets", "tokenduck.ico")
        if os.path.isfile(icon):
            self.root.iconbitmap(icon)
        self.root.overrideredirect(True)
        self.root.attributes("-toolwindow", True)
        self.root.attributes("-topmost", True)
        self.root.report_callback_exception = self._tk_exception  # 回调异常兜底
        auto_bg, auto_fg, _, _ = detect_theme_colors()
        # 默认透明背景：色键 = 采样到的任务栏色，文字抗锯齿恰好融入任务栏；
        # config 里设 background 则为纯色卡片模式
        self.transparent = not self.cfg["background"]
        self.bg, self.fg, self.muted_color, self.track_color = \
            self._resolve_theme(auto_bg, auto_fg)
        self.root.configure(bg=self.bg)
        if self.transparent:
            self.root.attributes("-transparentcolor", self.bg)

        size = int(self.cfg["font_size"])
        self.font = tkfont.Font(family="Microsoft YaHei UI", size=size,
                                weight="bold")           # 数据行
        self.font_top = tkfont.Font(family="Microsoft YaHei UI",
                                    size=max(6, size - 1))  # 标签行
        self.seg_remains = [[], [], []]  # 各行各窗口的余量，与文字中窗口顺序一致
        self.chip_color = self._chip_color()
        self.canvas = tk.Canvas(self.root, bg=self.bg, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        if self.transparent and self.cfg.get("chip", True):
            self.chip = self.canvas.create_polygon(
                _rr_points(1, 1, 10, 10, 7), smooth=True, splinesteps=36,
                fill=self.chip_color, outline="")
        else:
            self.chip = None
        # 每行三件套：标签 | 信息文字（数字%+倒计时，条上方） | 矮进度条（条下方）
        # 信息文字与条【上下叠放】：每窗口一个信息槽，文字在槽顶、条在槽底
        self.row_items = []
        for _ in range(3):
            label = self.canvas.create_text(5, 0, anchor="w",
                                            fill=self.muted_color,
                                            font=self.font_top, text="")
            main = self.canvas.create_text(5, 0, anchor="w",
                                           fill=self.fg, font=self.font, text="")
            timer = self.canvas.create_text(0, 0, anchor="e",
                                            fill=self.muted_color,
                                            font=self.font_top, text="")
            self.row_items.append((label, main, timer))
        # 每窗口一个信息文字（%+倒计时，7pt 紧凑字）+ 对应矮条；后建的在 z 序上层
        self.bar_colors = ("#3ba55d", "#4a9eff", "#b48cff")
        self.bars = []
        for color in self.bar_colors:
            segs = []
            for _ in range(2):
                bg = self.canvas.create_rectangle(0, 0, 0, 0, outline="",
                                                  fill=self.track_color)
                fg = self.canvas.create_rectangle(0, 0, 0, 0, outline="", fill=color)
                segs.append((bg, fg))
            self.bars.append(segs)
        self.seg_texts = []            # 每窗口的 "%数字" 文字
        self.seg_timers = []           # 每窗口的倒计时文字
        self.font_seg = tkfont.Font(family="Microsoft YaHei UI", size=self.cfg.get("data_font_size", 8),
                                    weight="bold")
        self.font_cd = tkfont.Font(family="Microsoft YaHei UI", size=self.cfg.get("data_font_size", 8),
                                   weight="bold")
        for _ in range(3):
            pct = [self.canvas.create_text(0, 0, anchor="w",
                                           fill=self.fg, font=self.font_seg,
                                           text="", state="hidden")
                   for _ in range(2)]
            cd = [self.canvas.create_text(0, 0, anchor="e",
                                          fill=self.muted_color,
                                          font=self.font_cd,
                                          text="", state="hidden")
                  for _ in range(2)]
            self.seg_texts.append(pct)
            self.seg_timers.append(cd)

        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<ButtonRelease-3>", self.show_menu)  # 松开才弹，避免同一次点击的释放误选菜单项
        self.canvas.bind("<Enter>", lambda e: self.show_tip())
        self.canvas.bind("<Leave>", lambda e: self.hide_tip())

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="立即刷新", command=self.refresh_now)
        self.menu.add_command(label="账户与登录…", command=self.show_account_settings)
        self.menu.add_command(label="显示与刷新设置…", command=self.show_display_settings)
        self.menu.add_separator()
        self.autostart_var = tk.BooleanVar(value=self.autostart_enabled())
        self.menu.add_checkbutton(label="开机启动", variable=self.autostart_var,
                                command=self.toggle_autostart)
        self.menu.add_separator()
        self.menu.add_command(label="关于 TokenDuck…", command=self.show_about)
        self.menu.add_command(label="退出", command=self.quit)

        self.root.update()
        self.render()

    @staticmethod
    def _tk_exception(exc, val, tb):
        """tkinter 回调异常兜底：写调试日志而非静默闪退。"""
        import traceback
        _dbg("tkinter 回调异常: %s\n%s" % (exc, "".join(
            traceback.format_exception(exc, val, tb))), force=True)

    # ---------- 数据 ----------

    def _fetch_codex(self):
        try:
            self.data = fetch_usage()
            self.error = None
            self.last_success["codex"] = time.time()
        except RuntimeError as e:
            self.error = str(e)
            _dbg("codex 获取失败: %s" % e)
        except Exception as e:
            self.error = "未知错误：%s" % e
            _dbg("codex 获取异常: %r" % e)

    def _fetch_kimi(self):
        try:
            self.kimi_data = fetch_kimi_quota()
            self.kimi_error = None
            self.last_success["kimi"] = time.time()
        except RuntimeError as e:
            self.kimi_error = str(e)
            _dbg("kimi 获取失败: %s" % e)
        except Exception as e:
            self.kimi_error = "未知错误：%s" % e
            _dbg("kimi 获取异常: %r" % e)

    def _fetch_zcode(self):
        try:
            self.zcode_data = fetch_zcode_quota()
            self.zcode_error = None
            self.last_success["zcode"] = time.time()
        except RuntimeError as e:
            self.zcode_error = str(e)
            _dbg("zcode 获取失败: %s" % e)
        except Exception as e:
            self.zcode_error = "未知错误：%s" % e
            _dbg("zcode 获取异常: %r" % e)

    def fetch_once(self):
        if not self.fetch_lock.acquire(blocking=False):
            return
        try:
            # 三家各自隔离错误、并行拉取（各自 15s 超时，串行最坏要 45s+）
            threads = [threading.Thread(target=t, daemon=True) for t in
                       (self._fetch_codex, self._fetch_kimi, self._fetch_zcode)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.last_refresh = datetime.now()
            self._save_cache()
        finally:
            self.fetch_lock.release()
        try:
            self.root.after(0, self.render)
        except RuntimeError:
            pass

    def refresh_now(self):
        threading.Thread(target=self.fetch_once, daemon=True).start()

    def _save_cache(self):
        save_usage_cache({name: {"data": data, "saved_at": self.last_success.get(name)}
                          for name, data in (("codex", self.data),
                                             ("kimi", self.kimi_data),
                                             ("zcode", self.zcode_data))})

    def on_left_click(self, _event):
        self._kick_lift()
        self.refresh_now()

    def poll_loop(self):
        while not self.stop_event.is_set():
            self.fetch_once()
            started = time.monotonic()
            while not self.stop_event.is_set():
                remaining = max(1, int(self.cfg["interval_minutes"])) * 60 - (time.monotonic() - started)
                if remaining <= 0:
                    break
                self.stop_event.wait(min(1, remaining))

    # ---------- 显示 ----------

    def bar_rows(self):
        """返回 [(label, main, reached, err, rem, reset_at), ...] 三行。
        布局：标签 | 进度条 | main（各窗口余量带标签，与分段左右对应）| 倒计时。
        main 形如 "5h99 w76"：左段=5h窗口，右段=周窗口，与条分段顺序一致。
        reset_at = 最近一次重置时间（倒计时用）。"""

        def fmt_row(windows):
            """windows=[{tag, used_percent, reset_at}] → (文本, 最紧余量, 最早重置)。"""
            parts, rems, resets = [], [], []
            for w in windows:
                pct = w.get("used_percent")
                if not isinstance(pct, (int, float)):
                    continue
                parts.append("%s%s" % (w["tag"], _remain(pct)))
                rems.append(100 - pct)
                if w.get("reset_at"):
                    resets.append(w["reset_at"])
            if not parts:
                return None, None, None
            return (" ".join(parts), min(rems), min(resets) if resets else None)

        rows = []
        codex_main, codex_rem, codex_reset = "--", None, None
        if self.data:
            windows = _display_windows("codex", self.data)
            m, r, t = fmt_row(windows)
            if m:
                codex_main, codex_rem, codex_reset = m, r, t
        rows.append(("codex", codex_main, bool(self.data and
                     (self.data.get("rate_limit") or {}).get("limit_reached")),
                     self.error, codex_rem, codex_reset))

        kimi_main, kimi_rem, kimi_reset = "--", None, None
        kimi_windows = _display_windows("kimi", self.kimi_data)
        if self.kimi_data:
            m, r, t = fmt_row(kimi_windows)
            if m:
                kimi_main, kimi_rem, kimi_reset = m, r, t
        kimi_reached = (any(w["used_percent"] >= 100 for w in kimi_windows) or
                        (_num((self.kimi_data or {}).get("used_ratio")) or 0) >= 1)
        rows.append(("kimi", kimi_main, kimi_reached,
                     self.kimi_error, kimi_rem, kimi_reset))

        zcode_main, zcode_rem, zcode_reset = "--", None, None
        zcode_wins = _display_windows("zcode", self.zcode_data)
        if self.zcode_data:
            z = self.zcode_data
            m, r, t = fmt_row(zcode_wins)
            if m:
                zcode_main, zcode_rem, zcode_reset = m, r, t
            elif z.get("used_percent") is not None:
                zcode_main, zcode_rem = "%s" % _remain(z["used_percent"]), 100 - z["used_percent"]
                zcode_reset = z.get("reset_at")
        zcode_reached = any(w.get("used_percent", 0) >= 100 for w in zcode_wins)
        rows.append(("zcode", zcode_main, zcode_reached,
                     self.zcode_error, zcode_rem, zcode_reset))
        return rows

    def tip_text(self):
        lines = []
        if self.error:
            lines.append("codex 获取失败：" + self.error)
        if self.data:
            plan = self.data.get("plan_type") or "?"
            lines.append("codex plan: %s" % plan)
            rl = self.data.get("rate_limit") or {}
            for w in (rl.get("primary_window"), rl.get("secondary_window")):
                if not w:
                    continue
                name = "5h" if window_tag(w) == "5h" else "周"
                reset = ""
                if w.get("reset_at"):
                    reset = datetime.fromtimestamp(w["reset_at"]).strftime("，重置于 %m-%d %H:%M")
                lines.append("codex %s窗口：已用 %s%%%s" % (name, w.get("used_percent", "?"), reset))
            credits = self.data.get("credits") or {}
            if credits.get("has_credits"):
                lines.append("codex credits 余额：%s" % credits.get("balance", "?"))
            if rl.get("limit_reached"):
                lines.append("codex 已达速率上限！")
        if self.kimi_error:
            lines.append("kimi 获取失败：" + self.kimi_error)
        if self.kimi_data:
            kd = self.kimi_data
            if kd.get("level"):
                lines.append("kimi 会员: %s" % kd["level"])
            for w in kd.get("windows") or []:
                reset = ""
                if w.get("reset_at"):
                    reset = datetime.fromtimestamp(w["reset_at"]).strftime("，重置于 %m-%d %H:%M")
                name = "周" if w["tag"] == "w" else w["tag"]
                lines.append("kimi %s窗口：已用 %d%%%s"
                             % (name, w["used_percent"], reset))
            if kd.get("used_ratio") is not None:
                line = "kimi 月总额度：已用 %d%%" % round(kd["used_ratio"] * 100)
                if kd.get("amount") and kd.get("amount_left") is not None:
                    line += "（剩余 %s/%s）" % (_fmt_amount(kd["amount_left"]),
                                                 _fmt_amount(kd["amount"]))
                if kd.get("reset_at"):
                    line += datetime.fromtimestamp(kd["reset_at"]).strftime(
                        "，重置于 %m-%d %H:%M")
                lines.append(line)
                if kd.get("code_used_ratio"):
                    lines.append("其中 Kimi Code 已用总额度的 %d%%"
                                 % round(kd["code_used_ratio"] * 100))
                if kd["used_ratio"] >= 1:
                    lines.append("kimi 月总额度已用尽！")
        if self.zcode_error:
            lines.append("zcode 获取失败：" + self.zcode_error)
        if self.zcode_data:
            zd = self.zcode_data
            if zd.get("plan_name"):
                lines.append("zcode 订阅: %s" % zd["plan_name"])
            elif zd.get("level"):
                lines.append("zcode 会员: %s" % zd["level"])
            for w in zd.get("windows") or []:
                name = {"w": "周窗口", "月": "月总额度"}.get(w["tag"], "%s 窗口" % w["tag"])
                reset = ""
                if w.get("reset_at"):
                    reset = datetime.fromtimestamp(w["reset_at"]).strftime("，重置于 %m-%d %H:%M")
                line = "zcode %s：剩余 %s%%" % (name, _remain(w.get("used_percent")))
                if w.get("amount") and w.get("amount_left") is not None:
                    line += "（剩 %s/%s）" % (_fmt_amount(w["amount_left"]),
                                               _fmt_amount(w["amount"]))
                lines.append(line + reset)
                if w.get("used_percent", 0) >= 100:
                    lines.append("zcode %s已用尽！" % name)
            if not (zd.get("windows")):
                pct = zd.get("used_percent")
                if pct is not None:
                    line = "zcode 月总额度：已用 %d%%" % pct
                    if zd.get("remaining") is not None and zd.get("limit") is not None:
                        line += "（剩余 %s/%s）" % (_fmt_amount(zd["remaining"]),
                                                     _fmt_amount(zd["limit"]))
                    lines.append(line)
            if zd.get("until"):
                lines.append("zcode 订阅到期：" + datetime.fromtimestamp(
                    zd["until"]).strftime("%Y-%m-%d %H:%M"))
        for name, data, error in (("codex", self.data, self.error),
                                  ("kimi", self.kimi_data, self.kimi_error),
                                  ("zcode", self.zcode_data, self.zcode_error)):
            saved_at = self.last_success.get(name)
            if data and saved_at:
                lines.append("%s 最后成功更新：%s%s" % (
                    name, datetime.fromtimestamp(saved_at).strftime("%m-%d %H:%M:%S"),
                    "（当前显示上次记录）" if error else ""))
        if any((self.error, self.kimi_error, self.zcode_error)):
            lines.append("* 表示刷新失败或等待刷新；灰色数字为上次记录")
        if self.last_refresh:
            lines.append("上次尝试刷新：" + self.last_refresh.strftime("%H:%M:%S"))
        lines.append("左键刷新 · 右键菜单")
        return "\n".join(lines)

    def render(self):
        self._apply_font_size()   # 先定字号再量宽，保证与 anchor 布局一致
        rows = self.bar_rows()
        label_w = max(self.font_top.measure(l + ("*" if err else ""))
                      for l, _, _, err, _, _ in rows) + 4
        self.label_w = label_w
        main_w = 0
        for (label_item, main_item, timer_item), (label, main, reached, err, rem, reset_at) in zip(self.row_items, rows):
            if err:
                fill = self.muted_color  # 获取失败：旧数据置灰，避免把过期数字当实时
            elif reached:
                fill = "#ff5555"        # 达上限：红
            else:
                fill = self.fg
            self.canvas.itemconfig(label_item, text=label + ("*" if err else ""),
                                   fill=fill if reached and not err else self.muted_color)
            self.canvas.itemconfig(main_item, text=main, fill=fill)
            timer_txt, timer_fill = "", self.muted_color
            if reset_at:
                left = reset_at - time.time()
                if left > 0:
                    timer_txt = fmt_countdown_short(reset_at)
                    if left <= 1800:
                        timer_fill = "#3ba55d"   # 快重置：绿，回血在即
            self.canvas.itemconfig(timer_item, text=timer_txt, fill=timer_fill)
            main_w = max(main_w, self.font.measure(main))
        self.last_main_w = main_w
        # 数字、进度条和重置时间从同一份窗口列表生成，避免过滤缺失值后错位。
        display = [_display_windows(name, data)[:2] for name, data in
                   (("codex", self.data), ("kimi", self.kimi_data),
                    ("zcode", self.zcode_data))]
        self.seg_remains = [[max(0, min(100, 100 - w["used_percent"])) for w in wins]
                            or [None] for wins in display]
        self.seg_resets = [[w.get("reset_at") for w in wins] or [None]
                           for wins in display]
        # 100% 比两位余量更宽；按实际字体和 DPI 量宽，避免与倒计时重叠。
        seg_w = max(70, self.font_seg.measure("100%") +
                    max(self.font_cd.measure("23h59m"),
                        self.font_cd.measure("31d23h")) + 6)
        bars_zone = seg_w * 2 + 3
        self.bars_zone = bars_zone
        self.seg_w = seg_w
        # 紧凑宽度：小边距+标签+3+条区+3
        self.width = 4 + label_w + 3 + bars_zone + 4
        self.anchor()
        self._update_account_status()

    def _apply_font_size(self):
        """按任务栏高度/行数选字号：三行挤不下时自动缩小（只降不升）。"""
        row_h = self.tb_h / float(len(self.row_items))
        want = int(self.cfg["font_size"])
        for size in sorted({want, max(6, want - 1), 7, 6}, reverse=True):
            if self.font.cget("size") != size:
                self.font.configure(size=size)
                self.font_top.configure(size=max(6, size - 1))
            if self.font.metrics("linespace") <= row_h:
                break
        size = int(self.cfg.get("data_font_size", 8))
        while True:
            self.font_seg.configure(size=size)
            self.font_cd.configure(size=size)
            if size <= 6 or self.font_seg.metrics("linespace") <= row_h + 3:
                break
            size -= 1

    def anchor(self):
        """把窗口吸附到底部任务栏、托盘图标区左侧（置顶悬浮，定期 lift 防被被盖）。
        每行 = 标签 | 分段进度条(按余量绿/黄/红) | 余量%。
        行高足够时竖排（文字上/条下）；紧凑时（如 16px/行）横排：
        条与文字同行，条宽自适应剩余空间。"""
        try:
            user32 = ctypes.windll.user32
            self._safe_lift()
            shell = user32.FindWindowW("Shell_TrayWnd", None)
            if not shell:
                return
            rect = RECT()
            user32.GetWindowRect(shell, ctypes.byref(rect))
            tb_h = rect.bottom - rect.top
            tray = user32.FindWindowExW(shell, None, "TrayNotifyWnd", None)
            right_edge = rect.right
            if tray:
                trect = RECT()
                user32.GetWindowRect(tray, ctypes.byref(trect))
                right_edge = trect.left
            self.screen_x = right_edge - self.width - int(self.cfg["offset_x"])
            self.screen_y = rect.top
            self.tb_h = tb_h
            self.root.geometry("%dx%d+%d+%d" %
                               (self.width, tb_h, self.screen_x, rect.top))
            if self.chip is not None:
                self.canvas.coords(self.chip,
                                   *_rr_points(1, 1, self.width - 1, tb_h - 1, 7))

            # ----- 三行布局：标签 | 信息槽(文字上+矮条下) x 2 -----
            n_rows = len(self.row_items)
            row_h = tb_h / float(n_rows)
            self._apply_font_size()
            ls = self.font.metrics("linespace")
            pad = 5 if self.chip is not None else 1
            label_w = getattr(self, "label_w", 30)
            bar_gap = 6                             # 标签与条区间距
            seg_gap = 3                             # 两槽间隙（紧凑）
            seg_w = getattr(self, "seg_w", 70)      # 每槽宽（文字+条）
            bars_zone = getattr(self, "bars_zone", seg_w * 2 + seg_gap)
            bar_h = 2                               # 细条：给文字让空间
            seg_ls = self.font_seg.metrics("linespace")
            # 行内空间：文字在上、条贴底。行高不够时只显示文字不画条
            # 8pt 文字 linespace=16 已占满行；但实际字形（数字）只占约 11px，
            # 条贴行底、文字略上移，允许 3px 重叠（视觉上数字底和条顶贴合可接受）
            stack_ok = seg_ls - 3 + bar_h <= row_h
            for i, ((label_item, main_item, timer_item), segs, rems,
                    texts, cts) in enumerate(
                    zip(self.row_items, self.bars, self.seg_remains,
                        self.seg_texts, self.seg_timers)):
                stale = bool((self.error, self.kimi_error, self.zcode_error)[i])
                text_fill = self.muted_color if stale else self.fg
                top_i = i * row_h
                y_text = top_i + (row_h - ls) / 2.0 + ls / 2.0
                self.canvas.coords(label_item, 5, y_text)
                # 标签永远占位；main/timer 老三件套隐藏（信息已按窗口拆进槽内）
                self.canvas.itemconfig(main_item, state="hidden")
                self.canvas.itemconfig(timer_item, state="hidden")
                resets = self.seg_resets[i] if i < len(self.seg_resets) else []
                avail = [r for r in rems if r is not None]
                if not avail:
                    # 无数据：main 文字兜底显示 "--"
                    self.canvas.itemconfig(main_item, state="normal",
                                           text="--")
                    self.canvas.coords(main_item,
                                       5 + label_w + bar_gap, y_text)
                zone_x = 5 + label_w + bar_gap
                zone_right = zone_x + bars_zone
                # 槽位 x：单窗口拉伸占满，双窗口各半
                n = len(avail)
                if n == 0:
                    slot_spans = []
                elif n == 1:
                    slot_spans = [(zone_x, zone_right)]
                else:
                    mid = (zone_x + zone_right - seg_gap) / 2.0
                    slot_spans = [(zone_x, mid), (mid + seg_gap, zone_right)]
                y_txt = top_i + (row_h - seg_ls) / 2.0 + seg_ls / 2.0 - 1.5
                y_bar = top_i + row_h - bar_h - 0.5
                for j, (bg_item, fg_item) in enumerate(segs):
                    pct_item, cd_item = texts[j], cts[j]
                    if j >= len(slot_spans) or not avail:
                        self.canvas.coords(bg_item, 0, 0, 0, 0)
                        self.canvas.coords(fg_item, 0, 0, 0, 0)
                        self.canvas.itemconfig(pct_item, state="hidden")
                        self.canvas.itemconfig(cd_item, state="hidden")
                        continue
                    sx0, sx1 = slot_spans[j]
                    rem = avail[j] if j < len(avail) else None
                    if rem is None:
                        continue
                    # 文字：% 左对齐（黑色加粗），倒计时右对齐（黑色加粗）
                    self.canvas.coords(pct_item, sx0, y_txt)
                    self.canvas.itemconfig(
                        pct_item, text="%d%%" % round(rem), state="normal",
                        fill=text_fill)
                    rst = resets[j] if j < len(resets) else None
                    if rst and rst > time.time():
                        left = rst - time.time()
                        self.canvas.coords(cd_item, sx1, y_txt)
                        self.canvas.itemconfig(
                            cd_item, text=fmt_countdown_short(rst),
                            state="normal", fill=text_fill)
                    else:
                        self.canvas.itemconfig(cd_item, state="hidden")
                    # 矮条贴槽底：填充 = 余量，颜色红绿灯
                    if stack_ok:
                        self.canvas.coords(bg_item, sx0, y_bar, sx1, y_bar + bar_h)
                        fw = sx0 + int(round((sx1 - sx0) * rem / 100.0))
                        if rem > 0:
                            fw = max(sx0 + 2, fw)
                        self.canvas.coords(fg_item, sx0, y_bar, fw, y_bar + bar_h)
                        self.canvas.itemconfig(fg_item, fill=(self.muted_color if stale
                                                              else self._remain_color(rem)))
                    else:
                        self.canvas.coords(bg_item, 0, 0, 0, 0)
                        self.canvas.coords(fg_item, 0, 0, 0, 0)
        except Exception:
            _dbg("anchor 异常")

    @staticmethod
    def _remain_color(rem):
        """余量 → 颜色（只用绿/红，黄在小字号下不清楚）：≥20 绿，<20 红。"""
        if rem >= 20:
            return "#3ba55d"      # 充足：绿
        return "#e74c3c"          # 告急：红

    def _chip_color(self):
        """垫层色：任务栏色混入少量文字色，近似透明但整块可点击。"""
        return _blend(self.bg, self.fg, 0.09)

    @staticmethod
    def _menu_open():
        """本进程当前是否有弹出的菜单（Win32 弹出菜单的窗口类名是 #32768）。"""
        try:
            user32 = ctypes.windll.user32
            pid = os.getpid()
            h = None
            while True:
                h = user32.FindWindowExW(None, h, "#32768", None)
                if not h:
                    return False
                if user32.IsWindowVisible(h):
                    wp = ctypes.c_ulong(0)
                    user32.GetWindowThreadProcessId(h, ctypes.byref(wp))
                    if wp.value == pid:
                        return True
        except Exception:
            return False

    def _safe_lift(self):
        """置顶防被任务栏盖住；但菜单弹出期间不抢层级，否则会遮住菜单。"""
        if not self._menu_open():
            try:
                self.root.lift()
            except Exception:
                pass

    def _kick_lift(self):
        """点击后任务栏会抢置顶，立即补几次置顶防止窗口被盖住。"""
        for delay in (0, 80, 250, 600):
            self.root.after(delay, self._safe_lift)

    def show_tip(self):
        self.hide_tip()
        tip = tk.Toplevel(self.root)
        tip.transient(self.root)
        tip.overrideredirect(True)
        tip.attributes("-toolwindow", True)
        tip.attributes("-topmost", True)
        label = tk.Label(tip, text=self.tip_text(), justify="left",
                         bg="#202020", fg="#eeeeee", font=("Microsoft YaHei UI", 9),
                         padx=10, pady=6, bd=1, relief="solid")
        label.pack()
        tip.update_idletasks()
        x = self.screen_x + self.width - tip.winfo_reqwidth()
        y = self.screen_y - tip.winfo_reqheight() - 6
        tip.geometry("+%d+%d" % (max(0, x), max(0, y)))
        self._tip = tip

    def hide_tip(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    # ---------- 菜单 / 自启 ----------

    def show_menu(self, event):
        self.hide_tip()
        self._kick_lift()
        self.autostart_var.set(self.autostart_enabled())
        try:
            # 先把本窗口设为前台：菜单才能压在最上层，且点别处能正常收起
            ctypes.windll.user32.SetForegroundWindow(self.root.winfo_id())
        except Exception:
            pass
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    @staticmethod
    def autostart_enabled():
        return os.path.exists(STARTUP_VBS)

    def show_account_settings(self):
        """只管理连接；三家额度仍常驻任务栏，不依赖此窗口。"""
        window = getattr(self, "_account_window", None)
        if window is not None and window.winfo_exists():
            window.lift()
            return
        window = self._account_window = tk.Toplevel(self.root)
        window.transient(self.root)
        window.title("TokenDuck · 账户与登录")
        window.resizable(False, False)
        window.attributes("-topmost", True)
        panel = ttk.Frame(window, padding=18)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="连接您的订阅账户", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        ttk.Label(panel, text="优先使用本机官方客户端登录。凭证仅在本机加密保存。",
                  padding=(0, 6, 0, 12)).pack(anchor="w")
        self._account_status_vars = {}
        for name, title in (("codex", "Codex / ChatGPT"), ("kimi", "Kimi"), ("zcode", "ZCode / GLM Coding Plan")):
            box = ttk.LabelFrame(panel, text=title, padding=10)
            box.pack(fill="x", pady=5)
            var = self._account_status_vars[name] = tk.StringVar()
            ttk.Label(box, textvariable=var, wraplength=470).pack(anchor="w")
            buttons = ttk.Frame(box)
            buttons.pack(anchor="w", pady=(8, 0))
            if name == "codex":
                ttk.Button(buttons, text="检测本机登录", command=self.refresh_now).pack(side="left")
                ttk.Button(buttons, text="官方登录", command=self.connect_codex).pack(side="left", padx=6)
                ttk.Label(box, text="官方登录会更新本机 Codex 登录；请在官方浏览器页面完成验证。",
                          wraplength=470).pack(anchor="w", pady=(6, 0))
            elif name == "kimi":
                ttk.Button(buttons, text="使用本机 Kimi 登录", command=lambda: self.rebind_kimi(False)).pack(side="left")
                ttk.Button(buttons, text="从浏览器连接", command=lambda: self.rebind_kimi(True)).pack(side="left", padx=6)
                ttk.Button(buttons, text="设置 Code key…", command=lambda: self.configure_key("kimi")).pack(side="left")
                ttk.Label(box, text="重新连接会以您当前登录的账号替换本工具的绑定；不会修改 Kimi 客户端登录。",
                          wraplength=470).pack(anchor="w", pady=(6, 0))
            else:
                ttk.Button(buttons, text="检测本机登录", command=self.refresh_now).pack(side="left")
                ttk.Button(buttons, text="设置套餐 key…", command=lambda: self.configure_key("zcode")).pack(side="left", padx=6)
        bottom = ttk.Frame(panel)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Label(bottom, text="TokenDuck " + APP_VERSION).pack(side="left")
        ttk.Button(bottom, text="完成", command=window.destroy).pack(side="right")
        self._update_account_status()

    def _update_account_status(self):
        window = getattr(self, "_account_window", None)
        if window is None or not window.winfo_exists():
            return
        messages = {"codex": "已发现本机 Codex 登录" if os.path.isfile(AUTH_PATH) else "尚未发现本机登录，请先完成官方登录",
                    "zcode": "自动读取本机 ZCode 套餐；也可设置自己的套餐 key"}
        try:
            cred = _read_kimi_web_cred()
            user = ACCOUNT_STORE.get("kimi_account_id")
            if ACCOUNT_STORE.get("kimi_auth_mode") == "key":
                messages["kimi"] = "已选择手动 Kimi Code key"
            elif user:
                tag = hashlib.sha256(str(user).encode("utf-8")).hexdigest()[:6]
                messages["kimi"] = "已绑定账号 " + tag + (" · 独立会话" if _kimi_own_session(cred) else " · 本机登录")
            else:
                messages["kimi"] = "尚未绑定，请在 Kimi 桌面端登录后连接"
        except CredentialStoreError as e:
            messages["kimi"] = str(e)
        for name, error in (("codex", self.error), ("kimi", self.kimi_error), ("zcode", self.zcode_error)):
            text = messages.get(name, "")
            if error:
                text += "\n" + error
            self._account_status_vars[name].set(text)

    def configure_key(self, provider):
        window = tk.Toplevel(self._account_window)
        window.transient(self._account_window)
        window.title("设置 " + ("Kimi Code" if provider == "kimi" else "GLM Coding Plan") + " key")
        window.resizable(False, False)
        window.attributes("-topmost", True)
        panel = ttk.Frame(window, padding=16)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="可选：保存您已有的套餐 key", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        ttk.Label(panel, text="使用 Windows 当前用户加密；不会在界面中回显已保存的 key。",
                  wraplength=420).pack(anchor="w", pady=8)
        site = tk.StringVar(value="智谱 BigModel")
        if provider == "zcode":
            ttk.Combobox(panel, textvariable=site, values=("智谱 BigModel", "Z.ai"), state="readonly").pack(fill="x", pady=(0, 8))
        entry = ttk.Entry(panel, width=48, show="●")
        entry.pack(fill="x")

        def save(remove=False):
            key = entry.get().strip()
            if not remove and not key:
                messagebox.showinfo("未填写 key", "请填写您已有的套餐 key。", parent=window)
                return
            entry.delete(0, "end")
            field = "kimi_api_key" if provider == "kimi" else "zcode_key"
            value = key if provider == "kimi" else {"key": key, "site": "zai" if site.get() == "Z.ai" else "bigmodel"}
            for button in buttons.winfo_children():
                button.configure(state="disabled")

            def finish(error):
                if not window.winfo_exists():
                    return
                if error:
                    messagebox.showerror("未能保存", error, parent=window)
                    for button in buttons.winfo_children():
                        button.configure(state="normal")
                else:
                    window.destroy()
                    if remove:
                        self.refresh_now()
                    else:
                        self.render()

            def work():
                error = None
                try:
                    with self.fetch_lock:
                        changes = {} if remove else {field: value}
                        if not remove:
                            if provider == "kimi":
                                data = _fetch_kimi_by_api_key(key)
                            else:
                                root = "https://api.z.ai" if value["site"] == "zai" else "https://open.bigmodel.cn"
                                wins, level, name, until = _fetch_zcode_monitor(credential=(key, root))
                                if wins is None:
                                    raise RuntimeError("无法读取此 key 的套餐额度，原连接已保留")
                                data = {"windows": wins, "level": level, "plan_name": name, "until": until}
                        if provider == "kimi":
                            changes["kimi_auth_mode"] = "web" if remove else "key"
                        ACCOUNT_STORE.update(changes, remove=(field,) if remove else ())
                        if not remove:
                            if provider == "kimi":
                                self.kimi_data, self.kimi_error = data, None
                            else:
                                self.zcode_data, self.zcode_error = data, None
                            self.last_success[provider] = time.time()
                            self._save_cache()
                except (RuntimeError, OSError) as e:
                    error = str(e)
                if not self.stop_event.is_set():
                    self.root.after(0, lambda: finish(error))
            threading.Thread(target=work, daemon=True).start()

        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="移除手动 key", command=lambda: save(True)).pack(side="left")
        ttk.Button(buttons, text="加密保存", command=save).pack(side="right")
        entry.focus_set()

    def connect_codex(self):
        if self._codex_login_running:
            return
        official = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "OpenAI", "Codex", "bin", "codex.exe")
        command = official if os.path.isfile(official) else shutil.which("codex.exe")
        if not command:
            messagebox.showinfo("连接 Codex", "请先安装并登录官方 Codex 客户端，再检测本机登录。", parent=self._account_window)
            webbrowser.open("https://chatgpt.com/codex")
            return
        self._codex_login_running = True
        self._account_status_vars["codex"].set("请在官方浏览器页面完成登录…")

        def work():
            error = None
            try:
                result = subprocess.run([command, "login"], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=600,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode:
                    error = "官方登录尚未完成，请重试"
            except (OSError, subprocess.TimeoutExpired):
                error = "官方登录未完成或已超时，请重试"
            self._codex_login_running = False
            self.error = error
            self.refresh_now()
            if not self.stop_event.is_set():
                self.root.after(0, self._update_account_status)
        threading.Thread(target=work, daemon=True).start()

    def rebind_kimi(self, allow_browser=None):
        """用户主动换号；清除工具自己的绑定后重新导入。"""
        def work():
            # 等正在进行的刷新结束后再删除凭证，避免旧请求把旧账号重新写回。
            with self.fetch_lock:
                try:
                    if allow_browser is not None:
                        settings = dict(self.cfg, allow_browser_import=bool(allow_browser))
                        save_config(settings)
                        self.cfg.update(settings)
                    data = connect_kimi_account(allow_browser)
                except (OSError, RuntimeError) as e:
                    self.kimi_error = "重新连接失败，原绑定已保留：%s" % e
                else:
                    self.kimi_data = data
                    self.kimi_error = None
                    self.last_success["kimi"] = time.time()
                    self.last_refresh = datetime.now()
                self._save_cache()
            if not self.stop_event.is_set():
                self.root.after(0, self.render)
                self.root.after(0, self._update_account_status)
        threading.Thread(target=work, daemon=True).start()

    def show_display_settings(self):
        window = getattr(self, "_settings_window", None)
        if window is not None and window.winfo_exists():
            window.lift()
            return
        window = self._settings_window = tk.Toplevel(self.root)
        window.transient(self.root)
        window.title("TokenDuck · 显示与刷新设置")
        window.resizable(False, False)
        window.attributes("-topmost", True)
        panel = ttk.Frame(window, padding=18)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="任务栏常驻显示", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        values = {}
        fields = (("data_font_size", "额度字号", 6, 14),
                  ("offset_x", "与托盘的间距（像素）", -1000, 10000),
                  ("interval_minutes", "自动刷新间隔（分钟）", 1, 1440))
        for row, (key, label, lo, hi) in enumerate(fields, 1):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=6, padx=(0, 15))
            variable = values[key] = tk.StringVar(value=str(self.cfg.get(key, DEFAULT_CONFIG[key])))
            ttk.Spinbox(panel, from_=lo, to=hi, width=10, textvariable=variable).grid(row=row, column=1)
        ttk.Label(panel, text="任务栏空间不足时会自动缩小文字。",
                  wraplength=300).grid(row=4, column=0, columnspan=2, sticky="w", pady=10)

        def apply():
            settings = dict(self.cfg)
            try:
                for key, _, lo, hi in fields:
                    n = int(values[key].get())
                    if not lo <= n <= hi:
                        raise ValueError()
                    settings[key] = n
            except ValueError:
                messagebox.showinfo("请检查设置", "请填写范围内的整数。", parent=window)
                return
            try:
                save_config(settings)
            except OSError:
                messagebox.showerror("未能保存", "无法写入本机设置，请稍后重试。", parent=window)
                return
            self.cfg.update(settings)
            self.render()
            window.destroy()

        ttk.Button(panel, text="保存并应用", command=apply).grid(row=5, column=1, sticky="e")

    def show_about(self):
        messagebox.showinfo("关于 TokenDuck", "TokenDuck " + APP_VERSION +
                            "\nCodex · Kimi · ZCode 订阅额度常驻显示\n\n"
                            "本工具凭证由 Windows 当前用户加密保存在本机。\n"
                            "左键刷新额度，右键管理账户和设置。", parent=self.root)

    def toggle_autostart(self):
        if self.autostart_var.get():
            try:
                write_autostart()
            except Exception as e:
                self.error = "写入开机自启失败：%s" % e
        else:
            try:
                os.remove(STARTUP_VBS)
            except FileNotFoundError:
                pass
            except Exception as e:
                self.error = "删除开机自启失败：%s" % e

    # ---------- 主循环 ----------

    def quit(self):
        self.stop_event.set()
        self.root.destroy()

    def run(self):
        threading.Thread(target=self.poll_loop, daemon=True).start()
        self.root.after(2000, self._anchor_tick)
        self.root.after(30000, self._render_tick)
        self.root.mainloop()

    def _anchor_tick(self):
        self.anchor()
        if not self.stop_event.is_set():
            self.root.after(1000, self._anchor_tick)

    def _render_tick(self):
        try:
            self.apply_theme()  # 跟随任务栏颜色变化（深浅主题自动切换等）
            self.render()       # 刷新倒计时显示
        except Exception:
            import traceback
            _dbg("主题/倒计时刷新异常:\n%s" % traceback.format_exc(), force=True)
        finally:
            if not self.stop_event.is_set():
                self.root.after(30000, self._render_tick)

    def _theme_exclude_rect(self):
        try:
            if not self.root.winfo_ismapped():
                return None
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            return x, y, x + self.root.winfo_width(), y + self.root.winfo_height()
        except Exception:
            return None

    def _resolve_theme(self, auto_bg, auto_fg):
        bg = self.cfg["background"] or auto_bg
        if self.cfg["text_color"]:
            fg = self.cfg["text_color"]
        elif self.cfg["background"]:
            fg = _contrast_text_color(bg)
        else:
            fg = auto_fg
        return _theme_palette(bg, fg)

    def apply_theme(self):
        auto_bg, auto_fg, _, _ = detect_theme_colors(self._theme_exclude_rect())
        bg, fg, muted, track = self._resolve_theme(auto_bg, auto_fg)
        if (bg, fg, muted, track) == (self.bg, self.fg,
                                      self.muted_color, self.track_color):
            return
        bg_changed = bg != self.bg
        self.bg, self.fg = bg, fg
        self.muted_color, self.track_color = muted, track
        if self.transparent:
            if bg_changed:
                self.root.configure(bg=bg)
                self.canvas.configure(bg=bg)
                self.root.attributes("-transparentcolor", bg)
        else:
            self.root.configure(bg=bg)
            self.canvas.configure(bg=bg)
        for segs in self.bars:
            for bg_item, _ in segs:
                self.canvas.itemconfig(bg_item, fill=track)
        for label_item, _, timer_item in self.row_items:
            self.canvas.itemconfig(label_item, fill=muted)
            self.canvas.itemconfig(timer_item, fill=muted)
        for texts, timers in zip(self.seg_texts, self.seg_timers):
            for item in texts + timers:
                self.canvas.itemconfig(item, fill=fg)
        if self.chip is not None:
            self.chip_color = self._chip_color()
            self.canvas.itemconfig(self.chip, fill=self.chip_color)


def startup_command():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return [pythonw if os.path.isfile(pythonw) else sys.executable,
            os.path.join(APP_DIR, "tokenduck.py")]


def write_autostart():
    command = " ".join('"%s"' % part for part in startup_command())
    content = ('Set sh = CreateObject("Wscript.Shell")\r\n'
               'sh.Run "%s", 0, False\r\n' % command.replace('"', '""'))
    os.makedirs(os.path.dirname(STARTUP_VBS), exist_ok=True)
    with open(STARTUP_VBS, "w", encoding="utf-16") as f:
        f.write(content)


_INSTANCE_MUTEX = None


def acquire_instance():
    global _INSTANCE_MUTEX
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    # 保留旧名称，阻止更名前后的程序并行续期同一个会话。
    handle = kernel.CreateMutexW(None, False, "Local\\CodexBarMutex")
    if not handle:
        raise RuntimeError("无法建立单实例保护，请重试启动")
    already_running = ctypes.get_last_error() == 183
    if already_running:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)
        return False
    _INSTANCE_MUTEX = handle
    return True


def self_check():
    """安装包离线自检：仅使用合成数据，不读取或续期真实账号。"""
    report = {"version": APP_VERSION, "ok": False}
    try:
        sample = b"TokenDuck synthetic credential self-check"
        report["user_encryption"] = unprotect_bytes(protect_bytes(sample)) == sample
        request = urllib.request.Request(USAGE_URL, headers={"Authorization": "Bearer synthetic"})
        try:
            _SameOriginRedirect().redirect_request(request, None, 302, "redirect", {}, "https://example.invalid/")
            report["cross_site_redirect_blocked"] = False
        except urllib.error.HTTPError as e:
            e.close()
            report["cross_site_redirect_blocked"] = True
        bar = TokenDuck(dict(DEFAULT_CONFIG), hidden=True)
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            user32.GetAncestor.restype = ctypes.c_void_p
            get_style = (user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
                         else user32.GetWindowLongW)
            get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
            get_style.restype = ctypes.c_ssize_t
            wrapper = user32.GetAncestor(bar.root.winfo_id(), 2)  # GA_ROOT：Tk 的原生外层窗口
            extended_style = get_style(wrapper, -20)  # GWL_EXSTYLE
            report["taskbar_icon_hidden"] = bool(extended_style & 0x80) and not bool(extended_style & 0x40000)
            bar.data = bar.zcode_data = None
            bar.error = bar.kimi_error = bar.zcode_error = None
            now = datetime.now(timezone.utc)
            bar.kimi_data = _parse_kimi_web_quota({
                "ratelimitCode5h": {"enabled": True, "resetTime": (now + timedelta(hours=2)).isoformat()},
                "ratelimitCode7d": {"enabled": True, "resetTime": (now + timedelta(days=6)).isoformat()}})
            bar.render()
            bar.root.update_idletasks()
            report["full_quota_visible"] = all(bar.canvas.itemcget(item, "text") == "100%"
                                                for item in bar.seg_texts[1])
            report["text_does_not_overlap"] = all(
                bar.canvas.bbox(pct)[2] + 2 <= bar.canvas.bbox(timer)[0]
                for pct, timer in zip(bar.seg_texts[1], bar.seg_timers[1]))
        finally:
            bar.quit()
        report["ok"] = all(report[k] for k in ("user_encryption", "cross_site_redirect_blocked",
                                               "full_quota_visible", "text_does_not_overlap",
                                               "taskbar_icon_hidden"))
    except Exception as e:
        report["error"] = type(e).__name__ + ": " + str(e)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "self_check.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    if sys.stdout:
        print(json.dumps(report, ensure_ascii=True))
    return report["ok"]


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    if "--self-check" in sys.argv:
        sys.exit(0 if self_check() else 1)
    if not acquire_instance():
        return
    try:
        migrate_data_files()
    except (OSError, ValueError, CredentialStoreError) as e:
        message = "本地账号迁移未完成，原有凭证已保留。\n" + str(e)
        if sys.stdout:
            print(message)
        else:
            messagebox.showerror("TokenDuck · 连接保护", message)
        return
    # --once：无窗口单次拉取，打印三家数据（调试接口/凭证用）
    if "--once" in sys.argv:
        out = {}
        for name, fn in (("codex", fetch_usage), ("kimi", fetch_kimi_quota),
                         ("zcode", fetch_zcode_quota)):
            try:
                out[name] = fn()
            except Exception as e:
                out[name] = "ERROR: %s" % e
        text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
        if sys.stdout:
            print(text)
        else:
            with open(os.path.join(DATA_DIR, "quota_diagnostics.json"), "w", encoding="utf-8") as f:
                f.write(text)
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    if os.path.isfile(STARTUP_VBS):
        write_autostart()  # 已启用自启时，升级为当前实际启动的 exe 或脚本路径。
    cfg = load_config()
    bar = TokenDuck(cfg)
    if "--accounts" in sys.argv:
        bar.root.after(200, bar.show_account_settings)
    bar.run()


if __name__ == "__main__":
    main()
