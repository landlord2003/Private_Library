html = '''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>我的图书馆</title>
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
.stat-box{background:#fff;padding:20px;border-radius:8px;text-align:center;min-width:130px}
.stat-box .num{font-size:32px;font-weight:bold}
.stat-box .lbl{font-size:13px;color:#999;margin-top:4px}
.panel{background:#fff;padding:16px;border-radius:8px}
.book-item{background:#fff;border-radius:8px;padding:14px;margin-bottom:8px;display:flex;gap:12px;align-items:center;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.cover-sm{width:60px;height:80px;object-fit:cover;border-radius:4px;background:linear-gradient(135deg,#667eea,#764ba2)}
.mbg{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);z-index:999;display:flex;align-items:center;justify-content:center;padding:20px}
.min{background:#fff;border-radius:12px;padding:24px;max-width:800px;width:100%;max-height:90vh;overflow-y:auto}
</style>
</head>
<body>
<nav>
<h2>📚 图书馆</h2>
<a onclick="L('home')">🏠 首页</a>
<a onclick="L('books')">📖 书库</a>
<a onclick="L('media')">🎧 媒体</a>
</nav>
<main id="m"></main>
<script>
var A=function(u,cb){var x=new XMLHttpRequest();x.open("GET","/api"+u,true);x.onload=function(){if(x.status==200){cb(JSON.parse(x.responseText));}else{cb(null);}};x.onerror=function(){cb(null);};x.send();};
var FC={pdf:"#ff4d4f",epub:"#1677ff",mobi:"#52c41a",azw3:"#fa8c16",txt:"#666",md:"#722ed1"};
var CC={"计算机与编程":"#1677ff","历史与人文":"#fa8c16","文学与小说":"#52c41a","哲学与思想":"#722ed1","科学与科普":"#13c2c2","经济与管理":"#eb2f96","心理与成长":"#fa541c","教育学习":"#2f54eb","艺术设计":"#a0d911","社会与政治":"#f5222d","生活与健康":"#7cb305","其他":"#999"};
var bP=1,bF="",bS="";

function L(p){if(p=="home")H();else if(p=="books"){bP=1;B();}else if(p=="media")Me();}

function tag(n,c){return '<span class="tag" style="background:'+c+'">'+n+"</span> ";}
function sbox(n,c,l){return '<div class="stat-box"><div class="num" style="color:'+c+'">'+n+'</div><div class="lbl">'+l+"</div></div>";}
function cover(id,big){var s=big?"width:200px;height:260px":"width:60px;height:80px";return id?'<img src="/api/covers/'+id+'.jpg" style="'+s+';object-fit:cover;border-radius:4px;background:#f0f0f0" onerror="this.outerHTML=\'<div class=cover-sm style=display:flex;align-items:center;justify-content:center;color:#fff;font-size:'+(big?'64':'28')+'px>📚</div>\'">':'<div class="cover-sm" style="display:flex;align-items:center;justify-content:center;color:#fff;font-size:'+(big?'64':'28')+'px">📚</div>';}

function H(){document.getElementById("m").innerHTML="<h2>加载中...</h2>";A("/stats",function(s){if(!s)return;var h="<h2>🏠 首页</h2><div style=display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px>";h+=sbox(s.total_books||0,"#1677ff","📚 书籍");h+=sbox(s.with_summary||0,"#52c41a","🤖 已摘要");h+=sbox(Object.keys(s.by_category||{}).length,"#fa8c16","🏷️ 分类");h+=sbox(Object.keys(s.by_format||{}).length,"#722ed1","📄 格式");h+="</div>";var f="",c="";for(var k in s.by_format)f+=tag(k.toUpperCase()+" "+s.by_format[k]+"本",FC[k]||"#999");for(var k in s.by_category)c+=tag(k+" "+s.by_category[k]+"本",CC[k]||"#999");h+='<div style=display:flex;gap:16px;flex-wrap:wrap><div class=panel style=flex:1;min-width:300px><h3>📊 格式分布</h3>'+f+'</div><div class=panel style=flex:1;min-width:300px><h3>🏷️ 分类分布</h3>'+c+"</div></div>";document.getElementById("m").innerHTML=h})}

function B(){document.getElementById("m").innerHTML="<h2>加载中...</h2>";var u="/books?page="+bP+"&page_size=20"+(bF?"&format="+bF:"");if(bS)u="/search?q="+encodeURIComponent(bS)+"&page="+bP+"&page_size=20"+(bF?"&format="+bF:"");A(u,function(d){if(!d)return;var h="<h2>📖 书库</h2><div style=display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap><input id=bs placeholder=搜索书名/作者/出版社 value="+bS+" style=flex:1;min-width:180px;padding:6px 10px;border:1px solid #ddd;border-radius:4px><select id=bf><option value=>全部</option><option value=pdf>PDF</option><option value=epub>EPUB</option></select><button class=\\"btn b\\" onclick=\\"bS=document.getElementById('bs').value;bF=document.getElementById('bf').value;bP=1;B()\\">搜索</button></div><div style=color:#999;margin-bottom:8px>共 "+d.total+" 本</div>";for(var i=0;i<d.items.length;i++){var b=d.items[i],ct="";for(var j=0;j<(b.categories||[]).length;j++)ct+=tag(b.categories[j].name,CC[b.categories[j].name]||"#999");h+='<div class=book-item onclick="D(\\''+b.id+'\\')">'+cover(b.id,false)+'<div style=flex:1;min-width:0><div style=font-weight:bold>'+b.title+'</div><div style=font-size:12px;color:#999;margin-top:2px>'+((b.authors||[]).map(function(a){return a.name}).join(", "))+'</div><div style=margin-top:4px>'+ct+'<span class=tag style=background:'+(FC[b.file_format]||"#999")+'">'+b.file_format.toUpperCase()+"</span></div></div></div>"}if(d.total>20){h+='<div style=text-align:center;margin-top:12px>';for(var i=1;i<=Math.min(Math.ceil(d.total/20),20);i++)h+='<button class=btn'+(i===bP?" b":"")+' onclick="bP='+i+';B()">'+i+"</button> ";h+="</div>"}document.getElementById("m").innerHTML=h;if(bF&&document.getElementById("bf"))document.getElementById("bf").value=bF})}

function D(id){A("/books/"+id,function(b){if(!b)return;var ct="";for(var j=0;j<(b.categories||[]).length;j++)ct+=tag(b.categories[j].name,CC[b.categories[j].name]||"#999");var h='<div class=mbg onclick="if(event.target===this)this.remove()"><div class=min onclick="event.stopPropagation()"><h2 style=margin-top:0>'+b.title+'</h2><div style=display:flex;gap:24px;flex-wrap:wrap><div>'+cover(b.id,true)+'</div><div style=flex:1;min-width:240px><p>作者: '+((b.authors||[]).map(function(a){return a.name}).join(", "))+"</p><p>格式: "+b.file_format.toUpperCase()+" | "+(b.file_size/1024/1024).toFixed(2)+"MB | 页数: "+(b.page_count||"-")+"</p><div style=margin:8px 0>"+ct+"</div>";if(b.summary)h+='<div style=background:#f9f9f9;padding:12px;border-radius:8px;margin:12px 0><b>🤖 AI 摘要</b><p style=white-space:pre-wrap;margin-top:8px;font-size:13px>'+b.summary+"</p></div>";h+="</div></div><div style=margin-top:16px><button class=\\"btn b\\" onclick=\\"event.stopPropagation();window.open('/api/books/"+b.id+"/"+(b.file_format=="pdf"?"file":"read")+"','_blank')\\">📖 阅读</button> <button class=btn onclick=\\"this.closest('.mbg').remove()\\">关闭</button></div></div></div>";document.body.insertAdjacentHTML("beforeend",h)})}

function Me(){document.getElementById("m").innerHTML="<h2>加载中...</h2>";A("/media?page=1&page_size=100",function(d){if(!d)return;var h="<h2>🎧 媒体库</h2><div style=color:#999;margin-bottom:8px>共 "+d.total+" 个</div>";for(var i=0;i<d.items.length;i++){var m=d.items[i],bg=m.media_type=="audio"?"#667eea,#764ba2":"#f093fb,#f5576c",icon=m.media_type=="audio"?"🎵":"🎬",dur=m.duration?Math.floor(m.duration/60)+":"+String(Math.floor(m.duration%60)).padStart(2,"0"):"--";h+='<div class=book-item onclick="PM(\\''+m.id+'\\')"><div style=width:60px;height:60px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:28px;background:linear-gradient(135deg,'+bg+');color:#fff>'+icon+'</div><div style=flex:1><div style=font-weight:bold>'+m.title+'</div><div style=font-size:12px;color:#999>'+m.artist+" | "+m.file_format.toUpperCase()+" | "+dur+"</div></div></div>"}document.getElementById("m").innerHTML=h})}

function PM(id){A("/media/"+id,function(m){if(!m)return;var p=m.media_type=="audio"?'<audio src="/api/media/'+id+'/file" controls style="width:100%;margin-top:12px"></audio>':'<video src="/api/media/'+id+'/file" controls style="width:100%;max-height:60vh;margin-top:12px"></video>';var h='<div class=mbg onclick="if(event.target===this)this.remove()"><div class=min onclick="event.stopPropagation()"><h2>'+m.title+'</h2><p>'+m.artist+" | "+m.file_format.toUpperCase()+"</p>"+p+'<button class=btn style=margin-top:12px onclick="this.closest(\'.mbg\').remove()">关闭</button></div></div>';document.body.insertAdjacentHTML("beforeend",h)})}

L("home");
</script>
</body>
</html>'''

with open("app.html","w",encoding="utf-8") as f:
    f.write(html)
print("OK - app.html generated")
