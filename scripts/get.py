import urllib.request
url = "http://localhost:8000/simple_server_new.py"
try:
    r = urllib.request.urlopen(url, timeout=10)
    open("simple_server.py", "wb").write(r.read())
    print("OK")
except Exception as e:
    print("FAIL:", e)
