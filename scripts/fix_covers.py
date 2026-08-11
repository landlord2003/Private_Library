import sqlite3
c = sqlite3.connect('data/library.db')
c.execute("UPDATE books SET cover_path = 'data/covers/' || id || '.jpg' WHERE cover_path LIKE '%covers%'")
c.commit()
print('Fixed:', c.total_changes)
c.close()
