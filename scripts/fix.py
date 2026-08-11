import re
h = open("app.html", "r", encoding="utf-8").read()
h = re.sub(r' onerror=.*?(?= style=| class=|>)', '', h)
open("app.html", "w", encoding="utf-8").write(h)
print("OK " + str(len(h)))
