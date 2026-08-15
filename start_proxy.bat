@echo off
setlocal
cd /d D:\OliviaProxy
echo [1/1] 启动 Olivia letter 拦截代理 (127.0.0.1:8080)
"D:\Program\Scripts\mitmdump.exe" --set confdir=D:\Program\mitmproxy-conf -s D:\OliviaProxy\olivia_letter_proxy.py --listen-port 8080