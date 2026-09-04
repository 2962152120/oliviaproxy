# Olivia 来信拦截助手 — 交接文档

> 版本：1.2.10（含新写信功能，未正式发版）
> 日期：2026-09-04
> Git 仓库：https://github.com/2962152120/oliviaproxy.git

---

## 一、项目目标

在 BSide Olivia（米哈游「林离」客户端）官方服务器下线（2026-08-27 停服）后，让「写信」功能继续可用：

- 用 mitmproxy 本地拦截 `/toy/letter/*` 接口，返回模拟信件数据
- 用 OpenAI 兼容 API（DeepSeek）生成回信
- 支持视频/语音回信（MiniMax、火山方舟、scnet、DashScope 等多家 provider）
- 打包成 Windows 安装包 + 便携版交付

---

## 二、技术架构

```
┌─────────────────────────────────────────────────┐
│  Olivia 客户端 (Qt + CEF/Chromium)               │
│  写信 → POST /toy/letter/send                    │
│  查信 → GET  /toy/letter/detail                  │
│  列表 → GET  /toy/letter/list                    │
└──────────────┬──────────────────────────────────┘
               │  HTTP (127.0.0.1:8080)
               ▼
┌─────────────────────────────────────────────────┐
│  mitmproxy + olivia_letter_proxy.py (addon)     │
│  - 拦截 /toy/letter/* → 模拟数据               │
│  - POST /toy/letter/send → 存信 + 异步 AI 回信  │
│  - GET  /toy/letter/list/detail → 返回信件列表   │
│  - dispatch 拦截 → 返回真实 enc_conf             │
│  - signIn 等接口 mock → code:0                   │
│  - 非 letter 的 /toy/* → 兜底 200               │
└──────────────┬──────────────────────────────────┘
               │  OpenAI 兼容 API (DeepSeek)
               ▼
┌─────────────────────────────────────────────────┐
│  AI 回信 (call_openai)                          │
│  - 注入记忆 (memory.json)                        │
│  - 可选：视频生成 (gen_video) + TTS (tts_synthesize) │
│  - ffmpeg 混流 → videos/<letter_id>.mp4          │
│  - 本地视频服务 127.0.0.1:8765                   │
└─────────────────────────────────────────────────┘
```

---

## 三、核心文件清单

### 源码（主版本）

| 文件 | 说明 |
|------|------|
| `gui/olivia_gui.py` | GUI 主程序（Tkinter），含配置编辑、写信面板、证书管理、代理开关 |
| `gui/olivia_letter_proxy.py` | mitmproxy addon（主版），拦截 + mock + AI 回信 + 视频/TTS |
| `config.json` | 配置文件（openai/persona/reply/video/tts/dispatch） |

### 构建/打包

| 文件 | 说明 |
|------|------|
| `build/OliviaGUI.spec` | PyInstaller 打包配置 |
| `build/pyi_env/` | PyInstaller 依赖环境 |
| `build/installer.iss` | Inno Setup 安装脚本（版本号在此） |
| `release/OliviaProxy/` | 安装包打包源（从便携版同步） |

### 交付物

| 路径 | 说明 |
|------|------|
| `桌面\Oliviaproxy\便携版1.2.2\` | 运行中的便携版副本 |
| `桌面\Oliviaproxy\便携版1.2.11\` | 新版便携版副本 |
| `桌面\Oliviaproxy\源码\` | 分发给用户的源码 |

### 游戏客户端

| 路径 | 说明 |
|------|------|
| `E:\SteamLibrary\...\BSide Olivia Lin Test\0.0.9.627\` | PC 客户端（Qt+CEF，web UI 在 resources/feapp.dat） |

---

## 四、修改文件后必须同步的四处

1. `D:\OliviaProxy\gui\olivia_letter_proxy.py` — addon 主版（改这里）
2. `桌面\Oliviaproxy\便携版\OliviaProxy\olivia_letter_proxy.py` — 运行副本
3. `桌面\Oliviaproxy\源码\olivia_letter_proxy.py` — 分发副本
4. `D:\OliviaProxy\release\OliviaProxy\olivia_letter_proxy.py` — 安装包副本

GUI 改动同理同步 `olivia_gui.py`，并重新打包 exe。

---

## 五、打包命令

### GUI exe
```bash
python -m PyInstaller --noconfirm --onefile --windowed --name OliviaGUI \
  --distpath "D:\OliviaProxy\release\OliviaProxy" \
  --workpath "D:\OliviaProxy\build\pyi_work" \
  "D:\OliviaProxy\gui\olivia_gui.py"
