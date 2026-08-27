# -*- coding: utf-8 -*-
# kg_build.py — 私有图书馆知识图谱生成（可续跑 · 盘符无关 · 跨机器通用）
# L1 结构层：书→作者/分类/出版社/标签 双链 + 反向链接 + AI摘要（不需 Ollama）。
# L2 语义层：调本机 Ollama 抽取实体-关系三元组，追加进 note（需 Ollama）。
# Vault 路径：--vault > 环境变量 KG_VAULT > 配置 kg_vault；两台机器各自设 KG_VAULT 即可。
import os
import sys
import time
import re
import argparse
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import libtools_common as C

ILLEGAL = '<>:"/\\|?*[]'


def safe(name):
    if not name:
        return "未命名"
    s = (name or "未命名").strip()
    s = s.replace("\u00a0", " ").replace("\u200b", "").replace("\u3000", " ")
    # 去掉 NUL 及全部控制字符（书名混入 \x00 会让 open() 报 embedded null character）
    s = "".join(ch for ch in s if ord(ch) >= 32 and ord(ch) != 0x7f)
    for c in ILLEGAL:
        s = s.replace(c, "_")
    while "  " in s:
        s = s.replace("  ", " ")
    s = s.strip()
    return s[:120] or "未命名"


def find_vault(args, cfg):
    for src in (args.vault, os.environ.get("KG_VAULT"), cfg.get("kg_vault")):
        if src and os.path.isdir(src):
            return src
    # 轻量自动搜索
    guesses = [
        r"D:\WorkBuddy\Claw\landlord知识库",
        os.path.expanduser(r"~\Documents\Obsidian Vault"),
    ]
    for g in guesses:
        if os.path.isdir(g):
            print(f"[自动猜测 Vault] {g}（建议设 KG_VAULT 环境变量固定）")
            return g
    raise SystemExit("找不到 Vault。请设置环境变量 KG_VAULT=你的Vault路径，或加 --vault 参数。")


def get_book_detail(conn, bid):
    b = conn.execute(
        "SELECT id,title,publisher,publish_date,isbn,language,description,summary,normalized_title "
        "FROM books WHERE id=?", (bid,)
    ).fetchone()
    if not b:
        return None
    authors = [r[0] for r in conn.execute(
        "SELECT a.name FROM book_authors ba JOIN authors a ON a.id=ba.author_id WHERE ba.book_id=?", (bid,))]
    cats = conn.execute(
        "SELECT c1.name, c2.name FROM book_categories bc "
        "LEFT JOIN categories c1 ON c1.id=bc.category_id "
        "LEFT JOIN categories c2 ON c2.id=bc.subcategory_id WHERE bc.book_id=?", (bid,)).fetchall()
    primary = [c[0] for c in cats if c[0]]
    sub = [c[1] for c in cats if c[1]]
    tags = [r[0] for r in conn.execute(
        "SELECT t.name FROM book_tags bt JOIN tags t ON t.id=bt.tag_id WHERE bt.book_id=?", (bid,))]
    return {"id": b["id"], "title": b["title"], "publisher": b["publisher"], "publish_date": b["publish_date"],
            "isbn": b["isbn"], "language": b["language"], "description": b["description"], "summary": b["summary"],
            "normalized": b["normalized_title"] or b["title"], "authors": authors,
            "primary": primary, "sub": sub, "tags": tags}


def build_note(d, mode):
    disp = d["normalized"]
    fn = safe(disp)
    lines = [f"# {disp}", ""]
    lines.append("> [!info] 私有图书馆知识图谱 · " + ("L2 语义" if mode == "l2" else "L1 结构"))
    lines.append(f"> book_id:: `{d['id']}`")
    lines.append(f"> 原始标题:: {d['title']}")
    lines.append("")
    if d["authors"]:
        lines.append("- 作者：" + "、".join(f"[[{safe(a)}|{a}]]" for a in d["authors"]))
    if d["primary"]:
        lines.append("- 一级分类：" + "、".join(f"[[{safe(c)}|{c}]]" for c in d["primary"]))
    if d["sub"]:
        lines.append("- 二级分类：" + "、".join(f"[[{safe(c)}|{c}]]" for c in d["sub"]))
    if d["tags"]:
        lines.append("- 标签：" + " ".join(f"#{(t if ' ' not in t else safe(t))}" for t in d["tags"][:12]))
    if d["publisher"]:
        lines.append(f"- 出版社：{d['publisher']}")
    if d["publish_date"]:
        lines.append(f"- 出版年：{d['publish_date']}")
    if d["isbn"]:
        lines.append(f"- ISBN：{d['isbn']}")
    if d["language"]:
        lines.append(f"- 语言：{d['language']}")
    lines.append("")
    lines.append("## AI 摘要")
    body = (d["summary"] or (d["description"] or "")[:600] or "（暂无摘要）")
    lines.append(body)
    return fn, disp, lines


