s = open("simple_server.py", "r", encoding="utf-8").read()

# A. Fix summary count
old = "AND summary IS NULL AND text_content IS NOT NULL LIMIT 3"
new = "AND summary IS NULL AND text_content IS NOT NULL AND text_content!='' LIMIT 3"
s = s.replace(old, new)

old2 = "AND text_content IS NOT NULL) AND id NOT IN"
new2 = "AND text_content IS NOT NULL AND text_content!='') AND id NOT IN"
s = s.replace(old2, new2)

# B. Fix remaining summary count on homepage
old3 = "AND text_content IS NOT NULL\""
new3 = "AND text_content IS NOT NULL AND text_content!=''\""
s = s.replace(old3, new3)

# C. Fix LIMIT 5 -> LIMIT 10
s = s.replace("LIMIT 5", "LIMIT 10")

# D. Fix LIMIT 80 -> paginated 20
old4 = "ORDER BY created_at DESC LIMIT 80"
new4 = "ORDER BY created_at DESC LIMIT 20"
s = s.replace(old4, new4)

open("simple_server.py", "w", encoding="utf-8").write(s)
print("OK - patched")

