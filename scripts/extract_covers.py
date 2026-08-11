"""补提取封面"""
import sqlite3, os, uuid, sys
sys.path.insert(0, "backend")

db = sqlite3.connect("data/library.db")
rows = db.execute("SELECT id, file_path, file_format FROM books WHERE cover_path IS NULL AND status='active'").fetchall()
print(f"需要提取封面: {len(rows)} 本")

for i, (bid, fpath, fmt) in enumerate(rows):
    if not os.path.exists(fpath): continue
    try:
        cover_data = None
        ext = os.path.splitext(fpath)[1].lower()
        if ext == '.pdf':
            import fitz
            doc = fitz.open(fpath)
            if doc.page_count > 0:
                pix = doc[0].get_pixmap(dpi=100)
                cover_data = pix.tobytes("jpg")
            doc.close()
        elif ext == '.epub':
            from ebooklib import epub
            book = epub.read_epub(fpath)
            for item in book.get_items():
                if item.get_type() == 6 and 'cover' in str(item.get_name()).lower():
                    cover_data = item.get_content()
                    break
        if cover_data:
            cpath = f"F:\\my-library\\data\\covers\\{bid}.jpg"
            os.makedirs(os.path.dirname(cpath), exist_ok=True)
            with open(cpath, 'wb') as f: f.write(cover_data)
            db.execute("UPDATE books SET cover_path=? WHERE id=?", (cpath, bid))
    except: pass
    if (i+1) % 100 == 0:
        db.commit()
        print(f"  [{i+1}/{len(rows)}]")
db.commit()
db.close()
print("完成")
