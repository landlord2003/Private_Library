# Run this to generate simple_server.py
open("simple_server.py", "w", encoding="utf-8").write(r'''"""My Library Server"""
import http.server, json, sqlite3, os, urllib.parse, uuid, hashlib, shutil, threading
from pathlib import Path

DB = "data/library.db"
_task_status = {}

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

def he(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
def fc(f): return {'pdf':'#ff4d4f','epub':'#1677ff','mobi':'#52c41a','txt':'#666','md':'#722ed1'}.get(f,'#999')
def cc(c): return {'计算机与编程':'#1677ff','历史与人文':'#fa8c16','文学与小说':'#52c41a','哲学与思想':'#722ed1','科学与科普':'#13c2c2','经济与管理':'#eb2f96','心理与成长':'#fa541c','教育学习':'#2f54eb','艺术设计':'#a0d911','社会与政治':'#f5222d','生活与健康':'#7cb305','其他':'#999'}.get(c,'#999')

CSS = """* { margin:0; padding:0; box-sizing:border-box; } body { font-family: "Microsoft YaHei", Arial, sans-serif; background: #f5f5f5; display: flex; min-height: 100vh; } nav { width: 200px; background: #fff; padding: 20px 0; box-shadow: 2px 0 8px rgba(0,0,0,0.05); } nav h2 { padding: 0 20px 20px; color: #1677ff; font-size: 18px; border-bottom: 1px solid #f0f0f0; margin-bottom: 10px; } nav a { display: block; padding: 12px 20px; color: #333; text-decoration: none; font-size: 15px; } nav a:hover { background: #e6f4ff; color: #1677ff; } main { flex: 1; padding: 24px; overflow-y: auto; } .sb { background: #fff; padding: 20px; border-radius: 8px; text-align: center; min-width: 140px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); text-decoration: none; color: inherit; } .sb .n { font-size: 28px; font-weight: bold; } .sb .l { font-size: 13px; color: #999; margin-top: 4px; } .row { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; } .tag { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 12px; margin: 3px; color: #fff; } .panel { background: #fff; padding: 16px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); } .panel h3 { margin-bottom: 12px; font-size: 16px; } .sch { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; } .sch input, .sch select { padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; } .sch input { flex: 1; min-width: 180px; } .sch button { padding: 8px 20px; background: #1677ff; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; } .bk { background: #fff; border-radius: 8px; padding: 14px; margin-bottom: 8px; display: flex; gap: 12px; align-items: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); cursor: pointer; } .bk:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.1); } .bk img { width: 50px; height: 70px; object-fit: cover; border-radius: 4px; flex-shrink: 0; } .bk .cv { width: 50px; height: 70px; border-radius: 4px; flex-shrink: 0; background: linear-gradient(135deg, #667eea, #764ba2); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 22px; } .bk .info { flex: 1; min-width: 0; } .bk .t { font-weight: bold; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .bk .m { font-size: 12px; color: #999; margin-top: 2px; } a { color: #1677ff; text-decoration: none; } a:hover { text-decoration: underline; } .co { color: #999; } .btn { padding: 8px 20px; background: #1677ff; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; margin: 2px; } .bb2 { background: #fff; color: #1677ff; border: 1px solid #1677ff; } .detail { background: #fff; border-radius: 12px; padding: 24px; max-width: 800px; margin: 0 auto; box-shadow: 0 2px 12px rgba(0,0,0,0.1); overflow: hidden; } .detail h1 { margin-bottom: 16px; font-size: 22px; margin-right: 170px; } .detail .meta { margin-bottom: 16px; color: #666; font-size: 14px; line-height: 1.8; margin-right: 170px; } .detail .sec { margin: 16px 0; } .detail-cover { float: right; width: 150px; height: 200px; object-fit: contain; border-radius: 8px; background: #f5f5f5; margin-left: 16px; } .detail-cv { float: right; width: 150px; height: 200px; border-radius: 8px; background: linear-gradient(135deg, #667eea, #764ba2); display: flex; align-items: center; justify-content: center; color: #fff; font-size: 48px; margin-left: 16px; }"""

NAV = '<nav><h2>📚 我的图书馆</h2><a href="/">🏠 首页</a><a href="/?p=books">📖 书库 ({B})</a><a href="/?p=media">🎧 媒体库 ({M})</a><a href="/?p=import">📥 导入新书</a></nav>'

COMMON_JS = """<script>
function EDT(id,old){var t=prompt("新书名:",old);if(t&&t!==old){var x=new XMLHttpRequest();x.open("POST","/api/books/"+id+"/edit");x.setRequestHeader("Content-Type","application/json");x.onload=function(){location.reload()};x.send(JSON.stringify({title:t}));}}
var _clsTimer=null,_sumTimer=null;
function CLS(){var b=document.getElementById("clsBtn");if(b.disabled)return;b.disabled=true;b.textContent="分类启动中...";document.getElementById("clsRes").innerHTML="启动中...";var x=new XMLHttpRequest();x.open("POST","/api/classify-batch");x.setRequestHeader("Content-Type","application/json");x.onload=function(){b.disabled=false;b.textContent="🤖 AI 分类 (10本/次)";_pollCls();};x.send("{}")}
function _pollCls(){clearTimeout(_clsTimer);var x=new XMLHttpRequest();x.open("GET","/api/task-status");x.onload=function(){var r=JSON.parse(x.responseText);var c=r.classify||{};if(c.total>0){document.getElementById("clsRes").innerHTML="分类中: "+c.done+"/"+c.total+" 本";if(c.done<c.total)_clsTimer=setTimeout(_pollCls,2000);else document.getElementById("clsRes").innerHTML="✅ 分类完成: "+c.done+" 本 <a href=/ onclick=location.reload()>刷新</a>";}else{document.getElementById("clsRes").innerHTML="AI处理中...";_clsTimer=setTimeout(_pollCls,2000);}};x.onerror=function(){_clsTimer=setTimeout(_pollCls,5000)};x.send()}
function SUM(){var b=document.getElementById("sumBtn");if(b.disabled)return;b.disabled=true;b.textContent="摘要启动中...";document.getElementById("sumRes").innerHTML="启动中...";var x=new XMLHttpRequest();x.open("POST","/api/summarize-batch");x.setRequestHeader("Content-Type","application/json");x.onload=function(){b.disabled=false;b.textContent="🤖 AI 摘要 (3本/次)";_pollSum();};x.send("{}")}
function _pollSum(){clearTimeout(_sumTimer);var x=new XMLHttpRequest();x.open("GET","/api/task-status");x.onload=function(){var r=JSON.parse(x.responseText);var s=r.summarize||{};if(s.total>0){document.getElementById("sumRes").innerHTML="摘要中: "+s.done+"/"+s.total+" 本";if(s.done<s.total)_sumTimer=setTimeout(_pollSum,3000);else document.getElementById("sumRes").innerHTML="✅ 摘要完成: "+s.done+" 本 <a href=/ onclick=location.reload()>刷新</a>";}else{document.getElementById("sumRes").innerHTML="AI处理中...";_sumTimer=setTimeout(_pollSum,3000);}};x.onerror=function(){_sumTimer=setTimeout(_pollSum,5000)};x.send()}
</script>"""

def parse_multipart(ctype, body):
    if 'multipart/form-data' not in ctype: return None
    for part in ctype.split(';'):
        if part.strip().startswith('boundary='): boundary = part.split('=')[1].strip('"').encode(); break
    else: return None
    parts = body.split(b'--' + boundary); fields = {}
    for part in parts:
        if not part or part in (b'--\r\n', b'--'): continue
        if b'\r\n\r\n' not in part: continue
        hd, data = part.split(b'\r\n\r\n', 1); headers = hd.decode('utf-8','ignore').split('\r\n')
        name = filename = None
        for h in headers:
            if 'name="' in h: name = h.split('name="')[1].split('"')[0]
            if 'filename="' in h: filename = h.split('filename="')[1].split('"')[0]
        if data.endswith(b'\r\n'): data = data[:-2]
        if name: fields[name] = {'filename': filename, 'data': data}
    return fields

def extract_cover_for(bid, fp, fmt):
    try:
        cv = None
        if fmt == 'pdf':
            import fitz; doc = fitz.open(fp)
            if doc.page_count > 0: pix = doc[0].get_pixmap(dpi=72); cv = pix.tobytes("jpg")
            doc.close()
        elif fmt == 'epub':
            from ebooklib import epub; bk = epub.read_epub(fp)
            for it in bk.get_items():
                if it.get_type() == 6 and ('cover' in str(it.get_name()).lower() or 'cover' in str(it.get_id()).lower()):
                    cv = it.get_content(); break
            if not cv:
                for it in bk.get_items():
                    if it.get_type() == 6: cv = it.get_content(); break
        if cv and len(cv) > 500:
            cvp = os.path.join("data","covers",bid+".jpg"); os.makedirs(os.path.dirname(cvp),exist_ok=True)
            with open(cvp,'wb') as f: f.write(cv)
            dbe("UPDATE books SET cover_path=? WHERE id=?",(cvp,bid))
    except: pass

def run_classify_async():
    if _task_status.get('cr'): return {"status":"running"}
    import requests
    _task_status['cr'] = True; _task_status['cr_r'] = {"done":0,"total":0}
    def w():
        try:
            books = dbq("SELECT id,title,text_content FROM books WHERE status='active' AND id NOT IN (SELECT book_id FROM book_categories) LIMIT 10")
            cats = ["计算机与编程","历史与人文","文学与小说","哲学与思想","科学与科普","经济与管理","心理与成长","教育学习","艺术设计","社会与政治","生活与健康"]
            rv = {"done":0,"total":len(books)}
            for b in books:
                try:
                    clist="\n".join("- "+c for c in cats)
                    prompt=f"判断以下书籍类别。可选类别：\n{clist}\n\n书名：{b['title']}\n内容：{(b['text_content'] or '')[:1500]}\n只返回JSON：{{\"category\":\"类别名\",\"tags\":[\"标签1\",\"标签2\"],\"difficulty\":\"入门/中级/高级\"}}"
                    r=requests.post("http://127.0.0.1:11434/api/generate",json={"model":"qwen2.5:7b","prompt":prompt,"stream":False,"temperature":0.1},timeout=120)
                    resp=r.json()["response"].strip()
                    if resp.startswith("```"): resp=resp.split("\n",1)[1].rsplit("\n",1)[0]
                    result=json.loads(resp); cn=result.get("category","其他")
                    cr=dbq("SELECT id FROM categories WHERE name=?",(cn,))
                    cid=cr[0]['id'] if cr else str(uuid.uuid4()); dbe("INSERT INTO categories(id,name) VALUES(?,?)",(cid,cn)) if not cr else None
                    dbe("INSERT OR IGNORE INTO book_categories(book_id,category_id) VALUES(?,?)",(b['id'],cid))
                    for tn in result.get("tags",[]):
                        tr=dbq("SELECT id FROM tags WHERE name=?",(tn,))
                        tid=tr[0]['id'] if tr else str(uuid.uuid4()); dbe("INSERT INTO tags(id,name) VALUES(?,?)",(tid,tn)) if not tr else None
                        dbe("INSERT OR IGNORE INTO book_tags(book_id,tag_id) VALUES(?,?)",(b['id'],tid))
                    if result.get("difficulty"): dbe("UPDATE books SET difficulty=? WHERE id=? AND difficulty IS NULL",(result["difficulty"],b['id']))
                    rv["done"]+=1; _task_status['cr_r']=rv
                except: pass
            _task_status['cr_r']=rv
        finally: _task_status['cr']=False
    threading.Thread(target=w,daemon=True).start()
    return {"status":"started"}

def run_summarize_async():
    if _task_status.get('sr'): return {"status":"running"}
    import requests
    _task_status['sr'] = True; _task_status['sr_r'] = {"done":0,"total":0}
    def w():
        try:
            books=dbq("SELECT id,title,text_content FROM books WHERE status='active' AND summary IS NULL AND text_content IS NOT NULL AND text_content!='' LIMIT 3")
            rv={"done":0,"total":len(books)}
            for b in books:
                try:
                    prompt=f"你是专业图书摘要助手。书名：{b['title']}\n内容：{(b['text_content'] or '')[:5000]}\n按以下结构输出（中文）：\n1. 一句话总结\n2. 核心观点（3-5条）\n3. 关键概念\n4. 适合读者\n5. 难度评级：入门/中级/高级"
                    r=requests.post("http://127.0.0.1:11434/api/generate",json={"model":"qwen2.5:7b","prompt":prompt,"stream":False,"temperature":0.3},timeout=180)
                    summary=r.json()["response"].strip()
                    if len(summary)>20:
                        dbe("UPDATE books SET summary=?,summary_model=?,summary_updated=datetime('now') WHERE id=?",(summary,"qwen2.5:7b",b['id']))
                        if "高级" in summary: dbe("UPDATE books SET difficulty='高级' WHERE id=? AND difficulty IS NULL",(b['id'],))
                        elif "中级" in summary: dbe("UPDATE books SET difficulty='中级' WHERE id=? AND difficulty IS NULL",(b['id'],))
                        elif "入门" in summary: dbe("UPDATE books SET difficulty='入门' WHERE id=? AND difficulty IS NULL",(b['id'],))
                        rv["done"]+=1; _task_status['sr_r']=rv
                except: pass
            _task_status['sr_r']=rv
        finally: _task_status['sr']=False
    threading.Thread(target=w,daemon=True).start()
    return {"status":"started"}

class H(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        p=urllib.parse.urlparse(self.path);path=p.path
        ctype=self.headers.get('Content-Type','')
        length=int(self.headers.get('Content-Length',0))
        body=self.rfile.read(length) if length>0 else b''
        try:
            if 'multipart/form-data' in ctype: self._upload(ctype,body);return
            data=json.loads(body)if body else{}
            if path=="/api/import-scan": self._scan(data.get('dir',r'F:\书籍'));return
            if path.startswith("/api/books/")and path.endswith("/edit"):
                bid=path.split("/")[3];title=data.get('title','').strip()
                if title:dbe("UPDATE books SET title=? WHERE id=?",(title,bid));self.json({"ok":True})
                else:self.json({"error":"empty"})
                return
            if path=="/api/classify-batch":self.json(run_classify_async());return
            if path=="/api/summarize-batch":self.json(run_summarize_async());return
            self.send_error(404)
        except Exception as e:self.send_error(500,str(e))

    def _upload(self,ctype,body):
        fields=parse_multipart(ctype,body)
        if not fields or'file'not in fields:self.json({"error":"parse"});return
        f=fields['file']
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
        self.json({"success":True,"id":bid,"title":fn})

    def _scan(self,d):
        if not os.path.exists(d):self.json({"error":"not found"});return
        E={'.pdf','.epub','.mobi','.azw3','.azw','.txt','.md','.zip','.rar','.7z'};nb=db=eb=0
        for r,_,fs in os.walk(d):
            for fn in fs:
                if fn.startswith('.'):continue
                ext=os.path.splitext(fn)[1].lower()
                if ext not in E:continue
                fp=os.path.join(r,fn)
                try:
                    h=hashlib.sha256()
                    with open(fp,'rb')as f:
                        for ck in iter(lambda:f.read(8192),b''):h.update(ck)
                    fh=h.hexdigest()
                    if dbq("SELECT id FROM books WHERE file_hash=?",(fh,)):db+=1;continue
                    bid=str(uuid.uuid4());dd=os.path.join("data","books",bid);os.makedirs(dd,exist_ok=True)
                    dest=os.path.join(dd,"original"+ext);shutil.copy2(fp,dest);fmt=ext.lstrip('.')
                    dbe("INSERT INTO books(id,title,file_path,file_format,file_size,file_hash,status)VALUES(?,?,?,?,?,?,'active')",(bid,os.path.splitext(fn)[0],dest,fmt,os.path.getsize(fp),fh))
                    extract_cover_for(bid,dest,fmt);nb+=1
                except:eb+=1
        self.json({"new":nb,"dupes":db,"errors":eb})

    def do_GET(self):
        p=urllib.parse.urlparse(self.path);path=p.path;qs=urllib.parse.parse_qs(p.query)
        try:
            if path=="/api/health":self.json({"status":"ok"})
            elif path=="/api/task-status":self.json({"classify":_task_status.get('cr_r',{}),"summarize":_task_status.get('sr_r',{})})
            elif path.startswith("/api/books/")and path.endswith("/read"):
                bid=path.split("/")[3]
                r=dbq("SELECT file_path,file_format,title FROM books WHERE id=?",(bid,))
                if not r:self.send_error(404);return
                fp,fmt,title=r[0]['file_path'],r[0]['file_format'],r[0]['title']
                if not os.path.exists(fp):self.send_error(404);return
                if fmt=='epub':
                    try:
                        from ebooklib import epub;from bs4 import BeautifulSoup
                        bk=epub.read_epub(fp);st,bp=[],[]
                        for it in bk.get_items():
                            if it.get_type()==5:
                                try:st.append(it.get_content().decode('utf-8','ignore'))
                                except:pass
                            elif it.get_type()==9:
                                try:sp=BeautifulSoup(it.get_content(),'html.parser');b=sp.find('body');bp.append(str(b)if b else str(sp))
                                except:pass
                        h='<!DOCTYPE html><html><head><meta charset=utf-8><title>'+title+'</title>'
                        for s in st[:3]:h+='<style>'+s+'</style>'
                        h+='<style>body{max-width:800px;margin:0 auto;padding:20px;font-family:serif;font-size:18px;line-height:1.8}img{max-width:100%}</style></head><body><h1>'+title+'</h1>'+'\n'.join(bp)+'</body></html>'
                        self._html(h)
                    except:self.send_error(500)
                else:
                    r2=dbq("SELECT text_content FROM books WHERE id=?",(bid,))
                    t=(r2[0]['text_content']if r2 else'')or''
                    t=t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                    h='<!DOCTYPE html><html><head><meta charset=utf-8><title>'+title+'</title><style>body{max-width:800px;margin:0 auto;padding:20px;font-family:serif;font-size:18px;line-height:2;white-space:pre-wrap}</style></head><body><h1>'+title+'</h1><div>'+t+'</div></body></html>'
                    self._html(h)
            elif path.startswith("/api/books/")and path.endswith("/file"):
                bid=path.split("/")[3];r=dbq("SELECT file_path,file_format FROM books WHERE id=?",(bid,))
                if not r:self.send_error(404);return
                fp,fmt=r[0]['file_path'],r[0]['file_format']
                if os.path.exists(fp):
                    self.send_response(200);self.send_header("Content-Type",{"pdf":"application/pdf"}.get(fmt,"application/octet-stream"))
                    self.send_header("Content-Disposition","inline");self.end_headers()
                    with open(fp,'rb')as f:self.wfile.write(f.read())
                else:self.send_error(404)
            elif path.startswith("/api/media/")and path.endswith("/file"):
                bid=path.split("/")[3];r=dbq("SELECT file_path,file_format FROM media WHERE id=?",(bid,))
                if not r:self.send_error(404);return
                fp,fmt=r[0]['file_path'],r[0]['file_format']
                if os.path.exists(fp):
                    self.send_response(200);self.send_header("Content-Type",{"mp3":"audio/mpeg","mp4":"video/mp4"}.get(fmt,"application/octet-stream"))
                    self.end_headers();with open(fp,'rb')as f:self.wfile.write(f.read())
                else:self.send_error(404)
            elif path.startswith("/api/covers/"):
                cv=Path("data/covers")/path.split("/")[-1]
                if cv.exists():self.send_response(200);self.send_header("Content-Type","image/jpeg");self.end_headers()
                    with open(cv,'rb')as f:self.wfile.write(f.read())
                else:self.send_error(404)
            elif path.startswith("/api/books/"):
                bid=path.split("/")[3];r=dbq("SELECT * FROM books WHERE id=?",(bid,))
                if not r:self.send_error(404);return
                self.json(dict(r[0]))
            elif path.startswith("/api/media/"):
                bid=path.split("/")[3];r=dbq("SELECT * FROM media WHERE id=?",(bid,))
                if not r:self.send_error(404);return
                self.json(dict(r[0]))
            elif path=="/api/categories":
                rows=dbq("SELECT id,name FROM categories ORDER BY name")
                self.json([dict(r)for r in rows])
            else:self._page(qs)
        except Exception as e:
            try:self.send_error(500,str(e))
            except:pass

    def _page(self,qs):
        tb=dbq("SELECT count(*)as c FROM books WHERE status='active'")[0]['c']
        tm=dbq("SELECT count(*)as c FROM media WHERE status='active'")[0]['c']
        ts=dbq("SELECT count(*)as c FROM books WHERE status='active' AND summary IS NOT NULL")[0]['c']
        pn=qs.get('p',['home'])[0]
        nv=NAV.replace('{B}',str(tb)).replace('{M}',str(tm))
        h='<!DOCTYPE html><html><head><meta charset=utf-8><title>我的图书馆</title><style>'+CSS+'</style></head><body>'+nv+'<main>'
        if pn=='books':
            q=qs.get('q',[''])[0];cat=qs.get('cat',[''])[0]
            s="SELECT id,title,file_format,file_size,cover_path FROM books WHERE status='active'";pa=[]
            if q:s+=" AND title LIKE ?";pa.append('%'+q+'%')
            if cat:s+=" AND id IN (SELECT book_id FROM book_categories WHERE category_id=?)";pa.append(cat)
            s+=" ORDER BY created_at DESC LIMIT 80"
            rows=dbq(s,tuple(pa))
            h+='<h2>📖 书库 ('+str(len(rows))+')</h2>'
            h+='<form class=sch method=get><input type=hidden name=p value=books><input name=q placeholder=搜索书名 value="'+he(q)+'"><select name=cat><option value="">全部分类</option>'
            for r in dbq("SELECT id,name FROM categories ORDER BY name"):
                sel=' selected'if r['id']==cat else''
                h+='<option value="'+r['id']+'"'+sel+'>'+he(r['name'])+'</option>'
            h+='</select><button>搜索</button></form>'
            for r in rows:
                cv='<img src="/api/covers/'+r['id']+'.jpg">'if r['cover_path']else'<div class=cv>📚</div>'
                h+='<div class=bk onclick="location.href=\'/?p=detail&id='+r['id']+'\'"><a href="/?p=detail&id='+r['id']+'" onclick="event.stopPropagation()">'+cv+'</a><div class=info><div class=t>'+he(r['title'])[:60]+'</div><div class=m>'+r['file_format'].upper()+' '+str(round(r['file_size']/1024/1024,1))+'MB</div></div></div>'
        elif pn=='detail':
            bid=qs.get('id',[None])[0];is_media=qs.get('type',[''])[0]=='media'
            if bid and not is_media:
                r=dbq("SELECT * FROM books WHERE id=?",(bid,))
                if r:
                    b=r[0];a=dbq("SELECT a.name FROM authors a JOIN book_authors ba ON a.id=ba.author_id WHERE ba.book_id=?",(bid,))
                    c=dbq("SELECT c.name FROM categories c JOIN book_categories bc ON c.id=bc.category_id WHERE bc.book_id=?",(bid,))
                    h+='<div class=detail>'
                    h+='<img src="/api/covers/'+bid+'.jpg" class=detail-cover onerror="this.outerHTML=\'<div class=detail-cv>📚</div>\'">'if b['cover_path']else'<div class=detail-cv>📚</div>'
                    h+='<h1>'+he(str(b['title']))+' <button class=btn onclick="event.stopPropagation();EDT(\''+bid+'\')" style="font-size:12px;padding:2px 8px">✏️</button></h1>'
                    h+='<div class=meta>'
                    if a:h+='<p><b>作者:</b> '+', '.join([he(x['name'])for x in a])+'</p>'
                    h+='<p><b>格式:</b> '+str(b['file_format']).upper()+' | <b>大小:</b> '+str(round(b['file_size']/1024/1024,1))+'MB | <b>页数:</b> '+str(b['page_count']or'-')+'</p>'
                    if b['publisher']:h+='<p><b>出版社:</b> '+he(str(b['publisher']))+'</p>'
                    if b['isbn']:h+='<p><b>ISBN:</b> '+str(b['isbn'])+'</p>'
                    h+='</div><div style="clear:both"></div>'
                    if c:
                        h+='<div class=sec>'
                        for x in c:h+='<span class=tag style=background:'+cc(x['name'])+'>'+he(x['name'])+'</span> '
                        h+='</div>'
                    if b['difficulty']:
                        dc={'入门':'#52c41a','中级':'#fa8c16','高级':'#ff4d4f'}
                        h+=' <span class=tag style=background:'+dc.get(b['difficulty'],'#999')+'>难度: '+b['difficulty']+'</span>'
                    if b['summary']:h+='<div class=sec><h3>🤖 AI 摘要</h3><div style=white-space:pre-wrap;line-height:1.8;background:#f9f9f9;padding:16px;border-radius:8px;margin-top:8px>'+he(str(b['summary']))+'</div></div>'
                    else:h+='<div class=sec><p class=co>暂无摘要</p></div>'
                    read_url='/api/books/'+bid+'/'+('file'if b['file_format']=='pdf'else'read')
                    h+='<div class=sec><a href="'+read_url+'" class=btn target=_blank>📖 阅读</a> <a href="/?p=books" class="btn bb2">返回</a></div></div>'
        elif pn=='media':
            rows=dbq("SELECT id,title,media_type,file_format,duration,file_size FROM media WHERE status='active' ORDER BY created_at DESC LIMIT 80")
            h+='<h2>🎧 媒体库 ('+str(len(rows))+')</h2>'
            for r in rows:
                ic='🎵'if r['media_type']=='audio'else'🎬';d=r['duration']or 0;dur=str(int(d/60))+':'+str(int(d%60)).zfill(2)
                h+='<div class=bk onclick="location.href=\'/?p=detail&id='+r['id']+'&type=media\'"><div style="width:60px;height:60px;border-radius:8px;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;font-size:28px;color:#fff;flex-shrink:0">'+ic+'</div><div class=info><div class=t>'+he(r['title'])[:60]+'</div><div class=m>'+r['file_format'].upper()+' · '+dur+'</div></div></div>'
        elif pn=='import':
            h+='<h2>📥 导入新书</h2>'
            h+='<div class=panel><h3>1. 选择文件上传</h3>'
            h+='<input type=file id=f1 multiple accept=".pdf,.epub,.mobi,.azw3,.txt,.md,.zip,.rar,.7z" style=display:none onchange="UF(this.files)"><input type=file id=f2 webkitdirectory style=display:none onchange="UF(this.files)">'
            h+='<button class=btn onclick="document.getElementById(\'f1\').click()">📁 选择文件</button> <button class=btn onclick="document.getElementById(\'f2\').click()">📂 选择文件夹</button>'
            h+='<div id=up style=margin-top:8px;font-size:13px;color:#999></div></div>'
            h+='<div class=panel><h3>2. 扫描本地目录</h3>'
            h+='<p style=color:#999;margin-bottom:8px>扫描 F:\\书籍 目录中的新书</p>'
            h+='<input type=text id=sd value="F:\\书籍" style="padding:8px;border:1px solid #ddd;border-radius:4px;width:300px"> <button class=btn id=scanBtn onclick="SCAN()">🔍 开始扫描</button>'
            h+='<div id=sr style=margin-top:8px;font-size:13px;color:#999></div></div>'
        else:
            import_rem=dbq("SELECT count(*)as c FROM books WHERE status='active' AND id NOT IN(SELECT book_id FROM book_categories)")[0]['c']
            sum_rem=dbq("SELECT count(*)as c FROM books WHERE status='active' AND summary IS NULL AND text_content IS NOT NULL AND text_content!=''")[0]['c']
            h+='<h2>🏠 首页</h2>'
            h+='<div class=row><a href="/?p=books" class=sb><div class=n style=color:#1677ff>'+str(tb)+'</div><div class=l>📚 书籍</div></a><a href="/?p=detail&list=1" class=sb><div class=n style=color:#52c41a>'+str(ts)+'</div><div class=l>🤖 已摘要</div></a><a href="/?p=media" class=sb><div class=n style=color:#fa8c16>'+str(tm)+'</div><div class=l>🎧 媒体</div></a></div>'
            h+='<div class=panel><h3>🤖 AI 处理</h3><p class=co style=margin-bottom:8px>需要 Ollama 在运行。未分类: '+str(import_rem)+' 本 | 未摘要: '+str(sum_rem)+' 本 (有文本的)</p>'
            h+='<button class=btn id=clsBtn onclick="CLS()" style=margin-right:8px>🤖 AI 分类 (10本/次)</button><button class=btn id=sumBtn onclick="SUM()">🤖 AI 摘要 (3本/次)</button>'
            h+='<div id=clsRes style=margin-top:4px;font-size:13px></div><div id=sumRes style=margin-top:4px;font-size:13px></div></div>'
            h+='<div class=panel><h3>📊 格式分布</h3>'
            for r in dbq("SELECT file_format,count(*)as c FROM books WHERE status='active' GROUP BY file_format ORDER BY c DESC"):
                h+='<span class=tag style=background:'+fc(r['file_format'])+'>'+r['file_format'].upper()+' '+str(r['c'])+'</span> '
            h+='</div><div class=panel><h3>🏷️ 分类分布</h3>'
            for r in dbq("SELECT cat.name,count(*)as c FROM categories cat JOIN book_categories bc ON cat.id=bc.category_id JOIN books b ON b.id=bc.book_id WHERE b.status='active' GROUP BY cat.name ORDER BY c DESC LIMIT 20"):
                h+='<span class=tag style=background:'+cc(r['name'])+'>'+he(r['name'])+' '+str(r['c'])+'</span> '
            h+='</div>'
        h+=COMMON_JS
        if pn=='import':
            h+='<script>var _f=[],_i=0,_ok=0,_d=0,_e=0;function UF(fs){_f=Array.from(fs);_i=0;_ok=0;_d=0;_e=0;NX()}function NX(){if(_i>=_f.length){document.getElementById("up").innerHTML="完成! 新增 "+_ok+" 本, 重复 "+_d+" 本"+(_e>0?", 失败 "+_e+" 本":"")+" <a href=/ onclick=location.reload()>刷新</a>";return}var fd=new FormData();fd.append("file",_f[_i]);_i++;var x=new XMLHttpRequest();x.open("POST","/api/import-upload");x.onload=function(){try{var r=JSON.parse(x.responseText);if(r.success)_ok++;else if(r.duplicate)_d++;else _e++;if(r.error)alert("错误: "+r.error)}catch(e){_e++}document.getElementById("up").innerHTML="上传中... "+_i+"/"+_f.length;NX()};x.onerror=function(){_e++;NX()};x.send(fd)}function SCAN(){var dir=document.getElementById("sd").value;document.getElementById("scanBtn").disabled=true;document.getElementById("scanBtn").textContent="扫描中...";var x=new XMLHttpRequest();x.open("POST","/api/import-scan");x.setRequestHeader("Content-Type","application/json");x.onload=function(){var r=JSON.parse(x.responseText);document.getElementById("sr").innerHTML=r.error?"错误: "+r.error:"新增 "+r.new+" 本, 跳过重复 "+r.dupes+" 本"+(r.errors>0?", 失败 "+r.errors+" 本":"")+" <a href=/ onclick=location.reload()>刷新</a>";document.getElementById("scanBtn").disabled=false;document.getElementById("scanBtn").textContent="🔍 开始扫描"};x.onerror=function(){document.getElementById("sr").innerHTML="错误";document.getElementById("scanBtn").disabled=false;document.getElementById("scanBtn").textContent="🔍 开始扫描"};x.send(JSON.stringify({dir:dir}))}</script>'
        h+='</main></body></html>'
        self._html(h)

    def _html(self,h):
        self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.end_headers()
        self.wfile.write(h.encode('utf-8'))

    def json(self,d):
        self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Access-Control-Allow-Origin","*");self.end_headers()
        self.wfile.write(json.dumps(d,ensure_ascii=False).encode('utf-8'))

if __name__=="__main__":
    print("🚀 http://localhost:8000")
    http.server.HTTPServer(("0.0.0.0",8000),H).serve_forever()
''')
print("OK - simple_server.py generated")

