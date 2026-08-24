#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量补标二级分类：为本机已有书籍（book_categories 中 subcategory_id 为空）调用本地 Ollama
打二级子类。多线程跑，进度打印到 stdout。可重复运行（已打的会跳过）。"""
import sqlite3, json, uuid, time, threading
import urllib.request, urllib.error

DB = "data/library.db"
OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen2.5:7b"
WORKERS = 3
BATCH = 4000  # 每次从 DB 拉取待处理书的量

_print_lock = threading.Lock()


def ollama_generate(prompt, timeout=180):
    payload = {"model": MODEL, "prompt": prompt, "stream": False,
               "temperature": 0.1, "options": {"num_ctx": 4096}}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8")).get("response", "").strip()


def load_taxonomy():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    # 一级名 -> id
    parents = {r['name']: r['id'] for r in con.execute("SELECT id,name FROM categories WHERE parent_id IS NULL")}
    # (一级名,二级名) -> id
    subs = {}
    for r in con.execute("SELECT s.id, s.name, p.name AS pname FROM categories s JOIN categories p ON s.parent_id=p.id"):
        subs[(r['pname'], r['name'])] = r['id']
    clist_lines = []
    for pname, pid in parents.items():
        clist_lines.append("- " + pname)
        for (pn, sn), sid in subs.items():
            if pn == pname:
                clist_lines.append("    - " + sn)
    con.close()
    return parents, subs, "\n".join(clist_lines)


def worker(book, clist, parents, subs, stats):
    bid, title, text, cat_name, cat_id = book
    prompt = (f"判断以下书籍分类。一级类别与二级子类只能从下列选择。\n{clist}\n\n"
              f"书名：{title}\n内容：{(text or '')[:1500]}\n（若内容为空，仅根据书名判断）\n"
              f"只返回JSON：{{\"category\":\"一级类别名\",\"subcategory\":\"二级子类名（必须属于所选一级）\"}}")
    try:
        resp = ollama_generate(prompt)
        if resp.startswith("```"):
            resp = resp.split("\n", 1)[1].rsplit("\n", 1)[0]
        result = json.loads(resp)
        sn = result.get("subcategory")
        if not sn:
            raise ValueError("no subcategory")
        sid = subs.get((cat_name, sn))
        if not sid:
            c0 = sqlite3.connect(DB, timeout=60); c0.row_factory = sqlite3.Row
            ex = c0.execute("SELECT id FROM categories WHERE name=?", (sn,)).fetchone()
            c0.close()
            if ex:
                sid = ex['id']; subs[(cat_name, sn)] = sid
        if not sid:
            sid = str(uuid.uuid4())
            c0 = sqlite3.connect(DB, timeout=60)
            try:
                c0.execute("INSERT INTO categories(id,name,parent_id) VALUES(?,?,?)", (sid, sn, cat_id))
                c0.commit()
                subs[(cat_name, sn)] = sid
            except sqlite3.IntegrityError:
                c0.rollback()
                rr = c0.execute("SELECT id FROM categories WHERE name=?", (sn,)).fetchone()
                if rr:
                    sid = rr['id']; subs[(cat_name, sn)] = sid
            c0.close()
        c = sqlite3.connect(DB, timeout=60)
        c.execute("UPDATE book_categories SET subcategory_id=? WHERE book_id=?", (sid, bid))
        c.commit(); c.close()
        with _print_lock:
            stats['done'] += 1
    except Exception as e:
        try:
            c = sqlite3.connect(DB, timeout=60)
            c.execute("UPDATE book_categories SET subcategory_id='__FAILED__' WHERE book_id=?", (bid,))
            c.commit(); c.close()
        except Exception:
            pass
        with _print_lock:
            stats['fail'] += 1
            if stats['fail'] <= 30:
                print(f"  [skip] {str(title)[:30]}: {type(e).__name__}: {e}", flush=True)
    with _print_lock:
        stats['total'] += 1
        if stats['total'] % 200 == 0:
            print(f"  进度 {stats['total']} | 成功 {stats['done']} | 失败 {stats['fail']}", flush=True)


def main():
    parents, subs, clist = load_taxonomy()
    stats = {"done": 0, "fail": 0, "total": 0}
    print(f"[start] 二级分类补标开始，线程数={WORKERS}")
    while True:
        con = sqlite3.connect(DB, timeout=120)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """SELECT b.id,b.title,b.text_content,c.name AS cat_name,bc.category_id
               FROM books b JOIN book_categories bc ON bc.book_id=b.id
               LEFT JOIN categories c ON c.id=bc.category_id
               WHERE bc.subcategory_id IS NULL AND b.status='active'
                 AND b.text_content IS NOT NULL AND length(b.text_content) > 20
               LIMIT ?""", (BATCH,)).fetchall()
        con.close()
        if not rows:
            break
        print(f"[batch] 本轮待处理 {len(rows)} 本", flush=True)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for r in rows:
                ex.submit(worker, (r['id'], r['title'], r['text_content'], r['cat_name'], r['category_id']),
                          clist, parents, subs, stats)
    print(f"[done] 完成：成功 {stats['done']} | 失败 {stats['fail']} | 共处理 {stats['total']}", flush=True)


if __name__ == "__main__":
    main()
