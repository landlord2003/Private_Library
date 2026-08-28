"""My Library Server"""
import http.server, json, sqlite3, os, sys, io, urllib.parse, urllib.request, urllib.error, uuid, hashlib, shutil, threading, time, subprocess, tempfile, concurrent.futures

from pathlib import Path

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# 在线元数据补全开关：默认关（离线优先、零依赖）。启用需设环境变量 LIB_METADATA_ONLINE=1 后重启。
ENABLE_ONLINE_METADATA = os.environ.get("LIB_METADATA_ONLINE", "1") == "1"

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
            "sum_rem": "SELECT count(*)as c FROM books WHERE status='active' AND summary IS NULL AND id IN (SELECT id FROM book_text WHERE text_content IS NOT NULL)",
            "no_text": "SELECT count(*)as c FROM books WHERE status='active' AND id NOT IN (SELECT id FROM book_text WHERE text_content IS NOT NULL)",
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

def get_text(book_id):
    """从副表 book_text 读取提取正文（保持 books 表窄行，使路径修正等 UPDATE 秒级完成）。"""
    r = dbq("SELECT text_content FROM book_text WHERE id=?", (book_id,))
    return (r[0]['text_content'] if r else '') or ''

def set_text(book_id, text):
    """写入/更新副表 book_text（UPSERT）。"""
    dbe("INSERT INTO book_text(id, text_content) VALUES(?, ?) "
        "ON CONFLICT(id) DO UPDATE SET text_content=excluded.text_content",
        (book_id, text))

def _pg():
    """续跑进度引擎：复用 tools/libtools_common 的 progress.db。不可用时优雅降级(返回None)。"""
    try:
        _td = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
        if _td not in sys.path: sys.path.insert(0, _td)
        import libtools_common as L
        pc = L.get_progress_conn(); L.ensure_progress(pc)
        return pc, L
    except Exception as e:
        print(f"[progress引擎不可用] {e}", flush=True)
        return None, None

def _mark(tool, bid, status):
    """标记某书/媒体在某工具下的续跑进度(done/skip/partial)。引擎缺失则静默跳过。"""
    pc, L = _pg()
    if pc:
        try: L.mark_progress(pc, bid, tool, status)
        except Exception: pass

_tool_procs = {}

def _tool_run(data):
    """启动离线工具（tools/ 脚本）为独立后台进程。进度写 progress.db，主服务重启不影响续跑。"""
    import subprocess as _sp
    d = data or {}
    tool = d.get('tool')
    if not tool:
        return {"ok": False, "msg": "缺少 tool 参数"}
    base = os.path.dirname(os.path.abspath(__file__))
    td = os.path.join(base, "tools")
    lim = int(d.get('limit') or 0) or 200
    regen = bool(d.get('regen'))
    py = sys.executable
    if tool == 'kg':
        cmd = [py, os.path.join(td, "kg_build.py"), "--mode", "l1", "--limit", str(lim)] + (["--regen"] if regen else [])
    elif tool == 'meta':
        if regen:
            cmd = [py, os.path.join(td, "meta_complete.py"), "--retry-skips", "--limit", str(lim)]
        else:
            cmd = [py, os.path.join(td, "meta_complete.py"), "--mode", (d.get('mode') or 'fast'), "--limit", str(lim)]
    elif tool == 'summary':
        cmd = [py, os.path.join(td, "summary_fix.py"), "--mode", "all", "--limit", str(lim)]
    else:
        return {"ok": False, "msg": "未知工具: " + str(tool)}
    if _tool_procs.get(tool) and _tool_procs[tool].poll() is None:
        return {"ok": False, "msg": f"{tool} 已在运行 (PID {_tool_procs[tool].pid})"}
    logp = os.path.join(td, tool + ".log")
    try:
        f = open(logp, "a", encoding="utf-8")
        cf = 0x08000000 if os.name == 'nt' else 0
        p = _sp.Popen(cmd, stdout=f, stderr=_sp.STDOUT, creationflags=cf)
        _tool_procs[tool] = p
        return {"ok": True, "msg": f"{tool} 已启动 PID {p.pid}，日志 {logp}"}
    except Exception as e:
        return {"ok": False, "msg": f"启动失败: {e}"}

def _tool_status():
    """读取 progress.db 中各离线工具续跑进度 + 运行态。"""
    pc, L = _pg()
    out = {}
    tools = ['kg','meta','summary','extract','classify','summarize','transcribe','media_summarize','metadata']
    for t in tools:
        done = skip = 0
        if pc:
            try:
                done = pc.execute("SELECT COUNT(*) FROM tool_progress WHERE tool=? AND status='done'", (t,)).fetchone()[0]
                skip = pc.execute("SELECT COUNT(*) FROM tool_progress WHERE tool=? AND status='skip'", (t,)).fetchone()[0]
            except Exception: pass
        running = bool(_tool_procs.get(t) and _tool_procs[t].poll() is None)
        out[t] = {"done": done, "skip": skip, "running": running}
    return out


def _lib_stats():
    """图书馆规模 + 数据覆盖率 + 各工具续跑进度，供统计页/接口展示。"""
    def _c(sql):
        return dbq(sql)[0]['c']
    total = _c("SELECT COUNT(*) c FROM books WHERE status='active'")
    total_media = _c("SELECT COUNT(*) c FROM media WHERE status='active'")
    cov = {
        "cover": _c("SELECT COUNT(*) c FROM books WHERE status='active' AND cover_path IS NOT NULL AND cover_path<>''"),
        "summary": _c("SELECT COUNT(*) c FROM books WHERE status='active' AND summary IS NOT NULL AND summary<>''"),
        "publisher": _c("SELECT COUNT(*) c FROM books WHERE status='active' AND publisher IS NOT NULL AND publisher<>''"),
        "isbn": _c("SELECT COUNT(*) c FROM books WHERE status='active' AND isbn IS NOT NULL AND isbn<>''"),
        "language": _c("SELECT COUNT(*) c FROM books WHERE status='active' AND language IS NOT NULL AND language<>''"),
        "text_extracted": _c("SELECT COUNT(*) c FROM books WHERE status='active' AND text_extracted=1"),
        "ocr_pending": _c("SELECT COUNT(*) c FROM books b JOIN book_text bt ON bt.id=b.id WHERE b.file_format='pdf' AND b.text_extracted=1 AND length(bt.text_content)<=200"),
        "named": _c("SELECT COUNT(*) c FROM books WHERE status='active' AND normalized_title IS NOT NULL AND normalized_title<>'' AND normalized_title NOT LIKE 'upload_%'"),
    }
    fake = 0
    for r in dbq("SELECT summary FROM books WHERE status='active' AND summary IS NOT NULL AND summary<>''"):
        if _is_fake_summary(r['summary']):
            fake += 1
    return {"total_books": total, "total_media": total_media, "coverage": cov, "fake_summary": fake, "tools": _tool_status()}

def _tool_center_html():
    """工具中心(卡片式)：标注每工具 作用 / 已完成工作量 / 成果入口 / 运行控制。"""
    st = _lib_stats()
    total = st['total_books'] or 1
    cov = st['coverage']; tools = st['tools']; fake = st.get('fake_summary', 0)
    def pct(n): return min(100, round((n or 0)*100.0/total, 1))
    def bar(n, color):
        return ('<div style="background:#eee;height:8px;border-radius:4px;width:100%%;margin-top:4px">'
                '<div style="background:%s;height:8px;border-radius:4px;width:%s%%"></div></div>') % (color, pct(n))
    def card(icon, name, purpose, wl_text, wl_n, color, rlink, rlabel, controls=''):
        c = '<div style="flex:1 1 340px;min-width:300px;border:1px solid #e3e3e3;border-radius:10px;padding:14px;margin:6px;background:#fff">'
        c += '<div style="font-size:15px;font-weight:700;margin-bottom:6px">%s %s</div>' % (icon, name)
        c += '<div style="font-size:13px;color:#555;line-height:1.6;margin-bottom:8px">%s</div>' % purpose
        c += '<div style="font-size:12px;color:#333;margin:6px 0 2px">📊 已完成工作量：<b>%s</b></div>' % wl_text
        c += bar(wl_n, color)
        if rlink:
            c += '<div style="margin:8px 0"><a class=btn href="%s">🔗 %s</a></div>' % (rlink, rlabel)
        if controls:
            c += '<div style="margin-top:8px">%s</div>' % controls
        c += '</div>'
        return c
    h = '<h2>🛠️ 工具中心</h2>'
    h += '<p class=co>每个工具标注「作用 · 已完成工作量 · 成果入口」。进度来自 progress.db 与实时统计，停了不白跑；进程崩溃可续跑。</p>'
    # 成果总览
    h += '<div class=panel><h3>🏆 已落地成果总览</h3><div class=row>'
    h += '<a class=sb href="/?p=title-norm"><div class=n style="color:#1677ff">%d</div><div class=l>📐 书名已规则化</div></a>' % cov.get('named',0)
    h += '<a class=sb href="/?p=stats"><div class=n style="color:#52c41a">%d</div><div class=l>📄 已抽全文</div></a>' % cov.get('text_extracted',0)
    h += '<a class=sb href="/?p=stats"><div class=n style="color:#fa8c16">%d</div><div class=l>🧬 图谱L1已生成</div></a>' % tools.get('kg',{}).get('done',0)
    h += '<a class=sb href="/?p=stats"><div class=n style="color:#c0392b">%d</div><div class=l>⚠️ 待修假摘要</div></a>' % fake
    h += '</div></div>'
    # 离线批处理
    h += '<div style="display:flex;flex-wrap:wrap;margin-top:6px">'
    h += '<div style="width:100%;font-weight:700;margin:10px 6px 0;color:#722ed1">⚙️ 离线批处理工具（tools/，可续跑）</div>'
    ext_n = cov.get('text_extracted',0)
    h += card('📄','提取文本',
        '抽取 PDF/EPUB/MOBI/TXT 正文存入 book_text，供 AI 摘要、知识图谱、全文检索。PDF 仅取前 5–30 页、上限 20 万字；&gt;50MB 大文件与无 tesseract 的扫描版回落书名。',
        '%d / %d 本 (%.1f%%)' % (ext_n, total, pct(ext_n)), ext_n, '#52c41a',
        '/?p=stats', '查看全文提取覆盖率',
        '<button class=btn onclick="EXTR()">▶ 全量抽取(续跑)</button> <span id=extRes></span>')
    ocr_n = cov.get('ocr_pending',0)
    h += card('📷','扫描版OCR',
        '对「已抽但正文极短(疑似书名兜底)」的扫描版PDF，用本机 tesseract+chi_sim 重新OCR识别，解锁无文字层书籍的正文。需本机已装 tesseract（tools/install_tesseract.bat）。',
        '待OCR重抽 %d 本' % ocr_n, max(0, ocr_n), '#eb2f96',
        '/?p=stats', '查看全文提取覆盖率',
        '<button class=btn onclick="EXTR_OCR()">▶ OCR 重抽扫描版</button> <span id=ocrRes></span>')
    nm_n = cov.get('named',0)
    h += card('📐','书名规则化',
        '套用 normalize_title() 清洗镜像站点标记/随机ID/作者括号/促销词/扩展名，展示「原书名→规则化」对比，可勾选采纳为正式书名。',
        '%d / %d 本已清洗 (%.1f%%)' % (nm_n, total, pct(nm_n)), nm_n, '#1677ff',
        '/?p=title-norm', '查看对比表 / 采纳',
        '<button class=btn onclick="TNREC()">🔄 重算写回</button> <span id=tnRes></span>')
    kg = tools.get('kg',{})
    h += card('🧬','知识图谱 L1',
        '结构层实体/关系抽取（不需 Ollama），落地 P2-D 知识图谱。基于已抽正文与书名生成。',
        '已完成 %d 本 · 跳过 %d · %s' % (kg.get('done',0), kg.get('skip',0), '🟢运行中' if kg.get('running') else '⚪空闲'),
        kg.get('done',0), '#fa8c16', '/?p=stats', '查看工具进度',
        '<input id=kgLimit value=300 style="width:70px"> <button class=btn onclick="TR(\'kg\',false)">▶ 生成</button> <button class=btn onclick="TR(\'kg\',true)">🔄 清空重跑</button> <span id=kgRes></span>')
    mt = tools.get('meta',{})
    pub_n = cov.get('publisher',0); isbn_n = cov.get('isbn',0)
    h += card('🌐','元数据补全',
        '用 Open Library(主源,直连免代理) + Google Books 回填出版社/ISBN/年份/简介。根治 Douban 403。',
        '出版社 %.1f%% · ISBN %.1f%% · 已完成 %d 本' % (pct(pub_n), pct(isbn_n), mt.get('done',0)),
        pub_n, '#13c2c2', '/?p=stats', '查看元数据覆盖率',
        '模式<select id=metaMode><option value=fast>fast</option><option value=full>full</option></select> <input id=metaLimit value=200 style="width:70px"> <button class=btn onclick="TR(\'meta\',false)">▶ 跑一批</button> <button class=btn onclick="TR(\'meta\',true)">🔁 重试失败</button> <span id=metaRes></span>')
    sm = tools.get('summary',{})
    h += card('✏️','摘要修复',
        '清掉 %d 条「假摘要」(导入时无正文被 LLM 编的模板示例)，用真全文经本机 Ollama 重跑真摘要。需 Ollama 在线。' % fake,
        '待修 %d 本 · 已完成 %d 本 · %s' % (fake, sm.get('done',0), '🟢运行中' if sm.get('running') else '⚪空闲'),
        max(0, fake), '#c0392b', '/?p=stats', '查看摘要健康',
        '<span id=sumPending style="color:#c0392b;font-size:12px"></span><br><input id=sumLimit value=20000 style="width:80px"> <button class=btn onclick="TR(\'summary\',false)">▶ 跑一批</button> <button class=btn onclick="TR(\'summary\',false,20000)">🔥 全量修复</button> <span id=sumRes></span>')
    h += '</div>'
    # 在服实时
    h += '<div style="display:flex;flex-wrap:wrap;margin-top:6px">'
    h += '<div style="width:100%;font-weight:700;margin:10px 6px 0;color:#1677ff">⚡ 在服实时工具（首页「AI 处理」面板触发）</div>'
    h += card('🏷️','AI 分类','导入或手动触发，调用本机 Ollama 给书打一级/二级分类+标签+难度。','进度 %d 本' % tools.get('classify',{}).get('done',0), tools.get('classify',{}).get('done',0), '#1677ff', '', '', '<a class=btn href="/">前往首页 AI 面板</a>')
    h += card('🤖','AI 摘要','基于正文生成结构化 AI 摘要(一句话/观点/概念/读者/难度)。','进度 %d 本' % tools.get('summarize',{}).get('done',0), tools.get('summarize',{}).get('done',0), '#1677ff', '', '', '<a class=btn href="/">前往首页 AI 面板</a>')
    h += card('🔎','在线元数据','导入时实时调 Open Library 补全出版社/ISBN。','进度 %d 本' % tools.get('metadata',{}).get('done',0), tools.get('metadata',{}).get('done',0), '#1677ff', '', '', '<a class=btn href="/">前往首页 AI 面板</a>')
    h += card('🎧','媒体转录','Whisper 转录音视频为文字，存 media.transcript。','进度 %d 条' % tools.get('transcribe',{}).get('done',0), tools.get('transcribe',{}).get('done',0), '#1677ff', '', '', '<a class=btn href="/?p=media">前往媒体库</a>')
    h += card('📝','媒体摘要','基于转录文本生成媒体 AI 摘要。','进度 %d 条' % tools.get('media_summarize',{}).get('done',0), tools.get('media_summarize',{}).get('done',0), '#1677ff', '', '', '<a class=btn href="/?p=media">前往媒体库</a>')
    h += '</div>'
    # JS：复用 TR/TP/SP/TNREC + 新增 EXTR
    h += '<div style="margin-top:10px"><button class=btn onclick="TP()">🔄 刷新进度</button> <span id=toolStat style="font-size:12px;color:#666"></span></div>'
    js = '''<script>
function EXTR(){var x=new XMLHttpRequest();x.open("POST","/api/extract-batch");x.setRequestHeader("Content-Type","application/json");
x.onload=function(){try{var r=JSON.parse(x.responseText);document.getElementById("extRes").textContent=r.status||(r.ok?"已启动":"失败");TP();}catch(e){document.getElementById("extRes").textContent="error"}};
x.send(JSON.stringify({count:20000}));}
function EXTR_OCR(){var x=new XMLHttpRequest();x.open("POST","/api/extract-ocr");x.setRequestHeader("Content-Type","application/json");
x.onload=function(){try{var r=JSON.parse(x.responseText);if(r.status=="no_tesseract"){document.getElementById("ocrRes").textContent="⚠️ 未装tesseract，先跑 install_tesseract.bat";return;}if(r.status=="no_chi_sim"){document.getElementById("ocrRes").textContent="⚠️ 缺中文包chi_sim，OCR无法识别中文，请把chi_sim.traineddata放入tessdata";return;}document.getElementById("ocrRes").textContent=r.status||"已启动";OCRPOLL();}catch(e){document.getElementById("ocrRes").textContent="error"}};
x.send(JSON.stringify({}));}
function OCRPOLL(){var x=new XMLHttpRequest();x.open("GET","/api/extract-ocr/status");x.onload=function(){try{var r=JSON.parse(x.responseText);var s=(r.running?"OCR中 "+r.done+"/"+r.total:"完成 "+r.done+"/"+r.total);document.getElementById("ocrRes").textContent=s;if(r.running)setTimeout(OCRPOLL,2000)}catch(e){}};x.send();}
function TNREC(){var x=new XMLHttpRequest();x.open("POST","/api/title-norm/recompute");x.onload=function(){try{var r=JSON.parse(x.responseText);document.getElementById("tnRes").textContent=r.msg||(r.ok?"已启动":"失败");if(r.ok)TNPOLL()}catch(e){document.getElementById("tnRes").textContent="error"}};x.send();}
function TNPOLL(){var x=new XMLHttpRequest();x.open("GET","/api/title-norm/recompute-status");x.onload=function(){try{var r=JSON.parse(x.responseText);var s=(r.running?"重算中 "+r.done+"/"+r.total:"完成 "+r.done+"/"+r.total)+(r.error?" 错误:"+r.error:"");document.getElementById("tnRes").textContent=s;if(r.running)setTimeout(TNPOLL,1500)}catch(e){}};x.send();}
function TR(t,re,lf){var lim=lf||(t=='kg'?document.getElementById('kgLimit').value:(t=='meta'?document.getElementById('metaLimit').value:document.getElementById('sumLimit').value));
var md=(t=='meta'?document.getElementById('metaMode').value:'');
var b=JSON.stringify({tool:t,limit:lim,mode:md,regen:!!re});
var x=new XMLHttpRequest();x.open('POST','/api/tools/run');x.setRequestHeader('Content-Type','application/json');
x.onload=function(){try{var r=JSON.parse(x.responseText);document.getElementById(t+'Res').textContent=r.msg||(r.ok?'已启动':'失败');TP();}catch(e){document.getElementById(t+'Res').textContent='error'}};x.send(b);}
function TP(){var x=new XMLHttpRequest();x.open('GET','/api/tools/status');x.onload=function(){try{var r=JSON.parse(x.responseText);var s='';for(var k in r){if(k=='_error'){s+='读取错误:'+r[k];continue;}var v=r[k];s+=k+': 完成'+v.done+' 跳过'+v.skip+(v.running?' [运行中]':'')+'  ';}document.getElementById('toolStat').textContent=s;}catch(e){}};x.send();}
function SP(){var x=new XMLHttpRequest();x.open('GET','/api/summary-fix/pending');x.onload=function(){try{var r=JSON.parse(x.responseText);document.getElementById('sumPending').textContent='待修假摘要 '+r.pending+' 本（有全文可重跑 '+r.has_text+' · 无全文将清空 '+r.no_text+'）';}catch(e){}};x.send();}
TP();SP();
</script>'''
    h += js
    return h


