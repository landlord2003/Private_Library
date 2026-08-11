import sqlite3
c = sqlite3.connect('data/library.db')
cur = c.execute('DELETE FROM categories WHERE id NOT IN (SELECT DISTINCT category_id FROM book_categories)')
c.commit()
print('Deleted:', cur.rowcount)
c.close()
