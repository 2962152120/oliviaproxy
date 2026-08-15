$proc = Start-Process -FilePath "D:\Program\Scripts\mitmdump.exe" `
    -ArgumentList "--set", "confdir=D:\Program\mitmproxy-conf", `
                 "-s", "C:\Users\ASUS\AppData\Local\Temp\opencode\diag2_proxy.py", `
                 "--listen-port", "8080" `
    -RedirectStandardOutput "D:\OliviaProxy\diag.out.log" `
    -RedirectStandardError "D:\OliviaProxy\diag.err.log" `
    -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 4
Write-Output "STARTED PID=$($proc.Id)"
curl.exe -s --ssl-no-revoke -x "http://127.0.0.1:8080" "https://toy-cnbeta01.olivia.miyoushe.com/toy/letter/list?pageSize=20" -o NUL
Start-Sleep -Seconds 2
Write-Output "===== STDOUT ====="
Get-Content "D:\OliviaProxy\diag.out.log" -ErrorAction SilentlyContinue
Write-Output "===== STDERR ====="
Get-Content "D:\OliviaProxy\diag.err.log" -ErrorAction SilentlyContinue
Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue