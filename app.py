import time
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import pytz
import json
from io import BytesIO
import requests

DB_PATH = "reviews.db"
GITHUB_OWNER = "PameryArredondo"
GITHUB_SCRAPER_REPO = "google-reviews-scraper-pro"
EST = pytz.timezone("America/New_York")


def to_est_date(utc_str):
    if not utc_str:
        return None
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(EST).strftime("%d-%b-%Y")
    except Exception:
        return None


def extract_text(field, lang="en"):
    if not field:
        return None
    try:
        data = json.loads(field) if isinstance(field, str) else field
        if isinstance(data, dict):
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

    cur.execute("PRAGMA table_info(reviews)")
    cols = {row[1] for row in cur.fetchall()}

    text_col       = "review_text"     if "review_text"     in cols else "description"
    owner_text_col = "owner_responses" if "owner_responses" in cols else "owner_reply"
    owner_date_col = "last_modified"   if "last_modified"   in cols else "owner_response_date"
    rating_col     = "rating"          if "rating"          in cols else "stars"
    date_col       = "review_date"     if "review_date"     in cols else "date"
    deleted_col    = "is_deleted"      if "is_deleted"      in cols else None
    params_col     = "custom_params"   if "custom_params"   in cols else None

    where = f"WHERE r.{deleted_col} = 0" if deleted_col else ""

    cur.execute(f"""
        SELECT
            r.author,
            r.{text_col}          AS description,
            r.{owner_text_col}    AS owner_responses,
            r.{owner_date_col}    AS owner_response_date,
            r.{rating_col}        AS rating,
            r.{date_col}          AS review_date,
            {'r.' + params_col + ' AS custom_params' if params_col else 'NULL AS custom_params'}
        FROM reviews r
        {where}
        ORDER BY r.{date_col} DESC
    """)
    rows = cur.fetchall()
    con.close()
    return rows


def build_dataframe(rows):
    records = []
    for r in rows:
        name = "Validated Claim Support"
        try:
            cp = json.loads(r["custom_params"]) if r["custom_params"] else {}
            name = cp.get("company") or name
        except Exception:
            pass

        owner_text     = extract_text(r["owner_responses"])
        owner_date_utc = r["owner_response_date"]

        records.append({
            "name":              name,
            "author_title":      r["author"],
            "review_text":       extract_text(r["description"]),
            "owner_answer":      owner_text,
            "owner_answer_date": to_est_date(owner_date_utc),
            "review_rating":     r["rating"],
            "review_date":       to_est_date(r["review_date"]),
        })
    return pd.DataFrame(records)


def to_excel(df):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Reviews")
        ws = writer.sheets["Reviews"]
        for col in ws.columns:
            max_len = max((len(str(c.value)) for c in col if c.value), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)
    buf.seek(0)
    return buf


def get_last_scrape_time(db_path):
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scrape_sessions'")
        if not cur.fetchone():
            con.close()
            return None
        cur.execute("SELECT MAX(completed_at) FROM scrape_sessions")
        row = cur.fetchone()
        con.close()
        return row[0] if row else None
    except Exception:
        return None


def trigger_github_scrape():
    token = st.secrets.get("GITHUB_TOKEN")
    if not token:
        return False, "GITHUB_TOKEN not found in Streamlit secrets."
    resp = requests.post(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_SCRAPER_REPO}/actions/workflows/244378066/dispatches",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json"
        },
        json={"ref": "master"}
    )
    if resp.status_code == 204:
        return True, None
    return False, f"GitHub API returned {resp.status_code}: {resp.text}"


def get_workflow_status():
    token = st.secrets.get("GITHUB_TOKEN")
    if not token:
        return None
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_SCRAPER_REPO}/actions/workflows/244378066/runs?per_page=1",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json"
            },
            timeout=5
        )
        if resp.status_code == 200:
            runs = resp.json().get("workflow_runs", [])
            if runs:
                run = runs[0]
                return {
                    "status": run.get("status"),
                    "conclusion": run.get("conclusion"),
                    "started": run.get("created_at"),
                    "url": run.get("html_url"),
                }
    except Exception:
        pass
    return None


def show_stats(df, label=""):
    avg_rating = df["review_rating"].mean()
    has_owner  = df["owner_answer"].notna() & (df["owner_answer"] != "")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Reviews",   len(df))
    col2.metric("Average Rating",  f"{avg_rating:.2f} ⭐")
    col3.metric("Owner Responses", has_owner.sum())

    st.subheader("Rating Breakdown")
    star_cols = st.columns(5)
    for i, star in enumerate(range(5, 0, -1)):
        count = (df["review_rating"] == star).sum()
        star_cols[i].metric(f"{'⭐' * star}", f"{count}")


# ── UI ───────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Google Reviews Export", page_icon="⭐", layout="centered")
st.markdown("""
    <style>
        .block-container { padding-top: 2rem; padding-bottom: 1rem; }
        div[data-testid="stVerticalBlock"] { gap: 0rem; }
        hr { margin: 0.5rem 0; }
    </style>
""", unsafe_allow_html=True)
st.title("⭐ Google Reviews Export")

# ── Step 1: Scrape ───────────────────────────────────────────────────────────
st.divider()
st.subheader("Step 1: Click 'Run Scrape Now'")