def parse_multipart(content_type, body):
    if 'multipart/form-data' not in content_type: return None
    for part in content_type.split(';'):
        if part.strip().startswith('boundary='):
            boundary = part.split('=')[1].strip('"').encode(); break
    else: return None
    parts = body.split(b'--' + boundary)
    fields = {}
    for part in parts:
        if not part or part in (b'--\r\n', b'--'): continue
        if b'\r\n\r\n' not in part: continue
        hd, data = part.split(b'\r\n\r\n', 1)
        headers = hd.decode('utf-8','ignore').split('\r\n')
        name = filename = None
        for h in headers:
            if 'name="' in h: name = h.split('name="')[1].split('"')[0]
            if 'filename="' in h: filename = h.split('filename="')[1].split('"')[0]
        if data.endswith(b'\r\n'): data = data[:-2]
        if name: fields[name] = {'filename': filename, 'data': data}
    return fields

def extract_cover_for(book_id, file_path, fmt):
    try:
        cover_data = None
        if fmt == 'pdf':
            import fitz; doc = fitz.open(file_path)
            if doc.page_count > 0: pix = doc[0].get_pixmap(dpi=72); cover_data = pix.tobytes("jpg")
            doc.close()
        elif fmt == 'epub':
            from ebooklib import epub; bk = epub.read_epub(file_path)
            for item in bk.get_items():
                if item.get_type() == 6 and ('cover' in str(item.get_name()).lower() or 'cover' in str(item.get_id()).lower()):
                    cover_data = item.get_content(); break
            if not cover_data:
                for item in bk.get_items():
                    if item.get_type() == 6: cover_data = item.get_content(); break
        if cover_data and len(cover_data) > 500:
            cvp = os.path.join("data","covers",book_id+".jpg"); os.makedirs(os.path.dirname(cvp),exist_ok=True)
            with open(cvp,'wb') as f: f.write(cover_data)
            dbe("UPDATE books SET cover_path=? WHERE id=?",(cvp,book_id))
    except: pass

