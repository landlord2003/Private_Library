# -*- coding: utf-8 -*-
"""summary_fix.py — 离线可续跑摘要修复（识别假摘要 + 补短摘要）

两类问题：
  A) 假摘要：导入时 LLM 在无正文情况下编的模板示例，首句典型如
     "由于提供的内容为空白，我将根据模板结构给出一个示例来帮助您理解如何生成书籍摘要。"
     处理：若有 book_text 全文 → 用真实文本重跑真实摘要；若无全文 → 清空 summary（不留假摘要）。
  B) 短摘要：长度 < --min-len。处理：有全文 → 重跑；无全文 → 跳过。

素材取自 book_text(全文前3000字) + description；调本机 Ollama；置信门禁后写回
summary / summary_model / summary_updated。进度存 progress.db（续跑不白跑）。
"""
import os
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import libtools_common as C

TOOL = "summary"

FAKE_START = ("由于", "抱歉", "（以下", "(以下", "您好", "你好", "（注", "注：",
              "根据您", "根据提供", "我将")
FAKE_MID = ("内容为空白", "提供的内容为空", "提供的内容为空白", "内容为空", "内容有限",
            "内容未知", "未提供", "无法获取", "无法访问", "空白", "占位", "示例摘要",
            "示例文本", "我将根据", "假设的内容", "虚构的内容", "假设性的框架",
            "假设一个虚构", "根据一般图书摘要", "根据常见图书摘要", "帮助您理解如何生成",
            "假设示例", "示例书籍摘要", "未知的书籍")
FAKE_EXACT = ("由于提供的内容为空白", "由于提供的书籍内容为空白",
              "根据模板结构给出一个示例", "我将根据虚构的内容来生成",
              "基于一个假设的框架来生成摘要", "根据一般图书摘要的结构给出一个示例",
              "由于提供的书籍内容为空，我将基于一个假设的示例")


