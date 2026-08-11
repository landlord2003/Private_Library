"""全格式封面提取"""
import sqlite3, os, sys
sys.path.insert(0, "backend")

db = sqlite3.connect("data/library.db")
rows = db.execute("""
    SELECT id, file_path, file_format FROM books 
    WHERE cover_path IS NULL AND status='active'
    AND file_format IN ('pdf','epub','mobi','azw3')
""").fetchall()
print(f"需要提取: {len(rows)} 本")

extracted = 0
for i, (bid, fpath, fmt) in enumerate(rows):
    if not os.path.exists(fpath): continue
    try:
        cover = None
        if fmt == 'pdf':
            import fitz
            doc = fitz.open(fpath)
            if doc.page_count > 0:
                pix = doc[0].get_pixmap(dpi=100)
                cover = pix.tobytes("jpg")
            doc.close()
        elif fmt == 'epub':
            from ebooklib import epub
            book = epub.read_epub(fpath)
            for item in book.get_items():
                if item.get_type() == 6 and ('cover' in str(item.get_name()).lower() or 'cover' in str(item.get_id()).lower()):
                    cover = item.get_content()
                    break
            if not cover:
                for item in book.get_items():
                    if item.get_type() == 6:
                        cover = item.get_content()
                        break
        elif fmt in ('mobi','azw3'):
            from mobi import Mobi
            try:
                m = Mobi(fpath)
                m.parse()
                if hasattr(m, 'cover_image') and m.cover_image:
                    cover = m.cover_image
                elif hasattr(m, 'image_count') and m.image_count > 0:
                    for idx in range(min(m.image_count, 5)):
                        try:
                            img = m.read_image(idx)
                            if img and len(img) > 10000:
                                cover = img
                                break
                        except: pass
            except: pass

        if cover and len(cover) > 1000:
            cpath = f"F:/my-library/data/covers/{bid}.jpg"
            os.makedirs(os.path.dirname(cpath), exist_ok=True)
            with open(cpath, 'wb') as f: f.write(cover)
            db.execute("UPDATE books SET cover_path=? WHERE id=?", (f"data/covers/{bid}.jpg", bid))
            extracted += 1

    except Exception as e:
        pass

    if (i+1) % 100 == 0:
        db.commit()
        print(f"  [{i+1}/{len(rows)}] 已提取 {extracted} 本")

db.commit()
db.close()
print(f"完成！提取 {extracted} 本封面")