def run_classify_async():
    if _task_status.get('cr'): return {"status":"running"}
    import requests
    _task_status['cr'] = True
    _task_status['cr_r'] = {"done":0,"total":0}
    def w():
        try:
            books = dbq("SELECT id,title,text_content FROM books WHERE status='active' AND id NOT IN (SELECT book_id FROM book_categories) LIMIT 5")
            cats = ["计算机与编程","历史与人文","文学与小说","哲学与思想","科学与科普","经济与管理","心理与成长","教育学习","艺术设计","社会与政治","生活与健康"]
            rv = {"done":0,"total":len(books)}
            for b in books:
                try:
                    clist="\n".join("- "+c for c in cats)
                    prompt=f"判断以下书籍类别。可选类别：\n{clist}\n\n书名：{b['title']}\n内容：{(b['text_content'] or '')[:1500]}\n只返回JSON：{{\"category\":\"类别名\",\"tags\":[\"标签1\",\"标签2\"],\"difficulty\":\"入门/中级/高级\"}}"
                    r=requests.post("http://127.0.0.1:11434/api/generate",json={"model":"qwen2.5:7b","prompt":prompt,"stream":False,"temperature":0.1},timeout=120)
                    resp=r.json()["response"].strip()
                    if resp.startswith("```"): resp=resp.split("\n",1)[1].rsplit("\n",1)[0]
                    result=json.loads(resp)
                    cn=result.get("category","其他")
                    cr=dbq("SELECT id FROM categories WHERE name=?",(cn,))
                    cid=cr[0]['id'] if cr else str(uuid.uuid4()); dbe("INSERT INTO categories(id,name) VALUES(?,?)",(cid,cn)) if not cr else None
                    dbe("INSERT OR IGNORE INTO book_categories(book_id,category_id) VALUES(?,?)",(b['id'],cid))
                    for tn in result.get("tags",[]):
                        tr=dbq("SELECT id FROM tags WHERE name=?",(tn,))
                        tid=tr[0]['id'] if tr else str(uuid.uuid4()); dbe("INSERT INTO tags(id,name) VALUES(?,?)",(tid,tn)) if not tr else None
                        dbe("INSERT OR IGNORE INTO book_tags(book_id,tag_id) VALUES(?,?)",(b['id'],tid))
                    if result.get("difficulty"): dbe("UPDATE books SET difficulty=? WHERE id=? AND difficulty IS NULL",(result["difficulty"],b['id']))
                    rv["done"]+=1; _task_status['cr_r']=rv
                except: pass
            _task_status['cr_r']=rv
        finally: _task_status['cr']=False
    threading.Thread(target=w,daemon=True).start()
    return {"status":"started"}