def migrate_schema():
    """P0：阅读进度(reading_status/last_page) + 智能书架(shelves)。幂等，可在启动时安全重复调用。"""
    c = sqlite3.connect(DB, timeout=30)
    cur = c.cursor()
    cols = {r[1] for r in cur.execute("PRAGMA table_info(books)").fetchall()}
    for col, ddl in [
        ("reading_status", "TEXT DEFAULT 'unread'"),
        ("last_page", "INTEGER DEFAULT 0"),
        ("last_read_at", "TEXT DEFAULT ''"),
        ("metadata_source", "TEXT DEFAULT ''"),
        ("metadata_conf", "REAL DEFAULT 0"),
        ("normalized_title", "TEXT DEFAULT ''"),
        ("text_extracted", "INTEGER DEFAULT 0"),
    ]:
        if col not in cols:
            cur.execute("ALTER TABLE books ADD COLUMN %s %s" % (col, ddl))
    cur.execute("""CREATE TABLE IF NOT EXISTS shelves (
        id TEXT PRIMARY KEY, name TEXT NOT NULL,
        q TEXT DEFAULT '', cat TEXT DEFAULT '', sub TEXT DEFAULT '',
        fmt TEXT DEFAULT '', diff TEXT DEFAULT '', rstat TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0)""")
    for col, ddl in [("author","TEXT DEFAULT ''"),("tags","TEXT DEFAULT ''"),("year","TEXT DEFAULT ''")]:
        _scols=[r[1] for r in cur.execute("PRAGMA table_info(shelves)").fetchall()]
        if col not in _scols:
            cur.execute("ALTER TABLE shelves ADD COLUMN %s %s" % (col, ddl))
    # 20260825：把内联在 books 里的大字段 text_content 迁出到副表 book_text，
    # 使 UPDATE books（如盘符路径修正）只改写窄行 -> 从“重写整张 12GB 表”变为“秒级”。
    # 注意：12GB 文本搬迁改为【后台分块】执行（见 migrate_text_content()），避免阻塞服务启动。
    cur.execute("""CREATE TABLE IF NOT EXISTS book_text (
        id TEXT PRIMARY KEY,
        text_content TEXT)""")
    # P2-A 阅读笔记：确保列与当前代码一致。旧版可能已建过不同 schema（content/position/chapter/note_type），
    # 用 IF NOT EXISTS 会跳过导致 note/page 列缺失 -> 所有笔记 SQL 报 no such column: note。
    # 故检测：表不存在则新建；表存在但缺 note 列则重建（当前 0 行，无数据损失）。
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reading_notes'")
    if cur.fetchone() is None:
        cur.execute("""CREATE TABLE reading_notes (
            id TEXT PRIMARY KEY, book_id TEXT NOT NULL, note TEXT DEFAULT '',
            page INTEGER DEFAULT 0, created_at TEXT DEFAULT '', updated_at TEXT DEFAULT '')""")
    else:
        cur.execute("SELECT COUNT(*) FROM pragma_table_info('reading_notes') WHERE name='note'")
        if cur.fetchone()[0] == 0:
            cur.execute("DROP TABLE IF EXISTS reading_notes")
            cur.execute("""CREATE TABLE reading_notes (
                id TEXT PRIMARY KEY, book_id TEXT NOT NULL, note TEXT DEFAULT '',
                page INTEGER DEFAULT 0, created_at TEXT DEFAULT '', updated_at TEXT DEFAULT '')""")
    c.commit(); c.close()

def migrate_text_content():
    """后台分块把 books.text_content 迁出到 book_text，避免 12GB 单事务阻塞启动。
    分块提交：每批释放写锁，服务期间的笔记/进度写入不被长时间阻塞。幂等可断点续传。"""
    try:
        c = sqlite3.connect(DB, timeout=60)
        cur = c.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS book_text (id TEXT PRIMARY KEY, text_content TEXT)")
        cols = {r[1] for r in cur.execute("PRAGMA table_info(books)").fetchall()}
        if 'text_content' not in cols:
            c.close(); return
        ids = [r[0] for r in cur.execute("SELECT id FROM books WHERE text_content IS NOT NULL").fetchall()]
        total = len(ids)
        batch = 200
        done = 0
        for i in range(0, total, batch):
            chunk = ids[i:i+batch]
            ph = ",".join("?" * len(chunk))
            rows = cur.execute(f"SELECT id, text_content FROM books WHERE id IN ({ph})", chunk).fetchall()
            cur.executemany("INSERT OR IGNORE INTO book_text(id, text_content) VALUES(?,?)",
                            [(r[0], r[1]) for r in rows])
            c.commit()
            done += len(rows)
            if done % 2000 == 0 or done == total:
                print(f"[migrate] text_content 迁出进度 {done}/{total}", flush=True)
        n_t = cur.execute("SELECT COUNT(*) FROM book_text").fetchone()[0]
        n_b = cur.execute("SELECT COUNT(*) FROM books WHERE text_content IS NOT NULL").fetchone()[0]
        if n_t == n_b:
            try:
                cur.execute("ALTER TABLE books DROP COLUMN text_content")
                c.commit()
                print(f"[migrate] text_content 已迁出至 book_text（{n_t} 本），books 表瘦身完成", flush=True)
            except Exception as e:
                print(f"[migrate] DROP COLUMN text_content 失败（保留原列）: {e}", flush=True)
        else:
            print(f"[migrate] text_content 复制未完成（{n_t}/{n_b}），暂缓 DROP 原列", flush=True)
        c.close()
    except Exception as e:
        print(f"[migrate] text_content 迁出出错: {e}", flush=True)

