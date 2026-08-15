$ErrorActionPreference = "Stop"
Start-Process -FilePath "D:\Program\Scripts\mitmdump.exe" `
    -ArgumentList "--set", "confdir=D:\Program\mitmproxy-conf", `
                 "-s", "D:\OliviaProxy\olivia_letter_proxy.py", `
                 "--listen-port", "8080" `
    -WindowStyle Hidden -PassThru | Select-Object Id, ProcessName | Format-Table -AutoSize