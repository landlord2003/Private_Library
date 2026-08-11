import re

with open("app.html", "r", encoding="utf-8") as f:
    html = f.read()

# 修小封面 onerror (60x80)
html = html.replace(
    'onerror=this.style.display=none',
    'onerror="var d=document.createElement(\'div\');d.className=\'cv\';d.style.cssText=\'background:linear-gradient(135deg,#667eea,#764ba2);display:flex;align-items:center;justify-content:center;color:#fff;font-size:28px\';d.textContent=\'📚\';this.replaceWith(d)"'
)

# 修大封面 onerror (200x260)
html = html.replace(
    'this.style.display=none',
    'var d=document.createElement(\'div\');d.style.cssText=\'width:200px;height:260px;background:linear-gradient(135deg,#667eea,#764ba2);border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:64px\';d.textContent=\'📚\';this.replaceWith(d)'
)

with open("app.html", "w", encoding="utf-8") as f:
    f.write(html)

print("OK - " + str(len(html)) + " bytes")
