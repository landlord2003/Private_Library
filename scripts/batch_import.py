"""命令行批量导入 — 同步版，更稳定"""
import os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

import sqlite3
db_path = r"F:\my-library\data\library.db"
conn = sqlite3.connect(db_path, check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")

# 直接用同步方式
import hashlib, uuid, shutil
from config import SUPPORTED_FORMATS, ARCHIVE_FORMATS, BOOKS_DIR

def file_hash(fp):
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def scan(root):
    files = []
    for dirpath, _, fnames in os.walk(root):
        for fn in fnames:
            if fn.startswith("."): continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in SUPPORTED_FORMATS or ext in ARCHIVE_FORMATS or ext in {".zip",".rar",".7z"}:
                files.append(os.path.join(dirpath, fn))
    return files

SCAN_DIR = r"F:\书籍"
print(f"Scanning {SCAN_DIR} ...")
files = scan(SCAN_DIR)
print(f"Found {len(files)} files\n")

success, dupes, errors, skipped = 0, 0, 0, 0
t0 = time.time()

for i, fpath in enumerate(files, 1):
    try:
        h = file_hash(fpath)
        # 检查重复
        row = conn.execute("SELECT id FROM books WHERE file_hash=?", (h,)).fetchone()
        if row:
            dupes += 1
            if i % 100 == 0:
                print(f"  [{i}/{len(files)}] +{success} dup{dupes} err{errors}")
            continue

        fname = os.path.basename(fpath)
        ext = os.path.splitext(fpath)[1].lower()
        fsize = os.path.getsize(fpath)
        bid = str(uuid.uuid4())
        bdir = os.path.join(str(BOOKS_DIR), bid)
        os.makedirs(bdir, exist_ok=True)
        dest = os.path.join(bdir, f"original{ext}")

        if not os.path.exists(dest):
            shutil.copy2(fpath, dest)

        title = os.path.splitext(fname)[0]
        fmt = ext.lstrip(".")

        conn.execute(
            "INSERT INTO books(id,title,file_path,file_format,file_size,file_hash,status,import_source) VALUES(?,?,?,?,?,?,?,?)",
            (bid, title, dest, fmt, fsize, h, "active", "batch")
        )
        conn.commit()
        success += 1

    except Exception as e:
        errors += 1
        if errors <= 5:
            print(f"  Error: {os.path.basename(fpath)} - {e}")

    if i % 100 == 0:
        elapsed = time.time() - t0
        spd = i / elapsed if elapsed > 0 else 0
        conn.commit()
        print(f"  [{i}/{len(files)}] {spd:.1f}/s | +{success} dup{dupes} err{errors}")

conn.commit()
conn.close()
elapsed = time.time() - t0
print(f"\nDone! +{success} dup{dupes} err{errors} in {elapsed:.0f}s")

