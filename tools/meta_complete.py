# -*- coding: utf-8 -*-
# meta_complete.py — 离线可续跑元数据补全
# 不依赖主服务，直连 library.db；进度存 progress.db（skip/done/partial），停了不白跑。
# 数据源：Open Library（主源，直连无需代理） + Google Books（补充） + 豆瓣（仅 LIB_PROXY 配置时兜底）。
# 快模式(fast)：仅标题检索填 年份+ISBN+出版社（快）。全模式(full)：加 works/editions 详情补简介（慢，按需）。
import os
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import libtools_common as C

# 修复 Windows GBK 控制台无法输出书名中的 •/— 等字符导致 UnicodeEncodeError 崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

TOOL = "meta"


def select_pending(conn, pconn, limit, mode):
    # 排除集合：fast 排除 skip+partial；full 只排除 skip（会重试 partial）
    exclude = ("skip", "partial") if mode == "fast" else ("skip",)
    # 主库取候选（任一字段空），再在内存按进度表过滤（tool_progress 在独立 progress.db，不能跨库子查询）
    sql = """SELECT b.id,b.title,b.publisher,b.isbn,b.language,b.description,
                     b.normalized_title, MAX(a.name) AS author
              FROM books b
              LEFT JOIN book_authors ba ON ba.book_id=b.id
              LEFT JOIN authors a ON a.id=ba.author_id
              WHERE b.status='active'
                AND (b.publisher IS NULL OR b.publisher='' OR b.isbn IS NULL OR b.isbn=''
                     OR b.description IS NULL OR b.description='')
              GROUP BY b.id
              ORDER BY b.id"""
    rows = conn.execute(sql).fetchall()
    smap = {bid: st for (bid, st) in pconn.execute(
        "SELECT book_id,status FROM tool_progress WHERE tool=?", (TOOL,))}
    return [r for r in rows if smap.get(r["id"]) not in exclude][:limit]


def all_filled(conn, bid):
    r = conn.execute(
        "SELECT publisher,isbn,description FROM books WHERE id=?", (bid,)
    ).fetchone()
    if not r:
        return True
    return bool(r["publisher"]) and bool(r["isbn"]) and bool(r["description"])


