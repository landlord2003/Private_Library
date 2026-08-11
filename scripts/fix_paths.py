import sqlite3
c = sqlite3.connect('data/library.db')
# 用内置函数一次搞定
c.execute("UPDATE books SET file_path = REPLACE(REPLACE(file_path,'G:','F:'),'F:\\my-library','F:\\my-library')")
c.execute("UPDATE media SET file_path = REPLACE(REPLACE(file_path,'G:','F:'),'F:\\my-library','F:\\my-library')")
c.commit()
print("OK")
c.close()