def he(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
def fc(f): return {'pdf':'#ff4d4f','epub':'#1677ff','rar':'#fa8c16','mobi':'#52c41a','azw3':'#13c2c2','txt':'#1677ff','md':'#722ed1'}.get(f,'#999')
def cc(c): return {'计算机与编程':'#1677ff','历史与人文':'#fa8c16','文学与小说':'#52c41a','哲学与思想':'#722ed1','科学与科普':'#13c2c2','经济与管理':'#eb2f96','心理与成长':'#fa541c','教育学习':'#2f54eb','艺术设计':'#a0d911','社会与政治':'#f5222d','生活与健康':'#7cb305','其他':'#999'}.get(c,'#999')

CSS = """* { margin:0; padding:0; box-sizing:border-box; } body { font-family: "Microsoft YaHei", Arial, sans-serif; background: #f5f5f5; display: flex; min-height: 100vh; } nav { width: 250px; background: #fff; padding: 20px 0; box-shadow: 2px 0 8px rgba(0,0,0,0.05); } nav h2 { padding: 0 20px 20px; color: #1677ff; font-size: 18px; border-bottom: 1px solid #f0f0f0; margin-bottom: 10px; } nav a { display: block; padding: 12px 20px; color: #333; text-decoration: none; font-size: 15px; } nav a:hover { background: #e6f4ff; color: #1677ff; } main { flex: 1; padding: 24px; overflow-y: auto; } .sb { background: #fff; padding: 20px; border-radius: 8px; text-align: center; min-width: 140px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); text-decoration: none; color: inherit; } .sb .n { font-size: 28px; font-weight: bold; } .sb .l { font-size: 13px; color: #999; margin-top: 4px; } .row { display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; } .tag { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 12px; margin: 3px; color: #fff; } .panel { background: #fff; padding: 16px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); } .panel h3 { margin-bottom: 12px; font-size: 16px; } .sch { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; } .sch input, .sch select { padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; } .sch input { flex: 1; min-width: 180px; } .sch button { padding: 8px 20px; background: #1677ff; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; } .bk { background: #fff; border-radius: 8px; padding: 14px; margin-bottom: 8px; display: flex; gap: 12px; align-items: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05); cursor: pointer; } .bk:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.1); } .bk img { width: 50px; height: 70px; object-fit: cover; border-radius: 4px; flex-shrink: 0; } .bk .cv { width: 50px; height: 70px; border-radius: 4px; flex-shrink: 0; background: linear-gradient(135deg, #667eea, #764ba2); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 22px; } .bk .info { flex: 1; min-width: 0; } .bk .t { font-weight: bold; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .bk .m { font-size: 12px; color: #999; margin-top: 2px; } a { color: #1677ff; text-decoration: none; } a:hover { text-decoration: underline; } .co { color: #999; } .btn { padding: 8px 20px; background: #1677ff; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; margin: 2px; } .bb2 { background: #fff; color: #1677ff; border: 1px solid #1677ff; } .detail { background: #fff; border-radius: 12px; padding: 24px; max-width: 800px; margin: 0 auto; box-shadow: 0 2px 12px rgba(0,0,0,0.1); overflow: hidden; } .detail h1 { margin-bottom: 16px; font-size: 22px; margin-right: 170px; } .detail .meta { margin-bottom: 16px; color: #666; font-size: 14px; line-height: 1.8; margin-right: 170px; } .detail .sec { margin: 16px 0; } .detail-cover { float: right; width: 150px; height: 200px; object-fit: contain; border-radius: 8px; background: #f5f5f5; margin-left: 16px; } .detail-cv { float: right; width: 150px; height: 200px; border-radius: 8px; background: linear-gradient(135deg, #667eea, #764ba2); display: flex; align-items: center; justify-content: center; color: #fff; font-size: 48px; margin-left: 16px; }"""

NAV = '<nav><h2>📚 我的图书馆</h2><a href="/">🏠 首页</a><a href="/?p=books">📖 书库 ({B})</a><a href="/?p=media">🎧 媒体库 ({M})</a><a href="/?p=import">📥 导入新书</a><a href="/?p=notes">📝 笔记 ({N})</a><a href="/?p=tools">🛠️ 工具中心</a><a href="/?p=stats">📊 统计</a><a href="/?p=title-norm">📐 书名规则化</a><div class="cat-tree">{TREE}</div><div class="shelf-box">{SHELVES}</div><div class="theme-row"><button class="theme-btn" onclick="toggleTheme()" title="切换深浅色">🌙 深色</button></div></nav>'

EXTRA_CSS = """
.cat-tree{padding:8px 0 14px;border-top:1px solid #f0f0f0;margin-top:6px;max-height:calc(100vh - 220px);overflow-y:auto}
.cat-tree .ci{margin:1px 0}
.cat-tree .cl{display:flex;align-items:center;padding:7px 20px;color:#333;font-size:14px;cursor:pointer}
.cat-tree .cl:hover,.cat-tree .cl.act{background:#e6f4ff;color:#1677ff}
.cat-tree .cl .ct{margin-left:auto;padding-left:8px;color:#bbb;font-size:12px}
.cat-tree .cl .caret{display:inline-flex;align-items:center;justify-content:center;width:16px;height:18px;color:#999;cursor:pointer;user-select:none;font-size:12px;flex-shrink:0}
.cat-tree .cl .caret:hover{color:#1677ff}
.cat-tree .clink{color:inherit;text-decoration:none}
.cat-tree .clink:hover{color:#1677ff}
.shelf-box{padding:6px 0 14px;border-top:1px solid #f0f0f0;margin-top:6px}
.shelf-box .sb-h{padding:6px 20px;color:#999;font-size:12px;font-weight:bold;display:flex;align-items:center;justify-content:space-between}
.shelf-box .sb-h a{color:#1677ff;text-decoration:none;font-weight:normal}
.shelf-box .shelf{display:flex;align-items:center;padding:6px 20px;color:#333;text-decoration:none;font-size:14px}
.shelf-box .shelf:hover{background:#f0f5ff;color:#1677ff}
.shelf-box .shelf .sn{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.shelf-box .shelf .sd{color:#bbb;cursor:pointer;margin-left:8px;font-size:12px}
.shelf-box .shelf .sd:hover{color:#ff4d4f}
.shelf-box .empty{color:#bbb;font-size:12px;padding:4px 20px}
.rb{display:inline-block;font-size:11px;padding:1px 6px;border-radius:10px;margin-top:4px;color:#fff}
.rb.unread{background:#bbb}
.rb.reading{background:#1677ff}
.rb.finished{background:#52c41a}
.sb-btn{background:#fff!important;color:#1677ff;border:1px solid #1677ff!important}
.rs-btn{background:#1677ff;color:#fff;border:1px solid #1677ff;border-radius:4px;padding:4px 12px;cursor:pointer;font-size:13px;margin-left:6px}
.rs-btn.off{background:#fff;color:#888;border-color:#ccc}
.cat-tree .sl{display:none;padding:2px 0 4px 12px}
.cat-tree .sl.open{display:block}
.cat-tree .sl a{display:block;padding:5px 20px 5px 30px;color:#666;text-decoration:none;font-size:13px}
.cat-tree .sl a:hover,.cat-tree .sl a.act{background:#f0f5ff;color:#1677ff}
.grid{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px}
.card{width:116px;text-decoration:none;color:inherit;display:block}
.card img,.card .cv{width:116px;height:162px;object-fit:cover;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.12);background:linear-gradient(135deg,#667eea,#764ba2)}
.card .cv{display:flex;align-items:center;justify-content:center;color:#fff;font-size:28px}
.card .t{font-size:12px;margin-top:6px;line-height:1.35;height:32px;overflow:hidden}
.topbar{display:none}
.overlay{display:none}
@media(max-width:768px){
  body{display:block}
  .topbar{display:flex;position:fixed;top:0;left:0;right:0;height:50px;align-items:center;gap:12px;padding:0 14px;background:#1677ff;color:#fff;z-index:1100;box-shadow:0 2px 6px rgba(0,0,0,.18)}
  .topbar .menu-btn{background:transparent;border:none;color:#fff;font-size:24px;cursor:pointer;line-height:1;padding:2px 6px}
  .topbar span{font-size:16px;font-weight:bold}
  .overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:999}
  body.nav-open .overlay{display:block}
  nav{position:fixed;top:0;left:0;height:100vh;width:82%;max-width:300px;z-index:1000;transform:translateX(-100%);transition:transform .25s ease;overflow-y:auto;padding-top:58px;box-shadow:2px 0 12px rgba(0,0,0,.25)}
  nav.open{transform:translateX(0)}
  main{padding:62px 12px 16px;overflow:visible;height:auto}
  .grid{gap:10px;margin-top:8px}
  .card{width:calc(50% - 5px)}
  .card img,.card .cv{width:100%;height:auto;aspect-ratio:116/162}
  .card .t{font-size:11px;height:28px}
  .sch{flex-direction:column;gap:8px}
  .sch input,.sch select,.sch button{width:100%}
  .sch input{min-width:0}
  .detail-cover,.detail-cv{width:120px;height:168px;float:none;margin:0 0 12px}
  .panel,.sb{padding:14px}
  h2{font-size:18px}
  .row{gap:10px}
}
@media(max-width:400px){
  .card{width:calc(50% - 4px)}
  .card .t{font-size:10px}
}
/* ===== P2-B 主题变量 + 暗色覆盖层（不改动原浅色样式） ===== */
:root{
  --bg:#f5f5f5; --panel:#fff; --text:#222; --muted:#999; --primary:#1677ff;
  --border:#f0f0f0; --border2:#ddd; --hover:#e6f4ff; --shadow:rgba(0,0,0,.05);
  color-scheme:light;
}
[data-theme="dark"]{
  --bg:#16181d; --panel:#21242b; --text:#e6e8eb; --muted:#8a9099; --primary:#4096ff;
  --border:#2c3038; --border2:#353a44; --hover:#283447; --shadow:rgba(0,0,0,.5);
  color-scheme:dark;
}
[data-theme="dark"] body{background:var(--bg);color:var(--text)}
[data-theme="dark"] nav{background:var(--panel);box-shadow:2px 0 8px var(--shadow)}
[data-theme="dark"] nav h2{color:var(--primary);border-color:var(--border)}
[data-theme="dark"] nav a{color:var(--text)}
[data-theme="dark"] nav a:hover{background:var(--hover);color:var(--primary)}
[data-theme="dark"] main{background:var(--bg)}
[data-theme="dark"] .panel,.sb{background:var(--panel);box-shadow:0 1px 3px var(--shadow)}
[data-theme="dark"] .panel h3{color:var(--text)}
[data-theme="dark"] .bk{background:var(--panel);box-shadow:0 1px 3px var(--shadow)}
[data-theme="dark"] .bk .t,[data-theme="dark"] .card .t{color:var(--text)}
[data-theme="dark"] .sch input,[data-theme="dark"] .sch select{background:var(--panel);color:var(--text);border-color:var(--border2)}
[data-theme="dark"] .cat-tree .cl{color:var(--text)}
[data-theme="dark"] .cat-tree .cl:hover,.cat-tree .cl.act{background:var(--hover);color:var(--primary)}
[data-theme="dark"] .cat-tree .clink{color:var(--text)}
[data-theme="dark"] .shelf-box .shelf{color:var(--text)}
[data-theme="dark"] .shelf-box .shelf:hover{background:var(--hover);color:var(--primary)}
[data-theme="dark"] .shelf-box .sb-h{color:var(--muted)}
[data-theme="dark"] .shelf-box .empty{color:var(--muted)}
[data-theme="dark"] .sb .l{color:var(--muted)}
[data-theme="dark"] .rb.unread{background:#555}
[data-theme="dark"] .tag{color:#fff}
[data-theme="dark"] .topbar{background:#1f6feb}
.theme-row{padding:14px 20px 18px;border-top:1px solid var(--border);margin-top:8px}
.theme-btn{width:100%;padding:9px 12px;border:1px solid var(--primary);background:transparent;color:var(--primary);border-radius:6px;cursor:pointer;font-size:14px;text-align:left}
.theme-btn:hover{background:var(--hover)}
[data-theme="dark"] .theme-btn{color:var(--primary)}
/* ===== P2-A 阅读笔记 ===== */
.note-item{background:var(--panel);border:1px solid var(--border2);border-radius:8px;padding:10px 12px;margin-bottom:8px;box-shadow:0 1px 2px var(--shadow)}
.note-body{white-space:pre-wrap;line-height:1.7;font-size:14px;color:var(--text)}
.note-meta{margin-top:6px;font-size:12px;color:var(--muted)}
.note-meta a{color:var(--muted);text-decoration:none;margin-left:4px}
.note-meta a:hover{color:#ff4d4f}
/* ===== 桌面自适应（两台不同宽度屏幕都好看） ===== */
@media (min-width: 769px){
  /* 侧栏宽度随屏宽流体缩放，而非死固定 250px */
  nav{ width: clamp(210px, 16vw, 260px); }
  /* 书卡网格：随可用宽度自动铺满、列数自适应，大小屏都均匀 */
  .grid{ display:grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap:16px; }
  .card{ width:auto; }
  .card img, .card .cv{ width:100%; height:auto; aspect-ratio:116/162; }
}
/* 超宽屏：限制主内容最大宽度并居中，避免被拉得过散 */
@media (min-width: 1700px){
  main{ max-width:1500px; margin:0 auto; }
}
"""

def build_cat_tree(active_cat='', active_sub=''):
    # 计数：INNER JOIN books 且 status='active'。
    # 注意：原 LEFT JOIN books ON ... AND b.status='active' 写法在 12GB 库上会触发 SQLite C 扩展崩溃（exit 1，无 traceback），
    # 故改为 INNER JOIN 聚合后于 Python 侧映射计数，安全且只统计 active 书。
    cat_n = {}
    for r in dbq("SELECT bc.category_id cid, COUNT(*) n FROM book_categories bc JOIN books b ON b.id=bc.book_id WHERE b.status='active' GROUP BY bc.category_id"):
        cat_n[r['cid']] = r['n']
    # 一级分类：其他固定在最底，其余按书数量降序排列
    raw = dbq("SELECT id,name FROM categories WHERE parent_id IS NULL")
    cats = sorted(raw, key=lambda r: (0 if r['name'] != '其他' else 1, -cat_n.get(r['id'], 0)))
    # 二级分类
    subs_all = dbq("SELECT id,name,parent_id FROM categories WHERE parent_id IS NOT NULL")
    sub_n = {}
    # 只统计“子类父级与一级分类一致”的书，使树显示数 == 点击子类后页面(按 cat+sub 双重过滤)的页数。
    # 背景：AI 批量补标约有 22% 的子类标签挂错父级（如把正经书错打“待整理”子类），
    # 若不过滤父级，树会把这些书计入错误的二级分类，导致“树上数量≠点击后实际数量”。
    for r in dbq("""SELECT bc.subcategory_id sid, COUNT(*) n FROM book_categories bc
                    JOIN books b ON b.id=bc.book_id
                    JOIN categories s ON s.id=bc.subcategory_id
                    WHERE b.status='active' AND bc.subcategory_id IS NOT NULL AND bc.category_id=s.parent_id
                    GROUP BY bc.subcategory_id"""):
        sub_n[r['sid']] = r['n']
    subs = {}
    for r in subs_all:
        subs.setdefault(r['parent_id'], []).append((r['id'], r['name'], sub_n.get(r['id'], 0)))
    out = ['<div class="cat-tree">']
    for c in cats:
        cid = c['id']; act = ' act' if cid == active_cat else ''
        n = cat_n.get(cid, 0)
        sl = subs.get(cid, [])
        opencls = ' open' if (sl and cid == active_cat) else ''
        caret = ('<span class="caret" onclick="toggleCat(this)">%s</span>' % ('▾' if opencls else '▸')) if sl else ''
        out.append('<div class="ci"><div class="cl%s">%s<a class="clink" href="/?p=books&cat=%s">%s</a><span class="ct">%s</span></div>' % (act, caret, cid, he(c['name']), n))
        if sl:
            out.append('<div class="sl%s">' % opencls)
            for sid, sn, sn_n in sl:
                sa = ' act' if sid == active_sub else ''
                out.append('<a class="%s" href="/?p=books&cat=%s&sub=%s">%s <span style="color:#bbb">(%s)</span></a>' % (sa, cid, sid, he(sn), sn_n))
            out.append('</div>')
        out.append('</div>')
    out.append('</div>')
    return ''.join(out)

def build_shelves():
    rows = dbq("SELECT id,name,q,cat,sub,fmt,diff,rstat,author,tags,year FROM shelves ORDER BY sort_order,name")
    if not rows:
        return '<div class="sb-h">📑 我的书架 <a href="/?p=books" title="去书库页保存">＋</a></div><div class="empty">暂无书架，在书库页点「存为书架」</div>'
    out = ['<div class="sb-h">📑 我的书架 <a href="/?p=books" title="去书库页保存">＋</a></div>']
    for r in rows:
        qs = []
        for k,v in (('q',r['q']),('cat',r['cat']),('sub',r['sub']),('fmt',r['fmt']),('diff',r['diff']),('rstat',r['rstat']),('author',r['author']),('tags',r['tags']),('year',r['year'])):
            if v: qs.append('%s=%s' % (k, he(str(v))))
        href = '/?p=books' + ('&'+'&'.join(qs) if qs else '')
        out.append('<div class="shelf"><a class="sn" href="%s" title="%s">%s</a><span class="sd" onclick="delShelf(\'%s\')" title="删除">✕</span></div>'
                   % (href, he(r['name']), he(r['name']), r['id']))
    return ''.join(out)

COMMON_JS = """<script>
(function(){try{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t;}catch(e){}})();
function toggleTheme(){var d=document.documentElement;var n=d.dataset.theme==='dark'?'light':'dark';d.dataset.theme=n;try{localStorage.setItem('theme',n)}catch(e){}var b=document.querySelector('.theme-btn');if(b)b.textContent=(n==='dark'?'☀️ 浅色':'🌙 深色');}
(function(){try{var t=document.documentElement.dataset.theme||'light';var b=document.querySelector('.theme-btn');if(b)b.textContent=(t==='dark'?'☀️ 浅色':'🌙 深色');}catch(e){}})();
function loadNotes(bid){
  var box=document.getElementById('notes-list'); if(!box)return;
  fetch('/api/books/'+bid+'/notes').then(function(r){return r.json();}).then(function(rows){
    box.innerHTML='';
    if(!rows.length){var p=document.createElement('p');p.className='co';p.textContent='还没有笔记，写下第一条吧';box.appendChild(p);return;}
    rows.forEach(function(n){
      var d=document.createElement('div'); d.className='note-item';
      var body=document.createElement('div'); body.className='note-body'; body.textContent=n.note;
      var meta=document.createElement('div'); meta.className='note-meta';
      meta.textContent=(n.page?('第 '+n.page+' 页 · '):'')+(n.created_at?n.created_at.slice(0,16):'')+' ';
      var e=document.createElement('a'); e.href='#'; e.textContent='✏️'; e.title='编辑'; e.onclick=function(ev){ev.preventDefault();editNote(bid,n);};
      var a=document.createElement('a'); a.href='#'; a.textContent='🗑️'; a.title='删除'; a.onclick=function(ev){ev.preventDefault();delNote(bid,n.id);};
      meta.appendChild(e); meta.appendChild(a);
      d.appendChild(body); d.appendChild(meta); box.appendChild(d);
    });
  }).catch(function(){var p=document.createElement('p');p.className='co';p.textContent='笔记加载失败';box.appendChild(p);});
}
var _editingNoteId=null;
function editNote(bid,n){
  var ta=document.getElementById('note-input'); var pg=document.getElementById('note-page');
  if(!ta)return; ta.value=n.note; if(pg)pg.value=n.page||'';
  _editingNoteId=n.id; ta.focus();
  var btn=document.querySelector('#notes-sec button.btn'); if(btn)btn.textContent='💾 更新笔记';
}
function addNote(bid){
  var ta=document.getElementById('note-input'); var pg=document.getElementById('note-page');
  var note=(ta.value||'').trim(); if(!note){alert('笔记内容不能为空');return;}
  var page=parseInt(pg.value)||0;
  var action=_editingNoteId?'update':'add';
  var payload={action:action,note:note,page:page};
  if(_editingNoteId)payload.id=_editingNoteId;
  var x=new XMLHttpRequest();x.open('POST','/api/books/'+bid+'/note');x.setRequestHeader('Content-Type','application/json');
  x.onload=function(){var r=JSON.parse(x.responseText);if(r.ok){ta.value='';if(pg)pg.value='';_editingNoteId=null;var btn=document.querySelector('#notes-sec button.btn');if(btn)btn.textContent='＋ 保存笔记';loadNotes(bid);}else alert('保存失败');};
  x.send(JSON.stringify(payload));
}
function delNote(bid,nid){
  if(!confirm('删除这条笔记？'))return;
  var x=new XMLHttpRequest();x.open('POST','/api/books/'+bid+'/note');x.setRequestHeader('Content-Type','application/json');
  x.onload=function(){loadNotes(bid);};
  x.send(JSON.stringify({action:'delete',id:nid}));
}
(function(){try{var nl=document.getElementById('notes-list');if(nl){var b=nl.getAttribute('data-bid');if(b)loadNotes(b);}}catch(e){}})();
function EDT(id,old){var t=prompt("新书名:",old);if(t&&t!==old){var x=new XMLHttpRequest();x.open("POST","/api/books/"+id+"/edit");x.setRequestHeader("Content-Type","application/json");x.onload=function(){location.reload()};x.send(JSON.stringify({title:t}));}}
function toggleCat(el){
  var ci=el.parentElement.parentElement;   // caret -> .cl -> .ci
  var sl=ci.querySelector('.sl');
  if(sl){
    sl.classList.toggle('open');
    el.textContent = sl.classList.contains('open') ? '▾' : '▸';
  }
}
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
var _metaTimer=null;
function META(){
  var b=document.getElementById("metaBtn");if(b.disabled)return;
  var cnt=parseInt(document.getElementById("metaCnt").value)||0;
  b.disabled=true;b.textContent="元数据启动中...";
  document.getElementById("metaRes").innerHTML="启动中，需联网访问 Open Library / Google Books，请稍候...";
  var x=new XMLHttpRequest();x.open("POST","/api/metadata-batch");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){
    var r=JSON.parse(x.responseText);
    if(r.status==="disabled"){b.disabled=false;b.textContent="🌐 补全元数据";document.getElementById("metaRes").innerHTML="⚠️ 未启用：设置环境变量 LIB_METADATA_ONLINE=1 并重启服务";return;}
    b.disabled=false;b.textContent="🌐 补全元数据";_pollMeta();
  };
  x.send(JSON.stringify({count:cnt}))
}
function _pollMeta(){
  clearTimeout(_metaTimer);
  var x=new XMLHttpRequest();x.open("GET","/api/task-status");
  x.onload=function(){
    var r=JSON.parse(x.responseText);var m=r.metadata||{};
    if(m.total>0){
      document.getElementById("metaRes").innerHTML="补全中: "+m.done+"/"+m.total+" 本（已填 "+m.filled+"，跳过 "+m.skipped+"）";
      if(m.done<m.total)_metaTimer=setTimeout(_pollMeta,3000);
      else document.getElementById("metaRes").innerHTML="✅ 补全完成: 共 "+m.total+" 本，填入 "+m.filled+" 本，跳过 "+m.skipped+" 本 <a href=/ onclick=location.reload()>刷新</a>";
    }else{
      document.getElementById("metaRes").innerHTML=m.total===0?"等待响应...":"";
      _metaTimer=setTimeout(_pollMeta,3000);
    }
  };
  x.onerror=function(){document.getElementById("metaRes").innerHTML="轮询出错，5秒后重试...";_metaTimer=setTimeout(_pollMeta,5000);};
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

// P0 阅读状态
function setStatus(bid,st){
  var x=new XMLHttpRequest();x.open("POST","/api/progress");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){location.reload();};
  x.onerror=function(){alert("更新失败");};
  x.send(JSON.stringify({id:bid,status:st,page:0}));
}
// P0 智能书架：保存当前筛选
function saveShelf(){
  var q=document.querySelector('input[name=q]').value;
  var cat=document.querySelector('select[name=cat]').value;
  var sub=document.querySelector('input[name=sub]').value;
  var fmt=document.querySelector('input[name=fmt]').value;
  var diff=document.querySelector('select[name=diff]').value;
  var rstat=document.querySelector('select[name=rstat]').value;
  var author=(document.querySelector('input[name=author]')||{}).value||'';
  var tags=(document.querySelector('input[name=tags]')||{}).value||'';
  var year=(document.querySelector('input[name=year]')||{}).value||'';
  var name=prompt("书架名称：", (cat?cat+' ':'')+(author?author+' ':'')+(rstat?rstat+' ':'')+(diff?diff+' ':'').trim()||"我的书架");
  if(!name)return;
  var x=new XMLHttpRequest();x.open("POST","/api/shelves");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){var r=JSON.parse(x.responseText);if(r.ok){alert("已保存书架："+name);location.reload();}else alert("保存失败");};
  x.send(JSON.stringify({name:name,q:q,cat:cat,sub:sub,fmt:fmt,diff:diff,rstat:rstat,author:author,tags:tags,year:year}));
}
// P0 删除书架
function delShelf(id){
  if(!confirm("删除这个书架？"))return;
  var x=new XMLHttpRequest();x.open("POST","/api/shelves/delete");x.setRequestHeader("Content-Type","application/json");
  x.onload=function(){location.reload();};
  x.send(JSON.stringify({id:id}));
}

function toggleNav(){var n=document.querySelector('nav');if(!n)return;n.classList.toggle('open');document.body.classList.toggle('nav-open');}
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
        elif fmt in ('rar','zip') and SEVEN_ZIP:
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

# === 压缩包支持（7z 可选；zip 用标准库）===
def find_7z():
    """在常见路径与 PATH 中查找 7z 可执行文件，找不到返回 None。"""
    import shutil
    for c in [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe", r"D:\7-Zip\7z.exe"]:
        if os.path.exists(c):
            return c
    return shutil.which("7z") or shutil.which("7za") or None

SEVEN_ZIP = find_7z()

def list_archive_contents(archive_path):
    """列出压缩包内文件。优先用 7z（支持 rar/7z/zip）；无 7z 时 zip 用标准库 zipfile。"""
    import zipfile
    if SEVEN_ZIP:
        import subprocess
        try:
            result = subprocess.run([SEVEN_ZIP, 'l', '-slt', '-sccUTF-8', archive_path],
                                    capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace')
            files = []; current = {}
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith('Path ='):
                    if current: files.append(current)
                    current = {'path': line[6:].strip()}
                elif line.startswith('Size ='):
                    try: current['size'] = int(line[6:].strip())
                    except: current['size'] = 0
            if current: files.append(current)
            return [f for f in files if f.get('size', 0) > 0]
        except Exception as e:
            print(f"[7z list error] {e}", flush=True)
    if archive_path.lower().endswith('.zip'):
        try:
            with zipfile.ZipFile(archive_path) as zf:
                return [{'path': i.filename, 'size': i.file_size} for i in zf.infolist() if not i.is_dir()]
        except Exception as e:
            print(f"[zip list error] {e}", flush=True)
    return []

def extract_archive_file(archive_path, file_name, dest_dir):
    """从压缩包提取单个文件。7z 优先；无 7z 时 zip 用标准库 zipfile。"""
    import zipfile
    if SEVEN_ZIP:
        import subprocess
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except (PermissionError, OSError) as e:
            print(f"[archive cache] dest_dir inaccessible, falling back to system temp: {e}", flush=True)
            dest_dir = os.path.join(tempfile.gettempdir(), "private_lib_archives", os.path.basename(dest_dir))
            os.makedirs(dest_dir, exist_ok=True)
        try:
            subprocess.run([SEVEN_ZIP, 'e', archive_path, file_name, f'-o{dest_dir}', '-y'], capture_output=True, timeout=120)
            extracted = os.path.join(dest_dir, os.path.basename(file_name))
            return extracted if os.path.exists(extracted) else None
        except Exception as e:
            print(f"[7z extract error] {e}", flush=True)
            return None
    if archive_path.lower().endswith('.zip'):
        try:
            os.makedirs(dest_dir, exist_ok=True)
            with zipfile.ZipFile(archive_path) as zf:
                zf.extract(file_name, dest_dir)
            extracted = os.path.join(dest_dir, file_name)
            return extracted if os.path.exists(extracted) else None
        except Exception as e:
            print(f"[zip extract error] {e}", flush=True)
    return None

# === EPUB 服务端解包直读（标准库 zipfile，零第三方依赖）===
import zipfile as _zf_mod, posixpath as _pp, re as _re_mod

def _epub_opf_path(zf):
    try:
        cont = zf.read('META-INF/container.xml').decode('utf-8', 'ignore')
    except Exception:
        cont = ''
    m = _re_mod.search(r'full-path="([^"]+)"', cont)
    if m: return m.group(1)
    for n in zf.namelist():
        if n.lower().endswith('.opf'): return n
    return None

def get_epub_data(fp):
    """返回 (title, [(zip_path, label), ...])；失败返回 (None, [])。"""
    try:
        zf = _zf_mod.ZipFile(fp)
    except Exception:
        return None, []
    try:
        opf = _epub_opf_path(zf)
        if not opf: return None, []
        opf_dir = _pp.dirname(opf)
        opf_xml = zf.read(opf).decode('utf-8', 'ignore')
        manifest = {}
        for m in _re_mod.finditer(r'<item\b([^>]*)>', opf_xml, _re_mod.I):
            attrs = m.group(1)
            idm = _re_mod.search(r'\bid="([^"]+)"', attrs, _re_mod.I)
            hm = _re_mod.search(r'\bhref="([^"]+)"', attrs, _re_mod.I)
            if idm and hm:
                manifest[idm.group(1)] = hm.group(1)
        spine_ids = _re_mod.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf_xml, _re_mod.I)
        tm = _re_mod.search(r'<dc:title[^>]*>(.*?)</dc:title>', opf_xml, _re_mod.I | _re_mod.S)
        title = tm.group(1).strip() if tm else ''
        chapters = []
        for sid in spine_ids:
            href = manifest.get(sid)
            if not href: continue
            zp = _pp.normpath(_pp.join(opf_dir, href))
            label = ''
            try:
                x = zf.read(zp).decode('utf-8', 'ignore')
                h1 = _re_mod.search(r'<h1[^>]*>(.*?)</h1>', x, _re_mod.I | _re_mod.S)
                if h1: label = _re_mod.sub(r'<[^>]+>', '', h1.group(1)).strip()
                else:
                    tt = _re_mod.search(r'<title[^>]*>(.*?)</title>', x, _re_mod.I | _re_mod.S)
                    if tt: label = _re_mod.sub(r'<[^>]+>', '', tt.group(1)).strip()
            except Exception:
                pass
            chapters.append((zp, label))
        if not chapters:
            for n in zf.namelist():
                if n.lower().endswith(('.xhtml', '.html', '.htm')):
                    chapters.append((n, _pp.basename(n)))
        return title, chapters
    finally:
        zf.close()

def _epub_chapter_html(fp, zip_path, bid):
    zf = _zf_mod.ZipFile(fp)
    try:
        data = zf.read(zip_path)
    finally:
        zf.close()
    m = _re_mod.search(r'encoding="([^"]+)"', data[:200].decode('ascii', 'ignore'), _re_mod.I)
    enc = m.group(1) if m else 'utf-8'
    try:
        html = data.decode(enc)
    except Exception:
        html = data.decode('utf-8', 'ignore')
    chapter_dir = _pp.dirname(zip_path)
    base = '/api/books/' + bid + '/epub/asset/'
    def rw(mo):
        attr = mo.group(1); val = mo.group(2)
        if val.startswith(('#', 'http:', 'https:', 'mailto:', 'data:', 'ftp:')):
            return mo.group(0)
        resolved = _pp.normpath(_pp.join(chapter_dir, val))
        return attr + '="' + base + urllib.parse.quote(resolved) + '"'
    return _re_mod.sub(r'(src|href)="([^"]+)"', rw, html, flags=_re_mod.I)

def _title_fallback(book_id):
    """Use book metadata as minimal text for books that can't be extracted.
    此路径代表“无真实正文”，故标记 text_extracted=0，供摘要/分类入口跳过、不生成假内容。"""
    try: dbe("UPDATE books SET text_extracted=0 WHERE id=?", (book_id,))
    except Exception: pass
    r = dbq("SELECT title,publisher,description FROM books WHERE id=?",(book_id,))
    if r:
        parts = [r[0]['title'] or '']
        if r[0]['publisher']: parts.append('Publisher: ' + r[0]['publisher'])
        if r[0]['description']: parts.append(r[0]['description'])
        text = '\n'.join(parts)
        if text.strip():
            set_text(book_id, text[:200000])
            return True
        return False

def _find_tesseract():
    """定位 tesseract 可执行文件：先查 PATH，再探测 Windows 标准安装路径(常不在 PATH)。"""
    import shutil as _sh, os as _os
    ts = _sh.which("tesseract") or _sh.which("tesseract.exe")
    if ts:
        return ts
    for cand in (
        r"F:\my-library\tools\tesseract_ocr\tesseract.exe",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if _os.path.exists(cand):
            return cand
    return None

def _ocr_pdf(file_path, max_pages=15):
    """扫描版PDF的OCR兜底。需主机安装 tesseract(+中文语言包 chi_sim)；缺失则优雅返回 ''，由调用方回落书名。"""
    import subprocess as _sp, tempfile, os as _os
    ts = _find_tesseract()
    if not ts:
        return ""
    # OCR 临时文件统一写到项目盘(F)下的可写目录, 避免沙箱/权限禁止写入系统 Temp
    # 导致 tesseract 输出写不进去、OCR 静默失败(整本回落书名)。
    _ocr_tmp = r"F:\my-library\tools\ocr_tmp"
    try:
        _os.makedirs(_ocr_tmp, exist_ok=True)
    except Exception:
        _ocr_tmp = tempfile.gettempdir()
    try:
        import fitz
        # 关闭 fitz 对超大页面图像的尺寸上限，否则扫描版大页会报
        # "Overly large image" 导致该页渲染失败、整本 OCR 回退书名。
        try:
            fitz.TOOLS().set_max_image_size(0)
        except Exception:
            pass
        doc = fitz.open(file_path)
        pages = min(max_pages, doc.page_count)
        texts = []
        for i in range(pages):
            # 自适应降分辨率：tesseract 单维像素上限约 32767px，超限会报
            # "Image too large" 拒绝。逐档(200→150→100→72)尝试，取到首个
            # 最大边<=32000px 的渲染；仍超限则至少交最后一档给 tesseract 试。
            pix = None
            for dpi in (200, 150, 100, 72):
                try:
                    p = doc[i].get_pixmap(dpi=dpi)
                except Exception:
                    continue
                pix = p
                if max(p.width, p.height) <= 32000:
                    break
            if pix is None:
                continue
            tmp = tempfile.NamedTemporaryFile(dir=_ocr_tmp, suffix=".png", delete=False).name
            try:
                pix.save(tmp)
            except Exception:
                try: _os.remove(tmp)
                except Exception: pass
                continue
            try:
                # 写到临时 txt(tesseract 默认以 UTF-8 写文件), 再读回, 规避 Windows 下
                # tesseract 经 stdout 输出 GBK 导致 Python text=True 解码崩溃、整页丢字的问题。
                out_txt = tempfile.NamedTemporaryFile(dir=_ocr_tmp, suffix=".txt", delete=False).name
                tessdata_dir = _os.path.join(_os.path.dirname(ts), "tessdata")
                r = _sp.run([ts, tmp, out_txt, "-l", "chi_sim+eng", "--tessdata-dir", tessdata_dir], capture_output=True, timeout=120)
                if r.returncode == 0 and _os.path.exists(out_txt):
                    with open(out_txt, "r", encoding="utf-8", errors="ignore") as _f:
                        texts.append(_f.read())
                try: _os.remove(out_txt)
                except Exception: pass
            except Exception:
                pass
            finally:
                try: _os.remove(tmp)
                except Exception: pass
        doc.close()
        return "\n".join(texts)
    except Exception as e:
        print(f"[OCR异常] {file_path}: {e}", flush=True)
        return ""

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
            # Scanned PDF fallback: try OCR, then title
            if not text.strip():
                ocr = _ocr_pdf(file_path, max_pages=15)
                if ocr.strip():
                    text = ocr
                    print(f"[扫描版PDF] OCR 获取 {len(ocr)} 字: {title_short}", flush=True)
                else:
                    print(f"[扫描版PDF] 无文字层且OCR不可用, 用书名兜底: {title_short}", flush=True)
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
                try:
                    raw = open(filepath, 'r', encoding='utf-8', errors='ignore').read()
                    from bs4 import BeautifulSoup
                    text = BeautifulSoup(raw, 'html.parser').get_text()
                finally:
                    shutil.rmtree(tempdir, ignore_errors=True)
            except Exception:
                # 尝试 calibre ebook-convert（若主机安装）
                cb = shutil.which("ebook-convert") or shutil.which("ebook-convert.exe")
                if cb:
                    try:
                        import tempfile, subprocess as _sp
                        out = tempfile.mktemp(suffix=".txt")
                        _sp.run([cb, file_path, out], capture_output=True, timeout=300)
                        if os.path.exists(out):
                            text = open(out, 'r', encoding='utf-8', errors='ignore').read()
                            os.remove(out)
                    except Exception: pass
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
            set_text(book_id, text)
            try: dbe("UPDATE books SET text_extracted=1 WHERE id=?", (book_id,))
            except Exception: pass
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
            # 20260827 P0修复：原续跑条件 `text_content IS NOT NULL` 会把“空字符串''(non-null)的空壳行”当成已提取而永久跳过。
            # 改为仅按 text_extracted 标志筛选：text_extracted=1 的书必有真实正文，其余(0/NULL)都需(重)抽取。
            # 不再扫 book_text 的 length()（会读全量 3GB 文本导致 MemoryError）。
            books = dbq("SELECT id,file_path,file_format,title FROM books WHERE status='active' AND text_extracted <> 1 LIMIT ?",(int(count),))
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
                    _mark('extract', b['id'], 'done' if ok else 'skip')
                except Exception as e: print(f"[批量提取异常] {b['title'][:30]}: {type(e).__name__}: {e}",flush=True)
            _task_status['er_r']=rv
        finally:
            _task_status['er']=False
            _count_cache["time"] = 0  # invalidate cache so counts refresh
    threading.Thread(target=w,daemon=True).start()
    return {"status":"started"}

def run_extract_ocr_async():
    """扫描版OCR重抽：后台 spawn tools/run_extract_full.py ocr（多线程、可续跑），并轮询其独立日志(_ocr_run.log)上报进度。需本机已装 tesseract。"""
    if _task_status.get('eor'): return {"status":"running"}
    if not _find_tesseract():
        return {"status":"no_tesseract", "msg":"本机未安装 tesseract，请先运行 tools/install_tesseract.bat"}
    # chi_sim 中文包检测：tesseract 已装但缺 chi_sim 时 OCR 会静默空转(回落书名)
    try:
        import subprocess as _sp
        ts = _find_tesseract()
        out = _sp.run([ts, "--list-langs"], capture_output=True, text=True, timeout=10).stdout
        if "chi_sim" not in out:
            return {"status":"no_chi_sim", "msg":"tesseract 已装但缺中文包 chi_sim，OCR 无法识别中文。请把 chi_sim.traineddata 放入 tessdata 目录，或重跑 tools/install_tesseract.bat"}
    except Exception:
        pass
    _task_status['eor'] = True
    _task_status['eor_r'] = {"done":0,"total":0,"running":True}
    def w():
        try:
            import subprocess, os, time, re
            py = sys.executable
            base = os.path.dirname(os.path.abspath(__file__))
            script = os.path.join(base, "tools", "run_extract_full.py")
            logp = os.path.join(base, "tools", "_ocr_run.log")
            # 0x00000008 = DETACHED_PROCESS：脱离服务进程独立运行，崩溃不影响在服
            proc = subprocess.Popen([py, script, "ocr"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=0x00000008)
            while True:
                if proc.poll() is not None: break
                try:
                    with open(logp, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.read().splitlines()
                    for ln in reversed(lines):
                        if "[prog] done=" in ln or "[done] total=" in ln or "[start] candidates=" in ln:
                            m = re.search(r"candidates=(\d+)", ln) or re.search(r"done=(\d+)/(\d+)", ln)
                            if m:
                                if "candidates" in ln: _task_status['eor_r']["total"] = int(m.group(1))
                                else: _task_status['eor_r']["done"] = int(m.group(1)); _task_status['eor_r']["total"] = int(m.group(2))
                            break
                except Exception: pass
                time.sleep(3)
            _task_status['eor_r']["running"] = False
            _task_status['eor_r']["done"] = _task_status['eor_r'].get("total", 0)
        finally:
            _task_status['eor'] = False
            _count_cache["time"] = 0  # 失效缓存，让覆盖率刷新
    threading.Thread(target=w, daemon=True).start()
    return {"status":"started"}

def _get_taxonomy():
    """从 categories 表构建 一级->[二级] 映射"""
    try:
        rows = dbq("SELECT c.name, s.name FROM categories s JOIN categories c ON s.parent_id=c.id WHERE s.parent_id IS NOT NULL")
        tax = {}
        for cat, sub in rows:
            tax.setdefault(cat, []).append(sub)
        return tax
    except Exception:
        return {}

def run_classify_async(count=10):
    if _task_status.get('cr'): return {"status":"running"}
    _task_status['cr'] = True
    _task_status['cr_r'] = {"done":0,"total":0}
    def w():
        try:
            # 取“无分类”或“有分类但缺二级”的书
            books = dbq("SELECT b.id,b.title,t.text_content FROM books b LEFT JOIN book_text t ON t.id=b.id WHERE b.status='active' AND b.id NOT IN (SELECT book_id FROM book_categories WHERE subcategory_id IS NOT NULL) LIMIT ?",(int(count),))
            tax = _get_taxonomy()
            cats = list(tax.keys()) if tax else ["计算机与编程","历史与人文","文学与小说","哲学与思想","科学与科普","经济与管理","心理与成长","教育学习","艺术设计","社会与政治","生活与健康","其他"]
            clist_lines = []
            for c in cats:
                clist_lines.append("- " + c)
                for s in tax.get(c, []):
                    clist_lines.append("    - " + s)
            clist = "\n".join(clist_lines)
            rv = {"done":0,"total":len(books)}
            for b in books:
                try:
                    prompt=f"判断以下书籍分类。一级类别与二级子类只能从下列选择。\n{clist}\n\n书名：{b['title']}\n内容：{(b['text_content'] or '')[:1500]}\n（若内容为空，仅根据书名判断）\n只返回JSON：{{\"category\":\"一级类别名\",\"subcategory\":\"二级子类名（必须属于所选一级）\",\"tags\":[\"标签1\",\"标签2\"],\"difficulty\":\"入门/中级/高级\"}}"
                    resp=_ollama_generate(prompt, model="qwen2.5:7b", timeout=180, temperature=0.1, num_ctx=4096)
                    if resp.startswith("```"): resp=resp.split("\n",1)[1].rsplit("\n",1)[0]
                    result=json.loads(resp)
                    cn=result.get("category","其他")
                    cr=dbq("SELECT id FROM categories WHERE name=?",(cn,))
                    cid=cr[0]['id'] if cr else str(uuid.uuid4()); dbe("INSERT INTO categories(id,name) VALUES(?,?)",(cid,cn)) if not cr else None
                    if not dbq("SELECT 1 FROM book_categories WHERE book_id=?",(b['id'],)):
                        dbe("INSERT INTO book_categories(book_id,category_id) VALUES(?,?)",(b['id'],cid))
                    sn=result.get("subcategory")
                    sid=None
                    if sn:
                        sr=dbq("SELECT id FROM categories WHERE name=? AND parent_id=?",(sn,cid))
                        if sr: sid=sr[0]['id']
                        else:
                            sid=str(uuid.uuid4()); dbe("INSERT INTO categories(id,name,parent_id) VALUES(?,?,?)",(sid,sn,cid))
                    if sid:
                        dbe("UPDATE book_categories SET subcategory_id=? WHERE book_id=?",(sid,b['id']))
                    for tn in result.get("tags",[]):
                        tr=dbq("SELECT id FROM tags WHERE name=?",(tn,))
                        tid=tr[0]['id'] if tr else str(uuid.uuid4()); dbe("INSERT INTO tags(id,name) VALUES(?,?)",(tid,tn)) if not tr else None
                        dbe("INSERT OR IGNORE INTO book_tags(book_id,tag_id) VALUES(?,?)",(b['id'],tid))
                    if result.get("difficulty"): dbe("UPDATE books SET difficulty=? WHERE id=? AND difficulty IS NULL",(result["difficulty"],b['id']))
                    rv["done"]+=1; _task_status['cr_r']=rv; _mark('classify', b['id'], 'done')
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
            books=dbq("SELECT b.id,b.title,t.text_content FROM books b JOIN book_text t ON t.id=b.id WHERE b.status='active' AND b.summary IS NULL AND b.text_extracted=1 LIMIT ?",(int(count),))
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
                        rv["done"]+=1; _task_status['sr_r']=rv; _mark('summarize', b['id'], 'done')
                except Exception as e: print(f"[摘要异常] {b['title'][:30]}: {type(e).__name__}: {e}",flush=True)
            _task_status['sr_r']=rv
        finally:
            _task_status['sr']=False
            _count_cache["time"] = 0
    threading.Thread(target=w,daemon=True).start()
    return {"status":"started"}

# ==================== 在线元数据补全（功能化整合，零依赖 urllib） ====================
def _clean_title(t):
    """清洗书名噪声用于相似度比对，避免‘全集/套装/插图版’等干扰匹配。"""
    import re
    t = (t or "").strip()
    t = re.sub(r"[（(][^（）()]*[)）]", " ", t)
    t = re.sub(r"[【\[][^】\]]*[\]\]]", " ", t)
    for w in ("套装","全集","合集","选集","作品集","典藏","精装","珍藏","插图版","图文版","彩图版",
              "修订版","增订版","校订版","注释版","译注版","典藏版","完整版","未删减","全本",
              "上下册","上中下册","新版","原版","正版","畅销","文库","丛书","系列"):
        t = t.replace(w, " ")
    return t.strip()

def _sim(a, b):
    import difflib
    return difflib.SequenceMatcher(None, _clean_title(a), _clean_title(b)).ratio()

def _http_get_text(url, timeout=8, max_bytes=None):
    """标准库 urllib 发 GET 返回文本（用于 HTML 页面，如豆瓣详情页）。失败抛异常。
    max_bytes: 限制读取字节数，用于大页面只取头部元数据（出版社/ISBN/简介均在前部），
    避免慢速连接下整页下载过久拖垮批量补全。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9"})
    proxy = _proxy_handler(url)
    opener = urllib.request.build_opener(proxy)
    with opener.open(req, timeout=timeout) as r:
        data = r.read(max_bytes) if max_bytes else r.read()
        return data.decode("utf-8", "ignore")


# 书名后缀/修饰词，检索时应剥离以提高 subject_suggest 命中率
_TITLE_SUFFIX = r'(丛书|全集|套书|套装|上下册|上册|下册|卷[一二三四五六七八九十百]+|第[0-9一二三四五六七八九十百]+版|含目录|扫描版|精装|修订版|增补版|译著|校订|注释|导读|图说|图鉴|简明|新版|影印|标点|校注|（中）|（上）|（下）)'

# 促销/来源废话起始词：出现即截断主书名（仅当不在标题最开头，避免误切真书名如“畅销书写作”）
_TITLE_PROMO_CUT = ['英国大使馆', '美国大使馆', '官方微博', '活动用书', '豆瓣高分']

def normalize_title(title):
    """清洗导入残留的脏标题为「可匹配主书名」，仅用于在线元数据检索，绝不改原 title。
    策略（保守、可回滚：仅加列、不覆盖 title；清洗过度则回退原标题）：
      1) 剥来源/镜像站点标记（Z-Library / z-lib.org/.sk / 1lib.sk / libgen / b-ok / bookzz 及裸标）；
      2) 括号内整段镜像域名列表（如 (z-library.sk, 1lib.sk, z-lib.sk)）；
      3) 前缀随机数字ID（≥5位，避开4位年份区间如1949-1952）；
      3b) 开头序号数字紧贴中文（如 27想象的→想象的）；
      4) 迭代剥括号内作者/译者/制作/丛书/年份（处理嵌套括号）；
      5) 去【…】促销括号（任意长度）及国籍标记【美】/【英】…、[美]/[英]…；
      6) 截断首个未闭合【及其后促销内容；
      7) 去尾部无闭合括号残留；
      8) 去 " by 作者" 英文作者后缀（含 [国籍]，直到行尾/括号/来源描述）；
      9) = 截断取中文主书名（左侧含≥2汉字时，去掉英文/拼音副书名）；
     10) 删连续≥2个拉丁词的拼音/纯英文噪音块（如 "Wen ge qian de ..."）；
     11) 去文件扩展名（.pdf/.epub/.mobi…）；
     12) 去 "-出版社/引进/出版/译丛/丛书" 等来源描述；
     13) 在首个促销起始词处截断主书名（仅非开头）；
     14) 压缩空格、去首尾标点；空则回退原标题。"""
    t = (title or '').strip()
    if not t:
        return t
    # 1) 括号内整段镜像域名列表（先删，避免裸标规则破坏结构）： (z-library.sk, 1lib.sk, z-lib.sk)
    t = _re_mod.sub(r'(?i)[\(（][^（）()]*?(?:z-?lib|1lib|b-?ok|bookzz|zlibrary|libgen)[^（）()]*?[）)]', '', t)
    # 2) 来源/站点标记（含括号与裸标）
    t = _re_mod.sub(r'(?i)\s*[\(（]?(?:Z-?Library|z-?lib(?:\.org|\.sk)?|1lib\.sk|libgen|b-?ok|bookzz|bok\.cc|z-lib)[\)）]?', '', t)
    t = t.strip()
    # 3) 前缀随机数字ID（≥5位，避开"1949-1952"这类4位年份区间）：3202915_ / 123456-
    t = _re_mod.sub(r'^\d{5,}[_\.\-]?\s*', '', t)
    # 3b) 开头序号（27想象的→想象的；排除 4位+连字符年份区间如 1949-1952）
    t = _re_mod.sub(r'^(?!\d{4}[-—–])\d{1,4}(?=[^\d])', '', t)
    # 4) 迭代剥括号（处理嵌套）：括号内多为作者/译者/丛书/年份/版次
    for _ in range(6):
        new = _re_mod.sub(r'[（(][^（）()]*[）)]', '', t)
        if new == t:
            break
        t = new
    # 5) 【…】促销括号（任意长度）
    t = _re_mod.sub(r'【[^】]*】', '', t)
    # 5b) 国籍标记 【美】/【英】… 及 [美]/[英]…（不在括号内时）
    t = _re_mod.sub(r'[【\[](?:美|英|法|日|德|加|澳|俄|意|西|韩|中|台)[】\]]', '', t)
    # 6) 截断首个未闭合【（其后皆为促销）
    _bi = t.find('【')
    if _bi >= 0:
        t = t[:_bi]
    # 7) 尾部无闭合括号残留：(... 或 （...
    t = _re_mod.sub(r'[（(][^）)]*$', '', t)
    # 8) " by 作者" 英文作者后缀（含 [国籍]，直到行尾 / 括号 / 来源描述）
    t = _re_mod.sub(r'\s+by\s+[^（）()]*?(?=[（(]|$|\s*[-—–]\s*(?:出版社|出版|引进|出品))', '', t, flags=_re_mod.I)
    t = _re_mod.sub(r'\s+by\s+.+$', '', t, flags=_re_mod.I)
    # 9) = 截断取中文主书名（左侧含≥2汉字时）
    _eq = t.find(' = ')
    if _eq < 0:
        _eq = t.find('＝')
    if _eq >= 0:
        _left = t[:_eq].strip()
        if _left and sum(1 for c in _left if '\u4e00' <= c <= '\u9fff') >= 2:
            t = _left
    # 10) 删连续≥2个拉丁词的拼音/纯英文噪音块（如 "Wen ge qian de Deng Xiaoping ..."）
    t = _re_mod.sub(r'(?i)\s*\b[A-Za-z]+(?:[.\-][A-Za-z0-9]+)*\b(?:\s+[A-Za-z]+(?:[.\-][A-Za-z0-9]+)*\b){1,}', '', t)
    # 11) 文件扩展名
    t = _re_mod.sub(r'\.(pdf|epub|mobi|azw3?|txt|djvu?|chm|docx?|fb2|rtf|zip|rar|7z)\s*$', '', t, flags=_re_mod.I)
    # 12) 来源描述： -出版社/引进/出版/译丛/丛书（连同其后非标点残留一并清）
    t = _re_mod.sub(r'\s*[-—–]\s*.*?(?:出版社|出版公司|引进|出品|出品方|译丛|丛书)[^，。、（）()]*', '', t)
    # 13) 在首个促销起始词处截断（仅当该词不在标题最开头，避免误切真书名）
    for _kw in _TITLE_PROMO_CUT:
        _j = t.find(_kw)
        if _j > 1:
            t = t[:_j]
            break
    # 14) 收尾：压缩空格、去首尾标点
    t = _re_mod.sub(r'\s{2,}', ' ', t).strip()
    t = t.strip(' .,，-—–、:：()（）[]【】=-')
    if not t:
        return (title or '').strip()  # 清洗过度则回退原标题
    return t


# ===== 书名规则化：重算写回（工具中心「重算写回」按钮调用）=====
_tn_rec = {"running": False, "done": 0, "total": 0, "error": ""}

def _title_norm_recompute():
    """重算全部书的 normalized_title（基于当前 title 套用 normalize_title），写回库但不改原 title。
    后台线程执行，避免阻塞请求；修复书名被元数据补全更新后的旧值漂移（如 33 本反转坏数据）。"""
    global _tn_rec
    if _tn_rec["running"]:
        return {"ok": False, "msg": "已在运行中，请稍候"}
    rows = dbq("SELECT id, title FROM books")
    total = len(rows)
    _tn_rec = {"running": True, "done": 0, "total": total, "error": ""}
    def _worker():
        global _tn_rec
        conn = sqlite3.connect(DB, timeout=30)
        try:
            cur = conn.cursor()
            for i, r in enumerate(rows):
                bid = r["id"]; t = r["title"] or ""
                cur.execute("UPDATE books SET normalized_title=? WHERE id=?", (normalize_title(t), bid))
                if (i+1) % 2000 == 0:
                    conn.commit(); _tn_rec["done"] = i+1
            conn.commit(); _tn_rec["done"] = total
        except Exception as e:
            _tn_rec["error"] = str(e)
            try: conn.commit()
            except Exception: pass
        finally:
            conn.close()
            _tn_rec["running"] = False
    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "msg": f"已启动，共 {total} 本，后台重算中"}

