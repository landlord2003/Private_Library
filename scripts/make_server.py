# 这个脚本会生成新的 simple_server.py
import json

code = r'''"""极简服务器"""
import http.server, json, sqlite3, os, urllib.parse
from pathlib import Path

DB = "data/library.db"

def dbq(sql, params=()):
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    r = [dict(row) for row in c.execute(sql, params).fetchall()]
    c.close()
    return r

def dbe(sql, params=()):
    c = sqlite3.connect(DB, timeout=10)
    c.execute(sql, params)
    c.commit()
    c.close()

def he(s):
    return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def fc(f):
    d = {'pdf':'#ff4d4f','epub':'#1677ff','mobi':'#52c41a','txt':'#666','md':'#722ed1'}
    return d.get(f, '#999')

def cc(c):
    d = {'\u8ba1\u7b97\u673a\u4e0e\u7f16\u7a0b':'#1677ff','\u5386\u53f2\u4e0e\u4eba\u6587':'#fa8c16','\u6587\u5b66\u4e0e\u5c0f\u8bf4':'#52c41a','\u54f2\u5b66\u4e0e\u601d\u60f3':'#722ed1','\u79d1\u5b66\u4e0e\u79d1\u666e':'#13c2c2','\u7ecf\u6d4e\u4e0e\u7ba1\u7406':'#eb2f96','\u5fc3\u7406\u4e0e\u6210\u957f':'#fa541c','\u6559\u80b2\u5b66\u4e60':'#2f54eb','\u827a\u672f\u8bbe\u8ba1':'#a0d911','\u793e\u4f1a\u4e0e\u653f\u6cbb':'#f5222d','\u751f\u6d3b\u4e0e\u5065\u5eb7':'#7cb305','\u5176\u4ed6':'#999'}
    return d.get(c, '#999')

CSS = "* { margin:0; padding:0; box-sizing:border-box; } body { font-family: 'Microsoft YaHei', Arial, sans-serif; background: #f5f5f5; display: flex; min-height: 100vh; } nav { width: 200px; background: #fff; padding: 20px 0; box-shadow: 2px 0 8px rgba(0,0,0,0.05); } nav h2 { padding: 0 20px 20px; color: #1677ff; font-size: 18px; border-bottom: 1px solid #f0f0f0; margin-bottom: 10px; } nav a { display: block; padding: 12px 20px; color: #333; text-decoration: none; font-size: 15px; } nav a:hover { background: #e6f4ff; color: #1677ff; } main { flex: 1; padding: 24px; overflow-y: auto; } .box { background: #fff; padding: 20px; border-radius: 8px; text-align: center; min-width: 140px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); } .box .n { font-size: 28px; font-weight: bold; } .box .l { font-size: 13px; color: #999; margin-top: 4px; } .row { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; } .tag { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 12px; margin: 3px; color: #fff; } .panel { background: #fff; padding: 16px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); } .panel h3 { margin-bottom: 12px; font-size: 16px; } .search { display: flex; gap: 8px; margin-bottom: 16px; } .search input { padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; flex: 1; } .search button { padding: 8px 20px; background: #1677ff; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; } .book { background: #fff; border-radius: 8px; padding: 14px; margin-bottom: 8px; display: flex; gap: 12px; align-items: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); } .book img { width: 50px; height: 70px; object-fit: cover; border-radius: 4px; flex-shrink: 0; } .book .cv { width: 50px; height: 70px; border-radius: 4px; flex-shrink: 0; background: linear-gradient(135deg, #667eea, #764ba2); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 22px; } .book .info { flex: 1; min-width: 0; } .book .t { font-weight: bold; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .book .m { font-size: 12px; color: #999; margin-top: 4px; } a { color: #1677ff; text-decoration: none; } a:hover { text-decoration: underline; } .col { color: #999; } .btn { padding: 8px 20px; background: #1677ff; color: #fff; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; margin-top: 4px; }"

NAV = '<nav><h2>📚 我的图书馆</h2><a href="/">🏠 首页</a><a href="/?p=books">📖 书库 ({BOOKS})</a><a href="/?p=media">🎧 媒体库 ({MEDIA})</a><a href="/?p=import">📥 导入新书</a></nav>'

class H(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        p = urllib.parse.urlparse(self.path); path = p.path
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}
        try:
            if path == "/api/import-scan":
                SCAN_DIR = body.get('dir', r'F:\书籍')
                if not os.path.exists(SCAN_DIR):
                    self.json({"error":"not found"}); return
                import hashlib, uuid, shutil
                E = {'.pdf','.epub','.mobi','.azw3','.azw','.txt','.md'}
                nb, db, eb = 0, 0, 0
                for d,_,fs in os.walk(SCAN_DIR):
                    for fn in fs:
                        if fn.startswith('.'): continue
                        ext = os.path.splitext(fn)[1].lower()
                        if ext not in E: continue
                        fp = os.path.join(d, fn)
                        try:
                            h = hashlib.sha256()
                            with open(fp,'rb') as f:
                                for c in iter(lambda:f.read(8192),b''): h.update(c)
                            fh = h.hexdigest()
                            if dbq("SELECT id FROM books WHERE file_hash=?",(fh,)):
                                db += 1; continue
                            id = str(uuid.uuid4()); dd = os.path.join("data","books",id)
                            os.makedirs(dd, exist_ok=True)
                            dest = os.path.join(dd,"original"+ext)
                            shutil.copy2(fp, dest)
                            dbe("INSERT INTO books(id,title,file_path,file_format,file_size,file_hash,status,import_source) VALUES(?,?,?,?,?,?,'active','scan')",
                                (id, os.path.splitext(fn)[0], dest, ext[1:], os.path.getsize(fp), fh))
                            nb += 1
                        except: eb += 1
                self.json({"new":nb,"dupes":db,"errors":eb})
            else: self.send_error(404)
        except Exception as e: self.send_error(500, str(e))

    def do_GET(self):
        p = urllib.parse.urlparse(self.path); path = p.path; qs = urllib.parse.parse_qs(p.query)
        try:
            if path == "/api/health": self.json({"status":"ok"})
            elif path.startswith("/api/books/") and path.endswith("/read"):
                bid = path.split("/")[3]
                r = dbq("SELECT file_path,file_format,title FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp, fmt, title = r[0]['file_path'], r[0]['file_format'], r[0]['title']
                if not os.path.exists(fp): self.send_error(404); return
                if fmt == 'epub':
                    try:
                        from ebooklib import epub; from bs4 import BeautifulSoup
                        bk = epub.read_epub(fp); st, bp = [], []
                        for it in bk.get_items():
                            if it.get_type()==5:
                                try: st.append(it.get_content().decode('utf-8','ignore'))
                                except: pass
                            elif it.get_type()==9:
                                try:
                                    sp = BeautifulSoup(it.get_content(),'html.parser')
                                    b = sp.find('body'); bp.append(str(b) if b else str(sp))
                                except: pass
                        h = '<!DOCTYPE html><html><head><meta charset=utf-8><title>'+title+'</title>'
                        for s in st[:3]: h += '<style>'+s+'</style>'
                        h += '<style>body{max-width:800px;margin:0 auto;padding:20px;font-family:serif;font-size:18px;line-height:1.8}img{max-width:100%}</style></head><body><h1>'+title+'</h1>'+'\n'.join(bp)+'</body></html>'
                        self._html(h)
                    except: self.send_error(500)
                else:
                    r2 = dbq("SELECT text_content FROM books WHERE id=?",(bid,))
                    t = (r2[0]['text_content'] if r2 else '') or ''
                    t = t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                    h = '<!DOCTYPE html><html><head><meta charset=utf-8><title>'+title+'</title><style>body{max-width:800px;margin:0 auto;padding:20px;font-family:serif;font-size:18px;line-height:2;white-space:pre-wrap}</style></head><body><h1>'+title+'</h1><div>'+t+'</div></body></html>'
                    self._html(h)
            elif path.startswith("/api/books/") and path.endswith("/file"):
                bid = path.split("/")[3]
                r = dbq("SELECT file_path,file_format FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp, fmt = r[0]['file_path'], r[0]['file_format']
                if os.path.exists(fp):
                    self.send_response(200)
                    self.send_header("Content-Type",{"pdf":"application/pdf"}.get(fmt,"application/octet-stream"))
                    self.send_header("Content-Disposition","inline"); self.end_headers()
                    with open(fp,'rb') as f: self.wfile.write(f.read())
                else: self.send_error(404)
            elif path.startswith("/api/media/") and path.endswith("/file"):
                bid = path.split("/")[3]
                r = dbq("SELECT file_path,file_format FROM media WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp, fmt = r[0]['file_path'], r[0]['file_format']
                if os.path.exists(fp):
                    self.send_response(200)
                    self.send_header("Content-Type",{"mp3":"audio/mpeg","mp4":"video/mp4"}.get(fmt,"application/octet-stream"))
                    self.end_headers()
                    with open(fp,'rb') as f: self.wfile.write(f.read())
                else: self.send_error(404)
            elif path.startswith("/api/covers/"):
                cv = Path("data/covers") / path.split("/")[-1]
                if cv.exists():
                    self.send_response(200); self.send_header("Content-Type","image/jpeg"); self.end_headers()
                    with open(cv,'rb') as f: self.wfile.write(f.read())
                else: self.send_error(404)
            elif path.startswith("/api/books/") or path.startswith("/api/media/"):
                bid = path.split("/")[3]; tbl = "books" if "books" in path else "media"
                r = dbq("SELECT * FROM "+tbl+" WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                self.json(dict(r[0]))
            elif path == "/api/books":
                pg = int(qs.get('page',[1])[0]); sz = int(qs.get('page_size',[20])[0])
                c = "id,title,file_format,file_size,cover_path,status,summary,difficulty,created_at"
                rows = dbq("SELECT "+c+" FROM books WHERE status='active' ORDER BY created_at DESC LIMIT "+str(sz)+" OFFSET "+str((pg-1)*sz))
                items = []
                for r in rows:
                    a = dbq("SELECT a.id,a.name FROM authors a JOIN book_authors ba ON a.id=ba.author_id WHERE ba.book_id=?",(r['id'],))
                    items.append({"id":r['id'],"title":r['title'],"file_format":r['file_format'],"file_size":r['file_size'],"cover_path":r['cover_path'],"status":r['status'],"summary":r['summary'],"difficulty":r['difficulty'],"created_at":r['created_at'],"authors":[dict(x) for x in a]})
                self.json({"total":dbq("SELECT count(*) as c FROM books WHERE status='active'")[0]['c'],"page":pg,"items":items})
            else:
                tb = dbq("SELECT count(*) as c FROM books WHERE status='active'")[0]['c']
                tm = dbq("SELECT count(*) as c FROM media WHERE status='active'")[0]['c']
                ts = dbq("SELECT count(*) as c FROM books WHERE status='active' AND summary IS NOT NULL")[0]['c']
                pn = qs.get('p',['home'])[0]
                nv = NAV.replace('{BOOKS}',str(tb)).replace('{MEDIA}',str(tm))
                h = '<!DOCTYPE html><html><head><meta charset=utf-8><title>My Library</title><style>'+CSS+'</style></head><body>'+nv+'<main>'
                if pn == 'books':
                    q = qs.get('q',[''])[0]
                    s = "SELECT id,title,file_format,file_size,cover_path FROM books WHERE status='active'"
                    pa = []
                    if q: s += " AND title LIKE ?"; pa.append('%'+q+'%')
                    s += " ORDER BY created_at DESC LIMIT 50"
                    rows = dbq(s, tuple(pa))
                    h += '<h2>📖 书库</h2><form class=search method=get><input type=hidden name=p value=books><input name=q placeholder=Search title value="'+he(q)+'"><button>Search</button></form><p class=col>'+str(len(rows))+' books</p>'
                    for r in rows:
                        cv = '<img src="/api/covers/'+r['id']+'.jpg">' if r['cover_path'] else '<div class=cv>📚</div>'
                        h += '<div class=book><a href="/api/books/'+r['id']+'/read">'+cv+'</a><div class=info><div class=t><a href="/api/books/'+r['id']+'/read">'+he(r['title'])[:50]+'</a></div><div class=m>'+r['file_format'].upper()+' · '+str(round(r['file_size']/1024/1024,1))+'MB</div></div></div>'
                elif pn == 'media':
                    rows = dbq("SELECT id,title,media_type,file_format,duration,file_size FROM media WHERE status='active' ORDER BY created_at DESC LIMIT 50")
                    h += '<h2>🎧 媒体库</h2><p class=col>'+str(len(rows))+'</p>'
                    for r in rows:
                        ic = '🎵' if r['media_type']=='audio' else '🎬'
                        d = r['duration'] or 0; dur = str(int(d/60))+':'+str(int(d%60)).zfill(2)
                        h += '<div class=book><div style="width:60px;height:60px;border-radius:8px;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;font-size:28px;color:#fff;flex-shrink:0">'+ic+'</div><div class=info><div class=t>'+he(r['title'])[:50]+'</div><div class=m>'+r['file_format'].upper()+' · '+dur+'</div></div></div>'
                elif pn == 'import':
                    h += '<h2>📥 Import</h2><p>Put new books in F:\\books dir</p>'
                    h += '<form method=post action=/api/import-scan onsubmit="return confirm(\'Scan F:\\\\books ?\')"><input name=dir value="F:\\书籍" style="padding:8px;border:1px solid #ddd;border-radius:4px;width:300px"> <button class=btn>Scan</button></form>'
                else:
                    h += '<h2>🏠 Home</h2><div class=row>'
                    h += '<a href="/?p=books" class=box style=text-decoration:none;color:inherit><div class=n style=color:#1677ff>'+str(tb)+'</div><div class=l>📚 Books</div></a>'
                    h += '<a href="/?p=books" class=box style=text-decoration:none;color:inherit><div class=n style=color:#52c41a>'+str(ts)+'</div><div class=l>🤖 Summarized</div></a>'
                    h += '<a href="/?p=media" class=box style=text-decoration:none;color:inherit><div class=n style=color:#fa8c16>'+str(tm)+'</div><div class=l>🎧 Media</div></a>'
                    h += '</div>'
                    h += '<div class=panel><h3>📊 Formats</h3>'
                    for r in dbq("SELECT file_format, count(*) as c FROM books WHERE status='active' GROUP BY file_format ORDER BY c DESC"):
                        h += '<span class=tag style=background:'+fc(r['file_format'])+'>'+r['file_format'].upper()+' '+str(r['c'])+'</span> '
                    h += '</div>'
                    h += '<div class=panel><h3>Categories</h3>'
                    for r in dbq("SELECT cat.name, count(*) as c FROM categories cat JOIN book_categories bc ON cat.id=bc.category_id JOIN books b ON b.id=bc.book_id WHERE b.status='active' GROUP BY cat.name ORDER BY c DESC LIMIT 20"):
                        h += '<span class=tag style=background:'+cc(r['name'])+'>'+he(r['name'])+' '+str(r['c'])+'</span> '
                    h += '</div>'
                h += '</main></body></html>'
                self._html(h)
        except Exception as e:
            try: self.send_error(500, str(e))
            except: pass

    def _html(self, h):
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(h.encode('utf-8'))

    def json(self, d):
        self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
        self.wfile.write(json.dumps(d,ensure_ascii=False).encode('utf-8'))

if __name__ == "__main__":
    print("🚀 http://localhost:8000")
    http.server.HTTPServer(("0.0.0.0",8000), H).serve_forever()
'''

open("simple_server.py", "w", encoding="utf-8").write(code)
print("OK - simple_server.py generated")
