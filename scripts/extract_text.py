"""批量提取书籍文本"""
import sqlite3, os, sys

db = sqlite3.connect("data/library.db")
rows = db.execute("SELECT id, file_path, file_format FROM books WHERE text_content IS NULL AND status='active'").fetchall()
print(f"需要提取文本: {len(rows)} 本")

sys.path.insert(0, "backend")
from services.parser import parse_file
from utils.text_utils import clean_text
import asyncio

async def extract():
    count = 0
    for i, (bid, fpath, fmt) in enumerate(rows):
        if not os.path.exists(fpath):
            continue
        try:
            parsed = await parse_file(fpath)
            text = clean_text(parsed.text_content or "")
            if text:
                db.execute("UPDATE books SET text_content=? WHERE id=?", (text, bid))
                count += 1
        except:
            pass
        if (i+1) % 100 == 0:
            db.commit()
            print(f"  [{i+1}/{len(rows)}] 已提取 {count} 本")
    db.commit()
    print(f"完成！提取 {count} 本")

asyncio.run(extract())
db.close()
