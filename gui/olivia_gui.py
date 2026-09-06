import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
import urllib.request
import urllib.error
import ctypes
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox

APP_NAME = "Olivia 来信拦截助手"
APP_VERSION = "1.2.12"
PROXY_ADDR = "127.0.0.1:8080"
LISTEN_PORT = "8080"

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE = app_dir()
CONFIG_PATH = os.path.join(BASE, "config.json")
ADDON_PATH = os.path.join(BASE, "olivia_letter_proxy.py")
LETTERS_PATH = os.path.join(BASE, "letters.json")
RUNTIME_DIR = os.path.join(BASE, "runtime")
MITMDUMP = os.path.join(RUNTIME_DIR, "Scripts", "mitmdump.exe")
PYTHON = os.path.join(RUNTIME_DIR, "python.exe")
BACKUP_PATH = os.path.join(BASE, "proxy_backup.txt")
CERTS_DIR = os.path.join(RUNTIME_DIR, "certs")
CERT_CER = os.path.join(CERTS_DIR, "mitmproxy-ca-cert.cer")
CERT_PEM = os.path.join(CERTS_DIR, "mitmproxy-ca.pem")

LEGAL_NOTICE = (
    "重要声明（请仔细阅读）\n\n"
    "本工具仅用于对您本人拥有或已获得明确授权的设备、账号进行学习、研究、"
    "数据备份与个人娱乐用途。\n\n"
    "您理解并同意：\n"
    "1. 本工具会拦截并模拟本机特定应用的网络请求，仅应作用于您本人登录的账号与设备。\n"
    "2. 严禁用于窥探、窃取或记录他人隐私、他人账号、支付信息；严禁用于绕过任何认证、"
    "安全防护或付费机制；严禁用于任何商业或非法用途。\n"
    "3. 使用过程中产生的数据（信件、回复、账号信息等）请勿对外传播或用于任何非法活动。\n"
    "4. 本软件按“现状”提供，不对其功能、可用性及由此产生的任何直接或间接后果承担"
    "责任。因个人滥用、违规使用或违反法律法规而导致的任何后果，由使用者自行承担。\n"
    "5. 请遵守您所在国家/地区及您使用目标应用之服务条款与当地法律法规。\n\n"
    "点击“同意”即表示您已阅读并接受以上条款，并承诺仅将该工具用于合法合规的个人用途。"
)

CERT_INSTALL_NOTICE = (
    "安装 CA 证书将把本工具生成的本地根证书加入系统“受信任的根证书颁发机构”存储。\n\n"
    "安装后，仅本机经此代理工具转发的 HTTPS 连接会被该证书信任，"
    "该证书仅存在于本机，不会在网络上传播。\n\n"
    "请仅在您本人拥有或已获授权的设备上执行此操作。安装证书属于较高权限的系统操作，"
    "如使用环境不允许或您不了解其含义，请选择取消。\n\n"
    "本人确认：仅在本人设备上、用于本人合法合规用途。是否继续？"
)

CERT_RENEW_NOTICE = (
    "重新生成 CA 证书将删除现有的本地根证书并生成新证书。\n"
    "新证书不会自动加入系统信任存储，您需要重新执行“安装 CA 证书”。\n"
    "此前信任旧证书的连接将不再被信任。\n\n"
    "本人确认仅在本人设备上执行该操作。是否继续？"
)

LEGAL_AGREED_KEY = "olivia_legal_agreed_v1"
AGREED_PATH = os.path.join(BASE, "legal_agreed.txt")

INTERNET_SETTINGS_UPDATE = 0x1
INTERNET_OPTION_REFRESH = 37
INTERNET_OPTION_SETTINGS_CHANGED = 39


