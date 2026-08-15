# Olivia 来信拦截助手 — 项目记忆

## 项目目标
在 BSide Olivia（米哈游 林离 客户端）官方服务器下线（2026-08-27 停服）后，让"写信"功能继续可用：
- 用 mitmproxy 本地拦截 `/toy/letter/*` 接口，返回模拟信件数据
- 用 OpenAI 兼容 API（DeepSeek）生成回信
- 打包成 Windows 安装包 + 便携版交付

## 关键状态（截至 2026-08-15，版本 1.0.7）
- **核心功能已全部打通并验证**：App 登录成功、进入主界面、写信/重发/每日上限均正常
- 登录方案：`/signIn` 等接口在 addon 中 mock 返回 `{"code":0,"message":"","data":{}}`；mitmproxy 根证书需安装到系统（本机已装，用户级+机器级）
- letter 拦截：addon 拦截 `/toy/letter/*`（list/detail/send/resend/unread_count/share），返回模拟数据，AI 回信走 `generate_reply` 后台线程

## 交付物（桌面 `D:\Users\ASUS\Desktop\Oliviaproxy\`）
- `OliviaProxy-Setup-1.0.7.exe`：安装包（Inno Setup）
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
- 便携版 zip：用 python zipfile 压缩便携版目录，排除 `debug.log letters.json proxy_backup.txt legal_agreed.txt __pycache__`
- 安装包：`"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "D:\Users\ASUS\Desktop\Oliviaproxy\源码\installer.iss"`
- 安装包版本在 installer.iss：`MyAppVersion` 和 `OutputBaseFilename`（如 1.0.7）

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
