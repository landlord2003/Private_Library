import sqlite3
db = sqlite3.connect("data/library.db")
db.execute("DELETE FROM book_categories")
db.execute("DELETE FROM book_tags")
db.execute("DELETE FROM tags")
db.execute("UPDATE books SET difficulty=NULL")
db.commit()
print("Cleared")
db.close()
