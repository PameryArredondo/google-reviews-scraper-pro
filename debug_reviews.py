import sqlite3
import json

# Connect to the database
con = sqlite3.connect("reviews.db")
con.row_factory = sqlite3.Row
cur = con.cursor()

# Query reviews that actually have an owner response
cur.execute("""
    SELECT author, review_date, owner_response_date, owner_responses
    FROM reviews
    WHERE owner_responses != '{}'
    AND owner_responses IS NOT NULL
    LIMIT 10
""")

rows = cur.fetchall()

if not rows:
    print("No reviews with owner responses found in the database.")

for row in rows:
    print("Author:             ", row["author"])
    print("Review Date:        ", row["review_date"])
    print("Owner Answer Date:  ", row["owner_response_date"])
    print("Owner Answer Text:  ", row["owner_responses"])
    print("-" * 50)

con.close()