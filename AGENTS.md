# Olivia 来信拦截助手 — 项目记忆

## 项目目标
在 BSide Olivia（米哈游 林离 客户端）官方服务器下线（2026-08-27 停服）后，让"写信"功能继续可用：
- 用 mitmproxy 本地拦截 `/toy/letter/*` 接口，返回模拟信件数据
- 用 OpenAI 兼容 API（DeepSeek）生成回信
- 打包成 Windows 安装包 + 便携版交付

## 关键状态（截至 2026-09-06，版本 1.2.12）
- **1.2.12 修复（2026-09-06，四处均已用 release runtime 跑真实代码验证）**：
  - 回信后置 `unread=True`，修复 `count_unread()` 恒为 0 / App 无未读红点（之前种子信件 2001 的手写 `unread` 掩盖了问题）
  - `send` 增加每日上限后端校验：锁内统计当日已发数，超限返回业务码 `429` + message，HTTP 仍 200（与 400/404 约定一致）；GUI 失败提示优先显示 `message`
  - `remember("user", content)` 移到回信线程 `start()` 之前，消除对 20s `reply_delay_seconds` 的竞态依赖（注意必须留在 `with state["lock"]` **外**，`remember` 内部会再加同一把非重入锁，移入会死锁）
  - GUI `_drain` 的 `root.after` 加 `(RuntimeError, tk.TclError)` 保护，窗口销毁后停止读取（与 1.2.11 修的 `_enable_proxy_when_ready` 同类，那次只补一处）
- **1.2.10 修复（重要）**：
  - 视频轮询误用 POST：OpenAI/火山 Ark 异步任务轮询改 `http_json_get`（GET）；MiniMax V1 轮询设计即 POST，保持不变
  - `resend` 不再重复记记忆（每封只记一次）+ 重发时清 `fail_reason`
  - GUI 代理开关：启用代理前若拦截未运行则先自动启动拦截，避免把系统代理指向死后端导致断网
  - 边缘健壮性：`is_letter_flow` 用 `LISTENER.get("path_prefix", "/toy/letter/")`；视频 HTTP 服务 `allow_reuse_address=True`
- **1.2.9 修复（重要）**：
  - 修复 1.2.8 引入的 addon 语法错误（`tts_openai`/`tts_volc` 改重试时缩进错乱，导致 mitmdump 加载失败、整个拦截不可用）——1.2.8 安装包/便携版不可用，务必用 1.2.9
  - GUI `_collect_video` 保存时保留 `fallback_provider`/`providers`/resolution/duration/ratio/watermark 等未编辑字段（此前整段覆盖会静默清掉 1.2.7 新功能）
  - `resend` 重置 `reply_type`/`reply_video_url`/`video_ready`/`video_fail`/`replied_at`
  - `generate_reply` 防重入 + `_video_in_progress` 加锁（消除 send+resend 重复调 AI、视频重复生成）
- **1.2.8 优化（补全 1.2.6/1.2.7 主链路健壮性）**：
  - 文字回信 `call_openai` 与记忆压缩 `compress_memory` 原先走裸 `urllib.request.urlopen`（网络抖动直接失败），现统一改走 `_urlopen_with_retry`（与视频/TTS 一致）
  - `tts_openai`/`tts_volc` 同样由裸 `urlopen` 改为 `_urlopen_with_retry`
  - 删除 `list` 接口里把整封信件 JSON 持续追加写 `debug.log` 的遗留诊断代码（写盘频繁且落 PII）
  - 瞬时错误判定函数 `_video_is_transient` 改名 `_is_transient`，视频/TTS 回退共用
  - **现状：所有对第三方 API 的 HTTP 请求（文字/TTS/视频/记忆压缩）均经统一重试包装**，仅认证类错误（401 等）立即失败不重试
