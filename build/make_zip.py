# -*- coding: utf-8 -*-
"""把指定便携版目录打包成 zip。

用法: python build/make_zip.py <版本号>
例:   python build/make_zip.py 1.2.12

排除 __pycache__/videos 目录，以及运行时生成的日志与用户数据文件，
确保分发包里不含真实 key 和用户信件。
"""
import os
import sys
import time
import zipfile

DESKTOP = r"D:\Users\ASUS\Desktop\Oliviaproxy"
EXCLUDE_DIRS = {"__pycache__", "videos"}
EXCLUDE_FILES = {
    "debug.log",
    "letters.json",
    "memory.json",
    "proxy_backup.txt",
    "legal_agreed.txt",
    "run_proxy.cmd",
}


def main():
    if len(sys.argv) < 2:
        print("usage: python build/make_zip.py <version>")
        return 1
    ver = sys.argv[1]
    src = os.path.join(DESKTOP, "便携版" + ver)
    dst = src + ".zip"
    if not os.path.isdir(src):
        print("source dir not found: %s" % src)
        return 1
    if os.path.exists(dst):
        os.remove(dst)

    t0 = time.time()
    n = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if f in EXCLUDE_FILES:
                    continue
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, os.path.dirname(src)))
                n += 1
    print("files=%d size=%.1f MB time=%.0fs -> %s"
          % (n, os.path.getsize(dst) / 1048576, time.time() - t0, dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
