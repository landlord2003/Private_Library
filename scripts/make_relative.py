import sqlite3, os

c = sqlite3.connect('data/library.db')

# 找所有含盘符的路径，改成相对路径
for tbl in ['books', 'media']:
    rows = c.execute(f"SELECT id, file_path FROM {tbl} WHERE file_path LIKE '%:\\%' OR file_path LIKE '%\\\\data\\\\%' ORDER BY file_path").fetchall()
    fixed = 0
    for rid, fp in rows:
        # 找 data\ 的位置
        idx = fp.replace('/', '\\').find('data\\')
        if idx >= 0:
            new_path = fp[idx:]  # data\books\xxx\original.pdf
            # 统一成反斜杠
            new_path = new_path.replace('/', '\\')
            c.execute(f"UPDATE {tbl} SET file_path=? WHERE id=?", (new_path, rid))
            fixed += 1
    print(f'{tbl}: 修正 {fixed}/{len(rows)} 条')

c.commit()

# 验证
sample = c.execute("SELECT file_path FROM books LIMIT 3").fetchall()
print('\n最终路径示例:')
for s in sample:
    print(f'  {s[0]}')
c.close()
print('\nDone')