def related_links(conn, d):
    bid = d["id"]
    out = []
    if d["authors"]:
        rel = []
        for a in d["authors"]:
            rows = conn.execute(
                "SELECT DISTINCT b.id, COALESCE(b.normalized_title,b.title) t FROM books b "
                "JOIN book_authors ba ON ba.book_id=b.id JOIN authors a ON a.id=ba.author_id "
                "WHERE a.name=? AND b.id<>? LIMIT 8", (a, bid)).fetchall()
            for r in rows:
                rel.append((r["t"], r["id"]))
        if rel:
            out.append(("同作者其他书", rel))
    if d["primary"]:
        rel = []
        for c in d["primary"]:
            rows = conn.execute(
                "SELECT DISTINCT b.id, COALESCE(b.normalized_title,b.title) t FROM books b "
                "JOIN book_categories bc ON bc.book_id=b.id "
                "LEFT JOIN categories c1 ON c1.id=bc.category_id "
                "LEFT JOIN categories c2 ON c2.id=bc.subcategory_id "
                "WHERE (c1.name=? OR c2.name=?) AND b.id<>? LIMIT 8", (c, c, bid)).fetchall()
            for r in rows:
                rel.append((r["t"], r["id"]))
        if rel:
            out.append(("同分类其他书", rel))
    return out


