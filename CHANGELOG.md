# Olivia 来信拦截助手 — 更新日志

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
