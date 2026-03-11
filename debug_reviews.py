import sqlite3

# Connect to the database
con = sqlite3.connect("reviews.db")
con.row_factory = sqlite3.Row
cur = con.cursor()

# --- Inspect available columns first ---
cur.execute("PRAGMA table_info(reviews)")
columns = [row["name"] for row in cur.fetchall()]
print("Columns in 'reviews' table:")
print(columns)
print("-" * 50)

# --- Check which owner-related columns exist ---
owner_text_col  = next((c for c in columns if "owner" in c.lower() and "text" in c.lower()), None)
owner_date_col  = next((c for c in columns if "owner" in c.lower() and "date" in c.lower()), None)

# Fallback: just print all owner-related columns found
owner_cols = [c for c in columns if "owner" in c.lower()]
print("Owner-related columns found:", owner_cols)
print("-" * 50)

if not owner_cols:
    print("No owner-related columns found at all. Owner responses may not be saved to the DB yet.")
    con.close()
    exit()

# --- Use whatever columns actually exist ---
text_col = owner_text_col or (owner_cols[0] if owner_cols else None)
date_col = owner_date_col or (owner_cols[1] if len(owner_cols) > 1 else None)

select_cols = ", ".join(filter(None, ["author", "review_date", date_col, text_col]))
where_col   = text_col or owner_cols[0]

query = f"""
    SELECT {select_cols}
    FROM reviews
    WHERE {where_col} IS NOT NULL
      AND TRIM({where_col}) != ''
    LIMIT 10
"""

print(f"Running query:\n{query}")
print("-" * 50)

cur.execute(query)
rows = cur.fetchall()

if not rows:
    print("No reviews with owner responses found in the database.")
    print("Tip: Check if owner selectors in RawReview.OWNER_RESP_SELECTORS are still valid for the current Google Maps DOM.")
else:
    for row in rows:
        print("Author:            ", row["author"])
        print("Review Date:       ", row["review_date"])
        if date_col:
            print("Owner Answer Date: ", row[date_col])
        print("Owner Answer Text: ", row[text_col])
        print("-" * 50)

con.close()