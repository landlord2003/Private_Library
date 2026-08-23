"""My Library Server"""
import http.server, json, sqlite3, os, sys, io, urllib.parse, urllib.request, urllib.error, uuid, hashlib, shutil, threading, time, subprocess, tempfile, concurrent.futures

from pathlib import Path

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "library.db")
_task_status = {}
_count_cache = {"time": 0}

class OllamaError(Exception): pass

def _ollama_generate(prompt, model="qwen2.5:7b", timeout=180, temperature=0.1, num_ctx=4096, num_predict=None):
    """调用 Ollama API，使用 stdlib urllib 替代 requests，无需安装第三方库"""
    payload = {"model": model, "prompt": prompt, "stream": False, "temperature": temperature, "options": {"num_ctx": num_ctx}}
    if num_predict is not None:
        payload["options"]["num_predict"] = num_predict
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("response", "").strip()
    except urllib.error.HTTPError as e:
        raise OllamaError(f"Ollama API 错误: {e.code}")
    except TimeoutError:
        raise OllamaError(f"Ollama 超时: 超过{timeout}秒")
    except urllib.error.URLError as e:
        if "timed out" in str(e).lower():
            raise OllamaError(f"Ollama 超时: 超过{timeout}秒")
        raise OllamaError("Ollama连接失败，请确认Ollama正在运行")

def get_counts():
    """同步获取统计数据。缓存 300 秒，导入新书后缓存被置 0 触发立即刷新。"""
    now = time.time()
    if now - _count_cache["time"] < 300 and "tb" in _count_cache:
        return _count_cache
    try:
        c = sqlite3.connect(DB, timeout=120)
        c.row_factory = sqlite3.Row
        queries = {
            "tb": "SELECT count(*)as c FROM books WHERE status='active'",
            "tm": "SELECT count(*)as c FROM media WHERE status='active'",
            "ts": "SELECT count(*)as c FROM books WHERE status='active' AND summary IS NOT NULL",
            "import_rem": "SELECT count(*)as c FROM books WHERE status='active' AND id NOT IN(SELECT book_id FROM book_categories)",
            "sum_rem": "SELECT count(*)as c FROM books WHERE status='active' AND summary IS NULL AND text_content IS NOT NULL",
            "no_text": "SELECT count(*)as c FROM books WHERE status='active' AND text_content IS NULL",
            "fmt_dist": "SELECT file_format as k,count(*)as c FROM books WHERE status='active' GROUP BY file_format ORDER BY c DESC",
            "cat_dist": "SELECT cat.id as cid,cat.name as k,count(*)as c FROM categories cat JOIN book_categories bc ON cat.id=bc.category_id JOIN books b ON b.id=bc.book_id WHERE b.status='active' GROUP BY cat.id,cat.name ORDER BY c DESC LIMIT 20",
            "mtr": "SELECT count(*)as c FROM media WHERE status='active' AND transcript IS NOT NULL",
            "msu": "SELECT count(*)as c FROM media WHERE status='active' AND summary IS NOT NULL",
        }
        for k, sql in queries.items():
            try:
                rows = [dict(row) for row in c.execute(sql).fetchall()]
                if k in ("fmt_dist", "cat_dist"):
                    _count_cache[k] = rows
                else:
                    _count_cache[k] = rows[0]['c'] if rows else 0
            except Exception as e:
                print(f"[count失败] {k}: {type(e).__name__}: {e}", flush=True)
                _count_cache[k] = 0 if k not in ("fmt_dist","cat_dist") else []
        c.close()
        _count_cache["time"] = time.time()
    except Exception as e:
        print(f"[统计缓存异常] {type(e).__name__}: {e}", flush=True)
    return _count_cache

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
def fc(f): return {'pdf':'#ff4d4f','epub':'#1677ff','rar':'#fa8c16','mobi':'#52c41a','azw3':'#13c2c2','txt':'#1677ff','md':'#722ed1'}.get(f,'#999')
def cc(c): return {'计算机与编程':'#1677ff','历史与人文':'#fa8c16','文学与小说':'#52c41a','哲学与思想':'#722ed1','科学与科普':'#13c2c2','经济与管理':'#eb2f96','心理与成长':'#fa541c','教育学习':'#2f54eb','艺术设计':'#a0d911','社会与政治':'#f5222d','生活与健康':'#7cb305','其他':'#999'}.get(c,'#999')

CSS = """* { margin:0; padding:0; box-sizing:border-box; } body { font-family: "Microsoft YaHei", Arial, sans-serif; background: #f5f5f5; display: flex; min-height: 100vh; } nav { width: 200px; background: #fff; padding: 20px 0; box-shadow: 2px 0 8px rgba(0,0,0,0.05); } nav h2 { padding: 0 20px 20px; color: #1677ff; font-size: 18px; border-bottom: 1px solid #f0f0f0; margin-bottom: 10px; } nav a { display: block; padding: 12px 20px; color: #333; text-decoration: none; font-size: 15px; } nav a:hover { background: #e6f4ff; color: #1677ff; } main { flex: 1; padding: 24px; overflow-y: auto; } .sb { background: #fff; padding: 20px; border-radius: 8px; text-align: center; min-width: 140px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); text-decoration: none; color: inherit; } .sb .n { font-size: 28px; font-weight: bold; } .sb .l { font-size: 13px; color: #999; margin-top: 4px; } .row { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; } .tag { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 12px; margin: 3px; color: #fff; } .panel { background: #fff; padding: 16px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); } .panel h3 { margin-bottom: 12px; font-size: 16px; } .sch { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; } .sch input, .sch select { padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; } .sch input { flex: 1; min-width: 180px; } .sch button { padding: 8px 20px; background: #1677ff; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; } .bk { background: #fff; border-radius: 8px; padding: 14px; margin-bottom: 8px; display: flex; gap: 12px; align-items: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); cursor: pointer; } .bk:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.1); } .bk img { width: 50px; height: 70px; object-fit: cover; border-radius: 4px; flex-shrink: 0; } .bk .cv { width: 50px; height: 70px; border-radius: 4px; flex-shrink: 0; background: linear-gradient(135deg, #667eea, #764ba2); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 22px; } .bk .info { flex: 1; min-width: 0; } .bk .t { font-weight: bold; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .bk .m { font-size: 12px; color: #999; margin-top: 2px; } a { color: #1677ff; text-decoration: none; } a:hover { text-decoration: underline; } .co { color: #999; } .btn { padding: 8px 20px; background: #1677ff; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; margin: 2px; } .bb2 { background: #fff; color: #1677ff; border: 1px solid #1677ff; } .detail { background: #fff; border-radius: 12px; padding: 24px; max-width: 800px; margin: 0 auto; box-shadow: 0 2px 12px rgba(0,0,0,0.1); overflow: hidden; } .detail h1 { margin-bottom: 16px; font-size: 22px; margin-right: 170px; } .detail .meta { margin-bottom: 16px; color: #666; font-size: 14px; line-height: 1.8; margin-right: 170px; } .detail .sec { margin: 16px 0; } .detail-cover { float: right; width: 150px; height: 200px; object-fit: contain; border-radius: 8px; background: #f5f5f5; margin-left: 16px; } .detail-cv { float: right; width: 150px; height: 200px; border-radius: 8px; background: linear-gradient(135deg, #667eea, #764ba2); display: flex; align-items: center; justify-content: center; color: #fff; font-size: 48px; margin-left: 16px; }"""

NAV = '<nav><h2>📚 我的图书馆</h2><a href="/">🏠 首页</a><a href="/?p=books">📖 书库 ({B})</a><a href="/?p=media">🎧 媒体库 ({M})</a><a href="/?p=import">📥 导入新书</a></nav>'