def _title_norm_recompute_status():
    return dict(_tn_rec)


# —— 假摘要识别（与 tools/summary_fix.py 同源，供工具中心/统计页展示待修数）——
_FAKE_START = ("由于", "抱歉", "（以下", "(以下", "您好", "你好", "（注", "注：",
               "根据您", "根据提供", "我将")
_FAKE_MID = ("内容为空白", "提供的内容为空", "提供的内容为空白", "内容为空", "内容有限",
             "内容未知", "未提供", "无法获取", "无法访问", "空白", "占位", "示例摘要",
             "示例文本", "我将根据", "假设的内容", "虚构的内容", "假设性的框架",
             "假设一个虚构", "根据一般图书摘要", "根据常见图书摘要", "帮助您理解如何生成",
             "假设示例", "示例书籍摘要", "未知的书籍")
_FAKE_EXACT = ("由于提供的内容为空白", "由于提供的书籍内容为空白",
               "根据模板结构给出一个示例", "我将根据虚构的内容来生成",
               "基于一个假设的框架来生成摘要", "根据一般图书摘要的结构给出一个示例",
               "由于提供的书籍内容为空，我将基于一个假设的示例")


def _is_fake_summary(s):
    if not s:
        return False
    s = s.strip()
    if len(s) < 8:
        return False
    if s.startswith(_FAKE_START) and any(m in s[:160] for m in _FAKE_MID):
        return True
    if any(m in s for m in _FAKE_EXACT):
        return True
    return False


