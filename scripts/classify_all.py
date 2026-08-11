"""独立分类脚本 — 锁安全版"""
import sqlite3, json, requests, time, uuid

def connect():
    c = sqlite3.connect("data/library.db", timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c

CATS = ["计算机与编程","历史与人文","文学与小说","哲学与思想","科学与科普","经济与管理","心理与成长","教育学习","艺术设计","社会与政治","生活与健康"]

db = connect()
for cn in CATS:
    cid = db.execute("SELECT id FROM categories WHERE name=?",(cn,)).fetchone()
    if not cid:
        db.execute("INSERT INTO categories(id,name) VALUES(?,?)",(str(uuid.uuid4()),cn))
db.commit()
db.close()

def ai_classify(title, author, text):
    s = (text or "")[:2000]
    au = author or "未知"
    cats = "\n".join(f"- {c}" for c in CATS)
    prompt = f"判断类别。可选：{cats}\n书名：{title}\n作者：{au}"
    if s: prompt += f"\n内容片段：{s}"
    prompt += "\n严格只返回JSON对象：{\"category\":\"类别名\",\"tags\":[\"标签1\",\"标签2\"],\"difficulty\":\"入门/中级/高级\"}"
    try:
        r = requests.post("http://localhost:11434/api/generate",
            json={"model":"qwen2.5:7b","prompt":prompt,"stream":False,"temperature":0.1}, timeout=180)
        resp = r.json()["response"].strip()
        start = resp.find('{')
        end = resp.rfind('}')
        if start >= 0 and end > start:
            return json.loads(resp[start:end+1])
    except: pass
    return None

round_num = 0
while True:
    round_num += 1
    db = connect()
    
    rows = db.execute("""
        SELECT b.id, b.title, b.text_content,
               (SELECT GROUP_CONCAT(a.name) FROM authors a JOIN book_authors ba ON a.id=ba.author_id WHERE ba.book_id=b.id) as author
        FROM books b WHERE b.status='active'
        AND b.id NOT IN (SELECT book_id FROM book_categories)
        LIMIT 5
    """).fetchall()

    if not rows:
        db.close()
        print("全部完成！")
        break

    for bid, title, text, author in rows:
        r = ai_classify(title, author, text)
        if r is None:
            print(f"  SKIP: {title[:50]}")
            db.close(); time.sleep(1); db = connect()
            continue

        cn = r.get("category","其他")
        cid_row = db.execute("SELECT id FROM categories WHERE name=?",(cn,)).fetchone()
        if not cid_row:
            cid = str(uuid.uuid4())
            try:
                db.execute("INSERT INTO categories(id,name) VALUES(?,?)",(cid,cn))
            except: pass
        else:
            cid = cid_row[0]

        retry = 0
        while retry < 5:
            try:
                db.execute("INSERT OR IGNORE INTO book_categories(book_id,category_id) VALUES(?,?)",(bid,cid))
                for tn in r.get("tags",[]):
                    tid_row = db.execute("SELECT id FROM tags WHERE name=?",(tn,)).fetchone()
                    if not tid_row:
                        tid = str(uuid.uuid4())
                        db.execute("INSERT OR IGNORE INTO tags(id,name) VALUES(?,?)",(tid,tn))
                    else:
                        tid = tid_row[0]
                    db.execute("INSERT OR IGNORE INTO book_tags(book_id,tag_id) VALUES(?,?)",(bid,tid))
                if r.get("difficulty"):
                    db.execute("UPDATE books SET difficulty=? WHERE id=?",(r["difficulty"],bid))
                db.commit()
                print(f"  [{round_num*5-5+rows.index((bid,title,text,author))+1}] {title[:50]} -> {cn}")
                break
            except sqlite3.OperationalError:
                retry += 1
                time.sleep(2)
                try: db.rollback()
                except: pass
                db.close()
                db = connect()

    db.close()
    time.sleep(0.5)

print("Done!")

