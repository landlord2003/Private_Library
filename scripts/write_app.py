# coding: utf-8
import os

lines = []
lines.append("<!DOCTYPE html>")
lines.append('<html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">')
lines.append("<title>我的图书馆</title>")
lines.append("<style>")
lines.append("*{margin:0;padding:0;box-sizing:border-box}")
lines.append("body{font-family:sans-serif;background:#f5f5f5;display:flex;min-height:100vh}")
lines.append("nav{width:180px;background:#fff;padding:20px 0;border-right:1px solid #eee;flex-shrink:0}")
lines.append("nav h2{padding:0 20px 16px;color:#1677ff;font-size:18px}")
lines.append("nav a{display:block;padding:10px 20px;color:#333;text-decoration:none;font-size:14px;cursor:pointer}")
lines.append("nav a:hover{background:#e6f4ff;color:#1677ff}")
lines.append("main{flex:1;padding:20px;overflow-y:auto}")
lines.append(".tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;margin:2px;color:#fff}")
lines.append(".btn{padding:6px 14px;border:1px solid #ddd;border-radius:4px;cursor:pointer;background:#fff;margin:2px}")
lines.append(".btn.b{background:#1677ff;color:#fff;border-color:#1677ff}")
lines.append("input,select{padding:6px 10px;border:1px solid #ddd;border-radius:4px}")
lines.append(".stat-box{background:#fff;padding:20px;border-radius:8px;text-align:center;min-width:130px}")
lines.append(".stat-box .num{font-size:32px;font-weight:bold}")
lines.append(".stat-box .lbl{font-size:13px;color:#999;margin-top:4px}")
lines.append(".panel{background:#fff;padding:16px;border-radius:8px}")
lines.append("</style></head><body>")
lines.append('<nav><h2>📚 我的图书馆</h2>')
lines.append('<a onclick="loadPage(\'home\')">🏠 首页</a>')
lines.append('<a onclick="loadPage(\'books\')">📖 书库</a>')
lines.append('<a onclick="loadPage(\'media\')">🎧 媒体库</a>')
lines.append('</nav><main id="main">加载中...</main>')
lines.append("<script>")
lines.append('var FC={pdf:"#ff4d4f",epub:"#1677ff",mobi:"#52c41a",azw3:"#fa8c16",txt:"#666",md:"#722ed1"};')
lines.append('var CC={"计算机与编程":"#1677ff","历史与人文":"#fa8c16","文学与小说":"#52c41a","哲学与思想":"#722ed1","科学与科普":"#13c2c2","经济与管理":"#eb2f96","心理与成长":"#fa541c","教育学习":"#2f54eb","艺术设计":"#a0d911","社会与政治":"#f5222d","生活与健康":"#7cb305","其他":"#999"};')
lines.append('var bPage=1,bFmt="",bSearch="";')

with open("app.html","w",encoding="utf-8") as f:
    f.write("\n".join(lines))
print("Part 1 written")

