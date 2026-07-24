import sqlite3
conn = sqlite3.connect('/home/hermeswebui/.hermes/state.db')
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
for row in cursor:
    print(row[0])
print("---SCHEMA---")
cursor = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'")
for row in cursor:
    if row[0]:
        print(row[0])
        print()
conn.close()
