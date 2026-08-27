#!/usr/bin/env python3
# 健壮版全量文本抽取（替代服务端单线程 run_extract_async）。
# - 多线程(max_workers) 避免单本 fitz 卡死阻塞全量
# - 每本硬超时(60s)，超时被丢弃并标记 skip，不影响其他书
# - 进度落盘(_extract_run.log)，可续跑：重抽 text_content<=10 或 NULL 且 text_extracted<>1 的书
import sys, os, time, sqlite3, traceback, concurrent.futures as cf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import Private_Lib as P

DB = r"F:/my-library/data/library.db"
WORKERS = 4
PER_BOOK_TIMEOUT = 60
# ocr 模式用独立日志，避免与全量抽取日志混写导致进度误读
_MODE = sys.argv[1] if len(sys.argv) > 1 else ""
LOG = r"F:/my-library/tools/_ocr_run.log" if _MODE == "ocr" else r"F:/my-library/tools/_extract_run.log"

logf = open(LOG, "a", encoding="utf-8")
def L(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True); logf.write(s + "\n"); logf.flush()

def work(bid, fpath, ff):
    try:
        ok = P.extract_text_for(bid, fpath, ff)
        return (bid, True if ok else False, None)
    except Exception as e:
        return (bid, False, f"{type(e).__name__}: {e}")

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    con = sqlite3.connect(DB, timeout=30)
    if mode == "ocr":
        # OCR 重跑模式：仅重抽「已抽过(text_extracted=1)但正文极短(<=200字,疑似书名兜底)」的 PDF。
        # 适用场景：装好 tesseract+chi_sim 后，把之前因无 OCR 而回落书名的扫描版 PDF 重新识别。
        # 注意：>50MB 大文件在 extract_text_for 内仍走跳过逻辑(不 OCR)，故超大扫描版需另行处理。
        q = """SELECT b.id,b.file_path,b.file_format FROM books b
               JOIN book_text bt ON bt.id=b.id
               WHERE b.status='active' AND b.file_format='pdf'
                 AND b.text_extracted=1 AND length(bt.text_content)<=200"""
        L("[mode] ocr-rerun: 仅重抽疑似书名兜底的扫描版PDF(正文<=200字)")
    else:
        # 仅按 text_extracted 标志筛选：text_extracted=1 的书必有真实正文，其余(text_extracted=0/NULL)都需(重)抽取。
        # 不再扫 book_text 的 length()（会读全量 3GB 文本导致 MemoryError）。
        q = """SELECT b.id,b.file_path,b.file_format FROM books b
               WHERE b.status='active' AND b.text_extracted<>1"""
    rows = con.execute(q).fetchall()
    con.close()
    # 大文件预标记：>50MB 的文件在 extract_text_for 内走跳过逻辑(不抽正文，仅回落书名)，
    # 但不会置 text_extracted=1，导致续跑/OCR 模式反复把它们重选进来死循环。
    # 这里一次性标记为大文件已处理(置 text_extracted=1, 空正文)，移出候选集，
    # 两种模式(全量/ocr)都排除，避免对超大扫描版反复抽。
    BIG = 50 * 1024 * 1024
    big_ids, real_rows = [], []
    for r in rows:
        try:
            if os.path.getsize(r[1]) > BIG:
                big_ids.append(r[0]); continue
        except OSError:
            pass
        real_rows.append(r)
    if big_ids:
        c2 = sqlite3.connect(DB, timeout=30)
        c2.executemany("UPDATE books SET text_extracted=1 WHERE id=?", [(i,) for i in big_ids])
        c2.commit(); c2.close()
        L(f"[skip-big] marked {len(big_ids)} files >50MB as processed (excluded from resume/ocr)")
    rows = real_rows
    workers = 2 if mode == "ocr" else WORKERS
    timeout = 180 if mode == "ocr" else PER_BOOK_TIMEOUT
    L(f"[start] candidates={len(rows)} mode={mode} workers={workers} timeout={timeout}s")
    done = extracted = skipped = 0
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, r[0], r[1], r[2]): r for r in rows}
        for fut in cf.as_completed(futs):
            try:
                bid, ok, err = fut.result(timeout=timeout)
            except cf.TimeoutError:
                bid = futs[fut][0]
                skipped += 1; done += 1
                L(f"  timeout {bid[:8]} (fitz hang, skipped)"); continue
            done += 1
            if ok:
                extracted += 1
            else:
                skipped += 1
                if err: L(f"  skip {bid[:8]}: {err}")
            if done % 50 == 0:
                dt = time.time() - t0
                L(f"[prog] done={done}/{len(rows)} extracted={extracted} skipped={skipped} elapsed={dt:.0f}s rate={done/dt:.1f}/s")
    L(f"[done] total={len(rows)} extracted={extracted} skipped={skipped} elapsed={time.time()-t0:.0f}s")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        L("FATAL"); traceback.print_exc(file=logf)
