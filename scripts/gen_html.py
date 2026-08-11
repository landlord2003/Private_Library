js = '''var FC={pdf:"#ff4d4f",epub:"#1677ff",mobi:"#52c41a",azw3:"#fa8c16",txt:"#666",md:"#722ed1"};
var CC={"计算机与编程":"#1677ff","历史与人文":"#fa8c16","文学与小说":"#52c41a","哲学与思想":"#722ed1","科学与科普":"#13c2c2","经济与管理":"#eb2f96","心理与成长":"#fa541c","教育学习":"#2f54eb","艺术设计":"#a0d911","社会与政治":"#f5222d","生活与健康":"#7cb305","其他":"#999"};
var bP=1,bF="",bS="";

function Q(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}

function A(u,cb){
  var x=new XMLHttpRequest();
  x.open("GET","/api"+u,true);
  x.onload=function(){if(x.status==200){try{cb(JSON.parse(x.responseText));}catch(e){cb(null);}}else{cb(null);}};
  x.onerror=function(){cb(null);};
  x.send();
}

function L(i){
  if(i==0)H();
  else if(i==1){bP=1;B();}
  else if(i==2)Me();
}

function H(){
  document.getElementById("m").innerHTML="<h2>Loading...</h2>";
  A("/stats",function(s){
    if(!s){document.getElementById("m").innerHTML="<h2>Cannot connect</h2>";return;}
    var h="<h2>Home</h2><div style=display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px>";
    h+='<div class=box><div class=n style=color:#1677ff>'+(s.total_books||0)+'</div><div class=l>Books</div></div>';
    h+='<div class=box><div class=n style=color:#52c41a>'+(s.with_summary||0)+'</div><div class=l>Summarized</div></div>';
    h+='<div class=box><div class=n style=color:#fa8c16>'+Object.keys(s.by_category||{}).length+'</div><div class=l>Categories</div></div>';
    h+='<div class=box><div class=n style=color:#722ed1>'+Object.keys(s.by_format||{}).length+'</div><div class=l>Formats</div></div></div>';
    var fmt="",cat="";
    for(var k in s.by_format) fmt+='<span class=tag style=background:'+(FC[k]||"#999")+">"+k.toUpperCase()+" "+s.by_format[k]+"</span> ";
    for(var k in s.by_category) cat+='<span class=tag style=background:'+(CC[k]||"#999")+">"+k+" "+s.by_category[k]+"</span> ";
    h+='<div style=display:flex;gap:16px;flex-wrap:wrap><div class=panel style=flex:1;min-width:300px><h3>Formats</h3>'+fmt+'</div><div class=panel style=flex:1;min-width:300px><h3>Categories</h3>'+cat+"</div></div>";
    document.getElementById("m").innerHTML=h;
  });
}

function B(){
  document.getElementById("m").innerHTML="<h2>Loading...</h2>";
  var u="/books?page="+bP+"&page_size=20"+(bF?"&format="+bF:"");
  if(bS) u="/search?q="+encodeURIComponent(bS)+"&page="+bP+"&page_size=20"+(bF?"&format="+bF:"");
  A(u,function(d){
    if(!d){document.getElementById("m").innerHTML="<h2>Failed</h2>";return;}
    var h="<h2>Books</h2>";
    h+='<div style=display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap><input id=bs placeholder=Search value="+bS+" style=flex:1;min-width:180px;padding:6px 10px;border:1px solid #ddd;border-radius:4px><select id=bf><option value=>All</option><option value=pdf>PDF</option><option value=epub>EPUB</option></select><button class="btn b" onclick="bS=document.getElementById(\'bs\').value;bF=document.getElementById(\'bf\').value;bP=1;B()">Search</button></div>';
    h+='<div style=color:#999;margin-bottom:8px>Total: '+d.total+"</div>";
    for(var i=0;i<d.items.length;i++){
      var b=d.items[i];
      var ct="";
      for(var j=0;j<(b.categories||[]).length;j++) ct+='<span class=tag style=background:'+(CC[b.categories[j].name]||"#999")+">"+b.categories[j].name+"</span> ";
      var cv=b.cover_path?"<img src=/api/covers/"+b.id+".jpg class=cv>":"<div class=cv style=background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;color:#fff;font-size:28px>📚</div>";
      h+='<div class=bi onclick="D(\\''+b.id+'\\')">'+cv+'<div style=flex:1;min-width:0><div style=font-weight:bold>'+Q(b.title)+'</div><div style=font-size:12px;color:#999>'+Q((b.authors||[]).map(function(a){return a.name}).join(", "))+'</div><div style=margin-top:4px>'+ct+'<span class=tag style=background:'+(FC[b.file_format]||"#999")+'">'+b.file_format.toUpperCase()+"</span></div></div></div>";
    }
    if(d.total>20){
      h+='<div style=text-align:center;margin-top:12px>';
      for(var i=1;i<=Math.min(Math.ceil(d.total/20),20);i++) h+='<button class=btn'+(i===bP?" b":"")+' onclick="bP='+i+';B()">'+i+"</button> ";
      h+="</div>";
    }
    document.getElementById("m").innerHTML=h;
    if(bF&&document.getElementById("bf")) document.getElementById("bf").value=bF;
  });
}

function D(id){
  A("/books/"+id,function(b){
    if(!b)return;
    var ct="";
    for(var j=0;j<(b.categories||[]).length;j++) ct+='<span class=tag style=background:'+(CC[b.categories[j].name]||"#999")+">"+b.categories[j].name+"</span> ";
    var cv=b.cover_path?"<img src=/api/covers/"+b.id+".jpg style=width:200px;height:260px;object-fit:contain;border-radius:8px;background:#f5f5f5>":"<div style=width:200px;height:260px;background:linear-gradient(135deg,#667eea,#764ba2);border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:64px>📚</div>";
    var h='<div class=mbg onclick="if(event.target===this)this.remove()"><div class=min onclick="event.stopPropagation()"><h2 style=margin-top:0>'+Q(b.title)+'</h2><div style=display:flex;gap:24px;flex-wrap:wrap><div>'+cv+'</div><div style=flex:1;min-width:240px><p>Author: '+Q((b.authors||[]).map(function(a){return a.name}).join(", "))+"</p><p>Format: "+b.file_format.toUpperCase()+" | "+(b.file_size/1024/1024).toFixed(2)+"MB | Pages: "+(b.page_count||"-")+"</p><div style=margin:8px 0>"+ct+"</div>";
    if(b.summary) h+='<div style=background:#f9f9f9;padding:12px;border-radius:8px;margin:12px 0><b>AI Summary</b><p style=white-space:pre-wrap;margin-top:8px;font-size:13px>'+Q(b.summary)+"</p></div>";
    h+="</div></div><div style=margin-top:16px><button class=\\"btn b\\" onclick=\\"event.stopPropagation();window.open('/api/books/"+b.id+"/"+(b.file_format=="pdf"?"file":"read")+"','_blank')\\">Read</button> <button class=btn onclick=\\"this.closest('.mbg').remove()\\">Close</button></div></div></div>";
    document.body.insertAdjacentHTML("beforeend",h);
  });
}

function Me(){
  document.getElementById("m").innerHTML="<h2>Loading...</h2>";
  A("/media?page=1&page_size=100",function(d){
    if(!d){document.getElementById("m").innerHTML="<h2>Failed</h2>";return;}
    var h="<h2>Media</h2><div style=color:#999;margin-bottom:8px>Total: "+d.total+"</div>";
    for(var i=0;i<d.items.length;i++){
      var m=d.items[i];
      var bg=m.media_type=="audio"?"#667eea,#764ba2":"#f093fb,#f5576c";
      var icon=m.media_type=="audio"?"🎵":"🎬";
      var dur=m.duration?Math.floor(m.duration/60)+":"+String(Math.floor(m.duration%60)).padStart(2,"0"):"--";
      h+='<div class=bi onclick="PM(\\''+m.id+'\\')"><div style=width:60px;height:60px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:28px;background:linear-gradient(135deg,'+bg+');color:#fff>'+icon+'</div><div style=flex:1><div style=font-weight:bold>'+Q(m.title)+'</div><div style=font-size:12px;color:#999>'+Q(m.artist)+" | "+m.file_format.toUpperCase()+" | "+dur+"</div></div></div>";
    }
    document.getElementById("m").innerHTML=h;
  });
}

function PM(id){
  A("/media/"+id,function(m){
    if(!m)return;
    var p=m.media_type=="audio"?"<audio src=/api/media/"+id+"/file controls style=width:100%;margin-top:12px></audio>":"<video src=/api/media/"+id+"/file controls style=width:100%;max-height:60vh;margin-top:12px></video>";
    var h='<div class=mbg onclick="if(event.target===this)this.remove()"><div class=min onclick="event.stopPropagation()"><h2>'+Q(m.title)+'</h2><p>'+Q(m.artist)+" | "+m.file_format.toUpperCase()+"</p>"+p+'<button class=btn style=margin-top:12px onclick="this.closest(\'.mbg\').remove()">Close</button></div></div>';
    document.body.insertAdjacentHTML("beforeend",h);
  });
}

L(0);'''

with open("app.js","w",encoding="utf-8") as f:
    f.write(js)
print("OK - app.js written, " + str(len(js)) + " bytes")