def _summary_fix_pending():
    """统计待修复的假摘要/短摘要数（供工具中心与统计页展示）。"""
    n = 0; has_text = 0; no_text = 0
    rows = dbq("SELECT id,summary FROM books WHERE LENGTH(COALESCE(summary,''))>0")
    for r in rows:
        if not _is_fake_summary(r['summary']):
            continue
        n += 1
        t = dbq("SELECT text_content FROM book_text WHERE id=?", [r['id']])
        if t and t[0]['text_content'] and len(t[0]['text_content'].strip()) >= 50:
            has_text += 1
        else:
            no_text += 1
    return {"pending": n, "has_text": has_text, "no_text": no_text}


def _title_query_variants(title):
    """生成多个检索变体：先 normalize_title 清洗 → 主标题(含汉字最多的空白段) → 去后缀 → 取前N字。
    subject_suggest 是书名前缀匹配接口，对长书名/丛书后缀极挑剔，多变体逐一尝试可大幅提升命中。"""
    t = normalize_title(title)
    if not t:
        t = (title or '').strip()
    # 按空白分段后取含汉字最多的段作主书名，避免年代/数字前缀抢首段
    _segs = [s.strip() for s in _re_mod.split(r'\s+', t)]
    _segs = [s for s in _segs if s]
    def _chc(s): return sum(1 for c in s if '\u4e00' <= c <= '\u9fff')
    _segs_sorted = sorted(_segs, key=_chc, reverse=True)
    head = _segs_sorted[0] if _segs_sorted else t
    vs = [t, head]
    t2 = _re_mod.sub(_TITLE_SUFFIX + r'$', '', head).strip()
    if t2 and t2 != head:
        vs.append(t2)
    for n in (14, 12, 10, 8, 6, 4):
        if len(head) >= n:
            vs.append(head[:n])
    seen = set(); out = []
    for x in vs:
        x = x.strip()
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out

def _douban_meta(title, author=None, isbn=None):
    """豆瓣中文书元数据：subject_suggest 多变体检索 + 详情页解析出版社/出版年/ISBN/简介。
    返回标准 result dict（含 trusted 信任标志）或 None。中文书命中率远高于 Open Library/Google，作为最高优先级源。"""
    best = None; best_sim = -1.0; matched_v = None
    if isbn:
        try:
            sug = _http_get_json("https://book.douban.com/j/subject_suggest?q=" + urllib.parse.quote(isbn), timeout=5)
            if isinstance(sug, list):
                for it in sug:
                    if it.get("isbn") and it["isbn"].replace("-", "") == isbn.replace("-", ""):
                        best = it; best_sim = 1.0; matched_v = isbn; break
        except Exception as e:
            print(f"[豆瓣ISBN检索失败] {title[:24]}: {e}", flush=True)
    if not best:
        for v in _title_query_variants(title):
            try:
                sug = _http_get_json("https://book.douban.com/j/subject_suggest?q=" + urllib.parse.quote(v), timeout=5)
            except Exception as e:
                print(f"[豆瓣检索失败] {title[:24]}: {e}", flush=True); continue
            if not isinstance(sug, list) or not sug:
                continue
            for it in sug:
                sm = _sim(v, it.get("title", ""))
                if sm > best_sim:
                    best_sim = sm; best = it; matched_v = v
            break  # 第一个有结果的变体即采用
    if not best:
        return None
    hid = best.get("id")
    if not hid:
        return None
    # 详情页可能超时（豆瓣对本机 IP 限速，book.douban.com 详情页下载极慢），
    # 先基于 suggest 结果构造兜底（含年份/ISBN），详情页成功则覆盖更全字段。
    pub = ""
    yr_text = (best.get("year") or "").strip()
    isbn_from_sug = best.get("isbn") or ""
    desc = ""
    try:
        h = _http_get_text("https://book.douban.com/subject/%s/" % hid, timeout=10, max_bytes=250000)
        pub_m = _re_mod.search(r'出版社:</span>\s*<a[^>]*>([^<]+)</a>', h)
        pub_m2 = _re_mod.search(r'出版社:</span>\s*([^<\n]+)', h)
        pub = pub_m.group(1).strip() if pub_m else (pub_m2.group(1).strip() if pub_m2 else "")
        yr = _re_mod.search(r'出版年:</span>\s*([^<\n]+)', h)
        if yr:
            yr_text = yr.group(1).strip()
        isbn_r = _re_mod.search(r'ISBN:</span>\s*([^<\n]+)', h)
        if isbn_r:
            isbn_from_sug = isbn_r.group(1).strip()
        intro = _re_mod.search(r'<div class="intro">\s*(.*?)</div>', h, _re_mod.S)
        desc = _re_mod.sub(r'<[^>]+>', '', intro.group(1)).strip() if intro else ""
    except Exception as e:
        print(f"[豆瓣详情失败·用suggest兜底] {title[:24]}: {e}", flush=True)
    is_isbn_hit = bool(isbn and best.get("isbn") and best["isbn"].replace("-", "") == isbn.replace("-", ""))
    bt = best.get("title", "")
    # 信任判定：ISBN 命中 / 变体与返回书名互含 / 高相似度（避免短词模糊错配）
    trusted = is_isbn_hit or (matched_v and (matched_v in bt or bt in matched_v)) or best_sim >= 0.6
    sim = 1.0 if is_isbn_hit else best_sim
    return {
        "publisher": pub,
        "publish_date": yr_text,
        "isbn": isbn_from_sug,
        "language": "zh",
        "description": desc[:2000],
        "source": "douban",
        "sim": sim,
        "trusted": trusted,
    }


# 豆瓣为国内站点，强制直连（国际代理会让其失败）；Open Library / Google Books 走代理（如有）。
_DIRECT_DOMAINS = ("book.douban.com", "douban.com", "localhost", "127.0.0.1")

def _proxy_handler(url=None):
    """域名分流代理：豆瓣等国内站/本机强制直连；Open Library / Google Books 走 LIB_PROXY 或系统代理（如有），否则直连。
    修复要点：配置 LIB_PROXY 国际代理时，豆瓣不再被误路由→直连必通；OL/Google 仍走代理以提升英文书覆盖。"""
    host = ""
    if url:
        try:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
    if host and any(host == d or host.endswith("." + d) for d in _DIRECT_DOMAINS):
        return urllib.request.ProxyHandler({})  # 直连，绕开任何代理
    p = os.environ.get("LIB_PROXY")
    if p:
        return urllib.request.ProxyHandler({"http": p, "https": p})
    return urllib.request.ProxyHandler(urllib.request.getproxies())