- **1.2.7 健壮性优化（代码层面）**：
  - 日志规范化：addon 内残留 `print()` 全部改为 `ctx.log.info/warn`（mitmproxy 事件日志，非 TTY 时不刷到 stderr 属正常）
  - HTTP 重试：`http_json_request`/`http_json_get`/`http_download` 统一加重试（默认 3 次，对 408/429/500/502/503/504 与网络抖动退避重试）
  - **视频/TTS 自动回退**：`gen_video`/`tts_synthesize` 支持 `fallback_provider` 配置。主 provider 失败后（命中瞬时错误特征：433/429/quota/10054/timeout/5xx 等）自动切到 fallback provider。每个 provider 可配独立 `providers.<name>` 子块覆盖 base_url/model/api_key（顶层字段作默认）
  - 视频生成并发去重：模块级 `_video_in_progress` 集合防同一 letter 重复生成视频（线程安全，finally 清理）
  - 启动自检：`OliviaLetterProxy.running()` 钩子在代理启动时打印 dispatch enc_conf 是否设置、video/tts 主+fallback provider、各 provider 是否缺 key、video 服务端口与触发概率，缺配置给明确 warn
  - 用法示例（config.json）：`"video": {"provider":"scnet","fallback_provider":"dashscope","providers":{"dashscope":{"api_key":"<真实key>","model":"wan2.7-t2v-2026-06-12"}}}`
- **千问 DashScope（通义万相）视频接入（1.2.6 新增）**：新 provider `dashscope`（别名 `ds`/`wan`），base_url `https://dashscope.aliyuncs.com/api/v1`（北京地域），`POST /services/aigc/video-generation/video-synthesis` + header `X-DashScope-Async: enable` → `output.task_id` → 轮询 `GET /tasks/{task_id}`（GET，15s 间隔）→ SUCCEEDED → `output.video_url` 下载（OSS 直链，无鉴权，24h 有效）。body `{model, input:{prompt}, parameters:{resolution,ratio,duration}}`。模型默认 `wan2.7-t2v-2026-06-12`（另有 wan2.6-t2v / wan2.2-t2v-plus）。addon `gen_video_dashscope()`；GUI `VIDEO_PROVIDERS` 加 `dashscope`（默认 base/model）。**已实测**：wan2.7-t2v 生成 5s/720P MP4 ✅（1280x720/30fps/AAC，App 内视频回信 replyType=3 完整链路通过，letter 2009）
- **dispatch 拦截修复（1.2.5 修复）**：App 报 "failed to get dispatch configuration" 的根因有二：① addon `request()` 未在每次请求时 `reload_config()`，dispatch 分支用旧/空 `DISPATCH_ENC_CONF` → 已修复（`request()` 开头调用 `reload_config()`）；② 手动启动 mitmdump 未传 `--set confdir=<runtime/certs>`，用了 `~/.mitmproxy` 的默认 CA（序列号 `1184c38d`），与系统已信任的 `runtime/certs` CA（序列号 `58f76b63`）不一致 → 所有客户端 TLS 握手失败（"Client TLS handshake failed ... does not trust the proxy's certificate"）。**修复：mitmdump 必须带 `--set confdir=<目录>/runtime/certs` 启动**（GUI 的 `mitmdump_cmd()` 本来就传了，手动启动容易漏）。另将 dispatch 匹配放宽为 host 含 `olivia.miyoushe.com` 且路径含 `dispatch`，或 host 含 `dispatcher`+`olivia`
- **scnet.cn 算力平台接入（1.2.4 新增）**：新 provider `scnet`（视频 + TTS）
  - base_url `https://api.scnet.cn/api/llm/v1`，鉴权 `Authorization: Bearer <API Key>`
  - **视频**（异步统一模式）：`POST /videos/generations` + header `X-MultiModal-Async: true` → `output.task_id` → 轮询 `GET /tasks/{task_id}`（GET）→ succeeded 后 `output.results[0]` 下载（无需鉴权）。body `{model, input:{prompt}, parameters:{resolution,ratio,duration,watermark}}`。模型：Seedance2.0 / Wan2.7-T2V / HappyHorse-1.0-T2V（同一接口，仅 model 不同）
  - **TTS**（同步）：`POST /audios/generations`，body `{model:"Qwen3-TTS-Instruct-Flash", input:{text, voice}}`，直接返回 `output.results[0]` 音频 URL。音色如 Cherry
  - addon：`gen_video_scnet()` / `tts_scnet()`；GUI `VIDEO_PROVIDERS`/`TTS_PROVIDERS` 加 `scnet`，默认 model/video=Seedance2.0、tts=Qwen3-TTS-Instruct-Flash、voice=Cherry
  - **已实测**：TTS ✅（Qwen3-TTS WAV 299KB）；视频 Seedance2.0 ✅（1280x720/5s/24fps）、Wan2.7-T2V ✅（1280x720/5s/30fps）、**HappyHorse-1.0-T2V ✅（2026-08-17 实测，1080p/5s，约 2.5 分钟生成，**注意每日每模型仅限一次**，第二次报 HTTP 433 quota）**