COMMON_JS = """<script>
function EDT(id,old){var t=prompt("新书名:",old);if(t&&t!==old){var x=new XMLHttpRequest();x.open("POST","/api/books/"+id+"/edit");x.setRequestHeader("Content-Type","application/json");x.onload=function(){location.reload()};x.send(JSON.stringify({title:t}));}}
var _clsTimer=null,_sumTimer=null;
function CLS(){
  var b=document.getElementById("clsBtn");if(b.disabled)return;
  var cnt=parseInt(document.getElementById("clsCnt").value)||10;
  b.disabled=true;b.textContent="分类启动中...";
  document.getElementById("clsRes").innerHTML="启动中（"+cnt+"本），请稍等...";
  var x=new XMLHttpRequest();x.open("POST","/api/classify-batch");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){b.disabled=false;b.textContent="🤖 AI 分类";_pollCls();};
  x.send(JSON.stringify({count:cnt}))
}
function _pollCls(){
  clearTimeout(_clsTimer);
  var x=new XMLHttpRequest();x.open("GET","/api/task-status");
  x.onload=function(){
    var r=JSON.parse(x.responseText);var c=r.classify||{};
    if(c.total>0){
      document.getElementById("clsRes").innerHTML="分类中: "+c.done+"/"+c.total+" 本";
      if(c.done<c.total)_clsTimer=setTimeout(_pollCls,2000);
      else document.getElementById("clsRes").innerHTML="✅ 分类完成: "+c.done+" 本 <a href=/ onclick=location.reload()>刷新</a>";
    }else{
      document.getElementById("clsRes").innerHTML=c.total===0?"等待AI响应...":"";
      _clsTimer=setTimeout(_pollCls,2000);
    }
  };
  x.onerror=function(){document.getElementById("clsRes").innerHTML="轮询出错，5秒后重试...";_clsTimer=setTimeout(_pollCls,5000);};
  x.send()
}
function SUM(){
  var b=document.getElementById("sumBtn");if(b.disabled)return;
  var cnt=parseInt(document.getElementById("sumCnt").value)||3;
  b.disabled=true;b.textContent="摘要启动中...";
  document.getElementById("sumRes").innerHTML="启动中（"+cnt+"本），请稍等...";
  var x=new XMLHttpRequest();x.open("POST","/api/summarize-batch");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){b.disabled=false;b.textContent="🤖 AI 摘要";_pollSum();};
  x.send(JSON.stringify({count:cnt}))
}
function _pollSum(){
  clearTimeout(_sumTimer);
  var x=new XMLHttpRequest();x.open("GET","/api/task-status");
  x.onload=function(){
    var r=JSON.parse(x.responseText);var s=r.summarize||{};
    if(s.total>0){
      document.getElementById("sumRes").innerHTML="摘要中: "+s.done+"/"+s.total+" 本";
      if(s.done<s.total)_sumTimer=setTimeout(_pollSum,3000);
      else document.getElementById("sumRes").innerHTML="✅ 摘要完成: "+s.done+" 本 <a href=/ onclick=location.reload()>刷新</a>";
    }else{
      document.getElementById("sumRes").innerHTML=s.total===0?"等待AI响应...":"";
      _sumTimer=setTimeout(_pollSum,3000);
    }
  };
  x.onerror=function(){document.getElementById("sumRes").innerHTML="轮询出错，5秒后重试...";_sumTimer=setTimeout(_pollSum,5000);};
  x.send()
}
var _extTimer=null;
function EXT(){
  var b=document.getElementById("extBtn");if(b.disabled)return;
  var cnt=parseInt(document.getElementById("extCnt").value)||10;
  b.disabled=true;b.textContent="提取启动中...";
  document.getElementById("extRes").innerHTML="提取中（"+cnt+"本），请稍等...";
  var x=new XMLHttpRequest();x.open("POST","/api/extract-batch");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){b.disabled=false;b.textContent="📄 提取文本";_pollExt();};
  x.send(JSON.stringify({count:cnt}))
}
function _pollExt(){
  clearTimeout(_extTimer);
  var x=new XMLHttpRequest();x.open("GET","/api/task-status");
  x.onload=function(){
    var r=JSON.parse(x.responseText);var e=r.extract||{};
    if(e.total>0){
      document.getElementById("extRes").innerHTML="提取中: "+e.done+"/"+e.total+" 本";
      if(e.done<e.total)_extTimer=setTimeout(_pollExt,2000);
      else document.getElementById("extRes").innerHTML="✅ 提取完成: "+e.done+" 本 <a href=/ onclick=location.reload()>刷新</a>";
    }else{
      document.getElementById("extRes").innerHTML=e.total===0?"等待响应...":"";
      _extTimer=setTimeout(_pollExt,2000);
    }
  };
  x.onerror=function(){document.getElementById("extRes").innerHTML="轮询出错，5秒后重试...";_extTimer=setTimeout(_pollExt,5000);};
  x.send()
}
//媒体转录、摘要前端20260801
var _trTimer=null;
function TRS(){
  var b=document.getElementById("trsBtn");if(b.disabled)return;
  var cnt=parseInt(document.getElementById("trsCnt").value)||10;
  var mt=document.getElementById("trsType").value;
  b.disabled=true;b.textContent="转录启动中...";
  document.getElementById("trsRes").innerHTML="启动中（"+cnt+"个），请稍等...";
  var x=new XMLHttpRequest();x.open("POST","/api/media/transcribe");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){b.disabled=false;b.textContent="🎙️ 媒体转录";_pollTrs();};
  x.send(JSON.stringify({count:cnt,media_type:mt}))
}
function _pollTrs(){
  clearTimeout(_trTimer);
  var x=new XMLHttpRequest();x.open("GET","/api/task-status");
  x.onload=function(){
    var r=JSON.parse(x.responseText);var t=r.transcribe||{};
    if(t.total>0){
      document.getElementById("trsRes").innerHTML="转录中: "+t.done+"/"+t.total;
      if(t.done<t.total)_trTimer=setTimeout(_pollTrs,3000);
      else document.getElementById("trsRes").innerHTML="✅ 转录完成: "+t.done+" 个 <a href=/ onclick=location.reload()>刷新</a>";
    }else{
      document.getElementById("trsRes").innerHTML=t.total===0?"等待中...":"";
      _trTimer=setTimeout(_pollTrs,3000);
    }
  };
  x.onerror=function(){document.getElementById("trsRes").innerHTML="轮询出错";_trTimer=setTimeout(_pollTrs,5000);};
  x.send()
}
var _msTimer=null;
function MSU(){
  var b=document.getElementById("msuBtn");if(b.disabled)return;
  var cnt=parseInt(document.getElementById("msuCnt").value)||10;
  b.disabled=true;b.textContent="摘要启动中...";
  document.getElementById("msuRes").innerHTML="启动中（"+cnt+"个），请稍等...";
  var x=new XMLHttpRequest();x.open("POST","/api/media/summarize");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){b.disabled=false;b.textContent="📝 转录→摘要";_pollMsu();};
  x.send(JSON.stringify({count:cnt}))
}
function _pollMsu(){
  clearTimeout(_msTimer);
  var x=new XMLHttpRequest();x.open("GET","/api/task-status");
  x.onload=function(){
    var r=JSON.parse(x.responseText);var s=r.media_summarize||{};
    if(s.total>0){
      document.getElementById("msuRes").innerHTML="摘要中: "+s.done+"/"+s.total;
      if(s.done<s.total)_msTimer=setTimeout(_pollMsu,3000);
      else document.getElementById("msuRes").innerHTML="✅ 摘要完成: "+s.done+" 个 <a href=/ onclick=location.reload()>刷新</a>";
    }else{
      document.getElementById("msuRes").innerHTML=s.total===0?"等待中...":"";
      _msTimer=setTimeout(_pollMsu,3000);
    }
  };
  x.onerror=function(){document.getElementById("msuRes").innerHTML="轮询出错";_msTimer=setTimeout(_pollMsu,5000);};
  x.send()
}

//媒体转录、摘要前端20260801结束
function editMediaTitle(mid,oldTitle){
  var t=prompt("新名称:",oldTitle);if(!t||t.trim()===''||t.trim()===oldTitle)return;
  var x=new XMLHttpRequest();x.open("POST","/api/media/"+mid+"/edit");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){var r=JSON.parse(x.responseText);if(r.ok)location.reload();else alert("编辑失败");};

  x.send(JSON.stringify({title:t.trim()}));
}
function EDTM(mid){var t=prompt("新名称:");if(t&&t.trim()){var x=new XMLHttpRequest();x.open("POST","/api/media/"+mid+"/edit");x.setRequestHeader("Content-Type","application/json");x.onload=function(){location.reload()};x.send(JSON.stringify({title:t.trim()}));}}

// 删除书籍/媒体 20260816
function DELB(id,title){
  if(!confirm("⚠️ 确定要删除这本书吗？\\n\\n《"+title+"》\\n\\n将删除：书籍记录、AI 摘要、分类/标签/作者关联、阅读笔记、封面。\\n注：网页上传的书会连源文件一起删除；磁盘扫描导入的原始文件会保留。\\n\\n此操作不可恢复！"))return;
  if(!confirm("再次确认：真的要删除《"+title+"》吗？删除后无法找回！"))return;
  var x=new XMLHttpRequest();x.open("POST","/api/books/"+id+"/delete");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){try{var r=JSON.parse(x.responseText);if(r.ok){alert("已删除");location.href="/?p=books";}else alert("删除失败: "+(r.error||"未知错误"));}catch(e){alert("删除失败")}};
  x.onerror=function(){alert("删除失败：网络错误")};
  x.send("{}");
}
function DELM(id,title){
  if(!confirm("⚠️ 确定要删除这个媒体文件吗？\\n\\n「"+title+"」\\n\\n将删除：媒体记录、转录文字、AI 摘要、标签/分类/笔记、上传的源文件。\\n\\n此操作不可恢复！"))return;
  if(!confirm("再次确认：真的要删除「"+title+"」吗？删除后无法找回！"))return;
  var x=new XMLHttpRequest();x.open("POST","/api/media/"+id+"/delete");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){try{var r=JSON.parse(x.responseText);if(r.ok){alert("已删除");location.href="/?p=media";}else alert("删除失败: "+(r.error||"未知错误"));}catch(e){alert("删除失败")}};
  x.onerror=function(){alert("删除失败：网络错误")};
  x.send("{}");
}

</script>"""

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

from contextlib import contextmanager

@contextmanager
def _suppress_mupdf_stdout():
    """线程安全地抑制 MuPDF 的 stdout/stderr 警告（不用 os.dup2，避免多线程干扰）"""
    _old_out = sys.stdout
    _old_err = sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = _old_out
        sys.stderr = _old_err

def _extract_epub_cover_zip(file_path):
    """从 EPUB ZIP 中直接提取封面图片（比 MuPDF 渲染快 10x+）"""
    import zipfile, xml.etree.ElementTree as ET
    OPF = '{http://www.idpf.org/2007/opf}'
    CNT = '{urn:oasis:names:tc:opendocument:xmlns:container}'
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            # 1. container.xml → OPF 路径
            croot = ET.fromstring(zf.read('META-INF/container.xml'))
            opf_path = None
            for rf in croot.iter(CNT + 'rootfile'):
                if rf.get('media-type') == 'application/oebps-package+xml':
                    opf_path = rf.get('full-path'); break
            if not opf_path: return None
            # 2. 解析 OPF，收集 manifest items
            oroot = ET.fromstring(zf.read(opf_path))
            opf_dir = opf_path.rsplit('/', 1)[0] + '/' if '/' in opf_path else ''
            items = {}
            for item in oroot.iter(OPF + 'item'):
                iid = item.get('id'); items[iid] = {
                    'href': item.get('href',''), 'mt': item.get('media-type',''),
                    'props': item.get('properties','')
                }
            # 3. 找封面 ID（三种常见方式）
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
            # 4. 提取图片
            href = items[cover_id]['href']
            for path in [opf_dir + href, href]:
                try:
                    data = zf.read(path)
                    if len(data) > 500: return data
                except KeyError: continue
    except Exception as _e:
        print(f"[cover ERR] EPUB cover extract failed: {file_path} -> {_e}")
    return None

def extract_cover_for(book_id, file_path, fmt):
    try:
        file_path = _resolve_path(file_path)
        cover_data = None
        if fmt == 'epub':
            # 快速路径：直接从 ZIP 提取封面图片
            cover_data = _extract_epub_cover_zip(file_path)
            if not cover_data:
                # 慢速路径：MuPDF 渲染第一页
                import fitz
                with _suppress_mupdf_stdout():
                    doc = fitz.open(file_path)
                    if doc.page_count > 0:
                        pix = doc[0].get_pixmap(dpi=72); cover_data = pix.tobytes("jpg")
                    doc.close()
        elif fmt in ('pdf','mobi','azw3'):
            import fitz
            with _suppress_mupdf_stdout():
                doc = fitz.open(file_path)
                if doc.page_count > 0:
                    pix = doc[0].get_pixmap(dpi=72); cover_data = pix.tobytes("jpg")
                doc.close()
        elif fmt in ('rar','zip'):
            import tempfile,subprocess
            r = subprocess.run([SEVEN_ZIP, 'l', '-slt', '-sccUTF-8', file_path], capture_output=True, text=True, timeout=30)
            entries = []; cur = {}
            for line in r.stdout.split('\n'):
                if line.startswith('Path ='): cur['path'] = line[7:].strip()
                elif line.startswith('Size ='): cur['size'] = int(line[7:].strip()) if line[7:].strip().isdigit() else 0
                elif line == '' and 'path' in cur: entries.append(cur); cur = {}
            if 'path' in cur: entries.append(cur)
            # 优先找PDF
            pdf_entry = next((e for e in entries if e['path'].lower().endswith('.pdf') and e.get('size',0) > 10000), None)
            if pdf_entry:
                tmpdir = tempfile.mkdtemp()
                try:
                    subprocess.run([SEVEN_ZIP, 'e', '-o'+tmpdir, '-sccUTF-8', '-y', file_path, pdf_entry['path']], capture_output=True, timeout=60)
                    tmp_pdf = os.path.join(tmpdir, os.path.basename(pdf_entry['path']))
                    if os.path.exists(tmp_pdf):
                        import fitz
                        with _suppress_mupdf_stdout():
                            doc = fitz.open(tmp_pdf)
                            if doc.page_count > 0: pix = doc[0].get_pixmap(dpi=72); cover_data = pix.tobytes("jpg")
                            doc.close()
                finally:
                    import shutil; shutil.rmtree(tmpdir, ignore_errors=True)
            # 没有PDF就找图片
            if not cover_data:
                img_entry = next((e for e in entries if e['path'].lower().endswith(('.jpg','.jpeg','.png','.bmp')) and e.get('size',0) > 5000), None)
                if img_entry:
                    tmpdir = tempfile.mkdtemp()
                    try:
                        subprocess.run([SEVEN_ZIP, 'e', '-o'+tmpdir, '-sccUTF-8', '-y', file_path, img_entry['path']], capture_output=True, timeout=60)
                        tmp_img = os.path.join(tmpdir, os.path.basename(img_entry['path']))
                        if os.path.exists(tmp_img):
                            with open(tmp_img, 'rb') as f: cover_data = f.read()
                    finally:
                        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)
        if cover_data and len(cover_data) > 500:
            cvp = os.path.join("data","covers",book_id+".jpg"); os.makedirs(os.path.dirname(cvp),exist_ok=True)
            with open(cvp,'wb') as f: f.write(cover_data)
            dbe("UPDATE books SET cover_path=? WHERE id=?",(cvp,book_id))
    except Exception as e:
        print(f"[cover_error] book_id={book_id} fmt={fmt}: {e}", flush=True)