def _http_get_json(url, timeout=5):
    """标准库 urllib 发 GET，自动读取 HTTP_PROXY/HTTPS_PROXY 环境变量（复用 git 代理）。失败抛出异常（由调用方按场景处理）。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PrivateLib)"})
    proxy = _proxy_handler(url)
    opener = urllib.request.build_opener(proxy)
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))

_google_cooldown_until = 0.0  # Google Books 命中 429 后的冷却时间戳，避免共享 IP 连环限流

def fetch_online_metadata(title, author=None, isbn=None, normalized_title=None):
    """在线补全单本书元数据（豆瓣优先 + Open Library/Google Books 兜底，均无需 key）。
    返回 dict: {publisher,publish_date,isbn,language,description,source,sim} 或 None。
    仅用于填空字段；sim 为书名相似度，ISBN 命中时置 1.0。
    说明：优先用已清洗的 normalized_title 作为检索查询（与预览一致、避免重复清洗）；
    未配置 LIB_PROXY 国际代理时，Open Library/Google Books 在国内直连必超时，故跳过它们，
    Douban 中文书直连即可，大幅提升批量速度。"""
    global _google_cooldown_until
    if not ENABLE_ONLINE_METADATA:
        return None
    # 优先用已清洗的 normalized_title 作为检索查询
    q = (normalized_title or "").strip() or (title or "").strip()
    if not q and not isbn:
        return None
    result = None
    best_sim = 0.0
    # 0) 豆瓣（中文书最高优先级；覆盖出版社/出版年/ISBN/简介，命中率高）
    try:
        dm = _douban_meta(q, author, isbn)
        if dm and dm.get("sim", 0) >= 0.5:
            result = dm
    except Exception as e:
        print(f"[豆瓣失败] {q[:30]}: {e}", flush=True)
    # 1) Open Library（英文/知名书补充源；仅在配置了 LIB_PROXY 国际代理时尝试，否则国内直连必超时）
    _have_proxy = bool(os.environ.get("LIB_PROXY"))
    try:
        ol = None
        if _have_proxy:
            if isbn:
                ol = _http_get_json("https://openlibrary.org/isbn/%s.json?jscmd=details&format=json" % isbn.replace("-",""), timeout=5)
                best_sim = 1.0
            if not ol and q:
                s = _http_get_json("https://openlibrary.org/search.json?title=" + urllib.parse.quote(q)
                                   + ("&author=" + urllib.parse.quote(author) if author else "") + "&limit=5", timeout=5)
                docs = (s or {}).get("docs", [])
                if docs:
                    best = None; bs = 0.0
                    for d in docs:
                        sm = _sim(q, d.get("title",""))
                        if sm > bs: bs = sm; best = d
                    best_sim = bs
                    if best:
                        ol = best
                        if str(best.get("key","")).startswith("/works/"):
                            wk = _http_get_json("https://openlibrary.org" + best["key"] + ".json", timeout=5)
                            if wk and isinstance(wk.get("description"), str):
                                ol = dict(ol); ol["_desc"] = wk["description"]
                            elif wk and isinstance(wk.get("description"), dict):
                                ol = dict(ol); ol["_desc"] = wk["description"].get("value","")
        else:
            print(f"[OL跳过] 未配置 LIB_PROXY，跳过 Open Library（国内直连超时）: {q[:24]}", flush=True)
        if ol:
            pub = ol.get("publishers")
            pub = pub[0] if isinstance(pub, list) and pub else ""
            pd = ol.get("first_publish_year") or (ol.get("publish_date") if isinstance(ol.get("publish_date"), str) else "")
            il = ol.get("isbn") if isinstance(ol.get("isbn"), list) else []
            isbn2 = il[0] if il else ""
            ll = ol.get("language") if isinstance(ol.get("language"), list) else []
            lang = ll[0] if ll else ""
            desc = ol.get("_desc") or (ol.get("description") if isinstance(ol.get("description"), str) else "")
            if isinstance(desc, dict): desc = desc.get("value","")
            if not result:
                result = {"publisher": pub or "", "publish_date": str(pd) if pd else "",
                          "isbn": isbn2 or "", "language": lang or "",
                          "description": (desc or "")[:2000], "source": "openlibrary", "sim": best_sim}
            else:
                # 以豆瓣为主，Open Library 仅补全缺失字段
                if not result.get("publisher"): result["publisher"] = pub or ""
                if not result.get("publish_date"): result["publish_date"] = str(pd) if pd else ""
                if not result.get("isbn"): result["isbn"] = isbn2 or ""
                if not result.get("language"): result["language"] = lang or ""
                if not result.get("description"): result["description"] = (desc or "")[:2000]
                if best_sim > result.get("sim", 0): result["sim"] = best_sim
    except Exception as e:
        print(f"[OL失败] {title[:30]}: {e}", flush=True)
    # 2) Google Books 兜底（仅在配置了 LIB_PROXY 时调用；未配置代理则直连超时，直接跳过）
    try:
        need_google = (not result) or (not result.get("description")) or (q and best_sim < 0.7)
        if _have_proxy and need_google and time.time() > _google_cooldown_until:
            gq = q + (" " + author if author else "")
            g = _http_get_json("https://www.googleapis.com/books/v1/volumes?q=" + urllib.parse.quote(gq) + "&maxResults=5", timeout=5)
            items = (g or {}).get("items", [])
            if items:
                vi = items[0].get("volumeInfo", {})
                gdesc = vi.get("description","")
                gsim = _sim(q, vi.get("title",""))
                if (not result) or (gdesc and not result.get("description")) or (gsim > result.get("sim",0)):
                    merged = dict(result) if result else {}
                    gis = ""; ids = vi.get("industryIdentifiers", [])
                    for i in ids:
                        if i.get("type") in ("ISBN_13","ISBN_10"): gis = i.get("identifier",""); break
                    merged.update({
                        "publisher": vi.get("publisher","") or merged.get("publisher",""),
                        "publish_date": vi.get("publishedDate","") or merged.get("publish_date",""),
                        "isbn": gis or merged.get("isbn",""),
                        "language": vi.get("language","") or merged.get("language",""),
                        "description": gdesc or merged.get("description",""),
                        "source": "googlebooks",
                        "sim": max(gsim, merged.get("sim",0)),
                    })
                    merged["description"] = (merged["description"] or "")[:2000]
                    result = merged
    except Exception as e:
        msg = str(e)
        if "429" in msg:
            _google_cooldown_until = time.time() + 120  # 命中限流，冷却 2 分钟，期间跳过 Google
            print(f"[GB 429 冷却] {title[:20]}: 2分钟内跳过 Google", flush=True)
        else:
            print(f"[GB失败] {title[:30]}: {e}", flush=True)
    return result

def _fetch_meta_timeout(title, author, isbn, normalized_title=None, timeout=15):
    """在独立线程里跑 fetch_online_metadata，硬性超时返回 None，避免外部 API 挂死拖垮整批。"""
    box = {}
    def _run():
        try:
            box['v'] = fetch_online_metadata(title, author, isbn, normalized_title=normalized_title)
        except Exception as e:
            print(f"[元数据线程异常] {title[:24]}: {type(e).__name__}: {e}", flush=True)
            box['v'] = None
    th = threading.Thread(target=_run, daemon=True); th.start()
    th.join(timeout)
    if th.is_alive():
        print(f"[元数据硬超时跳过] {title[:24]}", flush=True)
        return None
    return box.get('v')

def run_metadata_async(count=None):
    """异步批量补全在线元数据。count=None 表示全库扫描（默认回填存量）。
    仅填空字段、按相似度阈值防错配、限速、受 ENABLE_ONLINE_METADATA 开关控制。"""
    if _task_status.get('mr'): return {"status":"running"}
    if not ENABLE_ONLINE_METADATA:
        return {"status":"disabled", "msg":"在线元数据未启用（设置环境变量 LIB_METADATA_ONLINE=1 后重启服务）"}
    _task_status['mr'] = True
    _task_status['mr_r'] = {"done":0,"total":0,"filled":0,"skipped":0}
    def w():
        try:
            sql = ("SELECT b.id,b.title,b.publisher,b.isbn,b.language,b.description,"
                   "MAX(a.name) AS author FROM books b "
                   "LEFT JOIN book_authors ba ON ba.book_id=b.id "
                   "LEFT JOIN authors a ON a.id=ba.author_id "
                   "WHERE b.status='active' AND (b.publisher IS NULL OR b.publisher='') "
                   "AND (b.isbn IS NULL OR b.isbn='') AND (b.description IS NULL OR b.description='') "
                   "GROUP BY b.id")
            if count:
                sql += " LIMIT %d" % int(count)
            books = dbq(sql)
            rv = {"done":0,"total":len(books),"filled":0,"skipped":0}
            for b in books:
                try:
                    meta = _fetch_meta_timeout(b['title'], b.get('author'), b.get('isbn'), normalized_title=b.get('normalized_title'))
                    if meta:
                        sim = meta.get("sim", 0)
                        isbn_match = bool(b.get('isbn')) and meta.get("isbn") and b['isbn'].replace("-","")==meta["isbn"].replace("-","")
                        trusted = bool(meta.get("trusted")) or isbn_match or sim >= 0.7 or (sim >= 0.55 and meta.get("description")) or (sim >= 0.6 and meta.get("publisher"))
                        if trusted:
                            sets = []; params = []
                            for col in ("publisher","publish_date","isbn","language","description"):
                                v = (meta.get(col) or "").strip()
                                if v:
                                    sets.append(col + "=?"); params.append(v[:2000] if col=="description" else v)
                            if sets:
                                sets.append("metadata_source=?"); params.append(meta.get("source",""))
                                sets.append("metadata_conf=?"); params.append(round(sim,2))
                                params.append(b['id'])
                                dbe("UPDATE books SET " + ", ".join(sets) + " WHERE id=?", params)
                                rv["filled"] += 1
                        else:
                            rv["skipped"] += 1
                            print(f"[元数据低置信跳过] {b['title'][:30]}: sim={sim:.2f}", flush=True)
                    else:
                        rv["skipped"] += 1
                    rv["done"] += 1; _task_status['mr_r'] = rv; _mark('metadata', b['id'], 'done')
                    time.sleep(0.6)
                except Exception as e:
                    print(f"[元数据异常] {b['title'][:30]}: {type(e).__name__}: {e}", flush=True)
                    rv["done"] += 1; _task_status['mr_r'] = rv; _mark('metadata', b['id'], 'skip')
            _task_status['mr_r'] = rv
        finally:
            _task_status['mr'] = False
            _count_cache["time"] = 0
    threading.Thread(target=w, daemon=True).start()
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
            _mark('transcribe', m['id'], 'done')
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
            _mark('media_summarize', m['id'], 'done')
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
            # 导入完成后自动补全在线元数据（仅开关开启且当前无任务时）
            if ENABLE_ONLINE_METADATA and not _task_status.get('mr'):
                try: run_metadata_async(None)
                except Exception as e: print(f"[导入后自动元数据失败] {e}", flush=True)
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
            if path == "/api/metadata-batch": self.json(run_metadata_async(data.get('count') or None)); return
            if path == "/api/extract-batch": self.json(run_extract_async(data.get('count',10))); return
            if path == "/api/extract-ocr": self.json(run_extract_ocr_async()); return
            if path == "/api/extract-ocr/status": self.json(_task_status.get('eor_r', {"running":False,"done":0,"total":0})); return
            # 媒体转录/摘要 20260801
            if path == "/api/media/transcribe": self.json(run_transcribe_async(data.get('count',10), data.get('media_type','all'))); return
            if path == "/api/media/summarize": self.json(run_media_summarize_async(data.get('count',10))); return
            if path == "/api/media/transcribe-one": self.json(run_transcribe_one_async(data.get('media_id',''))); return
            if path == "/api/tools/run": self.json(_tool_run(data)); return
            if path == "/api/title-norm/recompute": self.json(_title_norm_recompute()); return
            if path == "/api/title-norm/adopt":
                ids = (data or {}).get("ids", [])
                adopted = skipped = 0
                if ids:
                    conn = sqlite3.connect(DB, timeout=30); cur = conn.cursor()
                    for bid in ids:
                        try:
                            bid = str(bid).strip()
                            cur.execute("SELECT title FROM books WHERE id=?", (bid,))
                            row = cur.fetchone()
                            if not row: skipped += 1; continue
                            t = row[0] or ""
                            nt = normalize_title(t)
                            if not nt or nt.startswith("upload_") or nt == (t or "").strip():
                                skipped += 1; continue
                            cur.execute("UPDATE books SET title=?, normalized_title=? WHERE id=?", (nt, nt, bid))
                            adopted += 1
                        except Exception:
                            skipped += 1
                    conn.commit(); conn.close()
                self.json({"adopted": adopted, "skipped": skipped}); return
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
            # P2-A 阅读笔记 CRUD
            if path.startswith("/api/books/") and path.endswith("/note"):
                bid=path.split("/")[3]; act=data.get('action','add')
                if act=='add':
                    note=(data.get('note','') or '').strip()
                    if not note: self.json({"error":"note empty"}); return
                    nid=str(uuid.uuid4()); pg=int(data.get('page',0) or 0)
                    dbe("INSERT INTO reading_notes(id,book_id,note,page,created_at,updated_at) VALUES(?,?,?,?,datetime('now'),datetime('now'))",(nid,bid,note,pg))
                    self.json({"ok":True,"id":nid}); return
                if act=='delete':
                    dbe("DELETE FROM reading_notes WHERE id=? AND book_id=?",(data.get('id',''),bid))
                    self.json({"ok":True}); return
                if act=='update':
                    dbe("UPDATE reading_notes SET note=?,page=?,updated_at=datetime('now') WHERE id=? AND book_id=?",((data.get('note','') or '').strip(),int(data.get('page',0) or 0),data.get('id',''),bid))
                    self.json({"ok":True}); return
                self.json({"error":"unknown action"}); return
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

            # P0 阅读进度：记录 未读/在读/读完 + 当前页
            if path == "/api/progress":
                bid=data.get('id',''); st=data.get('status','reading'); pg=int(data.get('page',0) or 0)
                if bid and st in ('unread','reading','finished'):
                    dbe("UPDATE books SET reading_status=?, last_page=?, last_read_at=datetime('now') WHERE id=?",(st, pg, bid))
                    self.json({"ok":True}); return
                self.json({"error":"invalid"}); return
            # P0 智能书架：保存当前筛选组合
            if path == "/api/shelves":
                name=(data.get('name','') or '').strip()
                if not name: self.json({"error":"name empty"}); return
                sid=str(uuid.uuid4())
                dbe("INSERT INTO shelves(id,name,q,cat,sub,fmt,diff,rstat,author,tags,year) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, name, data.get('q','') or '', data.get('cat','') or '', data.get('sub','') or '',
                     data.get('fmt','') or '', data.get('diff','') or '', data.get('rstat','') or '',
                     data.get('author','') or '', data.get('tags','') or '', data.get('year','') or ''))
                self.json({"ok":True,"id":sid}); return
            if path == "/api/shelves/delete":
                dbe("DELETE FROM shelves WHERE id=?",(data.get('id',''),))
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
            elif path=="/api/tools/status": self.json(_tool_status())
            elif path=="/api/task-status": self.json({"classify":_task_status.get('cr_r',{}),"summarize":_task_status.get('sr_r',{}),"extract":_task_status.get('er_r',{}),"transcribe":_task_status.get('tr_r',{}),"media_summarize":_task_status.get('ms_r',{}),"scan_import":_task_status.get('ir_r',{}),"metadata":_task_status.get('mr_r',{})})
            elif path=="/api/title-norm/recompute-status": self.json(_title_norm_recompute_status()); return
            elif path=="/api/stats": self.json(_lib_stats()); return
            elif path=="/api/summary-fix/pending": self.json(_summary_fix_pending()); return
            elif path.startswith("/api/books/") and path.endswith("/notes"):
                bid=path.split("/")[3]
                rows=dbq("SELECT id,note,page,created_at FROM reading_notes WHERE book_id=? ORDER BY created_at DESC",(bid,))
                self.json([dict(r) for r in rows]); return

            elif path.startswith("/api/books/") and path.endswith("/read"):
                bid=path.split("/")[3]
                r=dbq("SELECT file_path,file_format,title FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp,fmt,title=_resolve_path(r[0]['file_path']),r[0]['file_format'],r[0]['title']
                if not os.path.exists(fp): self.send_error(404); return
                if fmt=='epub':
                    _pr = dbq("SELECT last_page FROM books WHERE id=?",(bid,))
                    _start = int(_pr[0]['last_page']) if (_pr and _pr[0]['last_page']) else 0
                    viewer = '''<!DOCTYPE html><html><head><meta charset=utf-8>
<meta name="color-scheme" content="light only">
<title>__TITLE__</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:#fff;color:#222;font-family:system-ui,'Segoe UI',sans-serif}
#toolbar{position:fixed;top:0;left:0;right:0;height:48px;display:flex;align-items:center;gap:8px;padding:0 12px;background:#20232a;color:#fff;z-index:10}
#toolbar button,#toolbar select{background:#3a3f4b;color:#fff;border:none;border-radius:6px;padding:6px 10px;cursor:pointer;font-size:13px}
#toolbar button:hover,#toolbar select:hover{background:#4a5160}
#content{position:fixed;top:48px;left:0;right:0;bottom:0;overflow:auto;padding:24px;max-width:900px;margin:0 auto;line-height:1.9;font-size:18px}
#content img{max-width:100%}
.spacer{flex:1}
.prog{font-size:12px;color:#bbb}
</style></head><body>
<div id="toolbar">
<button onclick="prev()">◀ 上一章</button>
<button onclick="next()">下一章 ▶</button>
<select id="toc" onchange="show(this.value)"><option value="">☰ 目录</option></select>
<button onclick="decFont()">A−</button>
<button onclick="incFont()">A+</button>
<span class="spacer"></span>
<span class="prog" id="prog">…</span>
</div>
<div id="content"><p style="color:#888">加载中…</p></div>
<script>
var BOOK_ID="__BID__", START=__START__, chapters=[], assetMap={}, cur=0, fontSize=100;
function loadInfo(){
  fetch('/api/books/'+BOOK_ID+'/epub/info').then(function(r){return r.json();}).then(function(d){
    chapters=d.chapters;
    var sel=document.getElementById('toc');
    chapters.forEach(function(c){var o=document.createElement('option');o.value=c.i;o.textContent=(c.i+1)+'. '+(c.label||('第 '+(c.i+1)+' 节'));sel.appendChild(o);assetMap[encodeURIComponent(c.path)]=c.i;});
    cur=Math.max(0,Math.min(START,chapters.length-1));
    show(cur);
  }).catch(function(){document.getElementById('content').innerHTML='<p style="color:#c00">无法读取本书，请确认文件完好。</p>';});
}
function show(i){cur=parseInt(i);var box=document.getElementById('content');box.innerHTML='<p style="color:#888">加载中…</p>';
  fetch('/api/books/'+BOOK_ID+'/epub/chapter/'+cur).then(function(r){return r.text();}).then(function(h){
    box.innerHTML=h;applyFont();
    document.getElementById('toc').value=cur;
    document.getElementById('prog').textContent=(cur+1)+' / '+chapters.length;
    saveProgress(cur);
    box.scrollTop=0;
  });
}
function prev(){if(cur>0)show(cur-1);}
function next(){if(cur<chapters.length-1)show(cur+1);}
function applyFont(){document.getElementById('content').style.fontSize=fontSize+'%';}
function incFont(){fontSize=Math.min(fontSize+10,200);applyFont();}
function decFont(){fontSize=Math.max(fontSize-10,60);applyFont();}
function saveProgress(i){var x=new XMLHttpRequest();x.open('POST','/api/progress');x.setRequestHeader('Content-Type','application/json');x.send(JSON.stringify({id:BOOK_ID,status:'reading',page:i}));}
document.getElementById('content').addEventListener('click',function(e){var a=e.target.closest('a');if(!a)return;var h=a.getAttribute('href')||'';var k=h.indexOf('/epub/asset/');if(k>=0){e.preventDefault();var p=decodeURIComponent(h.substring(k+12));if(assetMap[p]!=null)show(assetMap[p]);}});
loadInfo();
</script>
</body></html>'''
                    viewer = viewer.replace('__BID__', bid).replace('__START__', str(_start)).replace('__TITLE__', he(title))
                    self.send_response(200)
                    self.send_header("Content-Type","text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(viewer.encode('utf-8'))
                    return
                elif fmt in ('rar','zip','7z'):
                    try:
                        files = list_archive_contents(fp)
                        if not files:
                            if fmt=='zip' and not SEVEN_ZIP:
                                note='⚠️ 该 ZIP 压缩包读取失败，请重试。'
                            elif not SEVEN_ZIP:
                                note='⚠️ 本机未安装 7-Zip，无法读取 RAR / 7z 压缩包。请到 https://7-zip.org 下载安装 7-Zip（默认路径 C:\\Program Files\\7-Zip\\7z.exe），重启服务后即可阅读。ZIP 压缩包无需 7-Zip。'
                            else:
                                note='压缩包内未识别到可读文件。'
                            h='<!DOCTYPE html><html><head><meta charset=utf-8><title>'+he(title)+'</title><style>body{max-width:760px;margin:0 auto;padding:40px 20px;font-family:sans-serif;color:#333;line-height:1.8}</style></head><body><h1>📦 '+he(title)+'</h1><div style="background:#fff3cd;padding:16px;border-radius:8px;color:#8a6d00">'+he(note)+'</div><p style="margin-top:16px"><a href="javascript:history.back()">← 返回</a></p></body></html>'
                            self._html(h); return
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
                            sz_str = str(round(sz/1048576,1))+'MB' if sz>1048576 else str(round(sz/1024))+'KB'
                            url = '/api/books/'+bid+'/archive/'+urllib.parse.quote(fn)
                            h+='<a class=fl href="'+url+'" target=_blank><span class=ic>'+ic+'</span><span class=nm>'+he(fn)+'</span><span class=sz>'+sz_str+'</span></a>'
                        h+='</body></html>'
                        self._html(h)
                    except Exception as e:
                        print(f"[RAR reader error] {e}", flush=True)
                        self.send_error(500, str(e))

                else:
                    r2=dbq("SELECT text_content FROM book_text WHERE id=?",(bid,))
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
            elif path.startswith("/api/books/") and path.endswith("/epub/info"):
                bid=path.split("/")[3]
                r=dbq("SELECT file_path,title FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp=_resolve_path(r[0]['file_path'])
                title,chapters=get_epub_data(fp)
                import json
                self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.end_headers()
                self.wfile.write(json.dumps({"title":(title or r[0]['title']),"chapters":[{"i":i,"label":(c[1] or ("第 %d 节"%(i+1))),"path":c[0]} for i,c in enumerate(chapters)],"total":len(chapters)},ensure_ascii=False).encode('utf-8'))
            elif path.startswith("/api/books/") and "/epub/chapter/" in path:
                bid=path.split("/")[3]
                try: idx=int(path.split("/epub/chapter/",1)[1])
                except Exception: idx=-1
                r=dbq("SELECT file_path FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp=_resolve_path(r[0]['file_path'])
                _,chapters=get_epub_data(fp)
                if idx<0 or idx>=len(chapters): self.send_error(404); return
                html=_epub_chapter_html(fp,chapters[idx][0],bid)
                self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.end_headers(); self.wfile.write(html.encode('utf-8'))
            elif path.startswith("/api/books/") and "/epub/asset/" in path:
                bid=path.split("/")[3]
                r=dbq("SELECT file_path FROM books WHERE id=?",(bid,))
                if not r: self.send_error(404); return
                fp=_resolve_path(r[0]['file_path'])
                zp=urllib.parse.unquote(path.split("/epub/asset/",1)[1])
                try:
                    zf=_zf_mod.ZipFile(fp); data=zf.read(zp); zf.close()
                except Exception:
                    self.send_error(404); return
                ext=os.path.splitext(zp)[1].lower()
                ct={'.xhtml':'application/xhtml+xml','.html':'text/html','.htm':'text/html','.css':'text/css','.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.gif':'image/gif','.svg':'image/svg+xml','.webp':'image/webp','.woff':'font/woff','.woff2':'font/woff2','.ttf':'font/ttf','.otf':'font/otf'}.get(ext,'application/octet-stream')
                self.send_response(200); self.send_header("Content-Type",ct); self.end_headers(); self.wfile.write(data)

            elif "/archive/" in path and path.startswith("/api/books/"):
                # 从压缩包中提取并服务单个文件: /api/books/<id>/archive/<filename>
                parts = path.split("/archive/", 1)
                bid = parts[0].split("/")[-1]
                inner_fn = urllib.parse.unquote(parts[1]) if len(parts) > 1 else ""
                r = dbq("SELECT file_path,file_format FROM books WHERE id=?", (bid,))
                if not r: self.send_error(404); return
                fp = _resolve_path(r[0]['file_path'])
                if not os.path.exists(fp): self.send_error(404); return
                # 提取到缓存目录（用系统临时目录，避免移动硬盘 ACL 损坏）
                cache_dir = os.path.join(tempfile.gettempdir(), "private_lib_archives", bid)
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
                        # P0 阅读进度：从 last_page 续读 + 翻页自动保存
                        _pr = dbq("SELECT reading_status,last_page FROM books WHERE id=?",(bid,))
                        _lp = _pr[0]['last_page'] if (_pr and _pr[0]['last_page']) else 1
                        viewer = viewer.replace(
                            "var pdfDoc=null,pageNum=1,pageRendering=false,pendingPage=null,scale=1.2;",
                            "var pdfDoc=null,pageNum=%d,BOOK_ID='%s',pageRendering=false,pendingPage=null,scale=1.2;\nvar _saveT=null;\nfunction saveProgress(p,st){if(_saveT)clearTimeout(_saveT);_saveT=setTimeout(function(){var x=new XMLHttpRequest();x.open('POST','/api/progress');x.setRequestHeader('Content-Type','application/json');x.send(JSON.stringify({id:BOOK_ID,status:st||'reading',page:p}));},800);}\n" % (_lp, bid))
                        viewer = viewer.replace("renderPage(1);", "renderPage(Math.min(%d,pdfDoc.numPages)||1);" % _lp)
                        viewer = viewer.replace("  document.getElementById('pageNum').value=n;", "  document.getElementById('pageNum').value=n;\n  saveProgress(n);")
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
            elif path.startswith("/epubjs/"):
                # Serve epub.js static files (epub.min.js + jszip.min.js)
                rel = path[8:]  # strip "/epubjs/" (8 chars)
                base = os.path.dirname(os.path.abspath(__file__))
                fp = os.path.join(base, "epubjs", rel)
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
        try: tn=dbq("SELECT COUNT(*) AS c FROM reading_notes")[0]['c']
        except Exception: tn=0
        pn=qs.get('p',['home'])[0]
        cat=qs.get('cat',[''])[0]; sub=qs.get('sub',[''])[0]
        nv=NAV.replace('{B}',str(tb)).replace('{M}',str(tm)).replace('{TREE}', build_cat_tree(cat, sub)).replace('{SHELVES}', build_shelves()).replace('{N}', str(tn))
        h='<!DOCTYPE html><html><head><meta charset=utf-8><title>我的图书馆</title><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+CSS+EXTRA_CSS+'</style></head><body>'+nv+'<div class="topbar"><button class="menu-btn" onclick="toggleNav()">☰</button><span>📚 我的图书馆</span></div><div class="overlay" onclick="toggleNav()"></div><main>'
        if pn=='books':
            q=qs.get('q',[''])[0];cat=qs.get('cat',[''])[0];sub=qs.get('sub',[''])[0];fmt=qs.get('fmt',[''])[0]
            diff=qs.get('diff',[''])[0];rstat=qs.get('rstat',[''])[0]
            author=qs.get('author',[''])[0];tags=qs.get('tags',[''])[0];year=qs.get('year',[''])[0]
            bp=int(qs.get('page',['1'])[0]);ps=85
            s="SELECT id,title,file_format,file_size,cover_path,reading_status,last_page FROM books WHERE status='active'";pa=[]
            if q:s+=" AND title LIKE ?";pa.append('%'+q+'%')
            if cat:s+=" AND id IN (SELECT book_id FROM book_categories WHERE category_id=?)";pa.append(cat)
            if sub:s+=" AND id IN (SELECT book_id FROM book_categories WHERE subcategory_id=?)";pa.append(sub)
            if fmt:s+=" AND file_format=?";pa.append(fmt)
            if diff:s+=" AND difficulty=?";pa.append(diff)
            if rstat:s+=" AND reading_status=?";pa.append(rstat)
            if author:s+=" AND id IN (SELECT book_id FROM book_authors ba JOIN authors a ON a.id=ba.author_id WHERE a.name LIKE ?)";pa.append('%'+author+'%')
            if tags:s+=" AND id IN (SELECT book_id FROM book_tags bt JOIN tags t ON t.id=bt.tag_id WHERE t.name LIKE ?)";pa.append('%'+tags+'%')
            if year:s+=" AND publish_date LIKE ?";pa.append(year+'%')
            total=dbq("SELECT count(*)as c FROM books WHERE "+s.split("WHERE",1)[1],tuple(pa))[0]['c']
            s+=" ORDER BY created_at DESC, title ASC LIMIT "+str(ps)+" OFFSET "+str((bp-1)*ps)
            rows=dbq(s,tuple(pa))
            subname=''
            if sub:
                sr=dbq("SELECT name FROM categories WHERE id=?",(sub,))
                if sr:subname=' › '+sr[0]['name']
            h+='<h2>📖 书库'+(' - '+fmt.upper() if fmt else '')+subname+' ('+str(len(rows))+'/'+str(total)+')</h2>'
            h+='<form class=sch method=get><input type=hidden name=p value=books><input type=hidden name=fmt value="'+he(fmt)+'"><input type=hidden name=sub value="'+he(sub)+'"><input name=q placeholder=搜索书名 value="'+he(q)+'">'
            h+='<select name=cat><option value="">全部分类</option>'
            for r in dbq("SELECT id,name FROM categories ORDER BY name"):
                sel=' selected'if r['id']==cat else''
                h+='<option value="'+r['id']+'"'+sel+'>'+he(r['name'])+'</option>'
            h+='</select>'
            h+='<select name=rstat><option value="">全部状态</option>'
            for v,l in (('unread','未读'),('reading','在读'),('finished','读完')):
                sel=' selected'if v==rstat else''
                h+='<option value="'+v+'"'+sel+'>'+l+'</option>'
            h+='</select>'
            h+='<select name=diff><option value="">全部难度</option>'
            for v in ('入门','中级','高级'):
                sel=' selected'if v==diff else''
                h+='<option value="'+v+'"'+sel+'>'+v+'</option>'
            h+='</select>'
            h+='<input name=author placeholder=作者 value="'+he(author)+'">'
            h+='<input name=tags placeholder=标签 value="'+he(tags)+'">'
            h+='<input name=year placeholder=出版年 value="'+he(year)+'" style="width:90px">'
            h+='<button>搜索</button><button type=button class=sb-btn onclick="saveShelf()">💾 存为书架</button></form>'
            h+='<div class=grid>'
            for r in rows:
                cv='<img src="/api/covers/'+r['id']+'.jpg" alt="">'if r['cover_path']else'<div class=cv>📚</div>'
                rb='';rs=r.get('reading_status') or 'unread';lp=r.get('last_page') or 0
                if rs=='reading':rb='<span class="rb reading">在读'+(str(lp) if lp else '')+'</span>'
                elif rs=='finished':rb='<span class="rb finished">读完✓</span>'
                h+='<a class=card href="/?p=detail&id='+r['id']+'">'+cv+'<div class=t>'+he(r['title'])[:44]+'</div>'+rb+'</a>'
            h+='</div>'
            if total>ps:
                tp=(total+ps-1)//ps;qs_str=""
                if q or cat or sub or fmt or diff or rstat:
                    qs_str="&q="+he(q)+"&cat="+(cat or"")+"&sub="+(sub or"")+"&fmt="+(fmt or"")+"&diff="+(diff or"")+"&rstat="+(rstat or"")+"&author="+(author or"")+"&tags="+(tags or"")+"&year="+(year or"")
                h+='<div style=text-align:center;margin-top:12px;font-size:14px>共 '+str(total)+' 本 页 '+str(bp)+'/'+str(tp)+' '
                if bp>1:h+='<a href="?p=books&page='+str(bp-1)+qs_str+'">上一页</a> '
                if bp<tp:h+='<a href="?p=books&page='+str(bp+1)+qs_str+'">下一页</a> '
                h+='</div>'
        elif pn=='detail':
            bid=qs.get('id',[None])[0];is_media=qs.get('type',[''])[0]=='media'
            if bid and not is_media:
                r=dbq("SELECT id,title,subtitle,publisher,publish_date,isbn,language,description,cover_path,file_path,file_format,file_size,page_count,summary,summary_model,summary_updated,difficulty,status,reading_status,last_page,created_at FROM books WHERE id=?",(bid,))
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
                    # 阅读状态控制（P0）
                    rs=b.get('reading_status') or 'unread'; lp=b.get('last_page') or 0
                    h+='<div class=sec><b>阅读状态:</b> '
                    for v,l in (('unread','未读'),('reading','在读'),('finished','读完')):
                        cls='rs-btn' if v==rs else 'rs-btn off'
                        h+='<button class="'+cls+'" onclick="setStatus(\''+bid+'\',\''+v+'\')">'+l+'</button>'
                    h+=' <span class=co id=rs-info>'+(('已读到第 '+str(lp)+' 页') if lp else '')+'</span></div>'
                    if c:
                        h+='<div class=sec>'
                        for x in c:h+='<span class=tag style=background:'+cc(x['name'])+'>'+he(x['name'])+'</span> '
                        h+='</div>'
                    if b['difficulty']:
                        dc={'入门':'#52c41a','中级':'#fa8c16','高级':'#ff4d4f'}
                        h+=' <span class=tag style=background:'+dc.get(b['difficulty'],'#999')+'>难度: '+b['difficulty']+'</span>'
                    if b['summary']:h+='<div class=sec><h3>🤖 AI 摘要</h3><div style=white-space:pre-wrap;line-height:1.8;background:#f9f9f9;padding:16px;border-radius:8px;margin-top:8px>'+he(str(b['summary']))+'</div></div>'
                    else:h+='<div class=sec><p class=co>暂无摘要</p></div>'
                    # P2-A 阅读笔记
                    h+='<div class=sec id=notes-sec><h3>📝 阅读笔记</h3><div id=notes-list data-bid="'+bid+'"></div>'
                    h+='<div style="margin-top:10px"><textarea id=note-input placeholder="写点笔记…（可选填页码）" style="width:100%;min-height:60px;padding:8px;border:1px solid var(--border2);border-radius:6px;font-family:inherit;font-size:14px;background:var(--panel);color:var(--text)"></textarea>'
                    h+='<div style="margin-top:6px;display:flex;gap:8px;align-items:center"><input id=note-page placeholder="页码(可选)" style="width:110px;padding:6px 8px;border:1px solid var(--border2);border-radius:6px;font-size:13px;background:var(--panel);color:var(--text)"><button class="btn" onclick="addNote(\''+bid+'\')">＋ 保存笔记</button></div></div>'
                    read_url='/api/books/'+bid+'/'+('file'if b['file_format']=='pdf'else'read')
                    cont = (' 续读第'+str(lp)+'页') if (b['file_format']=='pdf' and lp) else ''
                    h+='<div class=sec><a href="'+read_url+'" class=btn target=_blank>📖 阅读'+cont+'</a>'                                                                       #260727 修改 调用SumatraPDF
                    h+=' <a href="#" class=btn onclick="event.preventDefault();fetch(\'/api/books/'+bid+'/open\')">📖 外部阅读</a>'
                    _jt=str(b['title']).replace('\\','\\\\').replace("'","\\'").replace('\n',' ')   #260816 删除按钮（标题做JS转义）
                    h+=' <a href="#" class=btn style="background:#ff4d4f;color:#fff" onclick="event.preventDefault();DELB(\''+bid+'\',\''+_jt+'\')">🗑️ 删除</a>'
                    h+=' <a href="javascript:history.back()" class="btn bb2">返回</a></div></div>'
        elif pn=='notes':
            q=qs.get('q',[''])[0]
            s="SELECT n.id,n.note,n.page,n.created_at,n.book_id,b.title FROM reading_notes n LEFT JOIN books b ON b.id=n.book_id"
            pa=[]
            if q:
                s+=" WHERE n.note LIKE ?"; pa.append('%'+q+'%')
            s+=" ORDER BY n.created_at DESC LIMIT 500"
            try:
                rows=dbq(s,tuple(pa))
            except Exception as e:
                rows=[]; h+='<p class=co>笔记读取失败: '+he(str(e))+'</p>'
            h+='<h2>📝 全部阅读笔记 ('+str(len(rows))+')</h2>'
            h+='<form class=sch method=get><input type=hidden name=p value=notes><input name=q placeholder="搜索笔记内容" value="'+he(q)+'"><button>搜索</button></form>'
            if rows:
                h+='<div style="display:flex;flex-direction:column;gap:12px;margin-top:12px">'
                for r in rows:
                    bid2=r['book_id'] or ''
                    title=r['title'] or '(书籍已删除)'
                    meta=(('第 '+str(r['page'])+' 页 · ') if r['page'] else '')+(str(r['created_at'])[:16] if r['created_at'] else '')
                    h+='<div style="border:1px solid var(--border2);border-radius:8px;padding:12px 14px;background:var(--panel)">'
                    h+='<div style="margin-bottom:6px"><a href="/?p=detail&id='+bid2+'" target=_blank style="font-weight:600;color:var(--link);text-decoration:none">'+he(title)[:60]+'</a>'
                    h+=' <span style="color:#999;font-size:12px">'+he(meta)+'</span></div>'
                    h+='<div style="white-space:pre-wrap;line-height:1.7;font-size:14px">'+he(str(r['note']))+'</div>'
                    h+='</div>'
                h+='</div>'
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
        elif pn=='tools':
            h += _tool_center_html()

        elif pn=='stats':
            st = _lib_stats()
            total = st['total_books']; tm = st['total_media']
            cov = st['coverage']
            h+='<h2>📊 图书馆统计</h2>'
            h+='<div class=panel><h3>🧹 摘要健康</h3><p class=co>当前仍有 <b style="color:#c0392b">'+str(st.get('fake_summary',0))+'</b> 本<b>假摘要</b>（导入时无正文被 LLM 编的模板示例，典型首句「由于提供的内容为空白…」）。其中<b>无全文</b>的将清空、<b>有全文</b>的可经本机 Ollama 重跑真摘要。处理方式：工具中心「③ 摘要修复」→「🔥 全量修复」（需 Ollama 在线）。</p></div>'
            h+='<div class=panel><h3>📦 规模</h3><div class=row>'
            h+='<a class=sb><div class=n style=color:#1677ff>'+str(total)+'</div><div class=l>📚 书籍</div></a>'
            h+='<a class=sb><div class=n style=color:#fa8c16>'+str(tm)+'</div><div class=l>🎧 媒体</div></a></div></div>'
            h+='<div class=panel><h3>🧬 数据覆盖率（按 '+str(total)+' 本书计）</h3><table style="width:100%;border-collapse:collapse;font-size:13px"><tr style="background:#f3f3f3"><th style="border:1px solid #ddd;padding:6px;text-align:left">字段</th><th style="border:1px solid #ddd;padding:6px;text-align:left">已填</th><th style="border:1px solid #ddd;padding:6px;text-align:left">覆盖率</th><th style="border:1px solid #ddd;padding:6px;text-align:left">进度</th></tr>'
            labels={'cover':'封面','summary':'简介','publisher':'出版社','isbn':'ISBN','language':'语言','text_extracted':'全文提取','named':'已规则化命名'}
            for k,lab in labels.items():
                v=cov.get(k,0); pct=(v*100.0/total) if total else 0
                h+='<tr><td style="border:1px solid #ddd;padding:6px">'+lab+'</td><td style="border:1px solid #ddd;padding:6px">'+str(v)+'</td><td style="border:1px solid #ddd;padding:6px">'+('%.1f'%(pct))+'%</td><td style="border:1px solid #ddd;padding:6px;width:220px"><div style="background:#1677ff;height:10px;border-radius:5px;width:'+str(min(100,pct))+'%"></div></td></tr>'
            h+='</table></div>'
            h+='<div class=panel><h3>🛠️ 各工具续跑进度（progress.db）</h3><table style="width:100%;border-collapse:collapse;font-size:13px"><tr style="background:#f3f3f3"><th style="border:1px solid #ddd;padding:6px;text-align:left">工具</th><th style="border:1px solid #ddd;padding:6px;text-align:left">已完成(done)</th><th style="border:1px solid #ddd;padding:6px;text-align:left">已跳过(skip)</th><th style="border:1px solid #ddd;padding:6px;text-align:left">状态</th></tr>'
            tnames={'kg':'知识图谱 L1','meta':'元数据补全','summary':'摘要修复','extract':'提取文本','classify':'AI 分类','summarize':'AI 摘要','transcribe':'媒体转录','media_summarize':'媒体摘要','metadata':'在线元数据'}
            for t,v in st['tools'].items():
                run='🟢 运行中' if v.get('running') else '⚪ 空闲'
                h+='<tr><td style="border:1px solid #ddd;padding:6px">'+tnames.get(t,t)+'</td><td style="border:1px solid #ddd;padding:6px">'+str(v.get('done',0))+'</td><td style="border:1px solid #ddd;padding:6px">'+str(v.get('skip',0))+'</td><td style="border:1px solid #ddd;padding:6px">'+run+'</td></tr>'
            h+='</table></div>'
        elif pn=='title-norm':
            h+='<h2>📐 书名规则化对比表</h2>'
            _tn_page=int(qs.get('page',['1'])[0]); _tn_mode=qs.get('mode',['all'])[0]; _tn_q=qs.get('q',[''])[0]; _tn_ps=50
            _tot=dbq("SELECT COUNT(*) AS c FROM books")[0]['c']
            _chg=dbq("SELECT COUNT(*) AS c FROM books WHERE normalized_title IS NOT NULL AND normalized_title<>'' AND normalized_title<>title")[0]['c']
            _unc=dbq("SELECT COUNT(*) AS c FROM books WHERE normalized_title=title OR normalized_title='' OR normalized_title IS NULL")[0]['c']
            _up=dbq("SELECT COUNT(*) AS c FROM books WHERE normalized_title LIKE 'upload_%'")[0]['c']
            _ext=dbq("SELECT COUNT(*) AS c FROM books WHERE text_extracted=1")[0]['c']
            _noext=dbq("SELECT COUNT(*) AS c FROM books WHERE text_extracted=0 OR text_extracted IS NULL")[0]['c']
            _w="1=1"; _pa=[]
            if _tn_q: _w+=" AND title LIKE ?"; _pa.append('%'+_tn_q+'%')
            if _tn_mode=='changed': _w+=" AND normalized_title<>title AND normalized_title<>''"
            elif _tn_mode=='unchanged': _w+=" AND (normalized_title=title OR normalized_title='' OR normalized_title IS NULL)"
            elif _tn_mode=='upload': _w+=" AND normalized_title LIKE 'upload_%'"
            elif _tn_mode=='no_text': _w+=" AND (text_extracted=0 OR text_extracted IS NULL)"
            _tr=dbq("SELECT COUNT(*) AS c FROM books WHERE "+_w,_pa)[0]['c']
            _pages=max(1,( _tr+_tn_ps-1)//_tn_ps)
            _tn_page=max(1,min(_tn_page,_pages))
            _rows=dbq("SELECT id,title,normalized_title,file_format,text_extracted FROM books WHERE "+_w+" ORDER BY id LIMIT ? OFFSET ?",_pa+[_tn_ps,(_tn_page-1)*_tn_ps])
            h+='<div class=panel><p class=co>总书数 <b>'+str(_tot)+'</b> · 已被规则改写(存库) <b>'+str(_chg)+'</b> · 未变/无解回退 <b>'+str(_unc)+'</b> · 其中 upload_ 无解 <b>'+str(_up)+'</b> 本。 · 已抽正文 <b style="color:#52c41a">'+str(_ext)+'</b> 本 · 未抽 <b style="color:#fa8c16">'+str(_noext)+'</b> 本（扫描版/损坏/压缩包，详见下表「文本抽取」列）。</p>'
            h+='<p class=co>下表「规则化结果」为对<b>当前书名</b>实时套用 normalize_title() 规则所得（避免显示书名被后续补全更新造成的旧值漂移）。点「重算写回」(工具中心) 可把结果同步回 normalized_title 列。</p>'
            h+='<form class=sch method=get style="margin:8px 0"><input type=hidden name=p value=title-norm>模式<select name=mode><option value=all'+(' selected' if _tn_mode=='all' else '')+'>全部</option><option value=changed'+(' selected' if _tn_mode=='changed' else '')+'>仅被改写</option><option value=unchanged'+(' selected' if _tn_mode=='unchanged' else '')+'>仅未变</option><option value=upload'+(' selected' if _tn_mode=='upload' else '')+'>仅 upload_ 无解</option><option value=no_text'+(' selected' if _tn_mode=='no_text' else '')+'>仅未抽正文</option></select> <input name=q placeholder="搜索书名" value="'+he(_tn_q)+'"><button>筛选</button></form>'
            h+='<table style="width:100%;border-collapse:collapse;font-size:13px"><tr style="background:#f3f3f3"><th style="border:1px solid #ddd;padding:6px;text-align:left"><input type=checkbox id=selAll onclick="selAll(this)" title="全选本页"></th><th style="border:1px solid #ddd;padding:6px;text-align:left">#</th><th style="border:1px solid #ddd;padding:6px;text-align:left">原书名（当前）</th><th style="border:1px solid #ddd;padding:6px;text-align:left">规则化结果</th><th style="border:1px solid #ddd;padding:6px;text-align:left">状态</th><th style="border:1px solid #ddd;padding:6px;text-align:left">文本抽取</th></tr>'
            for _i,_r in enumerate(_rows):
                _t=_r['title'] or ''
                _nt=normalize_title(_t)
                _st='改写' if _nt!=(_t or '').strip() else '未变'
                if _nt.startswith('upload_'): _st='无解(random)'
                _fm=_r.get('file_format') or ''
                _te=_r.get('text_extracted') or 0
                if _te==1:
                    _ext='<span style="color:#52c41a">✅ 已抽</span>'
                else:
                    if _fm=='pdf': _ext='<span style="color:#888">⚪ 扫描版(无文字层)</span>'
                    elif _fm in ('epub','mobi','azw3'): _ext='<span style="color:#fa8c16">🟡 文件损坏/未抽</span>'
                    elif _fm in ('rar','zip','7z'): _ext='<span style="color:#1677ff">📦 压缩包</span>'
                    else: _ext='<span style="color:#888">⚪ 未抽</span>'
                h+='<tr><td style="border:1px solid #ddd;padding:6px"><input type=checkbox class=rowcb name=bid value="'+he(str(_r['id']))+'"></td><td style="border:1px solid #ddd;padding:6px">'+str((_tn_page-1)*_tn_ps+_i+1)+'</td><td style="border:1px solid #ddd;padding:6px">'+he(_t)+'</td><td style="border:1px solid #ddd;padding:6px">'+he(_nt)+'</td><td style="border:1px solid #ddd;padding:6px">'+_st+'</td><td style="border:1px solid #ddd;padding:6px">'+_ext+'</td></tr>'
            h+='</table>'
            h+='<div style="margin:12px 0 4px"><label style="font-size:13px"><input type=checkbox id=selAll2 onclick="selAll(this)"> 全选本页</label> &nbsp; <button class=btn onclick="ADOPT()">✅ 采纳选中为正式书名</button> <span id=tnAdoptRes style="font-size:13px;color:#1677ff"></span></div>'
            h+='<p class=co>「采纳为正式书名」将把勾选书的 <b>title</b> 改为上表「规则化结果」（upload_ 无解的书自动跳过，不会误覆盖）。</p>'
            h+='<div class=pager style="margin:10px 0">'
            if _tn_page>1: h+='<a class=btn href="/?p=title-norm&page='+str(_tn_page-1)+('&mode='+_tn_mode if _tn_mode!='all' else '')+('&q='+urllib.parse.quote(_tn_q) if _tn_q else '')+'">上一页</a> '
            h+=' 第 '+str(_tn_page)+'/'+str(_pages)+' 页（共 '+str(_tr)+' 条） '
            if _tn_page<_pages: h+='<a class=btn href="/?p=title-norm&page='+str(_tn_page+1)+('&mode='+_tn_mode if _tn_mode!='all' else '')+('&q='+urllib.parse.quote(_tn_q) if _tn_q else '')+'">下一页</a>'
            h+='</div>'
            h+='</div>'
            h+='<script>function selAll(cb){document.querySelectorAll(".rowcb").forEach(function(x){x.checked=cb.checked;});}function ADOPT(){var ids=[];document.querySelectorAll(".rowcb:checked").forEach(function(x){ids.push(x.value);});var r=document.getElementById("tnAdoptRes");if(!ids.length){r.textContent="请先勾选至少一本";return;}if(!confirm("确认把选中的 "+ids.length+" 本书名采纳为正式书名？将覆盖当前 title。"))return;var x=new XMLHttpRequest();x.open("POST","/api/title-norm/adopt");x.setRequestHeader("Content-Type","application/json");x.onload=function(){try{var j=JSON.parse(x.responseText);r.textContent="已采纳 "+j.adopted+" 本，跳过 "+j.skipped+" 本（upload_无解不采纳）";setTimeout(function(){location.reload();},800);}catch(e){r.textContent="error";}};x.send(JSON.stringify({ids:ids}));}</script>'
        else:
            ts=ct.get('ts',0); import_rem=ct.get('import_rem',0); sum_rem=ct.get('sum_rem',0); no_text=ct.get('no_text',0)
            _ld=""
            h+='<h2>🏠 首页</h2>'
            h+='<div class=row><a href="/?p=books" class=sb><div class=n style=color:#1677ff>'+str(tb)+'</div><div class=l>📚 书籍</div></a><a href="/?p=detail&list=1" class=sb><div class=n style=color:#52c41a>'+str(ts)+'</div><div class=l>🤖 已摘要</div></a><a href="/?p=media" class=sb><div class=n style=color:#fa8c16>'+str(tm)+'</div><div class=l>🎧 媒体</div></a><a href="/?p=media_transcribed" class=sb><div class=n style=color:#13c2c2>'+str(ct.get("mtr",0))+'</div><div class=l>🎙️ 已转录</div></a><a href="/?p=media_summarized" class=sb><div class=n style=color:#eb2f96>'+str(ct.get("msu",0))+'</div><div class=l>📝 媒体摘要</div></a></div>'
            h+='<div class=panel><h3>🤖 AI 处理</h3><p class=co style=margin-bottom:8px>未分类: '+str(import_rem)+' 本 | 未摘要: '+str(sum_rem)+' 本 | 无文本: '+str(no_text)+' 本'+_ld+'</p>'
            h+='<div style="margin-bottom:8px"><label style=font-size:13px>分类数量 </label><select id=clsCnt style="padding:4px 8px;border:1px solid #ddd;border-radius:4px"><option value=5>5 本</option><option value=10 selected>10 本</option><option value=20>20 本</option><option value=50>50 本</option><option value=100>100 本</option><option value=500>500 本</option><option value=1000>1000 本</option></select> <button class=btn id=clsBtn onclick="CLS()" style=margin-right:8px>🤖 AI 分类</button></div>'
            h+='<div style="margin-bottom:8px"><label style=font-size:13px>摘要数量 </label><select id=sumCnt style="padding:4px 8px;border:1px solid #ddd;border-radius:4px"><option value=1>1 本</option><option value=3 selected>3 本</option><option value=5>5 本</option><option value=10>10 本</option><option value=20>20 本</option><option value=100>100 本</option><option value=500>500 本</option><option value=1000>1000 本</option></select> <button class=btn id=sumBtn onclick="SUM()">🤖 AI 摘要</button></div>'
            h+='<div><label style=font-size:13px>提取数量 </label><select id=extCnt style="padding:4px 8px;border:1px solid #ddd;border-radius:4px"><option value=5>5 本</option><option value=10 selected>10 本</option><option value=20>20 本</option><option value=50>50 本</option><option value=100>100 本</option><option value=500>500 本</option><option value=1000>1000 本</option></select> <button class=btn id=extBtn onclick="EXT()">📄 提取文本</button></div>'
            h+='<div style="margin:10px 0 4px;font-size:12px;color:#888;border-top:1px dashed #eee;padding-top:8px">🌐 在线元数据补全（主源豆瓣，中文书覆盖好；默认关，start.bat 已自动启用）</div>'
            h+='<div style="margin-bottom:8px"><label style=font-size:13px>元数据数量 </label><select id=metaCnt style="padding:4px 8px;border:1px solid #ddd;border-radius:4px"><option value=0 selected>全部</option><option value=10>10 本</option><option value=50>50 本</option><option value=100>100 本</option><option value=500>500 本</option><option value=1000>1000 本</option></select> <button class=btn id=metaBtn onclick="META()" style=background:#13c2c2>🌐 补全元数据</button></div>'
            h+='<div id=clsRes style=margin-top:4px;font-size:13px></div><div id=sumRes style=margin-top:4px;font-size:13px></div><div id=extRes style=margin-top:4px;font-size:13px></div><div id=metaRes style=margin-top:4px;font-size:13px></div></div>'
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
        print(f"[ok] drive-path fix: books.file_path {n1}, books.cover_path {n2}, media.file_path {n3}", flush=True)
    except Exception as e:
        print(f"[warn] drive-path fix error: {e}", flush=True)

if __name__ == "__main__":
    import sys, threading
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    fix_drive_paths()
    migrate_schema()
    threading.Thread(target=migrate_text_content, daemon=True).start()
    HOST = os.environ.get("LIB_HOST", "127.0.0.1")
    PORT = int(os.environ.get("LIB_PORT", "8000"))
    print(f"http://localhost:{PORT}")
    print(f"Private Lib | listening on {HOST}:{PORT}")
    print(f"Metadata online (LIB_METADATA_ONLINE): {'ENABLED' if ENABLE_ONLINE_METADATA else 'DISABLED (default off, set via start.bat/restart.bat)'}", flush=True)
    if HOST == "0.0.0.0":
        print("Listening on all interfaces (LAN accessible). For 127.0.0.1 only set LIB_HOST=127.0.0.1")
    print("[migrate] 12GB 文本搬迁已在后台启动，界面可立即使用；AI 文本功能待搬迁完成后生效", flush=True)
    http.server.ThreadingHTTPServer((HOST, PORT), H).serve_forever()