def write_moc(conn, pconn, vault_kg, tool):
    """扫描实际生成的 note 文件（读其中的 book_id），按分类重建总览。
    用实际文件名作链接目标，保证 100% 可解析（含文件名碰撞加后缀的情况）。"""
    groups = {}
    for fn in os.listdir(vault_kg):
        if not fn.endswith(".md") or fn == "知识图谱总览.md":
            continue
        txt = open(os.path.join(vault_kg, fn), encoding="utf-8").read()
        m = re.search(r"book_id::\s*`([^`]+)`", txt)
        if not m:
            continue
        d = get_book_detail(conn, m.group(1))
        if not d:
            continue
        cat = d["primary"][0] if d["primary"] else "未分类"
        stem = os.path.splitext(fn)[0]
        groups.setdefault(cat, []).append(stem)
    lines = ["# 知识图谱总览", "", "> 由私有图书馆自动生成（L1 结构层）。点开任一笔记可见双链与反向链接。", ""]
    for cat in sorted(groups):
        lines.append(f"## {cat}")
        for stem in sorted(groups[cat]):
            lines.append(f"- [[{stem}|{stem}]]")
        lines.append("")
    with open(os.path.join(vault_kg, "知识图谱总览.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return sum(len(v) for v in groups.values())


def main():
    ap = argparse.ArgumentParser(description="知识图谱生成（可续跑）")
    ap.add_argument("--mode", choices=["l1", "l2"], default="l1")
    ap.add_argument("--cat", help="只处理某分类（含一/二级）")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--vault", help="Vault 路径（或用环境变量 KG_VAULT）")
    ap.add_argument("--model", default=None, help="L2 用 Ollama 模型")
    ap.add_argument("--regen", action="store_true", help="清空图谱进度重跑")
    args = ap.parse_args()

    cfg = C.load_config()
    model = args.model or cfg.get("ollama_model", "qwen2.5:7b")
    limit = args.limit or cfg.get("default_limit", 200)
    tool = "kg_" + args.mode

    conn = C.get_conn()
    pconn = C.get_progress_conn()
    C.ensure_progress(pconn)
    if args.regen:
        C.clear_status(pconn, tool)
        print(f"已清空 {tool} 进度，将重跑。")

    vault = find_vault(args, cfg)
    vault_kg = os.path.join(vault, "知识图谱")
    os.makedirs(vault_kg, exist_ok=True)
    print(f"Vault 知识图谱目录: {vault_kg}")

    # 选取待处理书
    if args.cat:
        sql = ("SELECT DISTINCT b.id FROM books b "
               "JOIN book_categories bc ON bc.book_id=b.id "
               "LEFT JOIN categories c1 ON c1.id=bc.category_id "
               "LEFT JOIN categories c2 ON c2.id=bc.subcategory_id "
               "WHERE (c1.name=? OR c2.name=?) AND b.status='active'")
        params = (args.cat, args.cat)
    else:
        sql = "SELECT b.id FROM books b WHERE b.status='active'"
        params = ()
    sql += " ORDER BY b.id LIMIT ?"
    all_ids = [r[0] for r in conn.execute(sql, params + (limit,)).fetchall()]
    # 过滤已 done（续跑核心）
    todo = [bid for bid in all_ids if C.get_status(pconn, bid, tool) != "done"]
    print(f"候选 {len(all_ids)} 本，未处理 {len(todo)} 本（已完成会自动跳过）。")
    if not todo:
        print("没有待处理书籍（如需重跑加 --regen）。")
        write_moc(conn, pconn, vault_kg, tool)
        return

    done = 0
    for i, bid in enumerate(todo, 1):
        d = get_book_detail(conn, bid)
        if not d:
            continue
        fn, disp, lines = build_note(d, args.mode)
        # 反向链接
        for title, rels in related_links(conn, d):
            lines.append("")
            lines.append(f"## {title}")
            for t, rid in rels:
                if rid == bid:
                    continue
                lines.append(f"- [[{safe(t)}|{t}]]")
        lines.append("")
        lines.append("## 知识图谱链接")
        lines.append("- 返回 [[知识图谱总览]]")
        # L2 语义抽取
        if args.mode == "l2":
            text = (d["description"] or "") + "\n" + (d["summary"] or "")
            if len(text.strip()) >= 30:
                prompt = (f"从书籍元数据中抽取实体-关系三元组(实体,关系,实体)，仅基于文本事实，中文输出，"
                          f"关系用动词/介词短语。书籍：《{d['title']}》\n简介：{text[:1500]}\n"
                          f"返回JSON: {{\"triples\":[[\"实体A\",\"关系\",\"实体B\"]]}}")
                resp = C.ollama_generate(prompt, model=model)
                if resp:
                    lines.append("")
                    lines.append("## 实体关系（L2）")
                    # 简化：抽取 [["A","rel","B"]] 形式
                    import re as _re
                    for m in _re.finditer(r'\["\s*([^"]+?)\s*"\s*,\s*"([^"]+?)"\s*,\s*"([^"]+?)\s*"\]', resp):
                        a, r, b = m.groups()
                        lines.append(f"- [[{safe(a)}|{a}]] --{r}--> [[{safe(b)}|{b}]]")
        path = os.path.join(vault_kg, fn + ".md")
        if os.path.exists(path):  # 书名碰撞：加短 ID 后缀保证唯一
            path = os.path.join(vault_kg, fn + "_" + str(bid)[:8] + ".md")
        with open(path, "w", encoding="utf-8") as f:
            # 双保险：内容里若混有 NUL/控制字符（原始 title/publisher/summary 字段）一并剔除
            f.write("\n".join(lines).replace("\x00", "").replace("\r", "") + "\n")
        C.mark_progress(pconn, bid, tool, "done")
        done += 1
        if i % 20 == 0:
            print(f"  [{i}/{len(todo)}] 已生成 {done} 本", flush=True)
        if args.mode == "l2":
            time.sleep(0.3)
    total = write_moc(conn, pconn, vault_kg, tool)
    print(f"\n本轮生成 {done} 本；累计 {tool} 完成 {total} 本。已写入 Vault：{vault_kg}")


if __name__ == "__main__":
    main()