- **MiniMax 视频 V2 接口修复（1.2.3 修复）**：MiniMax 已把视频模型升级为 **MiniMax-H3**，新接口走 V2（`POST /v2/video_generation` 异步创建 → `GET /v2/query/video_generation/{task_id}` 轮询，成功返回 `task.content.url` 直下，无需鉴权）。旧 V1 接口（`/v1/video_generation` + `/v1/files/retrieve`）已废弃会 404
  - addon `gen_video_minimax` 现自动路由：model 含 `minimax-h` 前缀或 `MiniMax-Hailuo-03` → V2；否则 V1 fallback
  - **V2 轮询必须用 GET**（POST 会 404），新增 `http_json_get()`；轮询间隔 10s（文档推荐）；下载 `content.url` 不带 Authorization
  - config.json `video` 段新增 `resolution`(默认768P)/`duration`(默认5)/`ratio`(默认16:9)；默认 model 改为 `MiniMax-H3`
  - GUI `MODEL_HINTS` 与默认 model 已同步（MiniMax-H3 / V2 接口）
- **MiniMax TTS 请求体按官方文档修正（1.2.3）**：改为 `voice_setting:{voice_id,speed,vol,pitch}` + `audio_setting:{sample_rate,bitrate,format,channel}` 结构（旧顶层 `voice_id` 参数可能被废弃）；响应兼容 `data.audio`（hex/base64 自动识别）与 `data.audio_file`；默认 model 改为 `speech-2.8-hd`
- **config.json UTF-8 BOM 兼容（1.2.3 修复）**：addon 与 GUI 读取 config.json 改用 `utf-8-sig`（兼容带 BOM 文件，避免 json 解析失败导致配置全空、接口报 401/404）
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
- **当前版本 1.2.12（2026-09-06）**：`OliviaProxy-Setup-1.2.12.exe`（73.8 MB）+ `便携版1.2.12.zip`（约 86 MB）+ `便携版1.2.12\`
- 便携版目录名**自带版本号，每版一个独立目录**（`便携版1.2.12\`），不是固定 `便携版\`
- `源码\`：分发给用户的源码（config.json 是占位符 key 模板，出包前必查）
- 历史版本遗留：桌面目录堆积了 1.1.0~1.2.11 的旧 Setup exe / zip / 便携版目录，用户尚未决定清理方式

## 开发目录
- `D:\OliviaProxy\gui\olivia_gui.py`：GUI 主程序源码
- `D:\OliviaProxy\gui\olivia_letter_proxy.py`：拦截 addon（源码主版，改这里）
- `D:\OliviaProxy\release\OliviaProxy\`：安装包打包源（从便携版同步）
- `D:\OliviaProxy\build\`：构建产物/installer.iss
- `D:\Users\ASUS\Desktop\Oliviaproxy\源码\installer.iss`：安装脚本（版本号在此）

## 修改文件后必须同步（addon 5 处 / GUI 2 处）
addon `olivia_letter_proxy.py`：
1. `D:\OliviaProxy\gui\`（**源码主版，改这里**）
2. `D:\OliviaProxy\olivia_letter_proxy.py`（开发根目录）
3. `D:\OliviaProxy\release\OliviaProxy\`（安装包打包源）
4. `D:\OliviaProxy\build\`
5. `D:\Users\ASUS\Desktop\Oliviaproxy\源码\`（分发源码）

GUI `olivia_gui.py`：`D:\OliviaProxy\gui\` + `源码\`，且**必须重打包 exe**（exe 内含编译后的字节码，改 py 不生效）。
改完用 `md5sum` 校验各类副本哈希唯一。桌面便携版目录是冻结产物，出新版时整体重建，不逐个同步。

## 打包命令（全部实测可用）
出包顺序：改版本号 → 同步副本 → 打 exe → 建便携版目录 → 打 zip / 编安装包。

1. **版本号**（3 处）：`gui/olivia_gui.py` 的 `APP_VERSION`、`build/installer.iss` 的 `MyAppVersion` 和 `OutputBaseFilename`；iss 改后同步 `源码/installer.iss`
2. **GUI exe**（约 90s，PyInstaller 装在隔离目录避免污染交付 runtime）：
   ```
   cd /d/OliviaProxy && PYTHONPATH='D:\OliviaProxy\build\pyi_env' "D:\OliviaProxy\release\OliviaProxy\runtime\python.exe" -m PyInstaller --noconfirm --onefile --windowed --name OliviaGUI --distpath "D:\OliviaProxy\release\OliviaProxy" --workpath "D:\OliviaProxy\build\pyi_work" "D:\OliviaProxy\gui\olivia_gui.py"
   ```
   打包完根目录可能生成 `OliviaGUI.spec`，删掉（已在 .gitignore）
3. **便携版目录**（约 6 分钟，runtime 大）：`cp -r release/OliviaProxy/. "D:/Users/ASUS/Desktop/Oliviaproxy/便携版<ver>/"`，复制完 md5 校验
4. **便携版 zip**（约 4 分钟）：`runtime\python.exe build\make_zip.py <ver>`（脚本在 `build/make_zip.py`，排除 `__pycache__ videos run_proxy.cmd` 及日志/用户数据文件；中断会产生损坏 zip，需删除重建）
5. **安装包**（约 190s）：`"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "D:\OliviaProxy\build\installer.iss"`（SrcDir=`release\OliviaProxy`），产物 `release\OliviaProxy-Setup-<ver>.exe`，手动复制到桌面

