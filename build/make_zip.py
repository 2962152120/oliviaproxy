import os, zipfile, time
src = r"D:/Users/ASUS/Desktop/Oliviaproxy/便携版1.2.11"
dst = r"D:/Users/ASUS/Desktop/Oliviaproxy/便携版1.2.11.zip"
exclude_dirs = {"__pycache__", "videos"}
exclude_files = {"debug.log", "letters.json", "memory.json", "proxy_backup.txt", "legal_agreed.txt"}
if os.path.exists(dst):
    os.remove(dst)
t0 = time.time()
n = 0
with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for f in files:
            if f in exclude_files:
                continue
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, os.path.dirname(src)))
            n += 1
print("files=%d size=%.1f MB time=%.0fs" % (n, os.path.getsize(dst) / 1048576, time.time() - t0))
