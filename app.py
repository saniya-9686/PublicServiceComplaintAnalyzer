import os

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Public Service Complaint Priority Analyzer",
    page_icon="🏛️",
    layout="wide",
)

DATA_PATH = os.path.join("data", "bbmp_2025.csv")

# ---------------------------------------------------------------
# Design choices (you can edit these and explain them in viva)
# ---------------------------------------------------------------
STATUS_GROUP = {
    "registered": "open",
    "in progress": "open",
    "reopen": "open",
    "long term solution": "open",
    "closed": "closed",
    "non relevant": "ignore",
    "unknown": "ignore",
}
STATUS_POINTS = {"reopen": 100, "registered": 70, "in progress": 50, "long term solution": 30}
RISK_POINTS = {
    "Health Dept": 100,
    "Water Crisis": 90,
    "Storm Water Drain(SWD)": 90,
    "Road Maintenance(Engg)": 80,
    "Road Infrastructure": 80,
    "Electrical": 70,
    "Solid Waste (Garbage) Related": 70,
    "Sanitation": 70,
    "Forest": 50,
    "Lakes": 50,
    "veterinary": 40,
    "Others": 30,
    "Revenue Department": 30,
    "E khata / Khata services": 30,
    "Property Tax services": 30,
    "Town Planning": 30,
    "Advertisement": 30,
}
DEFAULT_RISK = 40
AGE_CAP = 90      # days open after which age points stop growing
REPEAT_CAP = 5    # other open complaints (same ward + category) for full repeat points


@st.cache_data
def load_data():
    df = pd.read_csv(DATA_PATH)
    for col in ["Category", "Sub Category", "Ward Name", "Grievance Status"]:
        df[col] = (
            df[col].fillna("unknown").astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
        )
    df["Grievance Status"] = df["Grievance Status"].str.lower()
    df["Grievance Date"] = pd.to_datetime(df["Grievance Date"], errors="coerce")
    df = df.dropna(subset=["Grievance Date"])
    dupes = int(df["Complaint ID"].duplicated().sum())
    df = df.drop_duplicates(subset=["Complaint ID"])
    df["status_group"] = df["Grievance Status"].map(STATUS_GROUP).fillna("ignore")
    as_of = df["Grievance Date"].max().normalize()
    df["days_open"] = (as_of - df["Grievance Date"].dt.normalize()).dt.days
    return df, as_of, dupes


def score_open(df, weights, stuck_days):
    o = df[df["status_group"] == "open"].copy()
    o["status_pts"] = o["Grievance Status"].map(STATUS_POINTS).fillna(0)
    o["age_pts"] = o["days_open"].clip(lower=0, upper=AGE_CAP) / AGE_CAP * 100
    o["risk_pts"] = o["Category"].map(RISK_POINTS).fillna(DEFAULT_RISK)
    repeats = o.groupby(["Ward Name", "Category"])["Complaint ID"].transform("count") - 1
    o["repeat_pts"] = repeats.clip(upper=REPEAT_CAP) / REPEAT_CAP * 100
    total_w = sum(weights.values()) or 1
    o["Priority Score"] = sum(weights[k] * o[k + "_pts"] for k in weights) / total_w
    o["Priority"] = pd.cut(
        o["Priority Score"], bins=[-1, 50, 70, 101], labels=["Low", "Medium", "High"], right=False
    )
    o["Stuck"] = o["days_open"] > stuck_days
    return o


st.title("🏛️ Public Service Complaint Priority Analyzer")
st.write(
    "Finds complaints that are stuck, ranks them with a transparent score, "
    "and shows which wards need attention first."
)

if not os.path.exists(DATA_PATH):
    st.error("Dataset not found! Expected file: data/bbmp_2025.csv")
    st.stop()

