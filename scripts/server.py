"""统一服务器"""
import os, sys, argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_BUILD = BASE_DIR / "frontend" / "build"
APP_HTML = BASE_DIR / "app.html"
AUTO_SCAN = os.getenv("LIBRARY_AUTO_SCAN", "0") == "1"

sys.path.insert(0, str(BASE_DIR / "backend"))
from main import app
from database import init_db

@app.on_event("startup")
async def startup():
    await init_db()
    if AUTO_SCAN:
        await auto_scan_directories()

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str = ""):
    if full_path.startswith("api/"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    from fastapi.responses import FileResponse
    if not full_path or full_path in ("", "index.html"):
        if APP_HTML.exists(): return FileResponse(str(APP_HTML))
    if FRONTEND_BUILD.exists():
        fp = FRONTEND_BUILD / full_path
        if full_path and fp.exists() and fp.is_file(): return FileResponse(str(fp))
        return FileResponse(str(FRONTEND_BUILD / "index.html"))
    if APP_HTML.exists(): return FileResponse(str(APP_HTML))
    return FileResponse(str(APP_HTML))

async def auto_scan_directories():
    from config import AUTO_SCAN_DIRS, SUPPORTED_FORMATS, ARCHIVE_FORMATS
    from services.import_service import import_book, import_archive
    from services.archive_service import is_archive
    from database import async_session
    if not AUTO_SCAN_DIRS: return
    print("\n📂 Auto scanning...")
    all_ebooks = []
    for scan_dir in AUTO_SCAN_DIRS:
        path = Path(scan_dir)
        if not path.exists(): continue
        for fpath in path.rglob("*"):
            if fpath.is_file() and not fpath.name.startswith("."):
                if fpath.suffix.lower() in SUPPORTED_FORMATS | ARCHIVE_FORMATS:
                    all_ebooks.append(str(fpath))
    if not all_ebooks: return
    print(f"  Found {len(all_ebooks)} files")
    async with async_session() as db:
        s, d, e = 0, 0, 0
        for i, fp in enumerate(all_ebooks):
            try:
                if is_archive(fp): r = await import_archive(db, fp); s += r["success"]; d += r["duplicates"]; e += r["errors"]
                else: r = await import_book(db, fp); s += 1 if r.get("success") else 0; d += 1 if r.get("duplicate") else 0
            except: e += 1
        print(f"  ✅ +{s} dup{d} err{e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--scan", action="store_true")
    args = parser.parse_args()
    if args.scan: os.environ["LIBRARY_AUTO_SCAN"] = "1"
    import uvicorn
    print(f"\n╔══════════════════════════╗\n║   📚 个人电子图书馆      ║\n║   http://127.0.0.1:{args.port}  ║\n╚══════════════════════════╝\n")
    uvicorn.run("server:app", host=args.host, port=args.port, reload=False)

