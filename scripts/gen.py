cd /d F:\my-library
echo import urllib.request > gen.py
echo url = "https://webview.e2b.bj6.sandbox.cloudstudio.club/app.html?x-cs-sandbox-id=296209f712ea499f98062bee3fb96f00&x-cs-sandbox-port=8000" >> gen.py
echo try: >> gen.py
echo     r = urllib.request.urlopen(url, timeout=10) >> gen.py
echo     open("app.html","wb").write(r.read()) >> gen.py
echo     print("OK") >> gen.py
echo except Exception as e: >> gen.py
echo     print("FAIL:", e) >> gen.py
python gen.py
