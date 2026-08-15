@echo off
rem Olivia 来信拦截助手 - 便携版卸载/清理
setlocal
echo 正在停止拦截进程...
taskkill /IM mitmdump.exe /F >nul 2>&1
echo 正在还原系统代理设置...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /f >nul 2>&1
echo 系统代理已还原（ProxyEnable=0）。
echo.
echo 如曾安装过 CA 证书，请在"证书管理器 - 受信任的根证书颁发机构"中手动删除
echo "mitmproxy" 证书，或直接删除本文件夹即可完成清理。
echo.
pause
