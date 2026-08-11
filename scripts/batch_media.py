"""批量导入音视频 — 修复版"""
import os, sys, time, hashlib, uuid, json, subprocess, sqlite3
from pathlib import Path

db_path = r"F:\my-library\data\library.db"
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA journal_mode=WAL")

MEDIA_EXTS = {".mp3",".wav",".flac",".aac",".m4a",".ogg",".opus",".mp4",".mkv",".avi",".webm",".mov",".flv",".wmv",".m4v"}

def file_hash(fp):
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""): h.update(chunk)
    return h.hexdigest()

def probe(fp):
    info = {"duration": 0, "artist": "", "title": "", "width": 0, "height": 0}
    try:
        r = subprocess.run(["ffprobe","-v","quiet","-print_format","json","-show_format","-show_streams",fp],
            capture_output=True, timeout=30, encoding="utf-8", errors="replace")
        if r.returncode != 0: return info
        d = json.loads(r.stdout)
        fmt = d.get("format",{})
        info["duration"] = float(fmt.get("duration",0))
        tags = fmt.get("tags",{})
        info["title"] = tags.get("title","")
        info["artist"] = tags.get("artist","")
        for s in d.get("streams",[]):
            if s.get("codec_type")=="video":
                info["width"] = int(s.get("width",0))
                info["height"] = int(s.get("height",0))
    except: pass
    return info

def scan():
    files = []
    for dirpath, _, fnames in os.walk(r"F:\书籍"):
        for fn in fnames:
            if fn.startswith("."): continue
            if os.path.splitext(fn)[1].lower() in MEDIA_EXTS:
                files.append(os.path.join(dirpath, fn))
    return files

conn.execute("""CREATE TABLE IF NOT EXISTS media(
    id TEXT PRIMARY KEY, title TEXT, media_type TEXT, file_path TEXT, file_format TEXT,
    file_size INTEGER, file_hash TEXT, duration REAL, artist TEXT, width INTEGER, height INTEGER,
    status TEXT DEFAULT 'active', created_at TEXT
)""")
conn.commit()

print("Scanning...")
files = scan()
print(f"Found {len(files)} media files\n")

success, dupes, errors = 0, 0, 0
t0 = time.time()

for i, fpath in enumerate(files, 1):
    try:
        h = file_hash(fpath)
        if conn.execute("SELECT id FROM media WHERE file_hash=?", (h,)).fetchone():
            dupes += 1
            if i % 200 == 0: print(f"  [{i}/{len(files)}] +{success} dup{dupes}")
            continue

        fn = os.path.basename(fpath)
        ext = os.path.splitext(fpath)[1].lower()
        fsize = os.path.getsize(fpath)
        info = probe(fpath)
        mtype = "video" if info["width"] > 0 else "audio"
        title = info["title"] or os.path.splitext(fn)[0]

        conn.execute("INSERT INTO media(id,title,media_type,file_path,file_format,file_size,file_hash,duration,width,height,artist,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
            (str(uuid.uuid4()), title, mtype, fpath, ext.lstrip("."), fsize, h, info["duration"], info["width"], info["height"], info["artist"], "active"))
        success += 1
    except: errors += 1

    if i % 200 == 0:
        conn.commit()
        elapsed = time.time()-t0
        print(f"  [{i}/{len(files)}] {i/elapsed:.1f}/s | +{success} dup{dupes} err{errors}")

conn.commit()
conn.close()
print(f"\nDone! +{success} dup{dupes} err{errors} in {time.time()-t0:.0f}s")

