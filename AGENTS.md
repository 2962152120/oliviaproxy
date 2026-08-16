# Olivia 来信拦截助手 — 项目记忆

## 项目目标
在 BSide Olivia（米哈游 林离 客户端）官方服务器下线（2026-08-27 停服）后，让"写信"功能继续可用：
- 用 mitmproxy 本地拦截 `/toy/letter/*` 接口，返回模拟信件数据
- 用 OpenAI 兼容 API（DeepSeek）生成回信
- 打包成 Windows 安装包 + 便携版交付

## 关键状态（截至 2026-08-16，版本 1.2.2）
- **保存全部配置按钮（1.2.2 新增）**：GUI 顶部新增"保存全部配置"按钮（`save_all_config`），一键保存 openai/persona/reply/video/tts 全部字段；重构出 `_collect_video()` 供 `save_all_config` 与 `save_video_config` 复用
- **配置热加载（1.2.1 修复）**：addon 原来只在模块加载时读一次 config.json，GUI 保存后运行中的拦截进程不生效（"视频/TTS 没保存"）。现改为 `reload_config()` 基于 **config.json 的 mtime 变化**才重读（幂等、零开销），并在 `call_openai`/`generate_reply`/`gen_video`/`tts_synthesize`/`compress_memory`/`is_letter_flow` 入口调用——GUI 保存后**无需重启拦截**即生效
- **视频/语音回信（1.2.0 新增）**：写信后按 `reply.video_probability`（默认 0.3）概率触发视频回信
  - App 原生支持：`replyType` 枚举 `NONE=0/TEXT=1/SPEECH=2/MIX_PLAY=3/MIX_SVS=4`，非 TEXT 时前端渲染 `<video>`（`src=replyVideoUrl`，16:9），视频**单独交付**。本项目用 **MIX_PLAY=3**（视频+语音）
  - addon 流程：文本回复保存后，`if VIDEO_ENABLED and random.random() < VIDEO_PROBABILITY` 启动后台线程 → `gen_video()`（视频生成）→ `tts_synthesize()`（语音合成）→ `merge_audio_into_video()`（ffmpeg 混流）→ 存 `videos/<letter_id>.mp4` → letter 设 `reply_type=3` + `reply_video_url`；失败记 `video_fail`
  - 本地视频服务：`http.server` 线程监听 `127.0.0.1:8765`（VIDEO_PORT），惰性启动（首次触发时），幂等（模块级 `_video_server_ref` 防重复），serve `BASE_DIR/videos`
  - letter 映射：`letter_to_detail`/`letter_to_list_item` 读 `reply_type`，有 `reply_video_url` 时输出 `replyVideoUrl`（list/detail 均含）
  - **视频 Provider 三家**（均异步 创建→轮询→下载）：OpenAI `POST {base}/videos`（sora-2/sora-2-pro，**2026-09-24 停服**）；MiniMax `POST {base}/video_generation`（MiniMax-Hailuo-2.3/T2V-01-Director/T2V-01）；火山方舟 `POST {base}/contents/generations/tasks`（doubao-seedance-1-5-pro-251215 等）。config.json `video` 段：provider/api_key/base_url/model/timeout(600)
  - **TTS 三家**（同步）：OpenAI `POST /v1/audio/speech`（gpt-4o-mini-tts/tts-1/tts-1-hd）；MiniMax `POST /v1/t2a_v2`（speech-2.6-hd 等，返回 base64 `audio_file`）；火山 **openspeech.bytedance.com**（用 AppID+AccessToken，非方舟 key，`Authorization: Bearer; {token}`，seed-tts-1.0/2.0，音色 zh_female_vv_uranus_bigtts）。config.json `tts` 段：provider/api_key/base_url/model/voice/app_id/access_token
  - **注意火山 TTS base_url 是完整 URL 直接使用**（不拼接 `/tts`）；GUI 的 MODEL_HINTS 已列出各家支持模型/音色提示
  - **ffmpeg**：imageio-ffmpeg 0.6.0 提供二进制（已装便携版 runtime 和 release runtime，需镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`，pypi.org 直连超时）；混流命令 `-c:v copy -c:a aac -map 0:v:0 -map 1:a:0 -shortest -movflags +faststart`
  - **GUI 视频配置界面**：视频/语音开关、触发概率、三家 provider 下拉（切换自动填默认 base_url/model/voice）、api_key/base_url/model/voice、火山 TTS 专属 app_id/access_token、MODEL_HINTS 提示；保存写 `reply`/`video`/`tts` 三段；窗口 580x960
- **核心功能已全部打通并验证**：App 登录成功、进入主界面、写信/重发/每日上限均正常
- 登录方案：`/signIn` 等接口在 addon 中 mock 返回 `{"code":0,"message":"","data":{}}`；mitmproxy 根证书需安装到系统（本机已装，用户级+机器级）
- letter 拦截：addon 拦截 `/toy/letter/*`（list/detail/send/resend/unread_count/share），返回模拟数据，AI 回信走 `generate_reply` 后台线程
- **记忆系统（1.0.8 新增）**：AI 记住自己说过的话 + 用户说过的话，持久化到 `memory.json`
  - `remember(role, content)`：写入历史，超 `max_entries` 后最老的进 `overflow`
  - 每次回复成功后调 `compress_memory()`：把 overflow + 旧摘要用 AI 压缩成一条新摘要（进 `compressed`），失败则恢复 overflow 不丢记忆
  - 回信时 `build_memory_messages()` 把 compressed + history 注入 OpenAI messages（compressed 为 system 角色、history 保留原角色）
  - 配置在 config.json `memory.max_entries`(默认30) / `max_chars`(默认3000)
- **dispatch enc_conf（1.1.0 修复）**：App 启动会请求 `dispatcher.olivia.miyoushe.com` 拉取配置，addon mock 返回的 `enc_conf` 需为真实值（App 解密用，空字符串会导致 App 弹 error "Failed to decrypt enc_conf"）。真实 enc_conf 存于 config.json `dispatch.enc_conf`（从 Olivia.log 的 "Dispatch response" 行提取）。若停服后 App 无法启动，更新该值为新的真实配置即可
- **删除 CA 证书按钮（GUI 新增）**：GUI 证书管理区新增"删除 CA 证书"按钮（`do_uninstall_cert` → `uninstall_cert`），用 `certutil -user -delstore Root mitmproxy` 从用户信任存储删除，无需管理员

## 交付物（桌面 `D:\Users\ASUS\Desktop\Oliviaproxy\`）
- `OliviaProxy-Setup-1.2.2.exe`：安装包（Inno Setup）
- `便携版.zip` + `便携版\OliviaProxy\`：免安装版
- `源码\`：分发给用户的源码（config.json 是占位符 key 模板）

## 开发目录
- `D:\OliviaProxy\gui\olivia_gui.py`：GUI 主程序源码
- `D:\OliviaProxy\gui\olivia_letter_proxy.py`：拦截 addon（源码主版，改这里）
- `D:\OliviaProxy\release\OliviaProxy\`：安装包打包源（从便携版同步）
- `D:\OliviaProxy\build\`：构建产物/installer.iss
- `D:\Users\ASUS\Desktop\Oliviaproxy\源码\installer.iss`：安装脚本（版本号在此）

## 修改文件后必须同步的四处
1. `D:\OliviaProxy\gui\olivia_letter_proxy.py`（addon 主版）
2. `D:\Users\ASUS\Desktop\Oliviaproxy\便携版\OliviaProxy\olivia_letter_proxy.py`
3. `D:\Users\ASUS\Desktop\Oliviaproxy\源码\olivia_letter_proxy.py`
4. 安装包打包源 `D:\OliviaProxy\release\OliviaProxy\olivia_letter_proxy.py`
（GUI 改动同理同步 olivia_gui.py，并重打包 exe）

## 打包命令
- GUI exe：`D:\Program\python.exe -m PyInstaller --noconfirm --onefile --windowed --name OliviaGUI --icon "D:\OliviaProxy\build\icon.ico" "D:\OliviaProxy\gui\olivia_gui.py"`（输出在运行目录 dist/，复制到便携版和 release）
- 便携版 zip：用 python zipfile 压缩便携版目录，排除 `debug.log letters.json memory.json proxy_backup.txt legal_agreed.txt __pycache__ videos`（注意：zip 打包被中断会生成损坏文件，需删除重建并加长超时）
- 安装包：`"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "D:\Users\ASUS\Desktop\Oliviaproxy\源码\installer.iss"`
- 安装包版本在 installer.iss：`MyAppVersion` 和 `OutputBaseFilename`（如 1.2.0）；installer.iss 改后同步 build/ 副本

## Git（仓库在 D:\OliviaProxy，git 路径 `D:\Program Files\Git\cmd\git.exe`）
- 跟踪源码 + 构建产物 + 日志；排除 `*.exe`、`letters.json`、`legal_agreed.txt`、`proxy_backup.txt`、`__pycache__`
- 常用：`git status` / `git add -A` / `git commit -m "说明"` / `git log --oneline`

## 证书
- mitmproxy 根证书：`D:\Users\ASUS\Desktop\Oliviaproxy\便携版\OliviaProxy\runtime\certs\mitmproxy-ca-cert.cer`
- 安装：`certutil -user -addstore -f Root <cer>`（用户级）或提权装机器级
- GUI 有自动检测/安装/续期证书逻辑（cert_is_installed/install_cert/renew_cert）

## 登录相关技术要点
- App 是 Steam 版 BSide Olivia（0.0.9.615），Qt + CEF + 米哈游 SDK
- `/signIn` 走 `toy-cnbeta01.olivia.miyoushe.com`，**证书 pinning**（系统栈），必须装 mitm 根证书才能 MITM
- App 本地数据：`C:\Users\ASUS\AppData\Roaming\miHoYo\Olivia-steam\`（logs\Olivia.log 有完整请求记录）
- 代理绕过列表（ProxyOverride 注册表）：dispatcher/otel/pf-tracking/static + 所有 `*.mihoyo.com` 域直连；letter 域（toy-cnbeta01）走代理被拦截
- 注意：`*.miyoushe.com` 通配绕过会连 letter 域也绕过，需按需调整

## 8/27 停服后注意
- 停服后真实服务器可能完全无响应，需确保 addon 的 mock（signIn/letter/dispatch）覆盖所有请求
- 离线版会移除写信 UI，需阻止 App 自动更新（update.googleapis.com 等已在绕过/拦截范围）
- 目前无 OpenAI API key，AI 回信链路（call_openai → DeepSeek）未实际验证过

## config.json 字段
- `openai`: base_url/api_key/model/temperature/max_tokens
- `persona`: system_prompt/reply_delay_seconds/max_daily_letters（每日写信上限，GUI 可改）
- `listener`: host/path_prefix（默认 `/toy/letter/`）
- `reply`（1.2.0）: video_enabled(true)/tts_enabled(true)/video_probability(0.3)
- `video`（1.2.0）: provider(minimax)/api_key/base_url/model(MiniMax-Hailuo-2.3)/timeout(600)
- `tts`（1.2.0）: provider(minimax)/api_key/base_url/model(speech-2.6-hd)/voice(female-tianmei)/app_id/access_token
- config.json 同步 5 份：`D:\OliviaProxy\config.json`、便携版、源码、release、build