if st.button("Run Scrape Now", type="primary"):
    with st.spinner("Triggering scrape..."):
        ok, err = trigger_github_scrape()
    if ok:
        st.session_state["polling"] = True
        st.rerun()
    else:
        st.error(f"Failed to trigger: {err}")

if st.session_state.get("polling"):
    status_placeholder = st.empty()
    for _ in range(72):  # poll up to 6 minutes (72 x 5s)
        info = get_workflow_status()
        if info:
            s = info["status"]
            c = info["conclusion"]
            if s == "queued":
                status_placeholder.info("Setting up environment — installing dependencies in the background...")
            elif s == "in_progress":
                status_placeholder.info("Scrape is running... this usually takes 2–3 minutes.")
            elif s == "completed":
                st.session_state["polling"] = False
                if c == "success":
                    status_placeholder.success("✅ Scrape completed! Refreshing data...")
                    time.sleep(2)
                    st.rerun()
                else:
                    status_placeholder.error(f"❌ Scrape failed. [View run]({info['url']})")
                break
        time.sleep(5)
    else:
        st.session_state["polling"] = False
        st.warning("Scrape is taking longer than expected. Refresh the page manually in a few minutes.")

# ── Load data (required for steps 2 & 3) ────────────────────────────────────
try:
    rows = load_reviews(DB_PATH)
    df   = build_dataframe(rows)
    df["_date"]    = pd.to_datetime(df["review_date"], format="%d-%b-%Y", errors="coerce")
    df["_year"]    = df["_date"].dt.year
    df["_quarter"] = df["_date"].dt.quarter

    # Last scrape time
    last_scrape = get_last_scrape_time(DB_PATH)
    if last_scrape:
        try:
            dt = datetime.fromisoformat(last_scrape.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            dt_est = dt.astimezone(EST)
            st.caption(f"📅 Last scraped: {dt_est.strftime('%d/%m/%Y at %I:%M %p')} EST")
        except Exception:
            st.caption(f"📅 Last scraped: {last_scrape}")
    else:
        st.caption("📅 Last scraped: unknown")

    # ── Step 2: Date filter ──────────────────────────────────────────────────
    st.divider()
    st.subheader("Step 2: Apply Date Filter for Export")

    available       = df[["_year", "_quarter"]].dropna().drop_duplicates()
    available_years = sorted(available["_year"].unique(), reverse=True)

    filter_mode = st.radio("Filter by", ["Quarter", "Custom date range"], horizontal=True)

    if filter_mode == "Quarter":
        col_y, col_q = st.columns(2)
        selected_year = col_y.selectbox("Year", ["All"] + [int(y) for y in available_years])

        if selected_year == "All":
            available_quarters = sorted(available["_quarter"].unique())
        else:
            available_quarters = sorted(available[available["_year"] == selected_year]["_quarter"].unique())

        quarter_names = {1: "Q1 (Jan-Mar)", 2: "Q2 (Apr-Jun)", 3: "Q3 (Jul-Sep)", 4: "Q4 (Oct-Dec)"}
        selected_q = col_q.selectbox("Quarter", ["All"] + [quarter_names[q] for q in available_quarters])

        q_map = {v: k for k, v in quarter_names.items()}
        if selected_year == "All" and selected_q == "All":
            filtered = df.copy()
        elif selected_year == "All":
            filtered = df[df["_quarter"] == q_map[selected_q]]
        elif selected_q == "All":
            filtered = df[df["_year"] == selected_year]
        else:
            filtered = df[(df["_year"] == selected_year) & (df["_quarter"] == q_map[selected_q])]

        fname_tag = f"{selected_year}_{selected_q}".replace(" ", "_").replace("(", "").replace(")", "").replace("-", "")

    else:
        col_from, col_to = st.columns(2)
        date_from = col_from.date_input("From", value=df["_date"].min().date(), min_value=df["_date"].min().date(), max_value=df["_date"].max().date())
        date_to   = col_to.date_input("To",     value=df["_date"].max().date(), min_value=df["_date"].min().date(), max_value=df["_date"].max().date())
        filtered  = df[(df["_date"].dt.date >= date_from) & (df["_date"].dt.date <= date_to)]
        fname_tag = f"{date_from.strftime('%d%m%Y')}_to_{date_to.strftime('%d%m%Y')}"

    filtered = filtered.drop(columns=["_date", "_year", "_quarter"])

    # Filtered stats
    if last_scrape:
        st.divider()
        st.caption(f"{len(filtered)} of {len(df)} reviews match the selection.")
        show_stats(filtered, label="Filtered Reviews")

    # ── Step 3: Export ───────────────────────────────────────────────────────
    st.divider()
    st.subheader("Step 3: Click Export to Download Excel File")

    filename = f"google_reviews_{fname_tag}.xlsx"
    st.download_button(
        label="⬇️ Download Excel",
        data=to_excel(filtered),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # Preview
    st.divider()
    with st.expander("Preview data", expanded=False):
        st.dataframe(filtered, use_container_width=True)

except Exception as e:
    st.error(f"Could not load database: {e}")
    st.info("Make sure `reviews.db` exists in the same directory as this app, or update `DB_PATH`.")
