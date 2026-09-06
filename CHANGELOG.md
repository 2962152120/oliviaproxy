# Olivia 来信拦截助手 — 更新日志

## 未发布（2026-09-06）

- **修复回信后不置未读（App 无未读红点）**：`generate_reply` 成功后只设 `status=REPLIED`，未设 `unread=True`，导致 `count_unread()` 恒为 0、`unread_count` 接口永远返回 0。现回信成功后置 `unread=True`，读信时由 `detail` 接口清掉（`isRead` 语义不变）。注：种子信件 2001 的 `unread` 是手写值，此前掩盖了该问题。
- **修复每日上限形同虚设**：`send` 分支原先只校验 content 非空，`max_daily_letters` 仅在 `list` 接口算一个 `remainingToday` 返回给前端，后端完全不拦截，超限照样发信。现 `send` 在 `state["lock"]` 内统计当日已发信件数，超限时返回业务码 `429` + `message`「今日信件已达上限（N 封）」，不建信、不触发回信。HTTP 状态仍为 200（与现有 400/404 约定一致）。GUI 写信面板失败时优先显示 `message`，不再打印整段 JSON。
- **修复发信记忆写入竞态**：`remember("user", content)` 原先写在回信线程 `start()` **之后**，靠默认 20 秒 `reply_delay_seconds` 侥幸躲过竞态；一旦把延迟调小，用户来信就进不了记忆上下文。现移到 `start()` 之前（仍在 `state["lock"]` 块外，`remember` 内部会自行加锁，移入会死锁）。
- **修复 `_drain` 后台线程回调崩溃**：GUI 关闭后，mitmdump 输出读取线程仍调 `root.after(0, self._log, text)`，抛 `RuntimeError: main thread is not in main loop`。现捕获 `(RuntimeError, tk.TclError)` 并直接 return 停止读取。（与 1.2.11 修过的 `_enable_proxy_when_ready` 属同一类问题，那次只补了一处。）

## 1.2.10（2026-08-28）
- **修复视频轮询误用 POST**：OpenAI `gen_video_openai` 与火山 Ark `gen_video_volc` 的异步任务轮询本应 `GET`，原误用 `http_json_request`（POST），现改为 `http_json_get`；MiniMax V1 轮询设计即 POST，保持不变
- **修复 `resend` 重复记忆**：重发每封信都会 `remember("user", content)`，导致记忆随重发次数线性膨胀；现改为只在收信时记一次，重发不再重复写入
- **修复 `resend` 残留 `fail_reason`**：FAILED 重发后旧失败原因未清，列表里仍显示旧错误；现 `resend` 时 `pop("fail_reason")`
- **修复 GUI 代理开关指向死代理**：勾选启用代理时若拦截未运行，会立即把系统代理指向 127.0.0.1:8080 但后端实际没起来，导致断网；现改为先自动启动拦截再启用代理
- **边缘健壮性**：`is_letter_flow()` 的 `LISTENER["path_prefix"]` 改为 `LISTENER.get("path_prefix", "/toy/letter/")`，config 缺失 listener 时不再 KeyError；视频 HTTP 服务自定义 `ThreadingTCPServer` 设 `allow_reuse_address = True`，避免重启后 8765 端口占用报 `Address already in use`

## 1.2.9（2026-08-28）
- **修复 1.2.8 引入的严重回归**：`tts_openai` / `tts_volc` 改走重试包装时缩进错乱，导致 addon 语法错误、mitmdump 无法加载（1.2.8 版本代理完全不可用）。已修复并对全部 addon 副本重新打包
- **修复 GUI 保存配置丢失扩展字段**：`_collect_video()` 整段覆盖 `video`/`tts` 配置，会静默清掉 1.2.7 的 `fallback_provider` / `providers`（及 resolution/duration/ratio/watermark）。现改为保留这些未编辑字段
- **修复 `resend` 不清旧回信字段**：重发后 `reply_type`/`reply_video_url`/`video_ready`/`video_fail`/`replied_at` 一并重置，避免状态 FAILED 却残留旧视频
- **修复回信/视频生成并发竞态**：
  - `generate_reply` 加防重入（`_reply_in_progress` + 锁），send 后马上 resend 不再重复调 AI
  - `_video_in_progress` 的"检查-加入"改为加锁，杜绝 TOCTOU 重复生成视频