def run_summarize_async():
    if _task_status.get('sr'): return {"status":"running"}
    import requests
    _task_status['sr'] = True
    _task_status['sr_r'] = {"done":0,"total":0}
    def w():
        try:
            books=dbq("SELECT id,title,text_content FROM books WHERE status='active' AND summary IS NULL AND text_content IS NOT NULL LIMIT 3")
            rv={"done":0,"total":len(books)}
            for b in books:
                try:
                    prompt=f"你是专业图书摘要助手。书名：{b['title']}\n内容：{(b['text_content'] or '')[:5000]}\n按以下结构输出（中文）：\n1. 一句话总结\n2. 核心观点（3-5条）\n3. 关键概念\n4. 适合读者\n5. 难度评级：入门/中级/高级"
                    r=requests.post("http://127.0.0.1:11434/api/generate",json={"model":"qwen2.5:7b","prompt":prompt,"stream":False,"temperature":0.3},timeout=180)
                    summary=r.json()["response"].strip()
                    if len(summary)>20:
                        dbe("UPDATE books SET summary=?,summary_model=?,summary_updated=datetime('now') WHERE id=?",(summary,"qwen2.5:7b",b['id']))
                        if "高级" in summary: dbe("UPDATE books SET difficulty='高级' WHERE id=? AND difficulty IS NULL",(b['id'],))
                        elif "中级" in summary: dbe("UPDATE books SET difficulty='中级' WHERE id=? AND difficulty IS NULL",(b['id'],))
                        elif "入门" in summary: dbe("UPDATE books SET difficulty='入门' WHERE id=? AND difficulty IS NULL",(b['id'],))
                        rv["done"]+=1; _task_status['sr_r']=rv
                except: pass
            _task_status['sr_r']=rv
        finally: _task_status['sr']=False
    threading.Thread(target=w,daemon=True).start()
    return {"status":"started"}

