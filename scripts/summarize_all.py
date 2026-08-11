"""独立摘要脚本 v2"""
import sqlite3, json, requests, time, traceback

DB = "data/library.db"
OLLAMA = "http://127.0.0.1:11434/api/generate"

def db():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c

def ai(text, title, author):
    prompt = f"""你是专业图书摘要助手。为以下书籍生成摘要。

书名：{title}
作者：{author or '未知'}

内容：
{(text or '')[:6000]}

按以下结构输出（中文）：
1. 一句话总结（50字内）
2. 核心观点（3-5条）
3. 关键概念
4. 适合读者
5. 难度评级：入门/中级/高级"""
    try:
        r = requests.post(OLLAMA,
            json={"model":"qwen2.5:7b","prompt":prompt,"stream":False,"temperature":0.3},
            timeout=300)
        if r.status_code != 200:
            print(f"    Ollama HTTP {r.status_code}")
            return None
        return r.json()["response"].strip()
    except Exception as e:
        print(f"    Ollama error: {e}")
        return None

total_done = 0
while True:
    c = db()
    rows = c.execute("""
        SELECT b.id, b.title, b.text_content,
               (SELECT GROUP_CONCAT(a.name) FROM authors a JOIN book_authors ba ON a.id=ba.author_id WHERE ba.book_id=b.id) as author
        FROM books b WHERE b.status='active' AND b.summary IS NULL AND b.text_content IS NOT NULL
        LIMIT 2
    """).fetchall()
    c.close()

    if not rows:
        print("全部完成！")
        break

    for bid, title, text, author in rows:
        real_title = title
        if title.startswith("upload_"):
            real_title = title
        print(f"  摘要 [{total_done+1}]: {real_title[:50]}...")
        
        summary = ai(text, real_title, author)
        
        if summary and len(summary) > 20:
            for retry in range(5):
                try:
                    c = db()
                    c.execute("UPDATE books SET summary=?,summary_model=?,summary_updated=datetime('now') WHERE id=?",
                        (summary, "qwen2.5:7b", bid))
                    if "高级" in summary: c.execute("UPDATE books SET difficulty='高级' WHERE id=? AND difficulty IS NULL",(bid,))
                    elif "中级" in summary: c.execute("UPDATE books SET difficulty='中级' WHERE id=? AND difficulty IS NULL",(bid,))
                    elif "入门" in summary: c.execute("UPDATE books SET difficulty='入门' WHERE id=? AND difficulty IS NULL",(bid,))
                    c.commit()
                    c.close()
                    total_done += 1
                    print(f"    ✅ [{total_done}]")
                    break
                except sqlite3.OperationalError:
                    time.sleep(2)
        else:
            print(f"    ⚠️ SKIP (no response)")

    time.sleep(2)

