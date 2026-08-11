import sqlite3
conn = sqlite3.connect('data/library.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.execute('VACUUM')
conn.close()
print('Database optimized')
