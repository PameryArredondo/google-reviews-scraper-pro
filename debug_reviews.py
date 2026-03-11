import sqlite3
import json

con = sqlite3.connect("reviews.db")
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute("""
    SELECT author, owner_responses
    FROM reviews
    WHERE owner_responses != '{}'
    AND owner_responses IS NOT NULL
    LIMIT 5
""")
for row in cur.fetchall():
    print("author:", row["author"])
    print("owner_responses:", row["owner_responses"])
    print("---")

con.close()