def _resolve_path(file_path):
       """相对→绝对 + 盘符自动适配"""
       import os
       file_path = file_path.replace('/', '\\')
       # 相对路径转绝对
       if not os.path.isabs(file_path):
            file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), file_path)
       # 直接存在就直接用
       if os.path.exists(file_path):
            return file_path
       # 盘符变了，遍历所有盘符
       for drive in "CDEFGHIJK":
           alt = drive + file_path[1:]
           if os.path.exists(alt):
               return alt
       return file_path

# === 7z 压缩包支持 ===
SEVEN_ZIP = r"C:\Program Files\7-Zip\7z.exe"

def list_archive_contents(archive_path):
    """用 7z 列出压缩包内的文件列表"""
    import subprocess
    try:
        result = subprocess.run([SEVEN_ZIP, 'l', '-slt', '-sccUTF-8', archive_path],
                                capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')
        files = []
        current = {}
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line.startswith('Path ='):
                if current: files.append(current)
                current = {'path': line[6:].strip()}
            elif line.startswith('Size ='):
                try: current['size'] = int(line[6:].strip())
                except: current['size'] = 0
        if current: files.append(current)
        # 只返回实际文件（排除目录）
        return [f for f in files if f.get('size', 0) > 0]
    except Exception as e:
        print(f"[7z list error] {e}", flush=True)
        return []

def extract_archive_file(archive_path, file_name, dest_dir):
    """从压缩包中提取单个文件到 dest_dir，返回提取后的文件路径"""
    import subprocess
    try:
        os.makedirs(dest_dir, exist_ok=True)
        subprocess.run([SEVEN_ZIP, 'e', archive_path, file_name, f'-o{dest_dir}', '-y'],
                       capture_output=True, timeout=120)
        extracted = os.path.join(dest_dir, os.path.basename(file_name))
        return extracted if os.path.exists(extracted) else None
    except Exception as e:
        print(f"[7z extract error] {e}", flush=True)
        return None

def _title_fallback(book_id):
    """Use book metadata as minimal text for books that can't be extracted."""
    r = dbq("SELECT title,publisher,description FROM books WHERE id=?",(book_id,))
    if r:
        parts = [r[0]['title'] or '']
        if r[0]['publisher']: parts.append('Publisher: ' + r[0]['publisher'])
        if r[0]['description']: parts.append(r[0]['description'])
        text = '\n'.join(parts)
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
                return _title_fallback(book_id)
        elif fmt == 'epub':
            # Use zipfile to read EPUB directly (more robust than ebooklib)
            import zipfile
            from bs4 import BeautifulSoup
            with zipfile.ZipFile(file_path) as zf:
                for name in zf.namelist():
                    if name.endswith(('.html', '.xhtml', '.htm')):
                        try:
                            raw = zf.read(name)
                            soup = BeautifulSoup(raw, 'html.parser')
                            text += soup.get_text()
                        except: pass
        elif fmt in ('txt', 'md'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        elif fmt in ('mobi', 'azw3', 'azw'):
            try:
                import mobi
                tempdir, filepath = mobi.extract(file_path)
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                shutil.rmtree(tempdir, ignore_errors=True)
            except: pass
        elif fmt in ('rar', 'zip', '7z'):
            # Extract archive, find book files inside
            import zipfile, tempfile
            tmp = tempfile.mkdtemp()
            try:
                if fmt == 'zip' or file_path.endswith('.zip'):
                    with zipfile.ZipFile(file_path) as z:
                        z.extractall(tmp)
                elif fmt == 'rar' or file_path.endswith('.rar'):
                    try:
                        import rarfile
                        with rarfile.RarFile(file_path) as rf:
                            rf.extractall(tmp)
                    except ImportError:
                        pass  # rarfile not installed
                # Find book files in extracted directory
                for root, dirs, files in os.walk(tmp):
                    for fn in files:
                        ext = fn.rsplit('.',1)[-1].lower() if '.' in fn else ''
                        if ext in ('pdf','epub','txt','md'):
                            inner = os.path.join(root, fn)
                            try:
                                if ext == 'pdf':
                                    import fitz
                                    doc = fitz.open(inner)
                                    for i, page in enumerate(doc):
                                        if i >= 50: break
                                        text += page.get_text()
                                    doc.close()
                                elif ext == 'epub':
                                    from ebooklib import epub
                                    from bs4 import BeautifulSoup
                                    bk = epub.read_epub(inner, options={'ignore_ncx': True})
                                    for item in bk.get_items():
                                        if item.get_type() == 9:
                                            try:
                                                soup = BeautifulSoup(item.get_content(), 'html.parser')
                                                text += soup.get_text()
                                            except: pass
                                elif ext in ('txt','md'):
                                    with open(inner, 'r', encoding='utf-8', errors='ignore') as f:
                                        text += f.read()
                            except: pass
                        if len(text) > 5000: break
                    if len(text) > 5000: break
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        if text and len(text.strip()) > 10:
            text = text[:200000]
            dbe("UPDATE books SET text_content=? WHERE id=?", (text, book_id))
            return True
        # Fallback: use title if extraction yielded nothing
        return _title_fallback(book_id)
    except Exception as e:
        print(f"[文本提取异常] {file_path}: {type(e).__name__}: {e}", flush=True)
        return _title_fallback(book_id)

def run_extract_async(count=10):
    if _task_status.get('er'): return {"status":"running"}
    _task_status['er'] = True
    _task_status['er_r'] = {"done":0,"total":0}
    def w():
        try:
            books = dbq("SELECT id,file_path,file_format,title FROM books WHERE status='active' AND text_content IS NULL LIMIT ?",(int(count),))
            rv = {"done":0,"total":len(books)}
            for b in books:
                try:
                    # Per-book timeout: 30 seconds max
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        future = ex.submit(extract_text_for, b['id'], b['file_path'], b['file_format'])
                        try:
                            ok = future.result(timeout=30)
                        except concurrent.futures.TimeoutError:
                            print(f"[超时30s跳过] {b['title'][:40]} ({b['file_format']})", flush=True)
                            ok = _title_fallback(b['id'])
                    if ok:
                        rv["done"]+=1; _task_status['er_r']=rv
                except Exception as e: print(f"[批量提取异常] {b['title'][:30]}: {type(e).__name__}: {e}",flush=True)
            _task_status['er_r']=rv
        finally:
            _task_status['er']=False
            _count_cache["time"] = 0  # invalidate cache so counts refresh
    threading.Thread(target=w,daemon=True).start()
    return {"status":"started"}

def run_classify_async(count=10):
    if _task_status.get('cr'): return {"status":"running"}
    _task_status['cr'] = True
    _task_status['cr_r'] = {"done":0,"total":0}
    def w():
        try:
            books = dbq("SELECT id,title,text_content FROM books WHERE status='active' AND id NOT IN (SELECT book_id FROM book_categories) LIMIT ?",(int(count),))
            cats = ["计算机与编程","历史与人文","文学与小说","哲学与思想","科学与科普","经济与管理","心理与成长","教育学习","艺术设计","社会与政治","生活与健康"]
            rv = {"done":0,"total":len(books)}
            for b in books:
                try:
                    clist="\n".join("- "+c for c in cats)
                    prompt=f"判断以下书籍类别。可选类别：\n{clist}\n\n书名：{b['title']}\n内容：{(b['text_content'] or '')[:1500]}\n只返回JSON：{{\"category\":\"类别名\",\"tags\":[\"标签1\",\"标签2\"],\"difficulty\":\"入门/中级/高级\"}}"
                    resp=_ollama_generate(prompt, model="qwen2.5:7b", timeout=180, temperature=0.1, num_ctx=4096)
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
                except Exception as e: print(f"[分类异常] {b['title'][:30]}: {type(e).__name__}: {e}",flush=True)
            _task_status['cr_r']=rv
        finally:
            _task_status['cr']=False
            _count_cache["time"] = 0
    threading.Thread(target=w,daemon=True).start()
    return {"status":"started"}

def run_summarize_async(count=3):
    if _task_status.get('sr'): return {"status":"running"}
    _task_status['sr'] = True
    _task_status['sr_r'] = {"done":0,"total":0}
    def w():
        try:
            books=dbq("SELECT id,title,text_content FROM books WHERE status='active' AND summary IS NULL AND text_content IS NOT NULL LIMIT ?",(int(count),))
            rv={"done":0,"total":len(books)}
            for b in books:
                try:
                    prompt=f"你是专业图书摘要助手。书名：{b['title']}\n内容：{(b['text_content'] or '')[:2000]}\n按以下结构输出（中文）：\n1. 一句话总结\n2. 核心观点（3-5条）\n3. 关键概念\n4. 适合读者\n5. 难度评级：入门/中级/高级"
                    summary=_ollama_generate(prompt, model="qwen2.5:7b", timeout=300, temperature=0.3, num_ctx=4096)
                    if len(summary)>20:
                        dbe("UPDATE books SET summary=?,summary_model=?,summary_updated=datetime('now') WHERE id=?",(summary,"qwen2.5:7b",b['id']))
                        if "高级" in summary: dbe("UPDATE books SET difficulty='高级' WHERE id=? AND difficulty IS NULL",(b['id'],))
                        elif "中级" in summary: dbe("UPDATE books SET difficulty='中级' WHERE id=? AND difficulty IS NULL",(b['id'],))
                        elif "入门" in summary: dbe("UPDATE books SET difficulty='入门' WHERE id=? AND difficulty IS NULL",(b['id'],))
                        rv["done"]+=1; _task_status['sr_r']=rv
                except Exception as e: print(f"[摘要异常] {b['title'][:30]}: {type(e).__name__}: {e}",flush=True)
            _task_status['sr_r']=rv
        finally:
            _task_status['sr']=False
            _count_cache["time"] = 0
    threading.Thread(target=w,daemon=True).start()
    return {"status":"started"}
#20260801添加媒体提取摘要
# ==================== 媒体转录/摘要 ====================

def get_whisper_model():
    import os as _os
    _os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
    _os.environ['HF_HUB_DISABLE_XET'] = '1'
    
    import faster_whisper
    try:
        import torch
        device = "cuda"  if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
    except ImportError:
        device = "cpu"
        compute_type = "int8"
    model_size = os.environ.get("WHISPER_MODEL", "medium")
    print(f"[Whisper] 模型: {model_size}, device={device}", flush=True)
    return faster_whisper.WhisperModel(model_size, device=device, compute_type=compute_type)

def extract_audio(file_path, output_wav):
    cmd = ["ffmpeg", "-y", "-i", file_path, "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", "-loglevel", "error", output_wav]
    subprocess.run(cmd, check=True, timeout=600)

def get_audio_duration(file_path):
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except:
        return 0

def transcribe_file(file_path, media_type="audio"):
    """转录文件（调用方需自行处理超时）"""
    wav_path = None
    try:
        if media_type == "video":
            wav_path = tempfile.mktemp(suffix=".wav")
            extract_audio(file_path, wav_path)
            audio_path = wav_path
        else:
            audio_path = file_path
        duration = get_audio_duration(audio_path)
        if duration > 7200:
            return f"[文件时长 {duration/3600:.1f} 小时，超过2小时限制，已跳过]"
        model = get_whisper_model()
        segments, info = model.transcribe(audio_path, beam_size=5, language="zh", vad_filter=True)
        text_parts = [seg.text.strip() for seg in segments]
        return " ".join(text_parts) if text_parts else "[未检测到语音]"
    except Exception as e:
        return f"[转录失败: {str(e)[:200]}]"
    finally:
        if wav_path and os.path.exists(wav_path):
            try: os.unlink(wav_path)
            except: pass

def summarize_text(text, model_name="qwen2.5:7b", timeout_sec=180):
    if len(text) > 8000:
        text = text[:8000] + "\n... (文本过长已截断)"
    prompt = f"""请为以下音频/视频的转录文字写一个简洁的摘要（300字以内），包括：
1. 主题概述
2. 关键要点（3-5条）
3. 目标受众或用途

转录文字：
{text}

摘要："""
    try:
        result = _ollama_generate(prompt, model=model_name, timeout=timeout_sec, temperature=0.3, num_predict=600)
        return result if result else "[摘要为空]"
    except OllamaError as e:
        return f"[摘要失败: {str(e)[:100]}]"
    except Exception as e:
        return f"[摘要请求失败: {str(e)[:100]}]"


def run_transcribe_async(count=10, media_type="all"):
    if _task_status.get('tr'): return {"status":"running"}
    _task_status['tr'] = True
    _task_status['tr_r'] = {"done":0,"total":0}
    def w():
        try:
            wh = "status='active' AND transcript IS NULL"
            if media_type == 'audio': wh += " AND media_type='audio'"
            elif media_type == 'video': wh += " AND media_type='video'"
            media_list = dbq(f"SELECT id,title,file_path,media_type FROM media WHERE {wh} ORDER BY created_at ASC LIMIT ?", (int(count),))
            rv = {"done":0,"total":len(media_list),"current":"","error_count":0}
            for m in media_list:
                try:
                    fp = _resolve_path(m['file_path'])
                    rv["current"] = m['title'][:50]
                    _task_status['tr_r'] = rv
                    if not os.path.exists(fp):
                        dbe("UPDATE media SET transcript='[文件不存在]', updated_at=datetime('now') WHERE id=?", (m['id'],))
                        rv["done"] += 1; rv["error_count"] += 1
                        continue
                    result_holder = [None]
                    def _do():
                        result_holder[0] = transcribe_file(fp, m['media_type'])
                    t = threading.Thread(target=_do, daemon=True)
                    t.start()
                    t.join(timeout=1200)
                    if t.is_alive():
                        dbe("UPDATE media SET transcript='[转录超时: 超过20分钟，已跳过]', updated_at=datetime('now') WHERE id=?", (m['id'],))
                        rv["done"] += 1; rv["error_count"] += 1
                    else:
                        transcript = result_holder[0] if result_holder[0] else "[转录结果为空]"
                        model_name = os.environ.get("WHISPER_MODEL", "medium")
                        dbe("UPDATE media SET transcript=?, transcript_model=?, updated_at=datetime('now') WHERE id=?", (transcript, f"faster-whisper-{model_name}", m['id']))
                        rv["done"] += 1
                    _task_status['tr_r'] = rv
                except Exception as e:
                    print(f"[转录异常] {m['title'][:30]}: {e}", flush=True)
                    try:
                        dbe("UPDATE media SET transcript=?, updated_at=datetime('now') WHERE id=?", (f"[转录失败: {str(e)[:200]}]", m['id']))
                    except: pass
                    rv["done"] += 1; rv["error_count"] += 1
                    _task_status['tr_r'] = rv
            _task_status['tr_r'] = rv
        
        finally:
            _task_status['tr'] = False
            _count_cache["time"] = 0
    threading.Thread(target=w, daemon=True).start()
    return {"status":"started"}

def run_media_summarize_async(count=10):
    if _task_status.get('ms'): return {"status":"running"}
    _task_status['ms'] = True
    _task_status['ms_r'] = {"done":0,"total":0}
    def w():
        try:
            media_list = dbq("SELECT id,title,transcript FROM media WHERE status='active' AND transcript IS NOT NULL AND summary IS NULL LIMIT ?", (int(count),))
            rv = {"done":0,"total":len(media_list),"current":"","error_count":0}
            for m in media_list:
                try:
                    rv["current"] = m['title'][:50]
                    _task_status['ms_r'] = rv
                    if not m['transcript'] or m['transcript'].startswith('[转录失败') or m['transcript'].startswith('[转录超时') or m['transcript'] == '[文件不存在]':
                        dbe("UPDATE media SET summary='[无可转录文本]', summary_model='skipped', summary_updated=datetime('now') WHERE id=?", (m['id'],))
                        rv["done"] += 1; rv["error_count"] += 1
                        continue
                    result_holder = [None]
                    def _do(txt=m['transcript']):
                        result_holder[0] = summarize_text(txt)
                    t = threading.Thread(target=_do, daemon=True)
                    t.start()
                    t.join(timeout=300)
                    if t.is_alive():
                        dbe("UPDATE media SET summary='[摘要超时: 超过5分钟，已跳过]', summary_model='timeout', summary_updated=datetime('now') WHERE id=?", (m['id'],))
                        rv["done"] += 1; rv["error_count"] += 1
                    else:
                        summary = result_holder[0] if result_holder[0] else "[摘要结果为空]"
                        dbe("UPDATE media SET summary=?, summary_model=?, summary_updated=datetime('now') WHERE id=?", (summary, "qwen2.5:7b", m['id']))
                        rv["done"] += 1
                    _task_status['ms_r'] = rv
                except Exception as e:
                    print(f"[摘要异常] {m['title'][:30]}: {e}", flush=True)
                    try:
                        dbe("UPDATE media SET summary=?, summary_model='error', summary_updated=datetime('now') WHERE id=?", (f"[摘要失败: {str(e)[:200]}]", m['id']))
                    except: pass
                    rv["done"] += 1; rv["error_count"] += 1
            _task_status['ms_r'] = rv
       

        finally:
            _task_status['ms'] = False
            _count_cache["time"] = 0
    threading.Thread(target=w, daemon=True).start()
    return {"status":"started"}

def run_transcribe_one_async(media_id):
    if _task_status.get('tr1'): return {"status":"running"}
    _task_status['tr1'] = True
    _task_status['tr1_r'] = {"done":0,"total":1,"message":""}
    def w():
        try:
            m_list = dbq("SELECT id,title,file_path,media_type FROM media WHERE id=?", (media_id,))
            if not m_list:
                _task_status['tr1_r'] = {"done":0,"total":1,"message":"媒体未找到"}; return
            m = m_list[0]
            fp = _resolve_path(m['file_path'])
            if not os.path.exists(fp):
                _task_status['tr1_r'] = {"done":0,"total":1,"message":"文件不存在"}; return
            transcript = transcribe_file(fp, m['media_type'])
            model_name = os.environ.get("WHISPER_MODEL", "medium")
            dbe("UPDATE media SET transcript=?, transcript_model=?, updated_at=datetime('now') WHERE id=?", (transcript, f"faster-whisper-{model_name}", m['id']))
            _task_status['tr1_r'] = {"done":1,"total":1,"message":"转录完成"}
        except Exception as e:
            _task_status['tr1_r'] = {"done":0,"total":1,"message":f"转录失败: {str(e)[:100]}"}
        finally:
            _task_status['tr1'] = False
            _count_cache["time"] = 0
    threading.Thread(target=w, daemon=True).start()
    return {"status":"started"}

#20260801添加媒体提取摘要结束

def run_scan_import_async(directory, itype='all'):
    """异步扫描本地目录，导入所有支持的文件"""
    if _task_status.get('ir'): return {"status":"running"}
    _task_status['ir'] = True
    _task_status['ir_r'] = {"done":0,"total":0,"duplicates":0,"errors":0,"current":"","message":"扫描中..."}
    def w():
        try:
            BOOK_EXTS = {'.pdf','.epub','.mobi','.azw3','.azw','.txt','.md','.zip','.rar','.7z'}
            MEDIA_EXTS = {'.mp3','.mp4','.wav','.flac','.aac','.ogg','.wma','.avi','.mkv','.mov','.flv','.webm','.m4a','.m4v','.wmv','.ts'}
            # 收集所有文件
            files = []
            for root, dirs, fnames in os.walk(directory):
                for fn in fnames:
                    ext = os.path.splitext(fn)[1].lower()
                    if (itype in ('all','books') and ext in BOOK_EXTS) or (itype in ('all','media') and ext in MEDIA_EXTS):
                        files.append(os.path.join(root, fn))
            rv = {"done":0,"total":len(files),"duplicates":0,"errors":0,"current":"","message":f"找到 {len(files)} 个文件，开始导入..."}
            _task_status['ir_r'] = rv
            for fp in files:
                fn = os.path.basename(fp)
                ext = os.path.splitext(fn)[1].lower()
                rv["current"] = fn
                _task_status['ir_r'] = rv
                try:
                    # 计算文件 hash（流式读取，避免大文件内存溢出）
                    import hashlib
                    h = hashlib.sha256()
                    with open(fp, 'rb') as sf:
                        while True:
                            chunk = sf.read(8388608)  # 8MB chunks
                            if not chunk: break
                            h.update(chunk)
                    fh = h.hexdigest()
                    is_book = ext in BOOK_EXTS
                    if is_book:
                        if dbq("SELECT id FROM books WHERE file_hash=?", (fh,)):
                            rv["duplicates"] += 1; rv["done"] += 1; _task_status['ir_r'] = rv; continue
                        bid = str(uuid.uuid4()); dd = os.path.join("data","books",bid); os.makedirs(dd, exist_ok=True)
                        dest = os.path.join(dd, "original" + ext); fmt = ext.lstrip('.')
                        # 流式复制
                        import shutil
                        shutil.copy2(fp, dest)
                        fsize = os.path.getsize(dest)
                        dbe("INSERT INTO books(id,title,file_path,file_format,file_size,file_hash,status,created_at) VALUES(?,?,?,?,?,?,'active',datetime('now'))",
                            (bid, os.path.splitext(fn)[0], dest, fmt, fsize, fh))
                        extract_cover_for(bid, dest, fmt)
                        extract_text_for(bid, dest, fmt)
                    else:
                        if dbq("SELECT id FROM media WHERE file_hash=?", (fh,)):
                            rv["duplicates"] += 1; rv["done"] += 1; _task_status['ir_r'] = rv; continue
                        mid = str(uuid.uuid4()); dd = os.path.join("data","media",mid); os.makedirs(dd, exist_ok=True)
                        dest = os.path.join(dd, "original" + ext); fmt = ext.lstrip('.')
                        import shutil
                        shutil.copy2(fp, dest)
                        fsize = os.path.getsize(dest)
                        media_type = 'audio' if ext in {'.mp3','.wav','.flac','.aac','.ogg','.wma','.m4a'} else 'video'
                        duration = get_audio_duration(dest) if media_type == 'audio' else 0
                        dbe("INSERT INTO media(id,title,file_path,media_type,file_format,file_size,file_hash,duration,status,created_at) VALUES(?,?,?,?,?,?,?,?,'active',datetime('now'))",
                            (mid, os.path.splitext(fn)[0], dest, media_type, fmt, fsize, fh, duration))
                    rv["done"] += 1; _task_status['ir_r'] = rv
                except Exception as e:
                    rv["errors"] += 1; rv["done"] += 1; _task_status['ir_r'] = rv
                    print(f"[scan import error] {fn}: {e}", flush=True)
            rv["current"] = ""; rv["message"] = f"完成! 新增 {rv['done']-rv['duplicates']-rv['errors']} 个, 重复 {rv['duplicates']} 个" + (f", 失败 {rv['errors']} 个" if rv['errors'] else "")
            _task_status['ir_r'] = rv
            _count_cache["time"] = 0
        except Exception as e:
            _task_status['ir_r'] = {"done":0,"total":0,"duplicates":0,"errors":1,"current":"","message":f"扫描失败: {str(e)[:200]}"}
        finally:
            _task_status['ir'] = False
    threading.Thread(target=w, daemon=True).start()
    return {"status":"started"}

class H(http.server.SimpleHTTPRequestHandler):
    timeout = 600  # 防止请求体读取永久挂起
    def _rlog(self, msg):
        try:
            import datetime as _dtmod
            with open("_req_log.txt","a",encoding="utf-8") as _lf:
                _lf.write(f"[{_dtmod.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        except Exception: pass
    def do_POST(self):
        p = urllib.parse.urlparse(self.path); path = p.path
        ctype = self.headers.get('Content-Type','')
        length = int(self.headers.get('Content-Length',0))
        self._rlog(f"POST {path} clen={length}")
        body = self.rfile.read(length) if length > 0 else b''
        if length > 0: self._rlog(f"POST {path} body read: {len(body)}/{length} bytes")
        try:
            if 'multipart/form-data' in ctype: self._handle_upload(ctype,body); return
            data = json.loads(body) if body else {}
            if path == "/api/import-scan": self.json(run_scan_import_async(data.get('dir',''), data.get('import_type','all'))); return
            if path.startswith("/api/books/") and path.endswith("/edit"):
                bid=path.split("/")[3]; title=data.get('title','').strip()
                if title: dbe("UPDATE books SET title=? WHERE id=?",(title,bid)); self.json({"ok":True,"title":title})
                else: self.json({"error":"title empty"}); return
            if path == "/api/classify-batch": self.json(run_classify_async(data.get('count',10))); return
            if path == "/api/summarize-batch": self.json(run_summarize_async(data.get('count',3))); return
            if path == "/api/extract-batch": self.json(run_extract_async(data.get('count',10))); return
            # 媒体转录/摘要 20260801
            if path == "/api/media/transcribe": self.json(run_transcribe_async(data.get('count',10), data.get('media_type','all'))); return
            if path == "/api/media/summarize": self.json(run_media_summarize_async(data.get('count',10))); return
            if path == "/api/media/transcribe-one": self.json(run_transcribe_one_async(data.get('media_id',''))); return
            if path.startswith("/api/media/") and path.endswith("/edit"):
                mid=path.split("/")[3]; title=data.get('title','').strip()
                if title: dbe("UPDATE media SET title=?, updated_at=datetime('now') WHERE id=?",(title,mid)); self.json({"ok":True,"title":title})
                else: self.json({"error":"title empty"}); return
            # 删除书籍 20260816：DB记录+关联+封面；上传的书删源文件目录，扫描导入的原始文件保留
            if path.startswith("/api/books/") and path.endswith("/delete"):
                bid=path.split("/")[3]
                if not dbq("SELECT id FROM books WHERE id=?",(bid,)): self.json({"error":"book not found"}); return
                dbe("DELETE FROM book_authors WHERE book_id=?",(bid,))
                dbe("DELETE FROM book_tags WHERE book_id=?",(bid,))
                dbe("DELETE FROM book_categories WHERE book_id=?",(bid,))
                dbe("DELETE FROM reading_notes WHERE book_id=?",(bid,))
                dbe("DELETE FROM books WHERE id=?",(bid,))
                try: os.remove(os.path.join("data","covers",bid+".jpg"))
                except: pass
                shutil.rmtree(os.path.join("data","books",bid), ignore_errors=True)
                _count_cache["time"]=0
                self.json({"ok":True}); return
            # 删除媒体 20260816
            if path.startswith("/api/media/") and path.endswith("/delete"):
                mid=path.split("/")[3]
                if not dbq("SELECT id FROM media WHERE id=?",(mid,)): self.json({"error":"media not found"}); return
                dbe("DELETE FROM media_tags WHERE media_id=?",(mid,))
                dbe("DELETE FROM media_categories WHERE media_id=?",(mid,))
                dbe("DELETE FROM media_notes WHERE media_id=?",(mid,))
                dbe("DELETE FROM media WHERE id=?",(mid,))
                shutil.rmtree(os.path.join("data","media",mid), ignore_errors=True)
                _count_cache["time"]=0
                self.json({"ok":True}); return

            self.send_error(404)
        except Exception as e: self.send_error(500, str(e))
   
    def _handle_upload(self, ctype, body):
        fields = parse_multipart(ctype, body)
        if not fields or 'file' not in fields: self.json({"error":"parse failed"}); return
        f = fields['file']
        if not f['filename']: self.json({"error":"no filename"}); return
        data, fn = f['data'], f['filename']
        ext = os.path.splitext(fn)[1].lower()
        # 导入类型
        itype = 'all'
        if 'import_type' in fields:
            itype = fields['import_type'].get('data', b'all')
            if isinstance(itype, bytes): itype = itype.decode()
        
        BOOK_EXTS = {'.pdf','.epub','.mobi','.azw3','.azw','.txt','.md','.zip','.rar','.7z'}
        MEDIA_EXTS = {'.mp3','.mp4','.wav','.flac','.aac','.ogg','.wma','.avi','.mkv','.mov','.flv','.webm','.m4a','.m4v','.wmv','.ts'}
        
        is_book = ext in BOOK_EXTS
        is_media = ext in MEDIA_EXTS
        
        if itype == 'books' and not is_book: self.json({"error":"bad format: 请选择书籍文件"}); return
        if itype == 'media' and not is_media: self.json({"error":"bad format: 请选择音视频文件"}); return
        if not is_book and not is_media: self.json({"error":"bad format: 不支持的文件格式"}); return
        if len(data)==0: self.json({"error":"empty"}); return
        
        h = hashlib.sha256(); h.update(data); fh = h.hexdigest()
        
        if is_book:
            _rows = dbq("SELECT id,title,file_path FROM books WHERE file_hash=?",(fh,))
            if _rows:
                _row = _rows[0]
                try:
                    import datetime as _dt
                    with open("_dup_log.txt","a",encoding="utf-8") as _lf:
                        _lf.write(f"[{_dt.datetime.now()}] books hash={fh} -> id={_row['id']} title={_row['title']} path={_row['file_path']}\n")
                except Exception: pass
                self.json({"duplicate":True,"existing_id":_row['id'],"existing_title":_row['title']}); return
            bid=str(uuid.uuid4()); dd=os.path.join("data","books",bid); os.makedirs(dd,exist_ok=True)
            dest=os.path.join(dd,"original"+ext); fmt=ext.lstrip('.')
            with open(dest,'wb') as f: f.write(data)
            dbe("INSERT INTO books(id,title,file_path,file_format,file_size,file_hash,status,created_at) VALUES(?,?,?,?,?,?,'active',datetime('now'))",
                (bid,os.path.splitext(fn)[0],dest,fmt,len(data),fh))
            extract_cover_for(bid, dest, fmt)
            extract_text_for(bid, dest, fmt)
            _count_cache["time"] = 0
            self.json({"success":True,"id":bid,"title":fn,"type":"book"})
        else:
            _mrows = dbq("SELECT id,title FROM media WHERE file_hash=?",(fh,))
            if _mrows: self.json({"duplicate":True,"existing_id":_mrows[0]['id'],"existing_title":_mrows[0]['title']}); return
            mid=str(uuid.uuid4()); dd=os.path.join("data","media",mid); os.makedirs(dd,exist_ok=True)
            dest=os.path.join(dd,"original"+ext); fmt=ext.lstrip('.')
            media_type = 'audio' if ext in {'.mp3','.wav','.flac','.aac','.ogg','.wma','.m4a'} else 'video'
            with open(dest,'wb') as f: f.write(data)
            duration = get_audio_duration(dest) if media_type == 'audio' else 0
            dbe("INSERT INTO media(id,title,file_path,media_type,file_format,file_size,file_hash,duration,status,created_at) VALUES(?,?,?,?,?,?,?,?,'active',datetime('now'))",
                (mid,os.path.splitext(fn)[0],dest,media_type,fmt,len(data),fh,duration))
            _count_cache["time"] = 0
            self.json({"success":True,"id":mid,"title":fn,"type":"media"})


    def do_GET(self):
        p=urllib.parse.urlparse(self.path); path=p.path; qs=urllib.parse.parse_qs(p.query)
        try:
            if path=="/api/health": self.json({"status":"ok"})
            elif path=="/api/task-status": self.json({"classify":_task_status.get('cr_r',{}),"summarize":_task_status.get('sr_r',{}),"extract":_task_status.get('er_r',{}),"transcribe":_task_status.get('tr_r',{}),"media_summarize":_task_status.get('ms_r',{}),"scan_import":_task_status.get('ir_r',{})})

            elif path.startswith("/api/books/") and path.endswith("/read"):
                bid=path.split("/")[3]
                r=dbq("SELECT file_path,file_format,title FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp,fmt,title=_resolve_path(r[0]['file_path']),r[0]['file_format'],r[0]['title']
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
                elif fmt in ('rar','zip','7z'):
                    try:
                        files = list_archive_contents(fp)
                        h='<!DOCTYPE html><html><head><meta charset=utf-8><title>'+he(title)+'</title>'
                        h+='<style>body{max-width:900px;margin:0 auto;padding:20px;font-family:sans-serif;background:#fff;color:#333}'
                        h+='.fl{display:flex;align-items:center;padding:10px 16px;margin:4px 0;background:#f5f5f5;border-radius:8px;text-decoration:none;color:#333;transition:background .2s}'
                        h+='.fl:hover{background:#e3f2fd}'
                        h+='.fl .ic{font-size:24px;margin-right:12px}'
                        h+='.fl .nm{flex:1;font-size:15px}'
                        h+='.fl .sz{font-size:13px;color:#999}'
                        h+='.stats{padding:12px 16px;background:#e8f5e9;border-radius:8px;margin-bottom:16px;font-size:14px;color:#2e7d32}'
                        h+='</style></head><body><h1>📦 '+he(title)+'</h1>'
                        h+='<div class=stats>压缩包内共 '+str(len(files))+' 个文件</div>'
                        # 按文件名排序
                        files.sort(key=lambda x: x.get('path',''))
                        img_exts = {'.jpg','.jpeg','.png','.gif','.bmp','.webp'}
                        doc_exts = {'.pdf','.epub','.txt','.md'}
                        for f in files:
                            fn = f.get('path','')
                            sz = f.get('size',0)
                            ext = os.path.splitext(fn)[1].lower()
                            if ext in doc_exts: ic='📄'
                            elif ext in img_exts: ic='🖼️'
                            else: ic='📦'
                            sz_str = str(round(sz/1024/1024,1))+'MB' if sz>1048576 else str(round(sz/1024))+'KB'
                            url = '/api/books/'+bid+'/archive/'+urllib.parse.quote(fn)
                            h+='<a class=fl href="'+url+'" target=_blank><span class=ic>'+ic+'</span><span class=nm>'+he(fn)+'</span><span class=sz>'+sz_str+'</span></a>'
                        h+='</body></html>'
                        self._html(h)
                    except Exception as e:
                        print(f"[RAR reader error] {e}", flush=True)
                        self.send_error(500, str(e))
                else:
                    r2=dbq("SELECT text_content FROM books WHERE id=?",(bid,))
                    t=(r2[0]['text_content'] if r2 else '') or ''
                    t=t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                    h='<!DOCTYPE html><html><head><meta charset=utf-8><title>'+title+'</title><style>body{max-width:800px;margin:0 auto;padding:20px;font-family:serif;font-size:18px;line-height:2;white-space:pre-wrap}</style></head><body><h1>'+title+'</h1><div>'+t+'</div></body></html>'
                    self._html(h)
            elif path.startswith("/api/books/") and path.endswith("/open"):                     #260727  用sumatraPDF 打开epub
                bid=path.split("/")[3]
                r=dbq("SELECT file_path FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp=_resolve_path(r[0]['file_path'])
                if not os.path.exists(fp): self.send_error(404); return
                import subprocess
                sumatra = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SumatraPDF", "SumatraPDF.exe")
                if os.path.exists(sumatra):
                    subprocess.Popen([sumatra, fp], shell=True)
                else:
                    subprocess.Popen([fp], shell=True)
                
                self.json({"ok":True,"path":fp})                                                                           #260727  用sumatraPDF 打开epub 结束


            elif path.startswith("/api/books/") and path.endswith("/file"):
                bid=path.split("/")[3]
                r=dbq("SELECT file_path,file_format FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp,fmt=_resolve_path(r[0]['file_path']),r[0]['file_format']
                if os.path.exists(fp):
                    self.send_response(200)
                    self.send_header("Content-Type",{"pdf":"application/pdf"}.get(fmt,"application/octet-stream"))
                    self.send_header("Content-Disposition","inline"); self.end_headers()
                    with open(fp,'rb')as f: self.wfile.write(f.read())
                else: self.send_error(404)
            elif "/archive/" in path and path.startswith("/api/books/"):
                # 从压缩包中提取并服务单个文件: /api/books/<id>/archive/<filename>
                parts = path.split("/archive/", 1)
                bid = parts[0].split("/")[-1]
                inner_fn = urllib.parse.unquote(parts[1]) if len(parts) > 1 else ""
                r = dbq("SELECT file_path,file_format FROM books WHERE id=?", (bid,))
                if not r: self.send_error(404); return
                fp = _resolve_path(r[0]['file_path'])
                if not os.path.exists(fp): self.send_error(404); return
                # 提取到缓存目录
                cache_dir = os.path.join("data", "temp", "archives", bid)
                cached = os.path.join(cache_dir, os.path.basename(inner_fn))
                if not os.path.exists(cached):
                    extracted = extract_archive_file(fp, inner_fn, cache_dir)
                    if not extracted: self.send_error(500, "extraction failed"); return
                    cached = extracted
                if os.path.exists(cached):
                    ext = os.path.splitext(inner_fn)[1].lower()
                    raw_mode = qs.get('raw', [''])[0] == '1'
                    ctypes = {'.pdf':'application/pdf','.epub':'application/epub+zip','.txt':'text/plain','.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.gif':'image/gif','.webp':'image/webp'}
                    # PDF 用 PDF.js 渲染，绕过浏览器内置 PDF 阅读器的暗色反色
                    if ext == '.pdf' and not raw_mode:
                        raw_url = path + ('&raw=1' if p.query else '?raw=1')
                        viewer = '''<!DOCTYPE html><html><head><meta charset=utf-8>
<meta name="color-scheme" content="light only">
<title>''' + he(inner_fn) + '''</title>
<style>
:root{color-scheme:light only}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:#f0f0f0;overflow:hidden;font-family:sans-serif}
#toolbar{position:fixed;top:0;left:0;right:0;height:44px;background:#3b3b3b;display:flex;align-items:center;padding:0 12px;z-index:100;gap:8px}
#toolbar button{background:#555;color:#fff;border:none;border-radius:4px;padding:5px 12px;cursor:pointer;font-size:13px}
#toolbar button:hover{background:#777}
#toolbar span{color:#ccc;font-size:13px}
#pageNum{width:50px;text-align:center;background:#555;color:#fff;border:1px solid #777;border-radius:3px;padding:3px 6px;font-size:13px}
#canvasWrap{margin-top:44px;height:calc(100% - 44px);overflow:auto;display:flex;justify-content:center}
#pdfCanvas{background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.3)}
</style></head><body>
<div id="toolbar">
<button onclick="prevPage()">◀ 上一页</button>
<span>第 <input id="pageNum" value="1" onchange="goPage()"> / <span id="pageCount">-</span> 页</span>
<button onclick="nextPage()">下一页 ▶</button>
<span style="flex:1"></span>
<button onclick="zoomOut()">−</button>
<span id="zoomLabel">120%</span>
<button onclick="zoomIn()">+</button>
</div>
<div id="canvasWrap"><canvas id="pdfCanvas"></canvas></div>
<script src="/pdfjs/pdf.min.js"></script>
<script>
pdfjsLib.GlobalWorkerOptions.workerSrc='/pdfjs/pdf.worker.min.js';
var pdfDoc=null,pageNum=1,pageRendering=false,pendingPage=null,scale=1.2;
function renderPage(n){
  if(pageRendering){pendingPage=n;return;}
  pageRendering=true;
  pdfDoc.getPage(n).then(function(page){
    var viewport=page.getViewport({scale:scale});
    var canvas=document.getElementById('pdfCanvas');
    canvas.height=viewport.height;canvas.width=viewport.width;
    var ctx=canvas.getContext('2d');
    page.render({canvasContext:ctx,viewport:viewport}).promise.then(function(){
      pageRendering=false;
      if(pendingPage!==null){renderPage(pendingPage);pendingPage=null;}
    });
  });
  document.getElementById('pageNum').value=n;
}
function prevPage(){if(pageNum<=1)return;pageNum--;renderPage(pageNum);}
function nextPage(){if(pageNum>=pdfDoc.numPages)return;pageNum++;renderPage(pageNum);}
function goPage(){var n=parseInt(document.getElementById('pageNum').value);if(n>=1&&n<=pdfDoc.numPages){pageNum=n;renderPage(pageNum);}}
function zoomIn(){scale*=1.2;document.getElementById('zoomLabel').textContent=Math.round(scale*100)+'%';renderPage(pageNum);}
function zoomOut(){scale/=1.2;document.getElementById('zoomLabel').textContent=Math.round(scale*100)+'%';renderPage(pageNum);}
pdfjsLib.getDocument("''' + he(raw_url) + '''").promise.then(function(pdf){
  pdfDoc=pdf;
  document.getElementById('pageCount').textContent=pdf.numPages;
  renderPage(1);
});
</script>
</body></html>'''
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(viewer.encode('utf-8'))
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", ctypes.get(ext, "application/octet-stream"))
                    self.send_header("Content-Disposition", "inline")
                    self.end_headers()
                    with open(cached, 'rb') as f: self.wfile.write(f.read())
                else: self.send_error(404)
            elif path.startswith("/api/media/") and path.endswith("/file"):
                bid=path.split("/")[3]
                r=dbq("SELECT file_path,file_format FROM media WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp,fmt=_resolve_path(r[0]['file_path']),r[0]['file_format']
                if os.path.exists(fp):
                    self.send_response(200)
                    self.send_header("Content-Type",{"mp3":"audio/mpeg","mp4":"video/mp4"}.get(fmt,"application/octet-stream"))
                    self.end_headers()
                    with open(fp,'rb')as f: self.wfile.write(f.read())
                else: self.send_error(404)
            elif path.startswith("/pdfjs/"):
                # Serve PDF.js static files
                rel = path[7:]  # strip "/pdfjs/" (7 chars)
                base = os.path.dirname(os.path.abspath(__file__))
                fp = os.path.join(base, "pdfjs", rel)
                if os.path.exists(fp) and os.path.isfile(fp):
                    ext = os.path.splitext(fp)[1].lower()
                    ct = {'.js':'application/javascript','.css':'text/css','.html':'text/html','.json':'application/json'}.get(ext, 'application/octet-stream')
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    self.end_headers()
                    with open(fp, 'rb') as f: self.wfile.write(f.read())
                else:
                    self.send_error(404)
            elif path.startswith("/api/covers/"):
                cv = Path("data/covers")/path.split("/")[-1]
                if cv.exists():
                    self.send_response(200); self.send_header("Content-Type","image/jpeg"); self.end_headers()
                    with open(cv,'rb')as f: self.wfile.write(f.read())
                else: self.send_error(404)
            elif path.startswith("/api/books/"):
                bid=path.split("/")[3]
                r=dbq("SELECT id,title,subtitle,publisher,publish_date,isbn,language,description,cover_path,file_path,file_format,file_size,page_count,summary,summary_model,summary_updated,difficulty,status,created_at FROM books WHERE id=?",(bid,))
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
        ct=get_counts()  # 同步刷新统计，确保导入后首页立即显示正确数字
        tb=ct.get('tb',0); tm=ct.get('tm',0)
        pn=qs.get('p',['home'])[0]
        nv=NAV.replace('{B}',str(tb)).replace('{M}',str(tm))
        h='<!DOCTYPE html><html><head><meta charset=utf-8><title>我的图书馆</title><style>'+CSS+'</style></head><body>'+nv+'<main>'
        if pn=='books':
            q=qs.get('q',[''])[0];cat=qs.get('cat',[''])[0];fmt=qs.get('fmt',[''])[0];bp=int(qs.get('page',['1'])[0])
            s="SELECT id,title,file_format,file_size,cover_path FROM books WHERE status='active'";pa=[]
            if q:s+=" AND title LIKE ?";pa.append('%'+q+'%')
            if cat:s+=" AND id IN (SELECT book_id FROM book_categories WHERE category_id=?)";pa.append(cat)
            if fmt:s+=" AND file_format=?";pa.append(fmt)
            total=dbq("SELECT count(*)as c FROM books WHERE "+s.split("WHERE",1)[1],tuple(pa))[0]['c']
            s+=" ORDER BY created_at DESC, title ASC LIMIT 20 OFFSET "+str((bp-1)*20)
            rows=dbq(s,tuple(pa))
            h+='<h2>📖 书库'+(' - '+fmt.upper() if fmt else '')+' ('+str(len(rows))+'/'+str(total)+')</h2>'
            h+='<form class=sch method=get><input type=hidden name=p value=books><input type=hidden name=fmt value="'+he(fmt)+'"><input name=q placeholder=搜索书名 value="'+he(q)+'"><select name=cat><option value="">全部分类</option>'
            for r in dbq("SELECT id,name FROM categories ORDER BY name"):
                sel=' selected'if r['id']==cat else''
                h+='<option value="'+r['id']+'"'+sel+'>'+he(r['name'])+'</option>'
            h+='</select><button>搜索</button></form>'
            for r in rows:
                cv='<img src="/api/covers/'+r['id']+'.jpg">'if r['cover_path']else'<div class=cv>📚</div>'
                h+='<div class=bk onclick="location.href=\'/?p=detail&id='+r['id']+'\'"><a href="/?p=detail&id='+r['id']+'" onclick="event.stopPropagation()">'+cv+'</a><div class=info><div class=t>'+he(r['title'])[:60]+'</div><div class=m>'+r['file_format'].upper()+' '+str(round(r['file_size']/1024/1024,1))+'MB</div></div></div>'
            if total>20:
                tp=(total+19)//20;qs_str=""
                if q or cat or fmt:qs_str="&q="+he(q)+"&cat="+(cat or"")+"&fmt="+(fmt or"")
                h+='<div style=text-align:center;margin-top:12px;font-size:14px>共 '+str(total)+' 本 页 '+str(bp)+'/'+str(tp)+' '
                if bp>1:h+='<a href="?p=books&page='+str(bp-1)+qs_str+'">上一页</a> '
                if bp<tp:h+='<a href="?p=books&page='+str(bp+1)+qs_str+'">下一页</a> '
                h+='</div>'
        elif pn=='detail':
            bid=qs.get('id',[None])[0];is_media=qs.get('type',[''])[0]=='media'
            if bid and not is_media:
                r=dbq("SELECT id,title,subtitle,publisher,publish_date,isbn,language,description,cover_path,file_path,file_format,file_size,page_count,summary,summary_model,summary_updated,difficulty,status,created_at FROM books WHERE id=?",(bid,))
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
                    h+='<div class=sec><a href="'+read_url+'" class=btn target=_blank>📖 阅读</a>'                                                                       #260727 修改 调用SumatraPDF
                    h+=' <a href="#" class=btn onclick="event.preventDefault();fetch(\'/api/books/'+bid+'/open\')">📖 外部阅读</a>'
                    _jt=str(b['title']).replace('\\','\\\\').replace("'","\\'").replace('\n',' ')   #260816 删除按钮（标题做JS转义）
                    h+=' <a href="#" class=btn style="background:#ff4d4f;color:#fff" onclick="event.preventDefault();DELB(\''+bid+'\',\''+_jt+'\')">🗑️ 删除</a>'
                    h+=' <a href="javascript:history.back()" class="btn bb2">返回</a></div></div>'
        elif pn=='media_detail':
            mid=qs.get('id',[''])[0]
            m=dbq("SELECT * FROM media WHERE id=?",(mid,))
            if m:
                m=m[0]; ic='🎵'if m['media_type']=='audio'else'🎬'
                d=m['duration']or 0; dur=str(int(d//60))+':'+str(int(d%60)).zfill(2)
                
                h+='<h2>'+ic+' '+he(str(m['title']))[:60]+' <button class="btn btn-sm" onclick="event.stopPropagation();EDTM(\''+mid+'\')" style=margin-left:8px>✏️ 编辑</button></h2>'

                h+='<p class=co><a href="javascript:history.back()">← 返回</a></p>'
                h+='<div class=panel><h3>📋 基本信息</h3>'
                h+='<p><b>格式:</b> '+m['file_format'].upper()+' | <b>时长:</b> '+dur+' | <b>大小:</b> '+str(round(m['file_size']/1024/1024,1))+'MB</p>'
                if m['artist']:h+='<p><b>艺术家:</b> '+he(str(m['artist']))+'</p>'
                if m['album']:h+='<p><b>专辑:</b> '+he(str(m['album']))+'</p>'
                h+='<p><a href="/api/media/'+mid+'/file" class=btn target=_blank>▶️ 播放</a>'
                _mt=str(m['title']).replace('\\','\\\\').replace("'","\\'").replace('\n',' ')   #260816 删除按钮
                h+=' <a href="#" class=btn style="background:#ff4d4f;color:#fff" onclick="event.preventDefault();DELM(\''+mid+'\',\''+_mt+'\')">🗑️ 删除</a></p></div>'
                h+='<div class=panel><h3>🎙️ 转录文字</h3>'
                if m['transcript']:
                    full_len=len(m['transcript'])
                    if full_len>3000:
                        txt=m['transcript'][:3000]
                        h+='<div id=transcript-partial style=white-space:pre-wrap;line-height:1.8;max-height:400px;overflow-y:auto>'+he(txt)+'</div>'
                        h+='<div id=transcript-full style=display:none;white-space:pre-wrap;line-height:1.8;max-height:600px;overflow-y:auto>'+he(m['transcript'])+'</div>'
                        h+='<p class=co>... (共 '+str(full_len)+' 字) <button class="btn btn-sm" onclick="var p=document.getElementById(\'transcript-partial\');var f=document.getElementById(\'transcript-full\');var b=this;if(f.style.display==\'none\'){p.style.display=\'none\';f.style.display=\'block\';b.textContent=\'收起\'}else{p.style.display=\'block\';f.style.display=\'none\';b.textContent=\'展开全部\'}">展开全部</button></p>'
                    else:
                        h+='<div style=white-space:pre-wrap;line-height:1.8;max-height:400px;overflow-y:auto>'+he(m['transcript'])+'</div>'

                    if len(m['transcript'])>3000:h+='<p class=co>... (共 '+str(len(m['transcript']))+' 字)</p>'
                else:h+='<p class=co>尚未转录</p>'
                h+='</div>'
                h+='<div class=panel><h3>📝 AI 摘要</h3>'
                if m['summary']:h+='<div style=white-space:pre-wrap;line-height:1.8;background:#fffbe6;padding:16px;border-radius:8px>'+he(str(m['summary'])).replace('\n','<br>')+'</div>'
                else:h+='<p class=co>尚未摘要</p>'
                h+='</div>'
        elif pn=='media_transcribed':
            mp=int(qs.get('page',['1'])[0])
            rows=dbq("SELECT id,title,media_type,file_format,duration,file_size,transcript,summary FROM media WHERE status='active' AND transcript IS NOT NULL AND transcript NOT LIKE '[转录失败%' AND transcript NOT LIKE '[转录超时%' AND transcript!='[文件不存在]' ORDER BY updated_at DESC LIMIT 30 OFFSET ?",((mp-1)*30,))
            total=dbq("SELECT count(*)as c FROM media WHERE status='active' AND transcript IS NOT NULL AND transcript NOT LIKE '[转录失败%' AND transcript NOT LIKE '[转录超时%' AND transcript!='[文件不存在]'")[0]['c']
            h+='<h2>🎙️ 已转录媒体 ('+str(len(rows))+'/'+str(total)+')</h2>'
            h+='<p class=co><a href="javascript:history.back()">← 返回媒体库</a></p>'
            for r in rows:
                ic='🎵'if r['media_type']=='audio'else'🎬';d=r['duration']or 0;dur=str(int(d//60))+':'+str(int(d%60)).zfill(2)
                badges=''
                if r['transcript']:badges+='<span class="badge badge-ok">已转录</span> '
                if r['summary']:badges+='<span class="badge badge-ok">已摘要</span> '
                h+='<div class=bk><div style="width:60px;height:60px;border-radius:8px;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;font-size:28px;color:#fff;flex-shrink:0">'+ic+'</div><div class=info><div class=t><a href="/?p=media_detail&id='+r['id']+'">'+he(r['title'])[:60]+'</a></div><div class=m>'+r['file_format'].upper()+' · '+dur+' · '+str(round(r['file_size']/1024/1024,1))+'MB '+badges+'</div></div></div>'
            if total>30:
                tp=(total+29)//30
                h+='<div style=text-align:center;margin-top:12px>'
                if mp>1:h+='<a href="?p=media_transcribed&page='+str(mp-1)+'">上一页</a> '
                h+='页 '+str(mp)+'/'+str(tp)
                if mp<tp:h+=' <a href="?p=media_transcribed&page='+str(mp+1)+'">下一页</a>'
                h+='</div>'

        elif pn=='media_summarized':
            mp=int(qs.get('page',['1'])[0])
            rows=dbq("SELECT id,title,media_type,file_format,duration,file_size,transcript,summary FROM media WHERE status='active' AND summary IS NOT NULL AND summary NOT LIKE '[摘要%' AND summary NOT LIKE '[无可转录%' AND summary!='[摘要结果为空]' ORDER BY summary_updated DESC LIMIT 30 OFFSET ?",((mp-1)*30,))
            total=dbq("SELECT count(*)as c FROM media WHERE status='active' AND summary IS NOT NULL AND summary NOT LIKE '[摘要%' AND summary NOT LIKE '[无可转录%' AND summary!='[摘要结果为空]'")[0]['c']
            h+='<h2>📝 已摘要媒体 ('+str(len(rows))+'/'+str(total)+')</h2>'
            h+='<p class=co><a href="javascript:history.back()">← 返回媒体库</a></p>'
            for r in rows:
                ic='🎵'if r['media_type']=='audio'else'🎬';d=r['duration']or 0;dur=str(int(d//60))+':'+str(int(d%60)).zfill(2)
                h+='<div class=bk><div style="width:60px;height:60px;border-radius:8px;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;font-size:28px;color:#fff;flex-shrink:0">'+ic+'</div><div class=info><div class=t><a href="/?p=media_detail&id='+r['id']+'">'+he(r['title'])[:60]+'</a></div><div class=m>'+r['file_format'].upper()+' · '+dur+' · '+str(round(r['file_size']/1024/1024,1))+'MB <span class="badge badge-ok">已摘要</span> '
                if r['summary']:h+=he(str(r['summary']))[:80]+'...</div>'
                h+='</div></div></div>'
            if total>30:
                tp=(total+29)//30
                h+='<div style=text-align:center;margin-top:12px>'
                if mp>1:h+='<a href="?p=media_summarized&page='+str(mp-1)+'">上一页</a> '
                h+='页 '+str(mp)+'/'+str(tp)
                if mp<tp:h+=' <a href="?p=media_summarized&page='+str(mp+1)+'">下一页</a>'
                h+='</div>'

        elif pn=='media':
            mp=int(qs.get('page',['1'])[0])
            q=qs.get('q',[''])[0]
            wh="status='active'"
            params=[]
            if q: wh+=" AND title LIKE ?"; params.append('%'+q+'%')
            total=dbq(f"SELECT count(*)as c FROM media WHERE {wh}",tuple(params))[0]['c']
            rows=dbq(f"SELECT id,title,media_type,file_format,duration,file_size FROM media WHERE {wh} ORDER BY created_at DESC LIMIT 20 OFFSET ?",tuple(list(params)+[(mp-1)*20]))
            h+='<h2>🎧 媒体库 ('+str(len(rows))+'/'+str(total)+')</h2>'
            h+='<form class=search method=get><input type=hidden name=p value=media><input name=q placeholder="搜索音视频名称..." value="'+he(q)+'"><button>🔍 搜索</button></form>'
            for r in rows:
                ic='🎵'if r['media_type']=='audio'else'🎬';d=r['duration']or 0;dur=str(int(d/60))+':'+str(int(d%60)).zfill(2)
                
                h+='<div class=bk><div style="width:60px;height:60px;border-radius:8px;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;font-size:28px;color:#fff;flex-shrink:0">'+ic+'</div><div class=info><div class=t>'+he(r['title'])[:60]+'</div><div class=m>'+r['file_format'].upper()+' · '+dur+' <a href="/api/media/'+r['id']+'/file" target=_blank style="font-size:12px">▶播放</a> <a href="/?p=media_detail&id='+r['id']+'" style="font-size:12px">📋详情</a></div></div></div>'

               
            if total>20:
                tp=(total+19)//20;qe=urllib.parse.quote(q)
                h+='<div style=text-align:center;margin-top:12px;font-size:14px>共 '+str(total)+' 个 页 '+str(mp)+'/'+str(tp)+' '
                if mp>1:h+='<a href="?p=media&q='+qe+'&page='+str(mp-1)+'">上一页</a> '
                if mp<tp:h+='<a href="?p=media&q='+qe+'&page='+str(mp+1)+'">下一页</a> '
                h+='</div>'

        elif pn=='import':
            h+='<h2>📥 导入资料</h2>'
            h+='<div class=panel><h3>选择导入类型</h3>'
            h+='<select id=importType style="padding:8px 12px;border:1px solid #ddd;border-radius:4px;font-size:14px;margin-bottom:12px">'
            h+='<option value=books>📚 仅书籍</option>'
            h+='<option value=media>🎧 仅音视频</option>'
            h+='<option value=all selected>📦 全部（书籍+音视频）</option>'
            h+='</select></div>'
            h+='<div class=panel><h3>选择文件</h3>'
            h+='<input type=file id=f1 multiple style=display:none onchange="UF(this.files)">'
            h+='<input type=file id=f2 webkitdirectory style=display:none onchange="UF(this.files)">'
            h+='<button class=btn onclick="document.getElementById(\'f1\').click()">📁 选择文件</button> '
            h+='<button class=btn onclick="document.getElementById(\'f2\').click()">📂 选择文件夹</button>'
            h+='<div id=up style=margin-top:8px;font-size:13px;color:#999></div></div>'
            h+='<div class=panel><h3>扫描本地目录导入</h3>'
            h+='<p class=co style="margin-bottom:8px;font-size:13px">直接扫描服务器本机目录，无需浏览器上传。支持 PDF/EPUB/MOBI/RAR/ZIP 等格式。</p>'
            h+='<input type=text id=scanDir placeholder="例如: G:\\书籍\\待分类2" style="width:70%;padding:8px 12px;border:1px solid #ddd;border-radius:4px;font-size:14px"> '
            h+='<button class=btn onclick="SCAN()" style="background:#722ed1">🔍 开始扫描导入</button>'
            h+='<div id=scanRes style=margin-top:8px;font-size:13px></div></div>'
        else:
            ts=ct.get('ts',0); import_rem=ct.get('import_rem',0); sum_rem=ct.get('sum_rem',0); no_text=ct.get('no_text',0)
            _ld=""
            h+='<h2>🏠 首页</h2>'
            h+='<div class=row><a href="/?p=books" class=sb><div class=n style=color:#1677ff>'+str(tb)+'</div><div class=l>📚 书籍</div></a><a href="/?p=detail&list=1" class=sb><div class=n style=color:#52c41a>'+str(ts)+'</div><div class=l>🤖 已摘要</div></a><a href="/?p=media" class=sb><div class=n style=color:#fa8c16>'+str(tm)+'</div><div class=l>🎧 媒体</div></a><a href="/?p=media_transcribed" class=sb><div class=n style=color:#13c2c2>'+str(ct.get("mtr",0))+'</div><div class=l>🎙️ 已转录</div></a><a href="/?p=media_summarized" class=sb><div class=n style=color:#eb2f96>'+str(ct.get("msu",0))+'</div><div class=l>📝 媒体摘要</div></a></div>'
            h+='<div class=panel><h3>🤖 AI 处理</h3><p class=co style=margin-bottom:8px>未分类: '+str(import_rem)+' 本 | 未摘要: '+str(sum_rem)+' 本 | 无文本: '+str(no_text)+' 本'+_ld+'</p>'
            h+='<div style="margin-bottom:8px"><label style=font-size:13px>分类数量 </label><select id=clsCnt style="padding:4px 8px;border:1px solid #ddd;border-radius:4px"><option value=5>5 本</option><option value=10 selected>10 本</option><option value=20>20 本</option><option value=50>50 本</option><option value=100>100 本</option><option value=500>500 本</option><option value=1000>1000 本</option></select> <button class=btn id=clsBtn onclick="CLS()" style=margin-right:8px>🤖 AI 分类</button></div>'
            h+='<div style="margin-bottom:8px"><label style=font-size:13px>摘要数量 </label><select id=sumCnt style="padding:4px 8px;border:1px solid #ddd;border-radius:4px"><option value=1>1 本</option><option value=3 selected>3 本</option><option value=5>5 本</option><option value=10>10 本</option><option value=20>20 本</option><option value=100>100 本</option><option value=500>500 本</option><option value=1000>1000 本</option></select> <button class=btn id=sumBtn onclick="SUM()">🤖 AI 摘要</button></div>'
            h+='<div><label style=font-size:13px>提取数量 </label><select id=extCnt style="padding:4px 8px;border:1px solid #ddd;border-radius:4px"><option value=5>5 本</option><option value=10 selected>10 本</option><option value=20>20 本</option><option value=50>50 本</option><option value=100>100 本</option><option value=500>500 本</option><option value=1000>1000 本</option></select> <button class=btn id=extBtn onclick="EXT()">📄 提取文本</button></div>'
            h+='<div id=clsRes style=margin-top:4px;font-size:13px></div><div id=sumRes style=margin-top:4px;font-size:13px></div><div id=extRes style=margin-top:4px;font-size:13px></div></div>'
            #媒体库转录、摘要面板20260801
            h+='<div class=panel><h3>🎙️ 媒体转录与摘要</h3><p class=co style=margin-bottom:8px>待转录: '+str(tm - ct.get("mtr",0))+' 个 | 已转录待摘要: '+str(ct.get("mtr",0) - ct.get("msu",0))+' 个</p>'
            h+='<div style="margin-bottom:8px"><label style=font-size:13px>转录数量 </label><select id=trsCnt style="padding:4px 8px;border:1px solid #ddd;border-radius:4px"><option value=5>5 个</option><option value=10 selected>10 个</option><option value=50>50 个</option><option value=100>100 个</option><option value=500>500 个</option></select> <select id=trsType style="padding:4px 8px;border:1px solid #ddd;border-radius:4px"><option value=all>全部媒体</option><option value=audio>仅音频</option><option value=video>仅视频</option></select> <button class=btn id=trsBtn onclick="TRS()">🎙️ 媒体转录</button></div>'
            h+='<div><label style=font-size:13px>摘要数量 </label><select id=msuCnt style="padding:4px 8px;border:1px solid #ddd;border-radius:4px"><option value=50>50 个</option><option value=100 selected>100 个</option><option value=500>500 个</option><option value=1000>1000 个</option></select> <button class=btn id=msuBtn onclick="MSU()" style=background:#eb2f96>📝 转录→摘要</button></div>'
            h+='<div id=trsRes style=margin-top:4px;font-size:13px></div><div id=msuRes style=margin-top:4px;font-size:13px></div></div>'
    
            #媒体库转录、摘要面板20260801结束
            h+='<div class=panel><h3>📊 格式分布</h3>'
            fmt_dist = ct.get("fmt_dist", [])
            if not fmt_dist:
                fmt_dist = dbq("SELECT file_format as k,count(*)as c FROM books WHERE status='active' GROUP BY file_format ORDER BY c DESC")
            for r in fmt_dist:
                h+='<a class=tag style=background:'+fc(r['k'])+';text-decoration:none;cursor:pointer href="/?p=books&fmt='+r['k']+'">'+r['k'].upper()+' '+str(r['c'])+'</a> '
            h+='</div><div class=panel><h3>🏷️ 分类分布</h3>'
            cat_dist = ct.get("cat_dist", [])
            if not cat_dist:
                cat_dist = dbq("SELECT cat.id as cid,cat.name as k,count(*)as c FROM categories cat JOIN book_categories bc ON cat.id=bc.category_id JOIN books b ON b.id=bc.book_id WHERE b.status='active' GROUP BY cat.id,cat.name ORDER BY c DESC LIMIT 20")
            for r in cat_dist:
                h+='<a class=tag style=background:'+cc(r['k'])+';text-decoration:none;cursor:pointer href="/?p=books&cat='+r['cid']+'">'+he(r['k'])+' '+str(r['c'])+'</a> '
            h+='</div>'
        h+=COMMON_JS
      
        if pn=='import':
            h+='<script>var _f=[],_i=0,_ok=0,_d=0,_e=0;function UF(fs){_f=Array.from(fs);_i=0;_ok=0;_d=0;_e=0;_dt=[];NX()}function NX(){if(_i>=_f.length){document.getElementById("up").innerHTML="完成! 新增 "+_ok+" 个, 重复 "+_d+" 个"+(_e>0?", 失败 "+_e+" 个":"")+( (_dt&&_dt.length)?"<br>重复文件对应: "+_dt.map(function(t){return "《"+t+"》"}).join("、") :"")+" <a href=/ onclick=location.reload()>刷新</a>";return}var fd=new FormData();fd.append("file",_f[_i]);fd.append("import_type",document.getElementById("importType").value);_i++;var x=new XMLHttpRequest();x.open("POST","/api/import-upload");x.onload=function(){try{var r=JSON.parse(x.responseText);if(r.success)_ok++;else if(r.duplicate){_d++;_dt=(_dt||[]);_dt.push(r.existing_title||"未知")}else _e++;if(r.error)alert("错误: "+r.error)}catch(e){_e++}document.getElementById("up").innerHTML="上传中... "+_i+"/"+_f.length;NX()};x.onerror=function(){_e++;NX()};x.send(fd)};function SCAN(){var d=document.getElementById("scanDir").value;if(!d){alert("请输入目录路径");return}var t=document.getElementById("importType").value;document.getElementById("scanRes").innerHTML="正在启动扫描...";fetch("/api/import-scan",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({dir:d,import_type:t})}).then(r=>r.json()).then(r=>{if(r.status==="running"){alert("已有扫描任务在运行");SCNP()}else if(r.status==="started"){SCNP()}}).catch(e=>{document.getElementById("scanRes").innerHTML="启动失败: "+e})}function SCNP(){var x=new XMLHttpRequest();x.open("GET","/api/task-status");x.onload=function(){try{var r=JSON.parse(x.responseText);var s=r.scan_import||{};if(s.total>0){var pct=Math.round(s.done/s.total*100);document.getElementById("scanRes").innerHTML="导入中... "+s.done+"/"+s.total+" ("+pct+"%)"+(s.current?"<br>当前: "+s.current:"")+(s.duplicates?" 重复:"+s.duplicates:"")+(s.errors?" 失败:"+s.errors:"");if(s.done<s.total){setTimeout(SCNP,2000)}else{document.getElementById("scanRes").innerHTML+="<br><b>"+(s.message||"完成")+"</b> <a href=/ onclick=location.reload()>刷新</a>"}}else if(s.message){document.getElementById("scanRes").innerHTML=s.message;if(s.done<s.total||s.total===0){setTimeout(SCNP,2000)}}}catch(e){}};x.send()}</script>'
        h+='</main></body></html>'
        self._html(h)


    def _html(self,h):
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(h.encode('utf-8'))

    def json(self,d):
        self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
        self.wfile.write(json.dumps(d,ensure_ascii=False).encode('utf-8'))

def fix_drive_paths():
    """启动时检测盘符变化，自动修正数据库中的绝对路径。
    移动硬盘换电脑后盘符可能从 G: 变成 H: 等，此函数一次性修正所有路径。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cur_drive = script_dir[:2]  # e.g. "G:"
    try:
        c = sqlite3.connect(DB, timeout=120)
        c.row_factory = sqlite3.Row
        # 取一条样本路径看盘符
        row = c.execute("SELECT file_path FROM books WHERE file_path LIKE '_:%' LIMIT 1").fetchone()
        if not row:
            c.close(); return
        old_drive = row['file_path'][:2]  # e.g. "F:"
        if old_drive.upper() == cur_drive.upper():
            c.close(); return
        print(f"🔄 检测到盘符变化: {old_drive} → {cur_drive}，正在修正路径...", flush=True)
        # 批量替换 books.file_path
        n1 = c.execute("UPDATE books SET file_path = ? || substr(file_path, 3) WHERE file_path LIKE ? || '%'", (cur_drive, old_drive)).rowcount
        # 批量替换 books.cover_path
        n2 = c.execute("UPDATE books SET cover_path = ? || substr(cover_path, 3) WHERE cover_path LIKE ? || '%'", (cur_drive, old_drive)).rowcount
        # 批量替换 media.file_path
        n3 = c.execute("UPDATE media SET file_path = ? || substr(file_path, 3) WHERE file_path LIKE ? || '%'", (cur_drive, old_drive)).rowcount
        c.commit()
        c.close()
        print(f"✅ 路径修正完成: books.file_path {n1} 条, books.cover_path {n2} 条, media.file_path {n3} 条", flush=True)
    except Exception as e:
        print(f"⚠️ 盘符修正出错: {e}", flush=True)

if __name__ == "__main__":
    fix_drive_paths()
    HOST = os.environ.get("LIB_HOST", "127.0.0.1")
    PORT = int(os.environ.get("LIB_PORT", "8000"))
    print(f"🚀 http://localhost:{PORT}")
    print(f"📚 Private Lib | listening on {HOST}:{PORT}")
    if HOST == "0.0.0.0":
        print("⚠️  监听所有网卡（局域网可访问）。仅限 127.0.0.1 请设 LIB_HOST=127.0.0.1")
    http.server.ThreadingHTTPServer((HOST, PORT), H).serve_forever()
