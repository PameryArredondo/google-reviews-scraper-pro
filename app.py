import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import pytz
import json
from io import BytesIO
import requests
import subprocess
from packaging.version import Version

DB_PATH = "reviews.db"  # adjust path if needed
LOCAL_VERSION = "1.2.1"  # update this when you git pull
GITHUB_REPO  = "georgekhananaev/google-reviews-scraper-pro"
EST = pytz.timezone("America/New_York")

def to_est_date(utc_str):
    """Convert UTC ISO string to EST date only (no time)."""
    if not utc_str:
        return None
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(EST).strftime("%Y-%m-%d")
    except Exception:
        return None

def to_utc_str(utc_str):
    """Normalize UTC ISO string."""
    if not utc_str:
        return None
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return utc_str

def extract_text(field, lang="en"):
    """Extract text from JSON description/owner_responses field."""
    if not field:
        return None
    try:
        data = json.loads(field) if isinstance(field, str) else field
        if isinstance(data, dict):
            # Try requested lang first, then first available
            if lang in data:
                val = data[lang]
                return val.get("text", val) if isinstance(val, dict) else val
            for v in data.values():
                return v.get("text", v) if isinstance(v, dict) else v
    except Exception:
        return field
    return None

def load_reviews(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    # Discover actual column names
    cur.execute("PRAGMA table_info(reviews)")
    cols = {row[1] for row in cur.fetchall()}

    text_col        = "review_text"   if "review_text"   in cols else "description"
    owner_text_col  = "owner_responses" if "owner_responses" in cols else "owner_reply"
    owner_date_col  = "last_modified" if "last_modified"  in cols else "owner_response_date"
    rating_col      = "rating"        if "rating"        in cols else "stars"
    date_col        = "review_date"   if "review_date"   in cols else "date"
    deleted_col     = "is_deleted"    if "is_deleted"    in cols else None
    params_col      = "custom_params" if "custom_params" in cols else None

    where = f"WHERE r.{deleted_col} = 0" if deleted_col else ""

    cur.execute(f"""
        SELECT
            r.author,
            r.{text_col}        AS description,
            r.{owner_text_col}  AS owner_responses,
            r.{owner_date_col}  AS owner_response_date,
            r.{rating_col}      AS rating,
            r.{date_col}        AS review_date,
            p.name              AS place_name,
            {'r.' + params_col + ' AS custom_params' if params_col else 'NULL AS custom_params'}
        FROM reviews r
        LEFT JOIN places p ON r.place_id = p.place_id
        {where}
        ORDER BY r.{date_col} DESC
    """)
    rows = cur.fetchall()
    con.close()
    return rows

def build_dataframe(rows):
    records = []
    for r in rows:
        # Resolve business name: custom_params > places.name
        name = None
        try:
            cp = json.loads(r["custom_params"]) if r["custom_params"] else {}
            name = cp.get("company") or r["place_name"]
        except Exception:
            name = r["place_name"]

        owner_text = extract_text(r["owner_responses"])
        owner_date_utc = r["owner_response_date"]

        records.append({
            "name":                                  name,
            "author_title":                          r["author"],
            "review_text":                           extract_text(r["description"]),
            "owner_answer":                          owner_text,
            "owner_answer_timestamp_datetime_EST DATE ONLY": to_est_date(owner_date_utc),
            "owner_answer_timestamp_datetime_utc":   to_utc_str(owner_date_utc),
            "review_rating":                         r["rating"],
            "review_datetime_EST DATE ONLY":         to_est_date(r["review_date"]),
            "review_datetime_utc":                   to_utc_str(r["review_date"]),
        })
    return pd.DataFrame(records)

def to_excel(df):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Reviews")
        # Auto-size columns
        ws = writer.sheets["Reviews"]
        for col in ws.columns:
            max_len = max((len(str(c.value)) for c in col if c.value), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)
    buf.seek(0)
    return buf

def check_scraper_version():
    """Returns (is_outdated, latest_version) or (None, None) on failure."""
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=5
        )
        if r.status_code == 200:
            latest = r.json().get("tag_name", "").lstrip("v")
            return Version(latest) > Version(LOCAL_VERSION), latest
    except Exception:
        pass
    return None, None

# ── UI ──────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Google Reviews Export", page_icon="⭐", layout="centered")
st.title("⭐ Google Reviews Export")
st.caption("Reads from the local scraper database and exports to Excel.")

# Version check
is_outdated, latest = check_scraper_version()
if is_outdated:
    st.warning(
        f"⚠️ Scraper update available (v{latest}). "
        f"Update before your next scrape to stay current.",
        icon="⚠️"
    )
    st.link_button(
        "⬇️ Download Latest Version",
        f"https://github.com/{GITHUB_REPO}/releases/latest"
    )
elif is_outdated is None:
    st.info("Could not check for scraper updates — GitHub may be unreachable.", icon="ℹ️")

try:
    rows = load_reviews(DB_PATH)
    df = build_dataframe(rows)

    # Metrics
    avg_rating = df["review_rating"].mean()
    has_owner = df["owner_answer"].notna() & (df["owner_answer"] != "")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Reviews", len(df))
    col2.metric("Average Rating", f"{avg_rating:.2f} ⭐")
    col3.metric("Owner Responses", has_owner.sum())

    # Per-star breakdown
    st.divider()
    st.subheader("Rating Breakdown")
    star_cols = st.columns(5)
    for i, star in enumerate(range(5, 0, -1)):
        count = (df["review_rating"] == star).sum()
        pct = (count / len(df) * 100) if len(df) else 0
        star_cols[i].metric(f"{'⭐' * star}", f"{count}", delta=f"{pct:.1f}%", delta_color="off")

    # Preview
    with st.expander("Preview data", expanded=True):
        st.dataframe(df, use_container_width=True)

    # Rating filter
    st.divider()
    min_rating = st.slider("Filter by minimum rating", 1, 5, 1)
    filtered = df[df["review_rating"] >= min_rating]

    # Filtered metrics
    f_avg = filtered["review_rating"].mean() if len(filtered) else 0
    f_has_owner = (filtered["owner_answer"].notna() & (filtered["owner_answer"] != "")).sum()
    fc1, fc2, fc3 = st.columns(3)
    fc1.metric("Filtered Reviews", len(filtered), delta=f"{len(filtered)-len(df)} from total")
    fc2.metric("Filtered Avg Rating", f"{f_avg:.2f} ⭐")
    fc3.metric("Filtered Owner Responses", f_has_owner)

    # Download
    filename = f"google_reviews_{datetime.now().strftime('%Y%m%d')}.xlsx"
    st.download_button(
        label="⬇️ Download Excel",
        data=to_excel(filtered),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

except Exception as e:
    st.error(f"Could not load database: {e}")
    st.info("Make sure `reviews.db` exists in the same directory as this app, or update `DB_PATH`.")