```

### 便携版 zip
```powershell
Compress-Archive -Path "D:\OliviaProxy\release\OliviaProxy\*" \
  -DestinationPath "D:\Users\ASUS\Desktop\Oliviaproxy\便携版X.X.X.zip"
```

### 安装包
```bash
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "D:\OliviaProxy\build\installer.iss"
```
版本号在 `installer.iss` 的 `MyAppVersion` 和 `OutputBaseFilename`。

---

## 六、config.json 关键字段

```json
{
  "openai": {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-xxxx-your-key-here",
    "model": "deepseek-chat",
    "temperature": 0.9,
    "max_tokens": 500
  },
  "persona": {
    "system_prompt": "你叫林离（Olivia Lin）...",
    "reply_delay_seconds": 20,
    "max_daily_letters": 3
  },
  "reply": {
    "video_enabled": true,
    "tts_enabled": true,
    "video_probability": 0.3
  },
  "video": {
    "provider": "minimax",
    "fallback_provider": "",
    "api_key": "",
    "base_url": "https://api.minimaxi.com/v1",
    "model": "MiniMax-H3",
    "timeout": 600
  },
  "tts": {
    "provider": "minimax",
    "api_key": "",
    "base_url": "https://api.minimaxi.com/v1",
    "model": "speech-2.8-hd",
    "voice": "female-tianmei",
    "app_id": "",
    "access_token": ""
  },
  "dispatch": {
    "enc_conf": "<真实加密配置，从Olivia.log提取>"
  }
}
```

支持的视频/TTS provider：`minimax`、`volc`（火山方舟）、`scnet`、`dashscope`（通义万相）、`openai`

---

## 七、关键依赖

- Python 3.13+
- mitmproxy（addon 运行环境）
- PyInstaller 6.22+（打包 GUI exe）
- Inno Setup 6（安装包）
- ffmpeg（视频混流，由 imageio-ffmpeg 提供二进制）

---

## 八、已知问题与注意事项

1. **OpenAI API key 为空** — AI 回信链路（call_openai → DeepSeek）未实际验证过，回信会 401 → FAILED，代理不崩
2. **PC 客户端逆向（方案2）** — 已打补丁 `feapp.dat`（offlineMode=false + toyApiUrl→proxy + demo + 门控 neutralized），但 NutApp.dll 有完整性校验，待用户测试。若失败需还原：`feapp.dat.bak` → `feapp.dat`，撤回 `olivia_letter_proxy.py` 的 benign-200 改动
3. **GUI 写信面板（方案1）** — 已完成并部署，保底可用，不依赖 PC 客户端逆向
4. **config.json 同步 5 份** — 改一处需手动同步其他副本
5. **证书** — mitmproxy 根证书需安装到系统信任存储（`certutil -user -addstore -f Root <cer>`）
6. **dispatch enc_conf** — 真实服务器仍在线，enc_conf 每次请求轮换；若停服后无法获取，需手动更新 `config.json` 的 `dispatch.enc_conf`

---

## 九、Git 信息

- 仓库：`D:\OliviaProxy`
- 远程：`https://github.com/2962152120/oliviaproxy.git`
- 分支：`master`
- 最新 commit：`fe98af6` — feat: GUI写信面板 + 代理letter端点 + 非letter兜底200
- .gitignore 排除：build/、release/、*.log、test_body.json、raw_list.json

---

## 十、版本历史摘要

| 版本 | 日期 | 主要变更 |
|------|------|----------|
| 1.2.10 | 2026-08-28 | 视频轮询改GET、resend防重复记忆、GUI代理先启后切 |
| 1.2.9 | 2026-08-28 | 修复1.2.8语法错误（addon不可用）、GUI保留扩展字段 |
| 1.2.8 | 2026-08-26 | 主链路统一重试包装、删除遗留诊断代码 |
| 1.2.7 | 2026-08-26 | 视频/TTS自动回退、HTTP重试、启动自检 |
| 1.2.6 | 2026-08-26 | DashScope通义万相视频接入 |
| 1.2.5 | 2026-08-25 | dispatch拦截修复 |
| 1.2.4 | 2026-08-24 | scnet算力平台接入 |
| 1.2.3 | 2026-08-23 | MiniMax视频V2修复、TTS请求体修正、UTF-8 BOM兼容 |
| 1.2.2 | 2026-08-22 | 保存全部配置按钮 |
| 1.2.1 | 2026-08-22 | 配置热加载 |
| 1.2.0 | 2026-08-22 | 视频/语音回信 |

---

*文档结束*