def is_fake_summary(s):
    if not s:
        return False
    s = s.strip()
    if len(s) < 8:
        return False
    if s.startswith(FAKE_START) and any(m in s[:160] for m in FAKE_MID):
        return True
    if any(m in s for m in FAKE_EXACT):
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description="摘要修复（可续跑·识别假摘要+补短）")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--min-len", type=int, default=100, help="短于此字数视为需补")
    ap.add_argument("--mode", choices=["fake", "short", "all"], default="all",
                    help="fake=仅假摘要; short=仅短摘要; all=两者")
    ap.add_argument("--clear-no-text", action="store_true", default=True,
                    help="无全文的假摘要直接清空 summary（默认开）")
    ap.add_argument("--no-clear-no-text", dest="clear_no_text", action="store_false")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不调 Ollama")
    ap.add_argument("--retry", action="store_true", help="清除进度重跑")
    args = ap.parse_args()

    cfg = C.load_config()
    model = args.model or cfg.get("ollama_model", "qwen2.5:7b")
    limit = args.limit or cfg.get("default_limit", 200)

    conn = C.get_conn()
    pconn = C.get_progress_conn()
    C.ensure_progress(pconn)

    if args.retry:
        C.clear_status(pconn, TOOL)
        print("已清除摘要修复进度，将重跑。")

    cols = [r[1] for r in conn.execute("PRAGMA table_info(books)")]
    has_upd = "summary_updated" in cols
    has_model = "summary_model" in cols

    # —— 收集候选 ——
    fake_ids = set()
    if args.mode in ("fake", "all"):
        for r in conn.execute(
                "SELECT id,summary FROM books WHERE LENGTH(COALESCE(summary,''))>0"):
            if is_fake_summary(r["summary"]):
                fake_ids.add(r["id"])
    short_ids = set()
    if args.mode in ("short", "all"):
        for (bid,) in conn.execute(
                "SELECT id FROM books WHERE LENGTH(COALESCE(summary,''))<?", (args.min_len,)):
            short_ids.add(bid)
    cand_ids = fake_ids | short_ids
    rows = []
    if cand_ids:
        ph = ",".join("?" * len(cand_ids))
        rows = conn.execute(
            f"SELECT id,title,description,summary,normalized_title FROM books "
            f"WHERE id IN ({ph}) ORDER BY id", list(cand_ids)).fetchall()
    smap = {bid: st for (bid, st) in pconn.execute(
        "SELECT book_id,status FROM tool_progress WHERE tool=?", (TOOL,))}
    rows = [r for r in rows if smap.get(r["id"]) not in ("done", "skip")][:limit]

    report = {"fake": 0, "short": 0, "has_text": 0, "no_text": 0, "cleared": 0, "fixed": 0, "skip": 0}
    for r in rows:
        text_row = conn.execute("SELECT text_content FROM book_text WHERE id=?", (r["id"],)).fetchone()
        has_text = bool(text_row and text_row["text_content"] and len(text_row["text_content"].strip()) >= 50)
        if is_fake_summary(r["summary"]):
            report["fake"] += 1
        else:
            report["short"] += 1
        if has_text:
            report["has_text"] += 1
        else:
            report["no_text"] += 1

    print(f"候选（mode={args.mode}）: {len(rows)} 本 | 假摘要={report['fake']} 短摘要={report['short']}")
    print(f"  有全文可重跑真实摘要: {report['has_text']} 本 | 无全文: {report['no_text']} 本")
    print(f"  （无全文的假摘要正式跑将{'清空' if args.clear_no_text else '跳过不清空'}）")
    if not rows:
        print("没有待修复书籍。")
        return
    if args.dry_run:
        print("\n--- 假摘要样本(前8, 确认判定准确) ---")
        shown = 0
        for r in rows:
            if is_fake_summary(r["summary"]):
                print(f"  [{r['id'][:8]}] {(r['summary'] or '')[:82]}")
                shown += 1
                if shown >= 8:
                    break
        print("…（dry-run 结束，未调用 Ollama）")
        return

    for i, r in enumerate(rows, 1):
        bid = r["id"]
        title = r["title"] or r["normalized_title"] or bid
        text_row = conn.execute("SELECT text_content FROM book_text WHERE id=?", (bid,)).fetchone()
        text = text_row["text_content"] if text_row else ""
        has_text = bool(text and len(text.strip()) >= 50)
        cur_fake = is_fake_summary(r["summary"])

        if cur_fake and not has_text:
            if args.clear_no_text:
                conn.execute("UPDATE books SET summary='' WHERE id=?", (bid,))
                conn.commit()
                C.mark_progress(pconn, bid, TOOL, "done")
                report["cleared"] += 1
                print(f"  [{i}/{len(rows)}] 清空假摘要(无全文)✅ {title[:24]}", flush=True)
            else:
                C.mark_progress(pconn, bid, TOOL, "skip")
                report["skip"] += 1
            continue

        if not has_text:
            C.mark_progress(pconn, bid, TOOL, "skip")
            report["skip"] += 1
            continue

        material = "\n".join([r["description"] or "", text[:3000]]).strip()
        prompt = (
            "你是图书摘要助手。根据下面素材，用中文写一段结构化摘要（3-5 个要点，每点一行，"
            "以「- 」开头，总字数 80-200 字）。只基于素材事实，不编造。\n"
            f"书名：《{title}》\n素材：{material[:3000]}"
        )
        resp = C.ollama_generate(prompt, model=model, timeout=180)
        if not resp or len(resp.strip()) < 50:
            C.mark_progress(pconn, bid, TOOL, "skip")
            report["skip"] += 1
            print(f"  [{i}/{len(rows)}] 跳过(模型无有效输出): {title[:24]}", flush=True)
            continue
        if any(k in resp for k in ("抱歉", "无法", "作为AI", "我是一个")):
            C.mark_progress(pconn, bid, TOOL, "skip")
            report["skip"] += 1
            print(f"  [{i}/{len(rows)}] 跳过(模型拒绝): {title[:24]}", flush=True)
            continue
        sets = ["summary=?"]
        params = [resp.strip()]
        if has_model:
            sets.append("summary_model=?")
            params.append(model)
        if has_upd:
            sets.append("summary_updated=CURRENT_TIMESTAMP")
        params.append(bid)
        conn.execute("UPDATE books SET " + ",".join(sets) + " WHERE id=?", params)
        conn.commit()
        C.mark_progress(pconn, bid, TOOL, "done")
        report["fixed"] += 1
        print(f"  [{i}/{len(rows)}] 已修复✅ {title[:26]}", flush=True)
        time.sleep(0.2)

    print(f"\n本轮：修复 {report['fixed']} 本 | 清空假摘要 {report['cleared']} 本 | 跳过 {report['skip']} 本")
    print("下次再跑会跳过已处理的（progress.db 续跑）。")


if __name__ == "__main__":
    main()