**踩坑记录**：
- 系统 python / 托管 python 都**没有 tkinter**，无法打包；唯一可用的是交付 runtime 里的 `runtime\python.exe`（3.13.15，自带 tkinter 8.6）
- PyInstaller 安装到隔离目录：`runtime\python.exe -m pip install --target "D:\OliviaProxy\build\pyi_env" pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple`（约 10 分钟）
- 出包前**必查** config.json 只有占位符 key（分发包不能带真实密钥）

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
- `video`（1.2.0）: provider(minimax)/api_key/base_url/model(MiniMax-Hailuo-2.3)/timeout(600)；1.2.7 新增 `fallback_provider`（主 provider 瞬时失败自动回退）与 `providers.<name>` 子块（覆盖各 provider 的 base_url/model/api_key，顶层字段作默认）
- `tts`（1.2.0）: provider(minimax)/api_key/base_url/model(speech-2.6-hd)/voice(female-tianmei)/app_id/access_token；1.2.7 同支持 `fallback_provider`/`providers`
- config.json 同步 5 份：`D:\OliviaProxy\config.json`、便携版、源码、release、build

## 更新日志
- 完整版本历史见 `CHANGELOG.md`（1.2.5 dispatch 修复 / 1.2.6 DashScope 视频 / 1.2.7 健壮性优化 / 1.2.8 主链路重试补全）
