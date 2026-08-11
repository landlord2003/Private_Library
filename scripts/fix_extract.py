import re

with open('simple_server.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_func = '''def extract_text_for(book_id, file_path, fmt):
    try:
        file_path = _resolve_path(file_path)
        text = ""
        if fmt == 'pdf':
            import fitz
            doc = fitz.open(file_path)
            for i, page in enumerate(doc):
                if i >= 100: break
                text += page.get_text()
            doc.close()
            # Scanned PDF fallback: use title as minimal text
            if not text.strip():
                r = dbq("SELECT title,publisher,description FROM books WHERE id=?",(book_id,))
                if r:
                    parts = [r[0]['title'] or '']
                    if r[0]['publisher']: parts.append('Publisher: ' + r[0]['publisher'])
                    if r[0]['description']: parts.append(r[0]['description'])
                    text = '\\n'.join(parts)'''

new_func = '''def _title_fallback(book_id):
    """Use book metadata as minimal text for books that can't be extracted."""
    r = dbq("SELECT title,publisher,description FROM books WHERE id=?",(book_id,))
    if r:
        parts = [r[0]['title'] or '']
        if r[0]['publisher']: parts.append('Publisher: ' + r[0]['publisher'])
        if r[0]['description']: parts.append(r[0]['description'])
        text = '\\n'.join(parts)
        if text.strip():
            dbe("UPDATE books SET text_content=? WHERE id=?", (text[:200000], book_id))
            return True
    return False

def extract_text_for(book_id, file_path, fmt):
    try:
        file_path = _resolve_path(file_path)
        if not os.path.exists(file_path):
            print(f"[跳过] 文件不存在: {file_path}", flush=True)
            return _title_fallback(book_id)
        # Get file size from DB to decide strategy
        meta = dbq("SELECT file_size,title FROM books WHERE id=?",(book_id,))
        fsize = meta[0]['file_size'] if meta and meta[0]['file_size'] else 0
        size_mb = fsize / 1024 / 1024
        title_short = meta[0]['title'][:40] if meta else '?'
        # Large files (>50MB): skip extraction, use title fallback
        if size_mb > 50:
            print(f"[跳过大文件] {size_mb:.0f}MB {fmt} {title_short}", flush=True)
            return _title_fallback(book_id)
        text = ""
        if fmt == 'pdf':
            import fitz
            doc = fitz.open(file_path)
            # Limit pages based on file size for speed
            if size_mb > 20: max_pages = 5
            elif size_mb > 10: max_pages = 15
            else: max_pages = 30
            for i, page in enumerate(doc):
                if i >= max_pages: break
                text += page.get_text()
            doc.close()
            # Scanned PDF fallback: use title as minimal text
            if not text.strip():
                print(f"[扫描版PDF] 无文字层, 用书名兜底: {title_short}", flush=True)
                return _title_fallback(book_id)'''

if old_func in content:
    content = content.replace(old_func, new_func)
    print("Replaced extract_text_for start")
else:
    print("ERROR: old_func not found!")
    # Try to find it
    idx = content.find('def extract_text_for')
    if idx >= 0:
        print(f"Found at index {idx}")
        print(repr(content[idx:idx+200]))
    exit(1)

# Also replace the fallback at the end of the function
old_end = '''        if text and len(text.strip()) > 10:
            text = text[:200000]
            dbe("UPDATE books SET text_content=? WHERE id=?", (text, book_id))
            return True
        return False
    except Exception as e:
        print(f"[文本提取异常] {file_path}: {type(e).__name__}: {e}", flush=True)
        return False'''

new_end = '''        if text and len(text.strip()) > 10:
            text = text[:200000]
            dbe("UPDATE books SET text_content=? WHERE id=?", (text, book_id))
            return True
        # Fallback: use title if extraction yielded nothing
        return _title_fallback(book_id)
    except Exception as e:
        print(f"[文本提取异常] {file_path}: {type(e).__name__}: {e}", flush=True)
        return _title_fallback(book_id)'''

if old_end in content:
    content = content.replace(old_end, new_end)
    print("Replaced extract_text_for end")
else:
    print("ERROR: old_end not found!")
    exit(1)

with open('simple_server.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Done!")