class H(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        p = urllib.parse.urlparse(self.path); path = p.path
        ctype = self.headers.get('Content-Type','')
        length = int(self.headers.get('Content-Length',0))
        body = self.rfile.read(length) if length > 0 else b''
        try:
            if 'multipart/form-data' in ctype: self._handle_upload(ctype,body); return
            data = json.loads(body) if body else {}
            if path == "/api/import-scan": self._handle_scan(data.get('dir',r'F:\书籍')); return
            if path.startswith("/api/books/") and path.endswith("/edit"):
                bid=path.split("/")[3]; title=data.get('title','').strip()
                if title: dbe("UPDATE books SET title=? WHERE id=?",(title,bid)); self.json({"ok":True,"title":title})
                else: self.json({"error":"title empty"}); return
            if path == "/api/classify-batch": self.json(run_classify_async()); return
            if path == "/api/summarize-batch": self.json(run_summarize_async()); return
            self.send_error(404)
        except Exception as e: self.send_error(500, str(e))

    def _handle_upload(self, ctype, body):
        fields = parse_multipart(ctype, body)
        if not fields or 'file' not in fields: self.json({"error":"parse failed"}); return
        f = fields['file']
        if not f['filename']: self.json({"error":"no filename"}); return
        data, fn = f['data'], f['filename']
        ext = os.path.splitext(fn)[1].lower()
        E = {'.pdf','.epub','.mobi','.azw3','.azw','.txt','.md','.zip','.rar','.7z'}
        if ext not in E: self.json({"error":"bad format"}); return
        if len(data)==0: self.json({"error":"empty"}); return
        h = hashlib.sha256(); h.update(data); fh = h.hexdigest()
        if dbq("SELECT id FROM books WHERE file_hash=?",(fh,)): self.json({"duplicate":True}); return
        bid=str(uuid.uuid4()); dd=os.path.join("data","books",bid); os.makedirs(dd,exist_ok=True)
        dest=os.path.join(dd,"original"+ext)
        with open(dest,'wb') as f: f.write(data)
        fmt=ext.lstrip('.')
        dbe("INSERT INTO books(id,title,file_path,file_format,file_size,file_hash,status) VALUES(?,?,?,?,?,?,'active')",
            (bid,os.path.splitext(fn)[0],dest,fmt,len(data),fh))
        extract_cover_for(bid, dest, fmt)
        self.json({"success":True,"id":bid,"title":fn})

    def _handle_scan(self, d):
        if not os.path.exists(d): self.json({"error":"not found"}); return
        E={'.pdf','.epub','.mobi','.azw3','.azw','.txt','.md','.zip','.rar','.7z'}; nb=db=eb=0
        for r,_,fs in os.walk(d):
            for fn in fs:
                if fn.startswith('.'): continue
                ext=os.path.splitext(fn)[1].lower()
                if ext not in E: continue
                fp=os.path.join(r,fn)
                try:
                    h=hashlib.sha256()
                    with open(fp,'rb') as f:
                        for ck in iter(lambda:f.read(8192),b''): h.update(ck)
                    fh=h.hexdigest()
                    if dbq("SELECT id FROM books WHERE file_hash=?",(fh,)): db+=1;continue
                    bid=str(uuid.uuid4()); dd=os.path.join("data","books",bid); os.makedirs(dd,exist_ok=True)
                    dest=os.path.join(dd,"original"+ext); shutil.copy2(fp,dest); fmt=ext.lstrip('.')
                    dbe("INSERT INTO books(id,title,file_path,file_format,file_size,file_hash,status) VALUES(?,?,?,?,?,?,'active')",
                        (bid,os.path.splitext(fn)[0],dest,fmt,os.path.getsize(fp),fh))
                    extract_cover_for(bid,dest,fmt); nb+=1
                except: eb+=1
        self.json({"new":nb,"dupes":db,"errors":eb})

    def do_GET(self):
        p=urllib.parse.urlparse(self.path); path=p.path; qs=urllib.parse.parse_qs(p.query)
        try:
            if path=="/api/health": self.json({"status":"ok"})
            elif path=="/api/task-status": self.json({"classify":_task_status.get('cr_r',{}),"summarize":_task_status.get('sr_r',{})})
            elif path.startswith("/api/books/") and path.endswith("/read"):
                bid=path.split("/")[3]
                r=dbq("SELECT file_path,file_format,title FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp,fmt,title=r[0]['file_path'],r[0]['file_format'],r[0]['title']
                if not os.path.exists(fp): self.send_error(404); return
                if fmt=='epub':
                    try:
                        from ebooklib import epub; from bs4 import BeautifulSoup
                        bk=epub.read_epub(fp); st,bp=[],[]
                        for it in bk.get_items():
                            if it.get_type()==5:
                                try: st.append(it.get_content().decode('utf-8','ignore'))
                                except: pass
                            elif it.get_type()==9:
                                try:
                                    sp=BeautifulSoup(it.get_content(),'html.parser')
                                    b=sp.find('body'); bp.append(str(b)if b else str(sp))
                                except: pass
                        h='<!DOCTYPE html><html><head><meta charset=utf-8><title>'+title+'</title>'
                        for s in st[:3]: h+='<style>'+s+'</style>'
                        h+='<style>body{max-width:800px;margin:0 auto;padding:20px;font-family:serif;font-size:18px;line-height:1.8}img{max-width:100%}</style></head><body><h1>'+title+'</h1>'+'\n'.join(bp)+'</body></html>'
                        self._html(h)
                    except: self.send_error(500)
                else:
                    r2=dbq("SELECT text_content FROM books WHERE id=?",(bid,))
                    t=(r2[0]['text_content'] if r2 else '') or ''
                    t=t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                    h='<!DOCTYPE html><html><head><meta charset=utf-8><title>'+title+'</title><style>body{max-width:800px;margin:0 auto;padding:20px;font-family:serif;font-size:18px;line-height:2;white-space:pre-wrap}</style></head><body><h1>'+title+'</h1><div>'+t+'</div></body></html>'
                    self._html(h)
            elif path.startswith("/api/books/") and path.endswith("/file"):
                bid=path.split("/")[3]
                r=dbq("SELECT file_path,file_format FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp,fmt=r[0]['file_path'],r[0]['file_format']
                if os.path.exists(fp):
                    self.send_response(200)
                    self.send_header("Content-Type",{"pdf":"application/pdf"}.get(fmt,"application/octet-stream"))
                    self.send_header("Content-Disposition","inline"); self.end_headers()
                    with open(fp,'rb')as f: self.wfile.write(f.read())
                else: self.send_error(404)
            elif path.startswith("/api/media/") and path.endswith("/file"):
                bid=path.split("/")[3]
                r=dbq("SELECT file_path,file_format FROM media WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp,fmt=r[0]['file_path'],r[0]['file_format']
                if os.path.exists(fp):
                    self.send_response(200)
                    self.send_header("Content-Type",{"mp3":"audio/mpeg","mp4":"video/mp4"}.get(fmt,"application/octet-stream"))
                    self.end_headers()
                    with open(fp,'rb')as f: self.wfile.write(f.read())
                else: self.send_error(404)
            elif path.startswith("/api/covers/"):
                cv = Path("data/covers")/path.split("/")[-1]
                if cv.exists():
                    self.send_response(200); self.send_header("Content-Type","image/jpeg"); self.end_headers()
                    with open(cv,'rb')as f: self.wfile.write(f.read())
                else: self.send_error(404)
            elif path.startswith("/api/books/"):
                bid=path.split("/")[3]
                r=dbq("SELECT * FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                self.json(dict(r[0]))
            elif path.startswith("/api/media/"):
                bid=path.split("/")[3]
                r=dbq("SELECT * FROM media WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                self.json(dict(r[0]))
            elif path == "/api/categories":
                rows = dbq("SELECT id, name FROM categories ORDER BY name")
                self.json([dict(r) for r in rows])
            else:
                self._page(qs)
        except Exception as e:
            try: self.send_error(500,str(e))
            except: pass

    def _page(self,qs):
        tb=dbq("SELECT count(*) as c FROM books WHERE status='active'")[0]['c']
        tm=dbq("SELECT count(*) as c FROM media WHERE status='active'")[0]['c']
        ts=dbq("SELECT count(*) as c FROM books WHERE status='active' AND summary IS NOT NULL")[0]['c']
        pn=qs.get('p',['home'])[0]
        nv=NAV.replace('{B}',str(tb)).replace('{M}',str(tm))
        h='<!DOCTYPE html><html><head><meta charset=utf-8><title>我的图书馆</title><style>'+CSS+'</style></head><body>'+nv+'<main>'

        if pn=='books':
            q=qs.get('q',[''])[0]; cat=qs.get('cat',[''])[0]
            s="SELECT id,title,file_format,file_size,cover_path FROM books WHERE status='active'"; pa=[]
            if q: s+=" AND title LIKE ?"; pa.append('%'+q+'%')
            if cat: s+=" AND id IN (SELECT book_id FROM book_categories WHERE category_id=?)"; pa.append(cat)
            s+=" ORDER BY created_at DESC LIMIT 80"
            rows=dbq(s,tuple(pa))
            h+='<h2>📖 书库 ('+str(len(rows))+')</h2>'
            h+='<form class=sch method=get><input type=hidden name=p value=books><input name=q placeholder=搜索书名 value="'+he(q)+'"><select name=cat><option value="">全部分类</option>'
            for r in dbq("SELECT id,name FROM categories ORDER BY name"):
                sel=' selected' if r['id']==cat else ''
                h+='<option value="'+r['id']+'"'+sel+'>'+he(r['name'])+'</option>'
            h+='</select><button>搜索</button></form>'
            for r in rows:
                cv='<img src="/api/covers/'+r['id']+'.jpg">' if r['cover_path'] else '<div class=cv>📚</div>'
                h+='<div class=bk onclick="location.href=\'/?p=detail&id='+r['id']+'\'"><a href="/?p=detail&id='+r['id']+'" onclick="event.stopPropagation()">'+cv+'</a><div class=info><div class=t>'+he(r['title'])[:60]+'</div><div class=m>'+r['file_format'].upper()+' '+str(round(r['file_size']/1024/1024,1))+'MB</div></div></div>'

        elif pn=='detail':
            bid=qs.get('id',[None])[0]; is_media=qs.get('type',[''])[0]=='media'
            if bid and not is_media:
                r=dbq("SELECT * FROM books WHERE id=?",(bid,))
                if r:
                    b=r[0]
                    a=dbq("SELECT a.name FROM authors a JOIN book_authors ba ON a.id=ba.author_id WHERE ba.book_id=?",(bid,))
                    c=dbq("SELECT c.name FROM categories c JOIN book_categories bc ON c.id=bc.category_id WHERE bc.book_id=?",(bid,))
                    h+='<div class=detail>'
                    h+='<img src="/api/covers/'+bid+'.jpg" class=detail-cover onerror="this.outerHTML=\'<div class=detail-cv>📚</div>\'">' if b['cover_path'] else '<div class=detail-cv>📚</div>'
                    h+='<h1>'+he(str(b['title']))+' <button class=btn onclick="event.stopPropagation();EDT(\''+bid+'\')" style="font-size:12px;padding:2px 8px">✏️</button></h1>'
                    h+='<div class=meta>'
                    if a: h+='<p><b>作者:</b> '+', '.join([he(x['name']) for x in a])+'</p>'
                    h+='<p><b>格式:</b> '+str(b['file_format']).upper()+' | <b>大小:</b> '+str(round(b['file_size']/1024/1024,1))+'MB | <b>页数:</b> '+str(b['page_count']or'-')+'</p>'
                    if b['publisher']: h+='<p><b>出版社:</b> '+he(str(b['publisher']))+'</p>'
                    if b['isbn']: h+='<p><b>ISBN:</b> '+str(b['isbn'])+'</p>'
                    h+='</div><div style="clear:both"></div>'
                    if c:
                        h+='<div class=sec>'
                        for x in c: h+='<span class=tag style=background:'+cc(x['name'])+'>'+he(x['name'])+'</span> '
                        h+='</div>'
                    if b['difficulty']:
                        dc={'入门':'#52c41a','中级':'#fa8c16','高级':'#ff4d4f'}
                        h+=' <span class=tag style=background:'+dc.get(b['difficulty'],'#999')+'>难度: '+b['difficulty']+'</span>'
                    if b['summary']:
                        h+='<div class=sec><h3>🤖 AI 摘要</h3><div style=white-space:pre-wrap;line-height:1.8;background:#f9f9f9;padding:16px;border-radius:8px;margin-top:8px>'+he(str(b['summary']))+'</div></div>'
                    else:
                        h+='<div class=sec><p class=co>暂无摘要</p></div>'
                    read_url='/api/books/'+bid+'/'+('file' if b['file_format']=='pdf' else 'read')
                    h+='<div class=sec><a href="'+read_url+'" class=btn target=_blank>📖 阅读</a> <a href="/?p=books" class="btn bb2">返回</a></div></div>'

        elif pn=='media':
            rows=dbq("SELECT id,title,media_type,file_format,duration,file_size FROM media WHERE status='active' ORDER BY created_at DESC LIMIT 80")
            h+='<h2>🎧 媒体库 ('+str(len(rows))+')</h2>'
            for r in rows:
                ic='🎵' if r['media_type']=='audio' else '🎬'
                d=r['duration']or 0; dur=str(int(d/60))+':'+str(int(d%60)).zfill(2)
                h+='<div class=bk onclick="location.href=\'/?p=detail&id='+r['id']+'&type=media\'"><div style="width:60px;height:60px;border-radius:8px;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;font-size:28px;color:#fff;flex-shrink:0">'+ic+'</div><div class=info><div class=t>'+he(r['title'])[:60]+'</div><div class=m>'+r['file_format'].upper()+' · '+dur+'</div></div></div>'

        elif pn=='import':
            h+='<h2>📥 导入新书</h2>'
            h+='<div class=panel><h3>1. 选择文件上传</h3>'
            h+='<input type=file id=f1 multiple accept=".pdf,.epub,.mobi,.azw3,.txt,.md,.zip,.rar,.7z" style=display:none onchange="UF(this.files)"><input type=file id=f2 webkitdirectory style=display:none onchange="UF(this.files)">'
            h+='<button class=btn onclick="document.getElementById(\'f1\').click()">📁 选择文件</button> <button class=btn onclick="document.getElementById(\'f2\').click()">📂 选择文件夹</button>'
            h+='<div id=up style=margin-top:8px;font-size:13px;color:#999></div></div>'
            h+='<div class=panel><h3>2. 扫描本地目录</h3>'
            h+='<p style=color:#999;margin-bottom:8px>扫描 F:\\书籍 目录中的新书</p>'
            h+='<input type=text id=sd value="F:\\书籍" style="padding:8px;border:1px solid #ddd;border-radius:4px;width:300px"> <button class=btn id=scanBtn onclick="SCAN()">🔍 开始扫描</button>'
            h+='<div id=sr style=margin-top:8px;font-size:13px;color:#999></div></div>'

        else:
            import_rem = dbq("SELECT count(*) as c FROM books WHERE status='active' AND id NOT IN (SELECT book_id FROM book_categories)")[0]['c']
            sum_rem = dbq("SELECT count(*) as c FROM books WHERE status='active' AND summary IS NULL AND text_content IS NOT NULL")[0]['c']
            h+='<h2>🏠 首页</h2>'
            h+='<div class=row><a href="/?p=books" class=sb><div class=n style=color:#1677ff>'+str(tb)+'</div><div class=l>📚 书籍</div></a><a href="/?p=detail&list=1" class=sb><div class=n style=color:#52c41a>'+str(ts)+'</div><div class=l>🤖 已摘要</div></a><a href="/?p=media" class=sb><div class=n style=color:#fa8c16>'+str(tm)+'</div><div class=l>🎧 媒体</div></a></div>'
            h+='<div class=panel><h3>🤖 AI 处理</h3><p class=co style=margin-bottom:8px>需要 Ollama 在运行。未分类: '+str(import_rem)+' 本 | 未摘要: '+str(sum_rem)+' 本 (有文本的)</p>'
            h+='<button class=btn id=clsBtn onclick="CLS()" style=margin-right:8px>🤖 AI 分类 (5本/次)</button><button class=btn id=sumBtn onclick="SUM()">🤖 AI 摘要 (3本/次)</button>'
            h+='<div id=clsRes style=margin-top:4px;font-size:13px></div><div id=sumRes style=margin-top:4px;font-size:13px></div></div>'
            h+='<div class=panel><h3>📊 格式分布</h3>'
            for r in dbq("SELECT file_format,count(*)as c FROM books WHERE status='active' GROUP BY file_format ORDER BY c DESC"):
                h+='<span class=tag style=background:'+fc(r['file_format'])+'>'+r['file_format'].upper()+' '+str(r['c'])+'</span> '
            h+='</div><div class=panel><h3>🏷️ 分类分布</h3>'
            for r in dbq("SELECT cat.name,count(*)as c FROM categories cat JOIN book_categories bc ON cat.id=bc.category_id JOIN books b ON b.id=bc.book_id WHERE b.status='active' GROUP BY cat.name ORDER BY c DESC LIMIT 20"):
                h+='<span class=tag style=background:'+cc(r['name'])+'>'+he(r['name'])+' '+str(r['c'])+'</span> '
            h+='</div>'

        h+=COMMON_JS
        if pn=='import':
            h+='<script>var _f=[],_i=0,_ok=0,_d=0,_e=0;function UF(fs){_f=Array.from(fs);_i=0;_ok=0;_d=0;_e=0;NX()}function NX(){if(_i>=_f.length){document.getElementById("up").innerHTML="完成! 新增 "+_ok+" 本, 重复 "+_d+" 本" + (_e>0?", 失败 "+_e+" 本":"") + " <a href=/ onclick=location.reload()>刷新</a>";return}var fd=new FormData();fd.append("file",_f[_i]);_i++;var x=new XMLHttpRequest();x.open("POST","/api/import-upload");x.onload=function(){try{var r=JSON.parse(x.responseText);if(r.success)_ok++;else if(r.duplicate)_d++;else _e++;if(r.error)alert("错误: "+r.error)}catch(e){_e++}document.getElementById("up").innerHTML="上传中... "+_i+"/"+_f.length;NX()};x.onerror=function(){_e++;NX()};x.send(fd)}function SCAN(){var dir=document.getElementById("sd").value;document.getElementById("scanBtn").disabled=true;document.getElementById("scanBtn").textContent="扫描中...";var x=new XMLHttpRequest();x.open("POST","/api/import-scan");x.setRequestHeader("Content-Type","application/json");x.onload=function(){var r=JSON.parse(x.responseText);document.getElementById("sr").innerHTML=r.error?"错误: "+r.error:"新增 "+r.new+" 本, 跳过重复 "+r.dupes+" 本"+(r.errors>0?", 失败 "+r.errors+" 本":"")+" <a href=/ onclick=location.reload()>刷新</a>";document.getElementById("scanBtn").disabled=false;document.getElementById("scanBtn").textContent="🔍 开始扫描"};x.onerror=function(){document.getElementById("sr").innerHTML="错误";document.getElementById("scanBtn").disabled=false;document.getElementById("scanBtn").textContent="🔍 开始扫描"};x.send(JSON.stringify({dir:dir}))}</script>'

        h+='</main></body></html>'
        self._html(h)

    def _html(self,h):
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(h.encode('utf-8'))

    def json(self,d):
        self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
        self.wfile.write(json.dumps(d,ensure_ascii=False).encode('utf-8'))

if __name__ == "__main__":
    print("🚀 http://localhost:8000")
    http.server.HTTPServer(("0.0.0.0",8000), H).serve_forever()
''')
print("OK - simple_server.py generated")
