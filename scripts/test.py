import urllib.request
url = 'https://webview.e2b.bj6.sandbox.cloudstudio.club/app.html?x-cs-sandbox-id=296209f712ea499f98062bee3fb96f00&x-cs-sandbox-port=8000'
try:
    r = urllib.request.urlopen(url, timeout=10)
    with open('app_new.html', 'wb') as f:
        f.write(r.read())
    print('OK')
except Exception as e:
    print('FAIL:', e)