## 1.2.8（2026-08-26）
- 文字回信 `call_openai` 与记忆压缩 `compress_memory` 由裸 `urllib.request.urlopen` 改为统一重试包装 `_urlopen_with_retry`（此前网络抖动会直接失败）
- `tts_openai` / `tts_volc` 同样由裸 `urlopen` 改为 `_urlopen_with_retry`
- 删除 `list` 接口把整封信件 JSON 持续追加写 `debug.log` 的遗留诊断代码（写盘频繁且泄漏 PII）
- 瞬时错误判定函数 `_video_is_transient` 改名 `_is_transient`，视频/TTS 回退共用
- 现状：所有对第三方 API 的 HTTP 请求（文字 / TTS / 视频 / 记忆压缩）均经统一重试，仅 401 等认证错误立即失败不重试

## 1.2.7（2026-08-26）
- 视频 / TTS 支持 `fallback_provider` 自动回退：主 provider 命中瞬时错误（433/429/quota/10054/timeout/5xx 等）自动切 fallback provider
- 各 provider 可配独立 `providers.<name>` 子块覆盖 base_url / model / api_key（顶层字段作默认）
- `http_json_request` / `http_json_get` / `http_download` 统一加重试（默认 3 次，对 408/429/500/502/503/504 与网络抖动退避重试）
- addon 内残留 `print()` 全部改为 `ctx.log.info/warn`
- 新增 `OliviaLetterProxy.running()` 启动自检：打印 dispatch enc_conf 是否设置、video/tts 主+fallback provider、各 provider 是否缺 key、视频服务端口与触发概率
- 视频生成并发去重：模块级 `_video_in_progress` 集合防同一 letter 重复生成

## 1.2.6（2026-08-18）
- 新增千问 DashScope（通义万相）视频 provider `dashscope`（别名 `ds` / `wan`）
- 异步任务模式：`POST /services/aigc/video-generation/video-synthesis` + header `X-DashScope-Async: enable` → `output.task_id` → 轮询 `GET /tasks/{task_id}` → SUCCEEDED 取 `output.video_url`（OSS 直链，无鉴权，24h 有效）
- 模型默认 `wan2.7-t2v-2026-06-12`（另有 wan2.6-t2v / wan2.2-t2v-plus）
- addon `gen_video_dashscope()`；GUI `VIDEO_PROVIDERS` 加 `dashscope`（默认 base/model）
- App 内视频回信（replyType=3）实测通过（wan2.7-t2v 5s/720P/30fps，letter 2009）

## 1.2.5（2026-08-18）
- 修复 App 报 "failed to get dispatch configuration"
  - 根因①：`request()` 未在每次请求时 `reload_config()`，dispatch 分支用旧/空 `DISPATCH_ENC_CONF` → 已在 `request()` 开头调用 `reload_config()`
  - 根因②：手动启动 mitmdump 未传 `--set confdir=<runtime/certs>`，用了 `~/.mitmproxy` 默认 CA（序列号 1184c38d），与系统已信任的 `runtime/certs` CA（序列号 58f76b63）不一致 → 所有客户端 TLS 握手失败。修复：mitmdump 必须带 `--set confdir=<目录>/runtime/certs` 启动
  - dispatch 匹配放宽为 host 含 `olivia.miyoushe.com` 且路径含 `dispatch`，或 host 含 `dispatcher`+`olivia`

## 更早版本（摘要）
- 1.2.4：scnet.cn 算力平台接入（视频 Seedance2.0 / Wan2.7-T2V / HappyHorse-1.0-T2V + TTS Qwen3-TTS）
- 1.2.3：MiniMax 视频 V2 接口修复（MiniMax-H3，/v2/video_generation 异步）+ MiniMax TTS 请求体修正 + config.json UTF-8 BOM 兼容
- 1.2.2：GUI "保存全部配置"按钮
- 1.2.1：配置热加载（基于 config.json mtime 变化重读，GUI 保存后无需重启拦截即生效）
- 1.2.0：视频/语音回信（按 `video_probability` 概率触发，MIX_PLAY=3 视频+配音，本地视频服务 127.0.0.1:8765）
- 1.1.0：dispatch enc_conf 真实值注入
- 1.0.8：记忆系统（remember / compress_memory）
