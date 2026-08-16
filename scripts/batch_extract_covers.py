#!/usr/bin/env python
"""批量提取封面 - 多进程并行版"""
import os, sys, time, sqlite3
from multiprocessing import Pool, cpu_count

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEVEN_ZIP = r"C:\Program Files\7-Zip\7z.exe"

def _resolve_path(file_path):
    file_path = file_path.replace('/', '\\')
    if not os.path.isabs(file_path):
        file_path = os.path.join(BASE_DIR, file_path)
    if os.path.exists(file_path):
        return file_path
    for drive in "CDEFGHIJK":
        alt = drive + file_path[1:]
        if os.path.exists(alt):
            return alt
    return file_path

def _extract_epub_cover_zip(file_path):
    """从 EPUB ZIP 中直接提取封面图片（快速路径，~0.01s/本）"""
    import zipfile, xml.etree.ElementTree as ET
    OPF = '{http://www.idpf.org/2007/opf}'
    CNT = '{urn:oasis:names:tc:opendocument:xmlns:container}'
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            croot = ET.fromstring(zf.read('META-INF/container.xml'))
            opf_path = None
            for rf in croot.iter(CNT + 'rootfile'):
                if rf.get('media-type') == 'application/oebps-package+xml':
                    opf_path = rf.get('full-path'); break
            if not opf_path: return None
            oroot = ET.fromstring(zf.read(opf_path))
            opf_dir = opf_path.rsplit('/', 1)[0] + '/' if '/' in opf_path else ''
            items = {}
            for item in oroot.iter(OPF + 'item'):
                iid = item.get('id'); items[iid] = {
                    'href': item.get('href',''), 'mt': item.get('media-type',''),
                    'props': item.get('properties','')
                }
            cover_id = None
            for meta in oroot.iter(OPF + 'meta'):
                if meta.get('name') == 'cover': cover_id = meta.get('content'); break
            if not cover_id:
                for iid, it in items.items():
                    if 'cover-image' in it['props']: cover_id = iid; break
            if not cover_id:
                for iid, it in items.items():
                    if 'cover' in iid.lower() and it['mt'].startswith('image/'): cover_id = iid; break
            if not cover_id or cover_id not in items: return None
            href = items[cover_id]['href']
            for path in [opf_dir + href, href]:
                try:
                    data = zf.read(path)
                    if len(data) > 500: return data
                except KeyError: continue
    except: pass
    return None

def _init_worker():
    """每个 worker 进程启动时抑制 MuPDF 及 SWIG 回调的所有 stdout/stderr 输出"""
    _dn = os.open(os.devnull, os.O_WRONLY)
    os.dup2(_dn, 1)
    os.dup2(_dn, 2)
    os.close(_dn)

def worker(args):
    bid, file_path, fmt = args
    # 先检查封面文件是否已存在（可能之前运行已提取但 DB 未更新）
    cvp = os.path.join(BASE_DIR, "data", "covers", bid + ".jpg")
    if os.path.exists(cvp):
        if os.path.getsize(cvp) > 500:
            return (bid, True)  # 有效封面已存在
        else:
            try: os.remove(cvp)  # 清理 0 字节文件
            except: pass
    try:
        file_path = _resolve_path(file_path)
        cover_data = None

        if fmt == 'epub':
            cover_data = _extract_epub_cover_zip(file_path)
            if not cover_data:
                import fitz
                doc = fitz.open(file_path)
                if doc.page_count > 0:
                    pix = doc[0].get_pixmap(dpi=72)
                    cover_data = pix.tobytes("jpg")
                doc.close()
        elif fmt in ('pdf', 'mobi', 'azw3'):
            import fitz
            doc = fitz.open(file_path)
            if doc.page_count > 0:
                pix = doc[0].get_pixmap(dpi=72)
                cover_data = pix.tobytes("jpg")
            doc.close()
        elif fmt in ('rar', 'zip'):
            import tempfile, subprocess, shutil
            r = subprocess.run([SEVEN_ZIP, 'l', '-slt', '-sccUTF-8', file_path],
                             capture_output=True, text=True, timeout=30)
            entries = []; cur = {}
            for line in r.stdout.split('\n'):
                if line.startswith('Path ='): cur['path'] = line[7:].strip()
                elif line.startswith('Size ='):
                    s = line[7:].strip()
                    cur['size'] = int(s) if s.isdigit() else 0
                elif line == '' and 'path' in cur: entries.append(cur); cur = {}
            if 'path' in cur: entries.append(cur)

            pdf_entry = next((e for e in entries
                if e['path'].lower().endswith('.pdf') and e.get('size',0) > 10000), None)
            if pdf_entry:
                tmpdir = tempfile.mkdtemp()
                try:
                    subprocess.run([SEVEN_ZIP, 'e', '-o'+tmpdir, '-sccUTF-8', '-y',
                                  file_path, pdf_entry['path']],
                                 capture_output=True, timeout=60)
                    tmp_pdf = os.path.join(tmpdir, os.path.basename(pdf_entry['path']))
                    if os.path.exists(tmp_pdf):
                        import fitz
                        doc = fitz.open(tmp_pdf)
                        if doc.page_count > 0:
                            pix = doc[0].get_pixmap(dpi=72)
                            cover_data = pix.tobytes("jpg")
                        doc.close()
                finally:
                    shutil.rmtree(tmpdir, ignore_errors=True)

            if not cover_data:
                img_entry = next((e for e in entries
                    if e['path'].lower().endswith(('.jpg','.jpeg','.png','.bmp'))
                    and e.get('size',0) > 5000), None)
                if img_entry:
                    tmpdir = tempfile.mkdtemp()
                    try:
                        subprocess.run([SEVEN_ZIP, 'e', '-o'+tmpdir, '-sccUTF-8', '-y',
                                      file_path, img_entry['path']],
                                     capture_output=True, timeout=60)
                        tmp_img = os.path.join(tmpdir, os.path.basename(img_entry['path']))
                        if os.path.exists(tmp_img):
                            with open(tmp_img, 'rb') as f: cover_data = f.read()
                    finally:
                        shutil.rmtree(tmpdir, ignore_errors=True)

        if cover_data and len(cover_data) > 500:
            cvp = os.path.join(BASE_DIR, "data", "covers", bid + ".jpg")
            os.makedirs(os.path.dirname(cvp), exist_ok=True)
            try:
                with open(cvp, 'wb') as f: f.write(cover_data)
            except PermissionError:
                try:
                    os.remove(cvp)
                    with open(cvp, 'wb') as f: f.write(cover_data)
                except:
                    return (bid, False)
            return (bid, True)
    except:
        pass
    return (bid, False)

