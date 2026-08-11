"""自动循环分类"""
import urllib.request, json, time

while True:
    try:
        req = urllib.request.Request("http://localhost:8000/api/classify-all", method="POST")
        resp = urllib.request.urlopen(req, timeout=3600)
        data = json.loads(resp.read())
        print(json.dumps(data, ensure_ascii=False))
        if data.get("message") == "所有书籍已有分类" or data.get("total",0) == 0:
            print("\n全部完成！")
            break
    except Exception as e:
        print(f"出错: {e}，30秒后重试...")
        time.sleep(30)
