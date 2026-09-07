# Olivia 来信拦截助手

在 BSide Olivia（米哈游「林离」）官方服务器下线后，让「写信」功能继续可用。

## 功能

- **写信/查信** — 本地拦截 `/toy/letter/*` 接口，模拟信件收发
- **AI 回信** — 用 OpenAI 兼容 API（DeepSeek 等）生成林离风格的回信
- **视频/语音回信** — 可选触发视频回信（MiniMax、火山方舟、scnet、通义万相）
- **记忆系统** — AI 记住对话内容，回信更有连贯性
- **GUI 工具** — Tkinter 图形界面，配置编辑、写信面板、证书管理、代理开关
- **安装包 + 便携版** — Windows 一键安装或免安装使用

## 快速开始

### 便携版

1. 下载 `便携版X.X.X.zip`，解压到任意目录
2. 双击 `OliviaGUI.exe` 启动
3. 填入 OpenAI 兼容 API Key（如 DeepSeek）
4. 点击「启动拦截」，然后启动 Olivia 客户端

### 安装包

运行 `OliviaProxy-Setup-X.X.X.exe`，按向导安装后从开始菜单启动。

## 配置

编辑 `config.json`：

```json
{
  "openai": {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "your-api-key",
    "model": "deepseek-chat"
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
  }
}
```

### 视频 Provider

| Provider | 模型示例 | 说明 |
|----------|----------|------|
| minimax | MiniMax-H3 | 默认，异步生成 |
| volc | doubao-seedance-1-5-pro | 火山方舟 |
| scnet | Seedance2.0 / Wan2.7-T2V | scnet 算力平台 |
| dashscope | wan2.7-t2v-2026-06-12 | 通义万相 |

### TTS Provider

| Provider | 模型示例 | 说明 |
|----------|----------|------|
| minimax | speech-2.8-hd | 默认 |
| volc | seed-tts-1.0 | 火山语音，需 app_id + access_token |
| scnet | Qwen3-TTS-Instruct-Flash | scnet 算力平台 |

## 开发

### 环境

- Python 3.13+
- mitmproxy
- PyInstaller 6.22+（打包 exe）
- Inno Setup 6（安装包）

### 运行

```bash
# 启动 mitmproxy + addon
mitmdump --set confdir=runtime/certs -s gui/olivia_letter_proxy.py

# 或直接运行 GUI
python gui/olivia_gui.py
```

### 打包

```bash
# GUI exe
python -m PyInstaller --noconfirm --onefile --windowed --name OliviaGUI \
  --distpath release/OliviaProxy --workpath build/pyi_work gui/olivia_gui.py

# 安装包
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build/installer.iss
```

### 项目结构

```
├── gui/
│   ├── olivia_gui.py           # GUI 主程序
│   ├── olivia_letter_proxy.py  # mitmproxy addon（主版源码）
│   └── config.json             # 配置文件
├── build/
│   ├── installer.iss           # Inno Setup 脚本
│   └── pyi_env/                # PyInstaller 依赖
├── release/OliviaProxy/        # 安装包打包源
├── CHANGELOG.md                # 更新日志
├── HANDOVER.md                 # 交接文档
└── README.md                   # 本文件
```

### 同步规则

修改 addon/GUI 后须同步到四处：

1. `gui/olivia_letter_proxy.py`（主版）
2. 便携版副本
3. 源码副本
4. 安装包副本

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)

## 许可

仅供学习研究使用。
