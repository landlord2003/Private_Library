html_head = '''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>My Library</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:sans-serif;background:#f5f5f5;display:flex;min-height:100vh}
nav{width:180px;background:#fff;padding:20px 0;border-right:1px solid #eee;flex-shrink:0}
nav h2{padding:0 20px 16px;color:#1677ff;font-size:18px}
nav a{display:block;padding:10px 20px;color:#333;text-decoration:none;font-size:14px;cursor:pointer}
nav a:hover{background:#e6f4ff;color:#1677ff}
main{flex:1;padding:20px;overflow-y:auto}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;margin:2px;color:#fff}
.btn{padding:6px 14px;border:1px solid #ddd;border-radius:4px;cursor:pointer;background:#fff;margin:2px}
.btn.b{background:#1677ff;color:#fff;border-color:#1677ff}
input,select{padding:6px 10px;border:1px solid #ddd;border-radius:4px}
.box{background:#fff;padding:20px;border-radius:8px;text-align:center;min-width:130px}
.box .n{font-size:32px;font-weight:bold}
.box .l{font-size:13px;color:#999;margin-top:4px}
.panel{background:#fff;padding:16px;border-radius:8px}
.bi{background:#fff;border-radius:8px;padding:14px;margin-bottom:8px;display:flex;gap:12px;align-items:center;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.cv{width:60px;height:80px;object-fit:cover;border-radius:4px}
.mbg{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);z-index:999;display:flex;align-items:center;justify-content:center;padding:20px}
.min{background:#fff;border-radius:12px;padding:24px;max-width:800px;width:100%;max-height:90vh;overflow-y:auto}
</style>
</head>
<body>
<nav><h2>📚 My Library</h2>
<a onclick="L(0)">🏠 Home</a>
<a onclick="L(1)">📖 Books</a>
<a onclick="L(2)">🎧 Media</a>
</nav>
<main id="m"></main>
<script>
'''

html_tail = '\n</script></body></html>'

import os
if not os.path.exists("app.js"):
    print("ERROR: app.js not found. Run gen_html.py first!")
    exit(1)

js = open("app.js","r",encoding="utf-8").read()
open("app.html","w",encoding="utf-8").write(html_head + js + html_tail)
print("OK - " + str(len(html_head)+len(js)+len(html_tail)) + " bytes")
