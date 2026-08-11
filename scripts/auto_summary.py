"""自动循环摘要，跑完为止"""
import urllib.request, json, time

while True:
    try:
        req = urllib.request.Request("http://localhost:8000/api/summary/books/batch", method="POST")
        resp = urllib.request.urlopen(req, timeout=1200)
        data = json.loads(resp.read())
        print(json.dumps(data, ensure_ascii=False))
        
        if data.get("message") == "所有书籍已有摘要":
            print("\n全部完成！")
            break
        if data.get("total", 0) == 0:
            print("\n全部完成！")
            break
    except Exception as e:
        print(f"出错: {e}，30秒后重试...")
        time.sleep(30)