# Part 2: JavaScript functions
js = '''
function M(h){document.getElementById("main").innerHTML=h;}

function G(u,cb){
  var x=new XMLHttpRequest();
  x.open("GET","/api"+u,true);
  x.onload=function(){if(x.status===200){try{cb(JSON.parse(x.responseText));}catch(e){cb(null);}}else{cb(null);}};
  x.onerror=function(){cb(null);};
  x.send();
}

function loadPage(p){
  if(p==="home")loadHome();
  else if(p==="books"){bPage=1;loadBooks();}
  else if(p==="media")loadMedia();
}

function loadHome(){
  M("<h2>加载中...</h2>");
  G("/stats",function(s){
    if(!s){M("<h2>服务器未连接</h2>");return;}
    var t=s.total_books||0;
    var fmt="";
    for(var f in s.by_format){
      fmt+='<span class="tag" style="background:'+(FC[f]||"#999")+'">'+f.toUpperCase()+" "+s.by_format[f]+"本</span> ";
    }
    var cat="";
    for(var c in s.by_category){
      cat+='<span class="tag" style="background:'+(CC[c]||"#999")+'">'+c+" "+s.by_category[c]+"本</span> ";
    }
    var au="";
    (s.top_authors||[]).forEach(function(a){
      au+='<div style="font-size:13px;padding:2px 0"><span>'+a.name+'</span> <span style="color:#999">'+a.count+"本</span></div>";
    });
    var html='<h2>🏠 首页</h2>';
    html+='<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px">';
    html+='<div class="stat-box"><div class="num" style="color:#1677ff">'+t+'</div><div class="lbl">📚 书籍</div></div>';
    html+='<div class="stat-box"><div class="num" style="color:#52c41a">'+(s.with_summary||0)+'</div><div class="lbl">🤖 已摘要</div></div>';
    html+='<div class="stat-box"><div class="num" style="color:#fa8c16">'+Object.keys(s.by_category||{}).length+'</div><div class="lbl">🏷️ 分类</div></div>';
    html+='<div class="stat-box"><div class="num" style="color:#722ed1">'+Object.keys(s.by_format||{}).length+'</div><div class="lbl">📄 格式</div></div>';
    html+="</div>";
    html+='<div style="display:flex;gap:16px;flex-wrap:wrap">';
    html+='<div class="panel" style="flex:1;min-width:300px"><h3>📊 格式分布</h3>'+fmt+"</div>";
    html+='<div class="panel" style="flex:1;min-width:300px"><h3>🏷️ 分类分布</h3>'+cat+"</div>";
    html+="</div>";
    html+='<div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:16px">';
    html+='<div class="panel" style="flex:1;min-width:250px"><h3>👤 热门作者</h3>'+au+"</div>";
    html+="</div>";
    M(html);
  });
}

function loadBooks(){
  M("<h2>加载中...</h2>");
  var url="/books?page="+bPage+"&page_size=20"+(bFmt?"&format="+bFmt:"");
  if(bSearch)url="/search?q="+encodeURIComponent(bSearch)+"&page="+bPage+"&page_size=20"+(bFmt?"&format="+bFmt:"");
  G(url,function(d){
    if(!d){M("<h2>加载失败</h2>");return;}
    var h='<h2>📖 书库</h2>';
    h+='<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">';
    h+='<input id="bs" placeholder="搜索书名/作者/出版社" value="'+bSearch+'" style="flex:1;min-width:200px;padding:6px 10px;border:1px solid #ddd;border-radius:4px">';
    h+='<select id="bf"><option value="">全部格式</option><option value="pdf">PDF</option><option value="epub">EPUB</option><option value="mobi">MOBI</option><option value="txt">TXT</option></select>';
    h+='<button class="btn b" onclick="bSearch=document.getElementById(\'bs\').value;bFmt=document.getElementById(\'bf\').value;bPage=1;loadBooks()">搜索</button>';
    h+="</div>";
    h+='<div style="color:#999;margin-bottom:8px">共 '+d.total+" 本</div>";
    (d.items||[]).forEach(function(b){
      var ct="";
      (b.categories||[]).forEach(function(x){ct+='<span class="tag" style="background:'+(CC[x.name]||"#999")+'">'+x.name+"</span> ";});
      var cv=b.cover_path?'<img src="/api/covers/'+b.id+'.jpg" style="width:60px;height:80px;object-fit:cover;border-radius:4px" onerror="this.style.display=none">':'<div style="width:60px;height:80px;background:linear-gradient(135deg,#667eea,#764ba2);border-radius:4px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:28px">📚</div>';
      h+='<div style="background:#fff;border-radius:8px;padding:14px;margin-bottom:8px;display:flex;gap:12px;align-items:center;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.08)" onclick="showBook(\''+b.id+'\')">';
      h+=cv;
      h+='<div style="flex:1;min-width:0"><div style="font-weight:bold">'+b.title+'</div>';
      h+='<div style="font-size:12px;color:#999">'+(b.authors||[]).map(function(a){return a.name}).join(", ")+'</div>';
      h+='<div style="margin-top:4px">'+ct+'<span class="tag" style="background:'+(FC[b.file_format]||"#999")+'">'+b.file_format.toUpperCase()+"</span></div>";
      h+="</div></div>";
    });
    if(d.total>20){
      h+='<div style="text-align:center;margin-top:12px">';
      for(var i=1;i<=Math.min(Math.ceil(d.total/20),20);i++){
        h+='<button class="btn'+(i===bPage?" b":"")+'" onclick="bPage='+i+';loadBooks()">'+i+"</button> ";
      }
      h+="</div>";
    }
    M(h);
    if(bFmt)document.getElementById("bf").value=bFmt;
  });
}

function showBook(id){
  G("/books/"+id,function(b){
    if(!b)return;
    var cats="";
    (b.categories||[]).forEach(function(x){cats+='<span class="tag" style="background:'+(CC[x.name]||"#999")+'">'+x.name+"</span> ";});
    var cv=b.cover_path?'<img src="/api/covers/'+b.id+'.jpg" style="width:200px;height:260px;object-fit:contain;border-radius:8px;background:#f5f5f5">':'<div style="width:200px;height:260px;background:linear-gradient(135deg,#667eea,#764ba2);border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:64px">📚</div>';
    var html='<div onclick="if(event.target===this)this.remove()" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);z-index:999;display:flex;align-items:center;justify-content:center;padding:20px">';
    html+='<div onclick="event.stopPropagation()" style="background:#fff;border-radius:12px;padding:24px;max-width:800px;width:100%;max-height:90vh;overflow-y:auto">';
    html+='<h2 style="margin-top:0">'+b.title+"</h2>";
    html+='<div style="display:flex;gap:24px;flex-wrap:wrap">';
    html+='<div>'+cv+"</div>";
    html+='<div style="flex:1;min-width:240px">';
    html+='<p>作者: '+(b.authors||[]).map(function(a){return a.name}).join(", ")+"</p>";
    html+='<p>格式: '+b.file_format.toUpperCase()+" | "+(b.file_size/1024/1024).toFixed(2)+"MB | 页数: "+(b.page_count||"-")+"</p>";
    html+='<div style="margin:8px 0">'+cats+"</div>";
    if(b.summary){
      html+='<div style="background:#f9f9f9;padding:12px;border-radius:8px;margin:12px 0"><b>🤖 AI 摘要</b><p style="white-space:pre-wrap;margin-top:8px;font-size:13px">'+b.summary+"</p></div>";
    }
    html+="</div></div>";
    html+='<div style="margin-top:16px"><button class="btn b" onclick="event.stopPropagation();readBook(\''+b.id+'\',\''+b.file_format+'\')">📖 阅读</button> <button class="btn" onclick="this.closest(\'div[style*=fixed]\').remove()">关闭</button></div>';
    html+="</div></div>";
    document.body.insertAdjacentHTML("beforeend",html);
  });
}

function readBook(id,fmt){
  if(fmt==="pdf")window.open("/api/books/"+id+"/file","_blank");
  else window.open("/api/books/"+id+"/read","_blank");
}

function loadMedia(){
  M("<h2>加载中...</h2>");
  G("/media?page=1&page_size=100",function(d){
    if(!d){M("<h2>加载失败</h2>");return;}
    var h='<h2>🎧 媒体库</h2>';
    h+='<div style="color:#999;margin-bottom:8px">共 '+d.total+" 个</div>";
    (d.items||[]).forEach(function(m){
      h+='<div style="background:#fff;border-radius:8px;padding:14px;margin-bottom:8px;display:flex;gap:12px;align-items:center;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.08)" onclick="playM(\''+m.id+'\')">';
      h+='<div style="width:60px;height:60px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:28px;background:linear-gradient(135deg,'+(m.media_type==="audio"?"#667eea,#764ba2":"#f093fb,#f5576c")+');color:#fff">'+(m.media_type==="audio"?"🎵":"🎬")+"</div>";
      h+='<div style="flex:1"><div style="font-weight:bold">'+m.title+"</div>";
      h+='<div style="font-size:12px;color:#999">'+m.artist+" | "+m.file_format.toUpperCase()+" | "+(m.duration?Math.floor(m.duration/60)+":"+String(Math.floor(m.duration%60)).padStart(2,"0"):"--")+"</div>";
      h+="</div></div>";
    });
    M(h);
  });
}

function playM(id){
  G("/media/"+id,function(m){
    if(!m)return;
    var p=m.media_type==="audio"?"<audio src=\"/api/media/"+id+"/file\" controls style=\"width:100%;margin-top:12px\"></audio>":"<video src=\"/api/media/"+id+"/file\" controls style=\"width:100%;max-height:60vh;margin-top:12px\"></video>";
    var html='<div onclick="if(event.target===this)this.remove()" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);z-index:999;display:flex;align-items:center;justify-content:center;padding:20px">';
    html+='<div onclick="event.stopPropagation()" style="background:#fff;border-radius:12px;padding:24px;max-width:800px;width:100%">';
    html+="<h2 style=\"margin-top:0\">"+m.title+"</h2>";
    html+="<p>"+m.artist+" | "+m.file_format.toUpperCase()+"</p>";
    html+=p;
    html+="<button class=\"btn\" style=\"margin-top:12px\" onclick=\"this.closest('div[style*=fixed]').remove()\">关闭</button></div></div>";
    document.body.insertAdjacentHTML("beforeend",html);
  });
}

loadHome();
'''

with open("app.html","a",encoding="utf-8") as f:
    f.write("</script></body></html>\n")
    # 在 </script> 前插入 js
    import io
    with open("app.html","rb") as fin:
        content = fin.read()
    content = content.replace(b"</script></body>", js.encode('utf-8') + b"</script></body>")
    with open("app.html","wb") as fout:
        fout.write(content)

print("Done - app.html written")