if __name__ == '__main__':
    os.chdir(BASE_DIR)
    conn = sqlite3.connect('data/library.db')
    c = conn.cursor()
    c.execute("""SELECT id, file_path, file_format FROM books
        WHERE (cover_path IS NULL OR cover_path = '') AND file_format != 'txt'
        ORDER BY file_format, id""")
    books = c.fetchall()
    # 保持单连接用于 DB 更新（避免反复开关连接导致锁冲突）
    db_path = os.path.join(BASE_DIR, 'data', 'library.db')
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    n = len(books)
    print(f"共 {n} 本书需要提取封面", flush=True)
    fmt_counts = {}
    for _, _, fmt in books:
        fmt_counts[fmt] = fmt_counts.get(fmt, 0) + 1
    for fmt, cnt in sorted(fmt_counts.items()):
        print(f"  {fmt}: {cnt} 本", flush=True)

    nproc = min(6, cpu_count() or 4)
    print(f"使用 {nproc} 个进程并行处理\n", flush=True)

    success = 0
    fail = 0
    t0 = time.time()

    with Pool(processes=nproc, initializer=_init_worker) as pool:
        for i, (bid, ok) in enumerate(pool.imap_unordered(worker, books, chunksize=10)):
            if ok:
                success += 1
                try:
                    conn.execute("UPDATE books SET cover_path=? WHERE id=?",
                                 (os.path.join("data", "covers", bid + ".jpg"), bid))
                    conn.commit()
                except:
                    pass  # DB 更新失败不影响封面文件
            else:
                fail += 1

            if (i + 1) % 100 == 0 or i == n - 1:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (n - i - 1) / rate if rate > 0 else 0
                print(f"  [{i+1}/{n}] OK={success} FAIL={fail} {rate:.1f}/s ETA={eta:.0f}s", flush=True)

    elapsed = time.time() - t0
    print(f"\n=== 完成 ===", flush=True)
    print(f"总耗时: {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)", flush=True)
    print(f"成功: {success} / {n}", flush=True)
    print(f"失败: {fail}", flush=True)

    c = conn.cursor()
    c.execute("""SELECT file_format, COUNT(*),
        SUM(CASE WHEN cover_path IS NOT NULL AND cover_path != '' THEN 1 ELSE 0 END)
        FROM books GROUP BY file_format ORDER BY file_format""")
    print("\n=== 最终覆盖率 ===", flush=True)
    total_all = 0; total_cover = 0
    for fmt, total, has_cover in c.fetchall():
        total_all += total; total_cover += has_cover
        pct = has_cover * 100 / total if total > 0 else 0
        print(f"  {fmt}: {has_cover}/{total} ({pct:.1f}%)", flush=True)
    print(f"  总计: {total_cover}/{total_all} ({total_cover*100/total_all:.1f}%)", flush=True)
    conn.close()
