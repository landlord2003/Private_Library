s = open("simple_server.py", "r", encoding="utf-8").read()

# Find _upload and add text extraction
old = '''    def _upload(self,ctype,body):
        fields = parse_multipart(ctype, body)
        if not fields or 'file' not in fields:self.json({"error":"parse"});return
        f = fields['file']
        if not f['filename']:self.json({"error":"no filename"});return
        data,fn=f['data'],f['filename']
        ext=os.path.splitext(fn)[1].lower()
        E={'.pdf','.epub','.mobi','.azw3','.azw','.txt','.md','.zip','.rar','.7z'}
        if ext not in E:self.json({"error":"bad format"});return
        if len(data)==0:self.json({"error":"empty"});return
        h=hashlib.sha256();h.update(data);fh=h.hexdigest()
        if dbq("SELECT id FROM books WHERE file_hash=?",(fh,)):self.json({"duplicate":True});return
        bid=str(uuid.uuid4());dd=os.path.join("data","books",bid);os.makedirs(dd,exist_ok=True)
        dest=os.path.join(dd,"original"+ext)
        with open(dest,'wb')as f:f.write(data)
        fmt=ext.lstrip('.')
        dbe("INSERT INTO books(id,title,file_path,file_format,file_size,file_hash,status)VALUES(?,?,?,?,?,?,'active')",(bid,os.path.splitext(fn)[0],dest,fmt,len(data),fh))
        extract_cover_for(bid,dest,fmt)
        self.json({"success":True,"id":bid,"title":fn})'''

new = '''    def _upload(self,ctype,body):
        fields = parse_multipart(ctype, body)
        if not fields or 'file' not in fields:self.json({"error":"parse"});return
        f = fields['file']
        if not f['filename']:self.json({"error":"no filename"});return
        data,fn=f['data'],f['filename']
        ext=os.path.splitext(fn)[1].lower()
        E={'.pdf','.epub','.mobi','.azw3','.azw','.txt','.md','.zip','.rar','.7z'}
        if ext not in E:self.json({"error":"bad format"});return
        if len(data)==0:self.json({"error":"empty"});return
        h=hashlib.sha256();h.update(data);fh=h.hexdigest()
        if dbq("SELECT id FROM books WHERE file_hash=?",(fh,)):self.json({"duplicate":True});return
        bid=str(uuid.uuid4());dd=os.path.join("data","books",bid);os.makedirs(dd,exist_ok=True)
        dest=os.path.join(dd,"original"+ext)
        with open(dest,'wb')as f:f.write(data)
        fmt=ext.lstrip('.')
        dbe("INSERT INTO books(id,title,file_path,file_format,file_size,file_hash,status)VALUES(?,?,?,?,?,?,'active')",(bid,os.path.splitext(fn)[0],dest,fmt,len(data),fh))
        extract_cover_for(bid,dest,fmt)
        # Extract text content
        text = ""
        try:
            if fmt == 'pdf':
                import fitz
                doc = fitz.open(dest)
                parts = []
                for i in range(min(50, doc.page_count)):
                    parts.append(doc[i].get_text())
                text = "".join(parts).strip()
                doc.close()
            elif fmt == 'epub':
                from ebooklib import epub
                bk = epub.read_epub(dest)
                for it in bk.get_items():
                    if it.get_type() == 9:
                        try: text += it.get_content().decode('utf-8', 'ignore')
                        except: pass
            elif fmt in ('txt', 'md'):
                text = data.decode('utf-8', 'ignore')
            if text and len(text) > 50:
                dbe("UPDATE books SET text_content=? WHERE id=?", (text[:50000], bid))
        except: pass
        self.json({"success":True,"id":bid,"title":fn})'''

s = s.replace(old, new)
open("simple_server.py", "w", encoding="utf-8").write(s)
print("Patched")