def main():
    ap = argparse.ArgumentParser(description="离线元数据补全（可续跑）")
    ap.add_argument("--limit", type=int, default=None, help="本次处理数量")
    ap.add_argument("--mode", choices=["fast", "full"], default="fast")
    ap.add_argument("--retry-skips", action="store_true", help="清除 skip 后重试")
    ap.add_argument("--status", action="store_true", help="仅显示进度")
    ap.add_argument("--proxy", help="国际代理，如 http://127.0.0.1:7890")
    args = ap.parse_args()

    if args.proxy:
        os.environ["LIB_PROXY"] = args.proxy
    cfg = C.load_config()
    if cfg.get("proxy") and "LIB_PROXY" not in os.environ:
        os.environ["LIB_PROXY"] = cfg["proxy"]
    limit = args.limit or cfg.get("default_limit", 200)

    conn = C.get_conn()
    try:
        conn.execute("PRAGMA busy_timeout=60000")  # 写锁等待提到60s，避免与Web服务偶发写冲突
    except Exception:
        pass
    pconn = C.get_progress_conn()
    C.ensure_progress(pconn)

    if args.retry_skips:
        C.clear_status(pconn, TOOL, "skip")
        print("已清除 skip 记录，下一轮将重新尝试这些书。")
        return

    if args.status:
        total = conn.execute("SELECT COUNT(*) FROM books WHERE status='active'").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM books b WHERE b.status='active' "
            "AND (b.publisher IS NULL OR b.publisher='' OR b.isbn IS NULL OR b.isbn='' "
            "OR b.description IS NULL OR b.description='')"
        ).fetchone()[0]
        skipped = pconn.execute("SELECT COUNT(*) FROM tool_progress WHERE tool=? AND status='skip'", (TOOL,)).fetchone()[0]
        done = pconn.execute("SELECT COUNT(*) FROM tool_progress WHERE tool=? AND status='done'", (TOOL,)).fetchone()[0]
        partial = pconn.execute("SELECT COUNT(*) FROM tool_progress WHERE tool=? AND status='partial'", (TOOL,)).fetchone()[0]
        print(f"总书: {total}")
        print(f"仍有空字段待补: {pending}")
        print(f"已标记完成(done): {done}")
        print(f"已部分补(partial,待full): {partial}")
        print(f"已跳过(skip,无匹配): {skipped}")
        print("提示: 直接 run_meta.bat 跑一批；--mode full 补出版社+简介；--status 看进度。")
        return

    rows = select_pending(conn, pconn, limit, args.mode)
    print(f"本轮选取 {len(rows)} 本（mode={args.mode}）；每次停了再来都不白跑。")
    if not rows:
        print("没有待处理书籍了（或都已被标记 skip/partial，可用 --retry-skips / --mode full 重试）。")
        return

    detail = (args.mode == "full")
    rv = {"filled": 0, "skip": 0, "partial": 0}
    t0 = time.time()
    for i, b in enumerate(rows, 1):
        b = dict(b)
        bid = b["id"]
        norm = b["normalized_title"] or ""
        try:
            meta = C.fetch_online_metadata(
                b["title"], b["author"] or "", b["isbn"] or "",
                normalized_title=norm, detail=detail,
            )
        except Exception as e:
            print(f"  [{i}/{len(rows)}] 异常 {b['title'][:20]}: {e}", flush=True)
            meta = None
        if not meta:
            C.mark_progress(pconn, bid, TOOL, "skip")
            rv["skip"] += 1
            print(f"  [{i}/{len(rows)}] 跳过(无候选): {b['title'][:28]}", flush=True)
            continue
        sim = meta.get("sim", 0)
        isbn_match = bool(b["isbn"]) and meta.get("isbn") and b["isbn"].replace("-", "") == meta["isbn"].replace("-", "")
        trusted = (bool(meta.get("trusted")) or isbn_match or sim >= 0.7
                   or (sim >= 0.55 and meta.get("description")) or (sim >= 0.6 and meta.get("publisher")))
        if not trusted:
            C.mark_progress(pconn, bid, TOOL, "skip")
            rv["skip"] += 1
            print(f"  [{i}/{len(rows)}] 跳过(相似度不足 {sim:.2f}): {b['title'][:24]}", flush=True)
            continue
        # 仅填当前为空字段
        sets, params = [], []
        for col in ("publisher", "publish_date", "isbn", "language", "description"):
            cur = (b.get(col) or "").strip()
            v = (meta.get(col) or "").strip()
            if not cur and v:
                sets.append(col + "=?")
                params.append(v[:2000] if col == "description" else v)
        if not sets:
            # 候选没带来任何新字段
            C.mark_progress(pconn, bid, TOOL, "partial" if args.mode == "fast" else "skip")
            rv["partial"] += 1
            print(f"  [{i}/{len(rows)}] 无新增字段(标记partial): {b['title'][:24]}", flush=True)
            continue
        sets.append("metadata_source=?"); params.append(meta.get("source", ""))
        sets.append("metadata_conf=?"); params.append(round(sim, 2))
        params.append(bid)
        # 写库加锁重试：Web服务(8000)偶发写/长事务会持锁，撞 locked 不崩溃、等锁释放后继续
        _written = False
        for _att in range(30):
            try:
                conn.execute("UPDATE books SET " + ", ".join(sets) + " WHERE id=?", params)
                conn.commit()
                _written = True
                break
            except Exception as e:
                if "locked" in str(e).lower():
                    time.sleep(2)
                    continue
                raise
        if not _written:
            raise RuntimeError("books 写锁重试耗尽(30次)")
        if all_filled(conn, bid):
            C.mark_progress(pconn, bid, TOOL, "done")
            print(f"  [{i}/{len(rows)}] 完成✅ {b['title'][:26]} (sim {sim:.2f})", flush=True)
        else:
            C.mark_progress(pconn, bid, TOOL, "partial")
            rv["partial"] += 1
            print(f"  [{i}/{len(rows)}] 部分补(partial): {b['title'][:22]}", flush=True)
        rv["filled"] += 1
        time.sleep(0.4 if args.mode == "fast" else 1.0)
    dt = time.time() - t0
    print(f"\n本轮结束：填充 {rv['filled']} 本 | 部分 {rv['partial']} | 跳过 {rv['skip']} | 用时 {dt:.0f}s")
    print("下次直接再跑 run_meta.bat 即可续跑。")


if __name__ == "__main__":
    main()
