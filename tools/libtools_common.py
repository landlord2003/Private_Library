# -*- coding: utf-8 -*-
# libtools_common.py — 私有图书馆离线工具公共模块
# 被 meta_complete.py / kg_build.py / summary_fix.py 共享。
# 设计原则：
#   1) 盘符无关：DB 路径相对本脚本目录解析（脚本在移动盘上跟着走）。
#   2) 不依赖主服务：直连 library.db，可在服务端停止时单独跑。
#   3) 断点续跑：进度存于同目录 progress.db（独立文件，绝不污染主库 schema）。
#   4) 零第三方依赖：仅 Python 标准库。

import os
import re
import sys
import json
import time
import sqlite3
import urllib.parse
import urllib.request
import difflib
import threading

_re_mod = re  # 原函数用 _re_mod.sub，等价于 re.sub

# ---------------------------------------------------------------------------
# 1. 数据库定位（盘符无关）
# ---------------------------------------------------------------------------
_DB_PATH = None


def find_db():
    """定位 library.db：环境变量 > 脚本上级 data/ > 脚本同级 data/ > 常见盘符扫描。"""
    global _DB_PATH
    if _DB_PATH and os.path.exists(_DB_PATH):
        return _DB_PATH
    env = os.environ.get("LIB_DB")
    if env and os.path.exists(env):
        _DB_PATH = env
        return _DB_PATH
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        os.path.normpath(os.path.join(here, "..", "data", "library.db")),  # tools/../data
        os.path.normpath(os.path.join(here, "data", "library.db")),
    ):
        if os.path.exists(cand):
            _DB_PATH = cand
            return _DB_PATH
    for d in ("F", "G", "E", "D", "H", "I"):
        for base in (f"{d}:/my-library", f"{d}:/书籍", f"{d}:/my-library/data"):
            p = os.path.join(base, "data", "library.db") if base.endswith("data") else os.path.join(base, "data", "library.db")
            if os.path.exists(p):
                _DB_PATH = p
                return _DB_PATH
    raise FileNotFoundError("找不到 library.db，请设置环境变量 LIB_DB 指向数据库文件")