class Config:
    def __init__(self):
        self.data = self.load()

    def load(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            return {}

    def save(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


def refresh_wininet():
    try:
        ctypes.windll.Wininet.InternetSetOptionW(None, INTERNET_OPTION_SETTINGS_CHANGED, None, 0)
        ctypes.windll.Wininet.InternetSetOptionW(None, INTERNET_OPTION_REFRESH, None, 0)
    except Exception:
        pass


def read_reg(name):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v
    except Exception:
        return None


def write_reg(name, value, regtype):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
        winreg.SetValueEx(k, name, 0, regtype, value)


def get_proxy_state():
    enabled = read_reg("ProxyEnable")
    server = read_reg("ProxyServer")
    return int(enabled or 0) == 1, server or ""


def set_proxy(enabled, preserve_backup=True):
    if preserve_backup and enabled:
        old_enabled, old_server = get_proxy_state()
        backup = {"ProxyEnable": old_enabled, "ProxyServer": old_server,
                  "ProxyOverride": read_reg("ProxyOverride")}
        try:
            with open(BACKUP_PATH, "w", encoding="utf-8") as f:
                json.dump(backup, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    write_reg("ProxyEnable", 1 if enabled else 0, 4)  # REG_DWORD
    write_reg("ProxyServer", PROXY_ADDR if enabled else "", 1)
    if not enabled:
        override = read_reg("ProxyOverride")
        write_reg("ProxyOverride", override or "", 1)
    refresh_wininet()


def restore_backup():
    try:
        with open(BACKUP_PATH, "r", encoding="utf-8") as f:
            b = json.load(f)
        write_reg("ProxyEnable", 1 if b.get("ProxyEnable") else 0, 4)  # REG_DWORD
        write_reg("ProxyServer", b.get("ProxyServer") or "", 1)
        refresh_wininet()
        return True
    except Exception:
        return False


def mitmdump_cmd():
    port = LISTEN_PORT
    certs = os.path.join(RUNTIME_DIR, "certs")
    base = ["--listen-port", port, "-s", ADDON_PATH, "--set", "confdir=%s" % certs, "--set", "ssl_insecure=true"]
    if os.path.exists(MITMDUMP):
        return [MITMDUMP] + base
    # fallback: system python + mitmdump on PATH
    return ["mitmdump"] + base


def count_letters():
    try:
        with open(LETTERS_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return len(d.get("letters", {}))
    except Exception:
        return 0


def load_letters_detail():
    try:
        with open(LETTERS_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("letters", {})
    except Exception:
        return {}


def cert_info():
    """返回证书状态信息 dict，或 None（不可用）."""
    if not os.path.exists(CERT_CER):
        return None
    try:
        import ssl
        cert = ssl._ssl._test_decode_cert(CERT_CER)
        not_after = cert.get("notAfter", "")
        not_before = cert.get("notBefore", "")
        subject = cert.get("subject", ())
        cn = ""
        for rdns in subject:
            for k, v in rdns:
                if k == "commonName":
                    cn = v
                    break
        return {"cn": cn, "not_before": not_before, "not_after": not_after,
                "path": CERT_CER}
    except Exception:
        # 无法解析时仍返回基础信息，避免误报“不存在”
        return {"cn": "", "not_before": "", "not_after": "", "path": CERT_CER}


def _parse_cert_date(s):
    from email.utils import parsedate_to_datetime
    return parsedate_to_datetime(s)


def cert_is_valid():
    """证书文件存在且未过期则视为有效."""
    try:
        import ssl
        if not os.path.exists(CERT_CER):
            return False
        cert = ssl._ssl._test_decode_cert(CERT_CER)
        na = cert.get("notAfter", "")
        exp = _parse_cert_date(na)
        if exp.tzinfo is not None:
            now = datetime.now(exp.tzinfo)
        else:
            now = datetime.now()
        return exp > now
    except Exception:
        return False


def cert_is_installed():
    """检查证书是否已在 CurrentUser Root 存储. 通过颁发者 CN 匹配."""
    try:
        import subprocess
        r = subprocess.run(
            ["certutil", "-user", "-store", "Root"], capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "mitmproxy" in (r.stdout or "")
    except Exception:
        return False


def install_cert():
    """安装 CA 证书到 CurrentUser Root 存储，返回 (ok, msg)."""
    if not os.path.exists(CERT_CER):
        return False, "未找到证书文件 %s" % CERT_CER
    try:
        import subprocess
        r = subprocess.run(
            ["certutil", "-user", "-addstore", "-f", "Root", CERT_CER],
            capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0:
            return True, "证书安装成功"
        return False, "证书安装失败: %s" % (r.stderr or r.stdout)
    except Exception as e:
        return False, "证书安装异常: %s" % e


def uninstall_cert():
    """从 CurrentUser Root 存储删除 mitmproxy 证书，返回 (ok, msg)."""
    try:
        import subprocess
        r = subprocess.run(
            ["certutil", "-user", "-delstore", "Root", "mitmproxy"],
            capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0:
            return True, "证书已从系统信任存储删除"
        if "没有" in (r.stderr or r.stdout) or "could not be found" in (r.stderr or r.stdout):
            return True, "系统信任存储中没有该证书"
        return False, "证书删除失败: %s" % (r.stderr or r.stdout)
    except Exception as e:
        return False, "证书删除异常: %s" % e


def renew_cert():
    """删除旧证书并用运行时重新生成，返回 (ok, msg)."""
    try:
        if os.path.exists(CERTS_DIR):
            import shutil
            for fname in os.listdir(CERTS_DIR):
                p = os.path.join(CERTS_DIR, fname)
                if os.path.isfile(p):
                    os.remove(p)
                elif os.path.isdir(p):
                    shutil.rmtree(p)
        if not os.path.exists(PYTHON):
            return False, "未找到运行时 python.exe"
        # 用运行时 python + mitmproxy.certs 重新生成 CA
        script = (
            "from mitmproxy import certs\n"
            "certs.CertStore.from_store(%r, 'mitmproxy', 2048)\n" % CERTS_DIR
        )
        import subprocess
        r = subprocess.run(
            [PYTHON, "-c", script], capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            return False, "证书生成失败: %s" % (r.stderr or r.stdout)
        if os.path.exists(CERT_CER):
            return True, "新证书已生成"
        return False, "证书文件未生成"
    except Exception as e:
        return False, "证书重新生成异常: %s" % e


def legal_agreed():
    return os.path.exists(AGREED_PATH)


def mark_legal_agreed():
    try:
        with open(AGREED_PATH, "w", encoding="utf-8") as f:
            f.write(LEGAL_AGREED_KEY)
    except Exception:
        pass


MODEL_HINTS = (
    "支持模型参考:\n"
    "· 视频 OpenAI: sora-2 / sora-2-pro (2026-09-24 后停服)\n"
    "· 视频 MiniMax: MiniMax-H3 (V2 接口 /v2/video_generation)\n"
    "· 视频 火山引擎: doubao-seedance-1-5-pro-251215 等 Seedance 系列\n"
    "· 视频 算力平台(scnet.cn): Seedance2.0 / Wan2.7-T2V / HappyHorse-1.0-T2V\n"
    "· 视频 千问DashScope(通义万相): wan2.7-t2v-2026-06-12 / wan2.6-t2v / wan2.2-t2v-plus\n"
    "· 语音 OpenAI: gpt-4o-mini-tts / tts-1 / tts-1-hd (音色 coral/alloy/nova 等)\n"
    "· 语音 MiniMax: speech-2.8-hd / speech-2.6-hd / speech-02-hd 等\n"
    "· 语音 火山引擎: seed-tts-1.0 / seed-tts-2.0 (需 App ID + Access Token)\n"
    "· 语音 算力平台(scnet.cn): Qwen3-TTS-Instruct-Flash (音色 Cherry 等)\n"
)

VIDEO_PROVIDERS = ("minimax", "openai", "volcengine", "scnet", "dashscope")
VIDEO_DEFAULT_BASE = {
    "minimax": "https://api.minimaxi.com/v1",
    "openai": "https://api.openai.com/v1",
    "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
    "scnet": "https://api.scnet.cn/api/llm/v1",
    "dashscope": "https://dashscope.aliyuncs.com/api/v1",
}
VIDEO_DEFAULT_MODEL = {
    "minimax": "MiniMax-H3",
    "openai": "sora-2",
    "volcengine": "doubao-seedance-1-5-pro-251215",
    "scnet": "Seedance2.0",
    "dashscope": "wan2.7-t2v-2026-06-12",
}
TTS_PROVIDERS = ("minimax", "openai", "volcengine", "scnet")
TTS_DEFAULT_BASE = {
    "minimax": "https://api.minimaxi.com/v1",
    "openai": "https://api.openai.com/v1",
    "volcengine": "https://openspeech.bytedance.com/api/v1/tts",
    "scnet": "https://api.scnet.cn/api/llm/v1",
}
TTS_DEFAULT_MODEL = {
    "minimax": "speech-2.8-hd",
    "openai": "gpt-4o-mini-tts",
    "volcengine": "seed-tts-2.0",
    "scnet": "Qwen3-TTS-Instruct-Flash",
}
TTS_DEFAULT_VOICE = {
    "minimax": "female-tianmei",
    "openai": "coral",
    "volcengine": "zh_female_vv_uranus_bigtts",
    "scnet": "Cherry",
}


class OliviaGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("%s v%s" % (APP_NAME, APP_VERSION))
        self.root.geometry("580x1180")
        self.root.resizable(False, False)

        self.cfg = Config()
        self.proc = None

        self.proxy_var = tk.BooleanVar(value=get_proxy_state()[0])

        self._build_header()
        self._build_proxy_frame()
        self._build_cert_frame()
        self._build_api_frame()
        self._build_persona_frame()
        self._build_video_frame()
        self._build_compose_frame()
        self._build_status_frame()
        self._build_log_frame()
        self._build_footer()

        self._sync_from_config()
        self.refresh_status()
        self.refresh_cert_status()
        if not legal_agreed():
            self.root.after(200, self._show_legal_notice)
        self._poll()
        self._poll_cert()

    def _build_header(self):
        hdr = ttk.Frame(self.root, padding=(12, 10))
        hdr.pack(fill="x")
        row = ttk.Frame(hdr)
        row.pack(fill="x")
        tk.Label(row, text=APP_NAME, font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        ttk.Button(row, text="保存全部配置", command=self.save_all_config).pack(side="right")
        tk.Label(hdr, text="拦截 Olivia 来信接口，用第三方 OpenAI 兼容 API 生成回信",
                 fg="#888").pack(anchor="w")

    def _build_proxy_frame(self):
        f = ttk.LabelFrame(self.root, text="代理开关", padding=(10, 8))
        f.pack(fill="x", padx=12, pady=(8, 4))

        row = ttk.Frame(f)
        row.pack(fill="x")
        self.proxy_btn = ttk.Checkbutton(
            row, text="启用系统代理 (127.0.0.1:8080)", variable=self.proxy_var,
            command=self.toggle_proxy)
        self.proxy_btn.pack(side="left")
        self.server_lbl = ttk.Label(row, text="", foreground="#666")
        self.server_lbl.pack(side="left", padx=8)

        btn_row = ttk.Frame(f)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_row, text="启动拦截", command=self.start_proxy).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="停止拦截", command=self.stop_proxy).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="还原系统代理设置", command=self.restore_proxy).pack(side="left")

    def _build_cert_frame(self):
        f = ttk.LabelFrame(self.root, text="CA 证书管理", padding=(10, 8))
        f.pack(fill="x", padx=12, pady=4)
        self.cert_lbl = tk.Label(f, text="正在检查证书...", fg="#666", anchor="w")
        self.cert_lbl.pack(fill="x")
        btn_row = ttk.Frame(f)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="安装 CA 证书", command=self.do_install_cert).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="重新生成 CA 证书", command=self.do_renew_cert).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="删除 CA 证书", command=self.do_uninstall_cert).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="查看声明", command=self.show_legal).pack(side="left")

    def _show_legal_notice(self):
        r = messagebox.askyesno("法律声明", LEGAL_NOTICE, icon="warning")
        if r:
            mark_legal_agreed()
            self._log("已接受法律声明")
        else:
            self._log("未接受法律声明")
            messagebox.showwarning("提示", "您未接受法律声明。本工具应仅用于本人合法合规用途，请谨慎使用。")

    def show_legal(self):
        messagebox.showinfo("法律声明", LEGAL_NOTICE)

    def refresh_cert_status(self):
        info = cert_info()
        if info is None:
            self.cert_lbl.config(
                text="证书: 不存在或无效 (运行时/certs 缺失)，请点击“重新生成 CA 证书”",
                fg="#c0392b")
            return
        installed = cert_is_installed()
        valid = cert_is_valid()
        if not valid:
            self.cert_lbl.config(
                text="证书: 已过期/无效 (%s)，请重新生成并重新安装" % info.get("not_after", ""),
                fg="#c0392b")
        elif installed:
            self.cert_lbl.config(
                text="证书: 有效且已安装 (CN=%s, 到期 %s)" % (info.get("cn"), info.get("not_after")),
                fg="#2a7f2a")
        else:
            self.cert_lbl.config(
                text="证书: 有效但未安装 (CN=%s, 到期 %s)，请点击“安装 CA 证书”" % (info.get("cn"), info.get("not_after")),
                fg="#b9770e")

    def do_install_cert(self):
        if not cert_is_valid():
            if not messagebox.askyesno("证书无效", "检测到证书文件不存在或已过期。是否重新生成后再安装？", icon="warning"):
                self._log("用户取消安装证书")
                return
            ok, msg = renew_cert()
            self._log(msg)
            if not ok:
                messagebox.showerror("重新生成证书", msg)
                self.refresh_cert_status()
                return
        if not messagebox.askyesno("安装 CA 证书", CERT_INSTALL_NOTICE, icon="warning"):
            self._log("用户取消安装证书")
            return
        self._log("正在安装 CA 证书...")
        ok, msg = install_cert()
        self._log(msg)
        messagebox.showinfo("安装证书", msg)
        self.refresh_cert_status()

    def do_renew_cert(self):
        if not messagebox.askyesno("重新生成 CA 证书", CERT_RENEW_NOTICE, icon="warning"):
            self._log("用户取消重新生成证书")
            return
        self._log("正在重新生成 CA 证书...")
        ok, msg = renew_cert()
        self._log(msg)
        messagebox.showinfo("重新生成证书", msg)
        self.refresh_cert_status()

    def do_uninstall_cert(self):
        if not messagebox.askyesno(
            "删除 CA 证书",
            "将从系统“受信任的根证书颁发机构”存储中删除本工具的 mitmproxy 根证书。\n\n"
            "删除后，本工具经代理转发的 HTTPS 连接将不再被系统信任，"
            "如需恢复请点击“安装 CA 证书”。\n\n确定删除吗？",
            icon="warning"):
            self._log("用户取消删除证书")
            return
        self._log("正在删除 CA 证书...")
        ok, msg = uninstall_cert()
        self._log(msg)
        messagebox.showinfo("删除证书", msg)
        self.refresh_cert_status()

    def _build_api_frame(self):
        f = ttk.LabelFrame(self.root, text="OpenAI 兼容 API 配置", padding=(10, 8))
        f.pack(fill="x", padx=12, pady=4)

        tk.Label(f, text="Base URL").grid(row=0, column=0, sticky="w")
        self.base_url = ttk.Entry(f, width=50)
        self.base_url.grid(row=0, column=1, padx=(8, 0), pady=2)

        tk.Label(f, text="API Key").grid(row=1, column=0, sticky="w")
        self.api_key = ttk.Entry(f, width=50)
        self.api_key.grid(row=1, column=1, padx=(8, 0), pady=2)

        tk.Label(f, text="Model").grid(row=2, column=0, sticky="w")
        self.model = ttk.Entry(f, width=50)
        self.model.grid(row=2, column=1, padx=(8, 0), pady=2)

        tk.Label(f, text="Temperature").grid(row=3, column=0, sticky="w")
        self.temperature = ttk.Entry(f, width=12)
        self.temperature.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=2)

        tk.Label(f, text="回复延迟(秒)").grid(row=4, column=0, sticky="w")
        self.delay = ttk.Entry(f, width=12)
        self.delay.grid(row=4, column=1, sticky="w", padx=(8, 0), pady=2)

        tk.Label(f, text="每日信件上限").grid(row=5, column=0, sticky="w")
        self.max_daily = ttk.Entry(f, width=12)
        self.max_daily.grid(row=5, column=1, sticky="w", padx=(8, 0), pady=2)

        ttk.Button(f, text="保存配置", command=self.save_config).grid(row=6, column=1, sticky="w", pady=(6, 0))
        ttk.Button(f, text="编辑 config.json", command=self.edit_config).grid(row=6, column=0, sticky="w", pady=(6, 0))

    def _build_persona_frame(self):
        f = ttk.LabelFrame(self.root, text="人设 Prompt（林离的回信口吻）", padding=(10, 8))
        f.pack(fill="x", padx=12, pady=4)
        self.persona = scrolledtext.ScrolledText(f, height=4, wrap="word")
        self.persona.pack(fill="x")
        ttk.Button(f, text="保存人设", command=self.save_persona).pack(anchor="e", pady=(4, 0))

    def _build_video_frame(self):
        f = ttk.LabelFrame(self.root, text="视频/语音回信（约 30% 概率附带林离的视频回复）", padding=(10, 8))
        f.pack(fill="x", padx=12, pady=4)

        self.video_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="启用视频回信", variable=self.video_enabled).grid(row=0, column=0, sticky="w")
        tk.Label(f, text="视频触发概率").grid(row=0, column=2, sticky="e")
        self.video_prob = ttk.Entry(f, width=8)
        self.video_prob.grid(row=0, column=3, sticky="w", padx=(4, 0))
        self.tts_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="启用语音(读信)", variable=self.tts_enabled).grid(row=0, column=4, sticky="w", padx=(10, 0))

        tk.Label(f, text="视频 Provider").grid(row=1, column=0, sticky="w")
        self.video_provider = ttk.Combobox(f, values=VIDEO_PROVIDERS, width=18, state="readonly")
        self.video_provider.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=2)
        self.video_provider.bind("<<ComboboxSelected>>", self._on_video_provider_change)

        tk.Label(f, text="视频 API Key").grid(row=2, column=0, sticky="w")
        self.video_key = ttk.Entry(f, width=42, show="*")
        self.video_key.grid(row=2, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=2)

        tk.Label(f, text="视频 Base URL").grid(row=3, column=0, sticky="w")
        self.video_base = ttk.Entry(f, width=42)
        self.video_base.grid(row=3, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=2)

        tk.Label(f, text="视频 Model").grid(row=4, column=0, sticky="w")
        self.video_model = ttk.Entry(f, width=42)
        self.video_model.grid(row=4, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=2)

        tk.Label(f, text="语音 Provider").grid(row=5, column=0, sticky="w")
        self.tts_provider = ttk.Combobox(f, values=TTS_PROVIDERS, width=18, state="readonly")
        self.tts_provider.grid(row=5, column=1, sticky="w", padx=(8, 0), pady=2)
        self.tts_provider.bind("<<ComboboxSelected>>", self._on_tts_provider_change)

        tk.Label(f, text="语音 API Key").grid(row=6, column=0, sticky="w")
        self.tts_key = ttk.Entry(f, width=42, show="*")
        self.tts_key.grid(row=6, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=2)

        tk.Label(f, text="语音 Base URL").grid(row=7, column=0, sticky="w")
        self.tts_base = ttk.Entry(f, width=42)
        self.tts_base.grid(row=7, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=2)

        tk.Label(f, text="语音 Model").grid(row=8, column=0, sticky="w")
        self.tts_model = ttk.Entry(f, width=30)
        self.tts_model.grid(row=8, column=1, sticky="w", padx=(8, 0), pady=2)
        tk.Label(f, text="音色 Voice").grid(row=8, column=2, sticky="e")
        self.tts_voice = ttk.Entry(f, width=22)
        self.tts_voice.grid(row=8, column=3, sticky="w", padx=(4, 0), pady=2)

        tk.Label(f, text="火山 App ID").grid(row=9, column=0, sticky="w")
        self.tts_app_id = ttk.Entry(f, width=30)
        self.tts_app_id.grid(row=9, column=1, sticky="w", padx=(8, 0), pady=2)
        tk.Label(f, text="Access Token").grid(row=9, column=2, sticky="e")
        self.tts_access = ttk.Entry(f, width=22, show="*")
        self.tts_access.grid(row=9, column=3, sticky="w", padx=(4, 0), pady=2)

        tk.Label(f, text=MODEL_HINTS, fg="#666", justify="left", anchor="w", font=("Microsoft YaHei UI", 8)).grid(
            row=10, column=0, columnspan=5, sticky="w", pady=(4, 0))
        ttk.Button(f, text="保存视频/语音配置", command=self.save_video_config).grid(
            row=11, column=0, columnspan=5, sticky="w", pady=(6, 0))

    def _on_video_provider_change(self, _evt=None):
        p = self.video_provider.get()
        if p in VIDEO_DEFAULT_BASE:
            self.video_base.delete(0, "end")
            self.video_base.insert(0, VIDEO_DEFAULT_BASE[p])
        if p in VIDEO_DEFAULT_MODEL:
            self.video_model.delete(0, "end")
            self.video_model.insert(0, VIDEO_DEFAULT_MODEL[p])

    def _on_tts_provider_change(self, _evt=None):
        p = self.tts_provider.get()
        if p in TTS_DEFAULT_BASE:
            self.tts_base.delete(0, "end")
            self.tts_base.insert(0, TTS_DEFAULT_BASE[p])
        if p in TTS_DEFAULT_MODEL:
            self.tts_model.delete(0, "end")
            self.tts_model.insert(0, TTS_DEFAULT_MODEL[p])
        if p in TTS_DEFAULT_VOICE:
            self.tts_voice.delete(0, "end")
            self.tts_voice.insert(0, TTS_DEFAULT_VOICE[p])

    def _build_status_frame(self):
        f = ttk.LabelFrame(self.root, text="运行状态", padding=(10, 8))
        f.pack(fill="x", padx=12, pady=4)
        self.status_lbl = tk.Label(f, text="未启动", fg="#666", anchor="w")
        self.status_lbl.pack(fill="x")
        self.letters_lbl = tk.Label(f, text="信件数: -", anchor="w")
        self.letters_lbl.pack(fill="x")

    def _build_log_frame(self):
        f = ttk.LabelFrame(self.root, text="日志", padding=(10, 8))
        f.pack(fill="both", expand=True, padx=12, pady=4)
        self.log = scrolledtext.ScrolledText(f, height=8, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)

    def _build_footer(self):
        foot = ttk.Frame(self.root, padding=(12, 8))
        foot.pack(fill="x")
        tk.Label(foot, text="仅在本机生效 · 停止拦截并还原代理后不影响其他网络访问",
                 fg="#999", font=("Microsoft YaHei UI", 8)).pack(side="left")
        ttk.Button(foot, text="退出", command=self.on_close).pack(side="right")

    def _unwrap(self, r):
        if isinstance(r, dict) and "code" in r and "data" in r:
            return r["data"]
        return r

    def _proxy_post(self, path, payload):
        url = "http://%s%s" % (PROXY_ADDR, path)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _proxy_get(self, path):
        url = "http://%s%s" % (PROXY_ADDR, path)
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _build_compose_frame(self):
        f = ttk.LabelFrame(self.root, text="写信（直连本地代理发送，无需手机 App）", padding=(10, 8))
        f.pack(fill="x", padx=12, pady=4)
        self.compose_text = scrolledtext.ScrolledText(f, height=4, wrap="word")
        self.compose_text.pack(fill="x")
        btn_row = ttk.Frame(f)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="发送信件", command=self._send_letter).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="查看最近回信", command=self._show_last_reply).pack(side="left")
        self.compose_status = tk.Label(f, text="", fg="#666", anchor="w")
        self.compose_status.pack(fill="x", pady=(2, 0))
        self.reply_text = scrolledtext.ScrolledText(f, height=5, state="disabled", wrap="word")
        self.reply_text.pack(fill="x", pady=(2, 0))

    def _send_letter(self):
        content = self.compose_text.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("写信", "请先输入信件内容")
            return
        self.compose_status.config(text="正在发送...", fg="#b9770e")
        self.root.update_idletasks()

        def work():
            try:
                raw = self._proxy_post("/toy/letter/send", {"content": content, "material": {"stampId": "s1"}})
                body = self._unwrap(raw)
                letter_id = body.get("letterId")
                if not letter_id:
                    msg = raw.get("message") if isinstance(raw, dict) else ""
                    tip = msg or json.dumps(raw, ensure_ascii=False)
                    self.root.after(0, lambda: self.compose_status.config(
                        text="发送失败: %s" % tip, fg="#c0392b"))
                    return
                self.root.after(0, lambda: self.compose_status.config(
                    text="已发送 (letterId=%s)，等待林离回信..." % letter_id, fg="#2a7f2a"))
                self._poll_reply(letter_id)
            except urllib.error.HTTPError as e:
                try:
                    err = e.read().decode("utf-8", "replace")
                except Exception:
                    err = str(e)
                self.root.after(0, lambda: self.compose_status.config(
                    text="发送失败(HTTP %s): %s" % (e.code, err), fg="#c0392b"))
            except Exception as e:
                self.root.after(0, lambda: self.compose_status.config(
                    text="发送失败: %s（代理是否已启动？）" % e, fg="#c0392b"))

        threading.Thread(target=work, daemon=True).start()

    def _poll_reply(self, letter_id):
        def work():
            deadline = time.time() + 240
            while time.time() < deadline:
                try:
                    raw = self._proxy_get("/toy/letter/detail?letterId=%s" % letter_id)
                    body = self._unwrap(raw)
                except Exception:
                    time.sleep(3)
                    continue
                reply = body.get("replyText")
                status = body.get("letterStatus")
                if reply:
                    self.root.after(0, lambda: self._set_reply("林离回信：\n" + reply, "#2a7f2a"))
                    return
                if status == 5:  # LETTER_STATUS_FAILED
                    self.root.after(0, lambda: self._set_reply(
                        "回信生成失败：请检查 OpenAI API Key 是否已配置且有效。", "#c0392b"))
                    return
                time.sleep(3)
            self.root.after(0, lambda: self._set_reply(
                "等待回信超时（仍在生成中，可点“查看最近回信”刷新）", "#b9770e"))

        threading.Thread(target=work, daemon=True).start()

    def _set_reply(self, text, color):
        self.reply_text.configure(state="normal")
        self.reply_text.delete("1.0", "end")
        self.reply_text.insert("1.0", text)
        self.reply_text.configure(state="disabled", fg=color)

    def _show_last_reply(self):
        letters = load_letters_detail()
        if not letters:
            self._set_reply("（暂无信件）", "#666")
            return
        items = sorted(letters.values(), key=lambda x: x.get("created_at", 0), reverse=True)
        last = items[0]
        out = "【你的信】\n%s\n\n" % last.get("content", "")
        if last.get("reply_text"):
            out += "【林离回信】\n" + last["reply_text"]
        else:
            out += "【状态】%s（尚未回信）" % last.get("status", "")
        self._set_reply(out, "#2a7f2a" if last.get("reply_text") else "#b9770e")

    def _sync_from_config(self):
        oa = self.cfg.data.get("openai", {})
        pe = self.cfg.data.get("persona", {})
        rp = self.cfg.data.get("reply", {})
        vd = self.cfg.data.get("video", {})
        tt = self.cfg.data.get("tts", {})
        self.base_url.delete(0, "end")
        self.base_url.insert(0, oa.get("base_url", ""))
        self.api_key.delete(0, "end")
        self.api_key.insert(0, oa.get("api_key", ""))
        self.model.delete(0, "end")
        self.model.insert(0, oa.get("model", ""))
        self.temperature.delete(0, "end")
        self.temperature.insert(0, str(oa.get("temperature", "")))
        self.delay.delete(0, "end")
        self.delay.insert(0, str(pe.get("reply_delay_seconds", "")))
        self.max_daily.delete(0, "end")
        self.max_daily.insert(0, str(pe.get("max_daily_letters", "")))
        self.persona.delete("1.0", "end")
        self.persona.insert("1.0", pe.get("system_prompt", ""))

        self.video_enabled.set(bool(rp.get("video_enabled", True)))
        self.tts_enabled.set(bool(rp.get("tts_enabled", True)))
        self.video_prob.delete(0, "end")
        self.video_prob.insert(0, str(rp.get("video_probability", 0.3)))
        vp = vd.get("provider", "minimax")
        if vp not in VIDEO_PROVIDERS:
            vp = "minimax"
        self.video_provider.set(vp)
        self.video_key.delete(0, "end")
        self.video_key.insert(0, vd.get("api_key", ""))
        self.video_base.delete(0, "end")
        self.video_base.insert(0, vd.get("base_url", VIDEO_DEFAULT_BASE.get(vp, "")))
        self.video_model.delete(0, "end")
        self.video_model.insert(0, vd.get("model", VIDEO_DEFAULT_MODEL.get(vp, "")))
        tp = tt.get("provider", "minimax")
        if tp not in TTS_PROVIDERS:
            tp = "minimax"
        self.tts_provider.set(tp)
        self.tts_key.delete(0, "end")
        self.tts_key.insert(0, tt.get("api_key", ""))
        self.tts_base.delete(0, "end")
        self.tts_base.insert(0, tt.get("base_url", TTS_DEFAULT_BASE.get(tp, "")))
        self.tts_model.delete(0, "end")
        self.tts_model.insert(0, tt.get("model", TTS_DEFAULT_MODEL.get(tp, "")))
        self.tts_voice.delete(0, "end")
        self.tts_voice.insert(0, tt.get("voice", TTS_DEFAULT_VOICE.get(tp, "")))
        self.tts_app_id.delete(0, "end")
        self.tts_app_id.insert(0, tt.get("app_id", ""))
        self.tts_access.delete(0, "end")
        self.tts_access.insert(0, tt.get("access_token", ""))

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", "[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
        self.log.see("end")
        self.log.configure(state="disabled")

    def _collect_api(self):
        try:
            temperature = float(self.temperature.get() or 0.9)
        except ValueError:
            temperature = 0.9
        try:
            delay = int(self.delay.get() or 20)
        except ValueError:
            delay = 20
        try:
            max_daily = int(self.max_daily.get() or 3)
        except ValueError:
            max_daily = 3
        return {
            "openai": {
                "base_url": self.base_url.get().strip(),
                "api_key": self.api_key.get().strip(),
                "model": self.model.get().strip(),
                "temperature": temperature,
                "max_tokens": self.cfg.data.get("openai", {}).get("max_tokens", 500),
            },
            "persona": {
                "system_prompt": self.persona.get("1.0", "end").strip(),
                "reply_delay_seconds": delay,
                "max_daily_letters": max_daily,
            },
        }

    def save_config(self):
        d = self._collect_api()
        merged = dict(self.cfg.data)
        merged["openai"] = d["openai"]
        merged["persona"] = d["persona"]
        self.cfg.data = merged
        self.cfg.save()
        self._log("配置已保存")
        messagebox.showinfo("保存", "配置已保存")

    def _collect_video(self):
        try:
            prob = float(self.video_prob.get() or 0.3)
            prob = max(0.0, min(1.0, prob))
        except ValueError:
            prob = 0.3
        old_video = self.cfg.data.get("video", {})
        old_tts = self.cfg.data.get("tts", {})
        video = {
            "provider": self.video_provider.get() or "minimax",
            "api_key": self.video_key.get().strip(),
            "base_url": self.video_base.get().strip(),
            "model": self.video_model.get().strip(),
            "timeout": old_video.get("timeout", 600),
        }
        tts = {
            "provider": self.tts_provider.get() or "minimax",
            "api_key": self.tts_key.get().strip(),
            "base_url": self.tts_base.get().strip(),
            "model": self.tts_model.get().strip(),
            "voice": self.tts_voice.get().strip(),
            "app_id": self.tts_app_id.get().strip(),
            "access_token": self.tts_access.get().strip(),
        }
        # 保留 GUI 未编辑的扩展字段（1.2.7+：fallback_provider/providers，以及 resolution/duration/ratio/watermark）
        for k in ("fallback_provider", "providers", "resolution", "duration", "ratio", "watermark"):
            if k in old_video and k not in video:
                video[k] = old_video[k]
        for k in ("fallback_provider", "providers"):
            if k in old_tts and k not in tts:
                tts[k] = old_tts[k]
        return {
            "reply": {
                "video_enabled": bool(self.video_enabled.get()),
                "tts_enabled": bool(self.tts_enabled.get()),
                "video_probability": prob,
            },
            "video": video,
            "tts": tts,
        }

    def save_all_config(self):
        merged = dict(self.cfg.data)
        d = self._collect_api()
        v = self._collect_video()
        merged["openai"] = d["openai"]
        merged["persona"] = d["persona"]
        merged["reply"] = v["reply"]
        merged["video"] = v["video"]
        merged["tts"] = v["tts"]
        self.cfg.data = merged
        self.cfg.save()
        self._log("全部配置已保存")
        messagebox.showinfo("保存", "全部配置已保存（OpenAI / 人设 / 视频 / 语音）")

    def save_video_config(self):
        merged = dict(self.cfg.data)
        v = self._collect_video()
        merged["reply"] = v["reply"]
        merged["video"] = v["video"]
        merged["tts"] = v["tts"]
        self.cfg.data = merged
        self.cfg.save()
        self._log("视频/语音配置已保存")
        messagebox.showinfo("保存", "视频/语音配置已保存")

    def save_persona(self):
        self.save_config()

    def edit_config(self):
        try:
            webbrowser.open(CONFIG_PATH)
        except Exception:
            if os.path.exists(CONFIG_PATH):
                os.startfile(CONFIG_PATH)

    def toggle_proxy(self):
        if self.proxy_var.get():
            if not self._port_listening():
                self._log("拦截未运行，先启动拦截再启用代理")
                self.start_proxy()
                self.refresh_proxy_state()
                return
            set_proxy(True)
            self._log("系统代理已启用 -> %s" % PROXY_ADDR)
        else:
            if self._port_listening():
                self._log("拦截仍在运行，请先点击“停止拦截”再关闭代理")
                self.proxy_var.set(True)
                messagebox.showwarning("提示", "拦截仍在运行，请先点击“停止拦截”")
                return
            set_proxy(False)
            self._log("系统代理已关闭")
        self.refresh_proxy_state()

    def restore_proxy(self):
        if restore_backup():
            self._log("已还原原始系统代理设置")
            self.proxy_var.set(get_proxy_state()[0])
            messagebox.showinfo("还原", "已还原原始系统代理设置")
        else:
            messagebox.showerror("还原", "未找到备份 (proxy_backup.txt)")

    def start_proxy(self):
        if self._port_listening():
            self._log("端口 %s 已有拦截在监听" % LISTEN_PORT)
            if not self.proxy_var.get():
                set_proxy(True)
                self.proxy_var.set(True)
                self._log("系统代理已启用 -> %s" % PROXY_ADDR)
            return
        if not os.path.exists(MITMDUMP) and not os.path.exists(PYTHON):
            self._log("未找到运行时 (runtime/)，请先安装运行时")
            messagebox.showerror("运行时缺失", "未找到 runtime/python.exe，请重装或补充运行时")
            return
        if not os.path.exists(ADDON_PATH):
            self._log("未找到拦截脚本 olivia_letter_proxy.py")
            return
        if not self.proxy_var.get():
            set_proxy(True)
            self.proxy_var.set(True)
            self._log("系统代理已启用 -> %s" % PROXY_ADDR)
        cmd = mitmdump_cmd()
        self._log("启动: %s" % " ".join(cmd))
        try:
            self.proc = subprocess.Popen(
                cmd,
                cwd=BASE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            self._log("启动失败: %s" % e)
            messagebox.showerror("启动失败", str(e))
            return
        threading.Thread(target=self._drain, args=(self.proc,), daemon=True).start()
        self._log("拦截已启动 (端口 8080)")

    def stop_proxy(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
            self._log("拦截已停止")
        elif self._port_listening():
            # 外部启动的拦截进程：提示用户手动停止
            self._log("检测到外部拦截进程占用了端口 %s，请手动停止" % LISTEN_PORT)
            messagebox.showinfo("提示",
                "端口 %s 有外部拦截进程在监听（非本程序启动）。\n"
                "请手动停止该进程后再操作，或直接使用本程序重新启动拦截。" % LISTEN_PORT)
        else:
            self._log("拦截未在运行")
        # 停止拦截后同步关闭系统代理，避免空代理断网
        set_proxy(False)
        self.proxy_var.set(False)
        self._log("系统代理已关闭")
        self.refresh_status()

    def _drain(self, proc):
        for line in iter(proc.stdout.readline, b""):
            try:
                text = line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                text = str(line)
            try:
                self.root.after(0, self._log, text)
            except (RuntimeError, tk.TclError):
                # 窗口已销毁（用户关闭 GUI），后台线程不能再回调，直接停止读取
                return

    def refresh_proxy_state(self):
        enabled, server = get_proxy_state()
        self.proxy_var.set(enabled)
        if enabled and server == PROXY_ADDR:
            self.server_lbl.config(text="(已启用)", foreground="#2a7f2a")
        elif enabled:
            self.server_lbl.config(text="(已启用，但指向 %s)" % server, foreground="#b9770e")
        else:
            self.server_lbl.config(text="(未启用)", foreground="#666")

    def refresh_status(self):
        # 以实际监听状态为准：8080 有进程监听即视为拦截运行中
        port_running = self._port_listening()
        enabled, server = get_proxy_state()
        proxy_ok = enabled and server == PROXY_ADDR
        letters = count_letters()
        if port_running and proxy_ok:
            self.status_lbl.config(text="● 拦截运行中 (端口 %s)" % LISTEN_PORT, fg="#2a7f2a")
        elif port_running:
            self.status_lbl.config(
                text="● 端口 %s 有监听，但系统代理未指向 %s，拦截未生效" % (LISTEN_PORT, PROXY_ADDR),
                fg="#b9770e")
        else:
            self.status_lbl.config(text="○ 拦截未运行", fg="#888")
        self.letters_lbl.config(text="已收录信件: %d 封" % letters)

    def _port_listening(self):
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            r = s.connect_ex(("127.0.0.1", int(LISTEN_PORT)))
            s.close()
            return r == 0
        except Exception:
            return False

    def _poll(self):
        try:
            self.refresh_proxy_state()
            self.refresh_status()
        except Exception:
            pass
        self.root.after(2000, self._poll)

    def _poll_cert(self):
        try:
            self.refresh_cert_status()
        except Exception:
            pass
        self.root.after(8000, self._poll_cert)

    def on_close(self):
        if self._port_listening():
            if messagebox.askyesno("退出", "拦截仍在运行，退出程序将同时停止拦截。是否继续？"):
                self.stop_proxy()
                self.root.destroy()
            return
        # 拦截未运行但系统代理仍指向本工具时，退出前还原
        enabled, server = get_proxy_state()
        if enabled and server == PROXY_ADDR:
            set_proxy(False)
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    OliviaGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()