df_all, as_of, dupes = load_data()

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Settings")
    stuck_days = st.number_input("Stuck after (days open)", 7, 120, 30)
    min_complaints = st.number_input("Minimum complaints to rank a ward", 5, 100, 30)
    include_others = st.checkbox("Include category 'Others'", value=True)
    st.header("Score weights")
    weights = {
        "status": st.slider("Status", 0, 100, 30),
        "age": st.slider("Days open", 0, 100, 30),
        "risk": st.slider("Category risk", 0, 100, 25),
        "repeat": st.slider("Repeat complaints", 0, 100, 15),
    }
    st.caption("Weights are scaled to add up to 100%.")

scored_all = score_open(df_all, weights, stuck_days)
if include_others:
    df, scored = df_all, scored_all
else:
    df = df_all[df_all["Category"] != "Others"]
    scored = scored_all[scored_all["Category"] != "Others"]
valid = df[df["status_group"] != "ignore"]

tab1, tab2, tab3, tab4 = st.tabs(
    ["Overview", "Ward attention", "Priority ranking", "Complaint checker"]
)

# ---------------- Overview ----------------
with tab1:
    open_count = int((valid["status_group"] == "open").sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valid complaints", f"{len(valid):,}")
    c2.metric("Open", f"{open_count:,}")
    c3.metric("Stuck", f"{int(scored['Stuck'].sum()):,}")
    c4.metric("Wards", valid["Ward Name"].nunique())
    st.caption(
        f"Data: BBMP grievances 2025 (OpenCity). Days open are counted up to {as_of:%d %b %Y}, "
        "the last date in the data."
    )

    st.subheader("Stuck complaints by category")
    st.bar_chart(scored[scored["Stuck"]]["Category"].value_counts())

    month = valid["Grievance Date"].dt.to_period("M").astype(str)
    st.subheader("Complaints per month")
    st.line_chart(month.value_counts().sort_index())

    st.subheader("Share of complaints still open, by month (%)")
    st.bar_chart((valid["status_group"].eq("open").groupby(month).mean() * 100).round(1))
    st.caption(
        "Recent complaints look open only because they are new. "
        "That is why we focus on stuck complaints."
    )

    with st.expander("Data quality checks"):
        ignored = int((df["status_group"] == "ignore").sum())
        st.write(f"Duplicate complaint IDs removed: {dupes}")
        st.write(f"Complaints ignored (non relevant or blank status): {ignored}")
        st.write(f"Wards: {df['Ward Name'].nunique()} | Categories: {df['Category'].nunique()}")

# ---------------- Ward attention ----------------
with tab2:
    st.subheader("Wards that need attention")
    v = valid.copy()
    v["is_open"] = v["status_group"] == "open"
    v["is_old"] = v["days_open"] > stuck_days
    v["is_stuck"] = v["is_open"] & v["is_old"]
    v["is_reopen"] = v["Grievance Status"] == "reopen"
    wards = v.groupby("Ward Name").agg(
        Complaints=("Complaint ID", "count"),
        Open=("is_open", "sum"),
        Stuck=("is_stuck", "sum"),
        Older=("is_old", "sum"),
        Reopened=("is_reopen", "sum"),
    )
    wards["Stuck %"] = (100 * wards["Stuck"] / wards["Older"].where(wards["Older"] > 0)).round(1)

    rank_by = st.radio("Rank wards by", ["Stuck", "Stuck %"], horizontal=True)
    sort_cols = ["Stuck"] if rank_by == "Stuck" else ["Stuck %", "Stuck"]
    ranked = wards[wards["Complaints"] >= min_complaints].sort_values(sort_cols, ascending=False)

    st.caption(
        f"Only wards with at least {min_complaints} complaints are ranked "
        f"({len(ranked)} of {len(wards)} wards). 'Stuck %' = stuck complaints out of complaints "
        f"older than {stuck_days} days, so new complaints are not counted against a ward."
    )
    st.bar_chart(ranked[rank_by].head(15))
    st.dataframe(ranked.head(25))

# ---------------- Priority ranking ----------------
with tab3:
    st.subheader("Priority ranking of open complaints")
    f1, f2, f3 = st.columns(3)
    ward_pick = f1.selectbox("Ward", ["All wards"] + sorted(scored["Ward Name"].unique()))
    cat_pick = f2.selectbox("Category", ["All categories"] + sorted(scored["Category"].unique()))
    stuck_only = f3.checkbox("Only stuck complaints", value=True)

    r = scored.copy()
    if ward_pick != "All wards":
        r = r[r["Ward Name"] == ward_pick]
    if cat_pick != "All categories":
        r = r[r["Category"] == cat_pick]
    if stuck_only:
        r = r[r["Stuck"]]
    r = r.sort_values("Priority Score", ascending=False)

    show = r[
        ["Complaint ID", "Category", "Sub Category", "Ward Name",
         "Grievance Status", "days_open", "Priority Score", "Priority"]
    ].rename(columns={"days_open": "Days open"})
    show["Priority Score"] = show["Priority Score"].round(1)

    st.metric("Complaints shown", len(show))
    st.dataframe(show)
    st.download_button(
        "📥 Download this ranking (CSV)",
        show.to_csv(index=False).encode("utf-8"),
        "priority_ranking.csv",
        "text/csv",
    )

    with st.expander("How is the score calculated?"):
        st.markdown(
            "Score (0-100) = weighted average of four parts, each worth 0-100 points:\n"
            "- **Status:** reopen 100, registered 70, in progress 50, long term solution 30\n"
            f"- **Days open:** grows until {AGE_CAP} days, then stops\n"
            "- **Category risk:** our own table (health and drains high, paperwork low)\n"
            f"- **Repeats:** other open complaints in the same ward and category "
            f"(full points at {REPEAT_CAP})\n\n"
            "High is 70 or more, Medium is 50 to 69, Low is below 50. "
            "The weights are design choices, not scientific values. "
            "Move the sliders in the sidebar and watch the ranking change."
        )
        st.dataframe(pd.Series(RISK_POINTS, name="Category risk points"))

# ---------------- Complaint checker ----------------
with tab4:
    st.subheader("Check one complaint")
    cid_text = st.text_input("Enter a Complaint ID").strip()
    if cid_text:
        if not cid_text.isdigit():
            st.error("Complaint ID should be a number.")
        else:
            cid = int(cid_text)
            row = df_all[df_all["Complaint ID"] == cid]
            if row.empty:
                st.error("Complaint ID not found in this dataset.")
            else:
                rec = row.iloc[0]
                st.write(f"**{rec['Category']}** - {rec['Sub Category']}")
                st.write(
                    f"Ward: {rec['Ward Name']} | Date: {rec['Grievance Date']:%d %b %Y} "
                    f"| Status: {rec['Grievance Status']}"
                )
                s = scored_all[scored_all["Complaint ID"] == cid]
                if s.empty:
                    st.info("This complaint is closed or ignored, so it has no priority score.")
                else:
                    s = s.iloc[0]
                    total_w = sum(weights.values()) or 1
                    parts = [("Status", "status"), ("Days open", "age"),
                             ("Category risk", "risk"), ("Repeat complaints", "repeat")]
                    table = pd.DataFrame({
                        "Part": [p[0] for p in parts],
                        "Points (0-100)": [round(float(s[p[1] + "_pts"]), 1) for p in parts],
                        "Weight %": [round(100 * weights[p[1]] / total_w, 1) for p in parts],
                    })
                    table["Contribution"] = (
                        table["Points (0-100)"] * table["Weight %"] / 100
                    ).round(1)
                    st.write(f"Days open: {int(s['days_open'])}")
                    st.dataframe(table, hide_index=True)
                    st.metric("Priority score", f"{s['Priority Score']:.1f} ({s['Priority']})")
                    if s["Stuck"]:
                        st.warning(
                            f"Escalate: open for {int(s['days_open'])} days (limit {stuck_days})."
                        )
                    else:
                        st.success("Within normal time. Not stuck yet.")

st.divider()
st.caption(
    "Student prototype using public BBMP data. It is not an official BBMP tool and does not "
    "update any BBMP record. Score weights are design choices."
)