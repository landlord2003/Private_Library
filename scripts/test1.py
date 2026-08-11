import sqlite3, fitz, os

c = sqlite3.connect('data/library.db')
rows = c.execute("SELECT id,file_path FROM books WHERE status='active' AND (text_content IS NULL OR text_content='') AND file_format='pdf' LIMIT 500").fetchall()
print(f'{len(rows)} 本待处理')
done = 0
for bid, fp in rows:
    if not os.path.exists(fp): continue
    try:
        doc = fitz.open(fp)
        t = ''.join([doc[i].get_text() for i in range(min(5, doc.page_count))])
        doc.close()
        if t.strip():
            c.execute('UPDATE books SET text_content=? WHERE id=?', (t[:10000], bid))
            done += 1
            if done % 50 == 0:
                c.commit()
                print(f'  {done}/{len(rows)}')
    except: pass
c.commit(); c.close()
print(f'完成: {done} 本')