def get_conn():
    con = sqlite3.connect(find_db(), timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    return con


def get_progress_conn():
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "progress.db")
    con = sqlite3.connect(p, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


def ensure_progress(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tool_progress (
              book_id TEXT, tool TEXT, status TEXT, ts REAL,
              PRIMARY KEY(book_id, tool))"""
    )
    conn.commit()


def mark_progress(conn, book_id, tool, status):
    conn.execute(
        "INSERT OR REPLACE INTO tool_progress(book_id, tool, status, ts) VALUES(?,?,?,?)",
        (str(book_id), tool, status, time.time()),
    )
    conn.commit()


def get_status(conn, book_id, tool):
    r = conn.execute(
        "SELECT status FROM tool_progress WHERE book_id=? AND tool=?", (str(book_id), tool)
    ).fetchone()
    return r[0] if r else None


def clear_status(conn, tool, status=None):
    if status:
        conn.execute("DELETE FROM tool_progress WHERE tool=? AND status=?", (tool, status))
    else:
        conn.execute("DELETE FROM tool_progress WHERE tool=?", (tool,))
    conn.commit()


# ---------------------------------------------------------------------------
# 2. 网络：代理域名分流 + GET（原样移植自 Private_Lib.py）
# ---------------------------------------------------------------------------
_DIRECT_DOMAINS = ("book.douban.com", "douban.com", "localhost", "127.0.0.1")


def _proxy_handler(url=None):
    """域名分流：豆瓣/本机直连；Open Library/Google 走 LIB_PROXY 或系统代理，否则直连。"""
    host = ""
    if url:
        try:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
    if host and any(host == d or host.endswith("." + d) for d in _DIRECT_DOMAINS):
        return urllib.request.ProxyHandler({})
    p = os.environ.get("LIB_PROXY")
    if p:
        return urllib.request.ProxyHandler({"http": p, "https": p})
    return urllib.request.ProxyHandler(urllib.request.getproxies())


def _http_get_text(url, timeout=8, max_bytes=None):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    proxy = _proxy_handler(url)
    opener = urllib.request.build_opener(proxy)
    with opener.open(req, timeout=timeout) as r:
        data = r.read(max_bytes) if max_bytes else r.read()
        return data.decode("utf-8", "ignore")


def _http_get_json(url, timeout=5):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PrivateLib)"})
    proxy = _proxy_handler(url)
    opener = urllib.request.build_opener(proxy)
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


# ---------------------------------------------------------------------------
# 3. 标题清洗 + 检索变体（原样移植）
# ---------------------------------------------------------------------------
_TITLE_SUFFIX = r'(丛书|全集|套书|套装|上下册|上册|下册|卷[一二三四五六七八九十百]+|第[0-9一二三四五六七八九十百]+版|含目录|扫描版|精装|修订版|增补版|译著|校订|注释|导读|图说|图鉴|简明|新版|影印|标点|校注|（中）|（上）|（下）)'
_TITLE_PROMO_CUT = ['英国大使馆', '美国大使馆', '官方微博', '活动用书', '豆瓣高分']


def normalize_title(title):
    t = (title or '').strip()
    if not t:
        return t
    t = _re_mod.sub(r'(?i)[\(（][^（）()]*?(?:z-?lib|1lib|b-?ok|bookzz|zlibrary|libgen)[^（）()]*?[）)]', '', t)
    t = _re_mod.sub(r'(?i)\s*[\(（]?(?:Z-?Library|z-?lib(?:\.org|\.sk)?|1lib\.sk|libgen|b-?ok|bookzz|bok\.cc|z-lib)[\)）]?', '', t)
    t = t.strip()
    t = _re_mod.sub(r'^\d{5,}[_\.\-]?\s*', '', t)
    t = _re_mod.sub(r'^(?!\d{4}[-—–])\d{1,4}(?=[^\d])', '', t)
    for _ in range(6):
        new = _re_mod.sub(r'[（(][^（）()]*[）)]', '', t)
        if new == t:
            break
        t = new
    t = _re_mod.sub(r'【[^】]*】', '', t)
    t = _re_mod.sub(r'[【\[](?:美|英|法|日|德|加|澳|俄|意|西|韩|中|台)[】\]]', '', t)
    _bi = t.find('【')
    if _bi >= 0:
        t = t[:_bi]
    t = _re_mod.sub(r'[（(][^）)]*$', '', t)
    t = _re_mod.sub(r'\s+by\s+[^（）()]*?(?=[（(]|$|\s*[-—–]\s*(?:出版社|出版|引进|出品))', '', t, flags=_re_mod.I)
    t = _re_mod.sub(r'\s+by\s+.+$', '', t, flags=_re_mod.I)
    _eq = t.find(' = ')
    if _eq < 0:
        _eq = t.find('＝')
    if _eq >= 0:
        _left = t[:_eq].strip()
        if _left and sum(1 for c in _left if '\u4e00' <= c <= '\u9fff') >= 2:
            t = _left
    t = _re_mod.sub(r'(?i)\s*\b[A-Za-z]+(?:[.\-][A-Za-z0-9]+)*\b(?:\s+[A-Za-z]+(?:[.\-][A-Za-z0-9]+)*\b){1,}', '', t)
    t = _re_mod.sub(r'\.(pdf|epub|mobi|azw3?|txt|djvu?|chm|docx?|fb2|rtf|zip|rar|7z)\s*$', '', t, flags=_re_mod.I)
    t = _re_mod.sub(r'\s*[-—–]\s*.*?(?:出版社|出版公司|引进|出品|出品方|译丛|丛书)[^，。、（）()]*', '', t)
    for _kw in _TITLE_PROMO_CUT:
        _j = t.find(_kw)
        if _j > 1:
            t = t[:_j]
            break
    t = _re_mod.sub(r'\s{2,}', ' ', t).strip()
    t = t.strip(' .,，-—–、:：()（）[]【】=-')
    if not t:
        return (title or '').strip()
    return t


def _title_query_variants(title):
    t = normalize_title(title)
    if not t:
        t = (title or '').strip()
    _segs = [s.strip() for s in _re_mod.split(r'\s+', t)]
    _segs = [s for s in _segs if s]
    def _chc(s):
        return sum(1 for c in s if '\u4e00' <= c <= '\u9fff')
    _segs_sorted = sorted(_segs, key=_chc, reverse=True)
    head = _segs_sorted[0] if _segs_sorted else t
    vs = [t, head]
    t2 = _re_mod.sub(_TITLE_SUFFIX + r'$', '', head).strip()
    if t2 and t2 != head:
        vs.append(t2)
    for n in (14, 12, 10, 8, 6, 4):
        if len(head) >= n:
            vs.append(head[:n])
    seen = set()
    out = []
    for x in vs:
        x = x.strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _sim(a, b):
    a = (a or '').strip()
    b = (b or '').strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------
# 4. 豆瓣元数据（detail=True 解析详情页；False 仅 suggest，速度快）
# ---------------------------------------------------------------------------
def _douban_meta(title, author=None, isbn=None, detail=True):
    best = None
    best_sim = -1.0
    matched_v = None
    if isbn:
        try:
            sug = _http_get_json("https://book.douban.com/j/subject_suggest?q=" + urllib.parse.quote(isbn), timeout=5)
            if isinstance(sug, list):
                for it in sug:
                    if it.get("isbn") and it["isbn"].replace("-", "") == isbn.replace("-", ""):
                        best = it
                        best_sim = 1.0
                        matched_v = isbn
                        break
        except Exception as e:
            print(f"[豆瓣ISBN检索失败] {title[:24]}: {e}", flush=True)
    if not best:
        for v in _title_query_variants(title):
            try:
                sug = _http_get_json("https://book.douban.com/j/subject_suggest?q=" + urllib.parse.quote(v), timeout=5)
            except Exception as e:
                print(f"[豆瓣检索失败] {title[:24]}: {e}", flush=True)
                continue
            if not isinstance(sug, list) or not sug:
                continue
            for it in sug:
                sm = _sim(v, it.get("title", ""))
                if sm > best_sim:
                    best_sim = sm
                    best = it
                    matched_v = v
            break
    if not best:
        return None
    hid = best.get("id")
    if not hid:
        return None
    pub = ""
    yr_text = (best.get("year") or "").strip()
    isbn_from_sug = best.get("isbn") or ""
    desc = ""
    if detail:
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


_google_cooldown_until = 0.0


def fetch_online_metadata(title, author=None, isbn=None, normalized_title=None, detail=True):
    """在线补全单本元数据。detail=False 仅用豆瓣 suggest（快，填年份+ISBN）。"""
    global _google_cooldown_until
    q = (normalized_title or "").strip() or (title or "").strip()
    if not q and not isbn:
        return None
    result = None
    best_sim = 0.0
    # 0) 豆瓣
    try:
        dm = _douban_meta(q, author, isbn, detail=detail)
        if dm and dm.get("sim", 0) >= 0.5:
            result = dm
    except Exception as e:
        print(f"[豆瓣失败] {q[:30]}: {e}", flush=True)
    # 1) Open Library / 2) Google（仅在 detail 全模式 + 配置了 LIB_PROXY 时尝试）
    _have_proxy = bool(os.environ.get("LIB_PROXY"))
    if detail and _have_proxy:
        try:
            ol = None
            if isbn:
                ol = _http_get_json("https://openlibrary.org/isbn/%s.json?jscmd=details&format=json" % isbn.replace("-", ""), timeout=5)
                best_sim = 1.0
            if not ol and q:
                s = _http_get_json("https://openlibrary.org/search.json?title=" + urllib.parse.quote(q)
                                   + ("&author=" + urllib.parse.quote(author) if author else "") + "&limit=5", timeout=5)
                docs = (s or {}).get("docs", [])
                if docs:
                    best = None
                    bs = 0.0
                    for d in docs:
                        sm = _sim(q, d.get("title", ""))
                        if sm > bs:
                            bs = sm
                            best = d
                    best_sim = bs
                    if best:
                        ol = best
                        if str(best.get("key", "")).startswith("/works/"):
                            wk = _http_get_json("https://openlibrary.org" + best["key"] + ".json", timeout=5)
                            if wk and isinstance(wk.get("description"), str):
                                ol = dict(ol)
                                ol["_desc"] = wk["description"]
                            elif wk and isinstance(wk.get("description"), dict):
                                ol = dict(ol)
                                ol["_desc"] = wk["description"].get("value", "")
            if ol:
                pub = ol.get("publishers")
                pub = pub[0] if isinstance(pub, list) and pub else ""
                pd = ol.get("first_publish_year") or (ol.get("publish_date") if isinstance(ol.get("publish_date"), str) else "")
                il = ol.get("isbn") if isinstance(ol.get("isbn"), list) else []
                isbn2 = il[0] if il else ""
                ll = ol.get("language") if isinstance(ol.get("language"), list) else []
                lang = ll[0] if ll else ""
                desc = ol.get("_desc") or (ol.get("description") if isinstance(ol.get("description"), str) else "")
                if isinstance(desc, dict):
                    desc = desc.get("value", "")
                if not result:
                    result = {"publisher": pub or "", "publish_date": str(pd) if pd else "",
                              "isbn": isbn2 or "", "language": lang or "",
                              "description": (desc or "")[:2000], "source": "openlibrary", "sim": best_sim}
                else:
                    if not result.get("publisher"):
                        result["publisher"] = pub or ""
                    if not result.get("publish_date"):
                        result["publish_date"] = str(pd) if pd else ""
                    if not result.get("isbn"):
                        result["isbn"] = isbn2 or ""
                    if not result.get("language"):
                        result["language"] = lang or ""
                    if not result.get("description"):
                        result["description"] = (desc or "")[:2000]
                    if best_sim > result.get("sim", 0):
                        result["sim"] = best_sim
        except Exception as e:
            print(f"[OL失败] {title[:30]}: {e}", flush=True)
        try:
            need_google = (not result) or (not result.get("description")) or (q and best_sim < 0.7)
            if need_google and time.time() > _google_cooldown_until:
                gq = q + (" " + author if author else "")
                g = _http_get_json("https://www.googleapis.com/books/v1/volumes?q=" + urllib.parse.quote(gq) + "&maxResults=5", timeout=5)
                items = (g or {}).get("items", [])
                if items:
                    vi = items[0].get("volumeInfo", {})
                    gdesc = vi.get("description", "")
                    gsim = _sim(q, vi.get("title", ""))
                    if (not result) or (gdesc and not result.get("description")) or (gsim > result.get("sim", 0)):
                        merged = dict(result) if result else {}
                        gis = ""
                        ids = vi.get("industryIdentifiers", [])
                        for i in ids:
                            if i.get("type") in ("ISBN_13", "ISBN_10"):
                                gis = i.get("identifier", "")
                                break
                        merged.update({
                            "publisher": vi.get("publisher", "") or merged.get("publisher", ""),
                            "publish_date": vi.get("publishedDate", "") or merged.get("publish_date", ""),
                            "isbn": gis or merged.get("isbn", ""),
                            "language": vi.get("language", "") or merged.get("language", ""),
                            "description": gdesc or merged.get("description", ""),
                            "source": "googlebooks",
                            "sim": max(gsim, merged.get("sim", 0)),
                        })
                        merged["description"] = (merged["description"] or "")[:2000]
                        result = merged
        except Exception as e:
            msg = str(e)
            if "429" in msg:
                _google_cooldown_until = time.time() + 120
                print(f"[GB 429 冷却] {title[:20]}: 2分钟内跳过 Google", flush=True)
            else:
                print(f"[GB失败] {title[:30]}: {e}", flush=True)
    return result


# ---------------------------------------------------------------------------
# 5. Ollama（仅主机可达；沙箱/无 Ollama 时返回 None，脚本降级）
# ---------------------------------------------------------------------------
def ollama_generate(prompt, model="qwen2.5:7b", timeout=180, host=None):
    host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    url = host.rstrip("/") + "/api/generate"
    data = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.2}}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore")).get("response", "")
    except Exception as e:
        print(f"[Ollama调用失败] {e}", flush=True)
        return None


# ---------------------------------------------------------------------------
# 6. 配置加载（lib_config.json + lib_config.local.json + 环境变量）
# ---------------------------------------------------------------------------
def load_config():
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = {}
    for f in ("lib_config.json", "lib_config.local.json"):
        p = os.path.join(here, f)
        if os.path.exists(p):
            try:
                cfg.update(json.load(open(p, encoding="utf-8")))
            except Exception:
                pass
    if os.environ.get("KG_VAULT"):
        cfg["vault_path"] = os.environ["KG_VAULT"]
    if os.environ.get("LIB_PROXY"):
        cfg.setdefault("proxy", os.environ["LIB_PROXY"])
    if os.environ.get("OLLAMA_MODEL"):
        cfg["ollama_model"] = os.environ["OLLAMA_MODEL"]
    if os.environ.get("OLLAMA_HOST"):
        cfg["ollama_host"] = os.environ["OLLAMA_HOST"]
    return cfg


if __name__ == "__main__":
    print("libtools_common 自检：")
    print("  DB:", find_db())
    print("  归一化示例:", normalize_title("27想象的重构 (Z-Library)【美】作者 by Smith = The Reconstruction"))
