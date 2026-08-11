import sqlite3
c = sqlite3.connect('data/library.db')
rows = c.execute("SELECT name, count(*) as cnt FROM categories GROUP BY name HAVING cnt>1").fetchall()
print('重名分类:')
for r in rows:
    print(f'  {r[0]}: {r[1]}个')
if not rows:
    print('  无重名')
c.close()
