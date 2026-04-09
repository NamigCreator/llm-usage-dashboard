from datetime import datetime, timedelta, timezone
from io import BytesIO

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from api import fetch as _fetch
from data import agg, fmt_table, timeline_data


@st.cache_data(ttl=300, show_spinner="Fetching data from OpenAI API...")
def fetch(start, end):
    return _fetch(start, end)

# ── charts ───────────────────────────────────────────────────────────────────

PAL = ["#2D6FD4", "#27AE60", "#E67E22", "#8E44AD", "#E74C3C", "#16A085", "#2980B9", "#C0392B"]


def timeline(data, color_dim, metric, title, top_n=8):
    if data.empty:
        return go.Figure()
    dates, cats, g = timeline_data(data, color_dim, metric, top_n)
    fig = go.Figure()
    for i, cat in enumerate(cats):
        dm = g[g[color_dim] == cat].set_index("date")[metric]
        vals = [dm.get(d, 0) for d in dates]
        fig.add_trace(go.Bar(x=dates, y=vals, name=cat, marker_color=PAL[i % len(PAL)]))
    fig.update_layout(plot_bgcolor="#F7F9FC", paper_bgcolor="white",
                      title=title, barmode="stack", showlegend=True,
                      height=380, margin=dict(t=40, b=130, l=60, r=10),
                      legend=dict(orientation="h", y=-0.38),
                      xaxis=dict(type="category", tickangle=-35))
    return fig


def bar_chart(data, dim, metric, title, horizontal=False):
    if data.empty:
        return go.Figure()
    data = data.sort_values(metric if horizontal else dim)
    fig = px.bar(data, y=dim if horizontal else metric, x=metric if horizontal else dim,
                 title=title, orientation="h" if horizontal else "v",
                 color_discrete_sequence=[PAL[0]])
    fig.update_layout(plot_bgcolor="#F7F9FC", paper_bgcolor="white",
                      showlegend=False, yaxis_title="", xaxis_title="")
    return fig


def stacked_chart(data, dim, title, horizontal=False):
    if data.empty:
        return go.Figure()
    data = data.sort_values("inp" if horizontal else dim)
    fig = go.Figure()
    for col, label, color in [("cached", "Cached", "#4E9AF1"), ("uncached", "Uncached", "#F4A261"), ("out", "Output", "#2ECC71")]:
        kw = dict(y=data[dim], x=data[col], orientation="h") if horizontal else dict(x=data[dim], y=data[col])
        fig.add_trace(go.Bar(name=label, marker_color=color, **kw))
    fig.update_layout(barmode="stack", title=title, plot_bgcolor="#F7F9FC",
                      paper_bgcolor="white", legend=dict(orientation="h", y=-0.15, x=0),
                      yaxis_title="", xaxis_title="")
    return fig


# ── dashboard ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="OpenAI Usage", layout="wide")
st.title("OpenAI Usage Report")

# sidebar controls
with st.sidebar:
    st.header("Filters")
    today = datetime.now(timezone.utc).date()
    default_start = today - timedelta(days=7)
    start = st.date_input("Start date", value=default_start)
    end   = st.date_input("End date", value=today)
    run = st.button("Run", type="primary", width="stretch")

if not run and "df" not in st.session_state:
    st.info("Select date range and press **Run** in the sidebar.")
    st.stop()

if run:
    st.session_state["df"] = fetch(str(start), str(end))

df = st.session_state["df"]

if df.empty:
    import pandas as pd
    fallback_df = pd.read_excel("sample_data.xlsx", sheet_name="Usage")
    fallback_df["date"] = fallback_df["date"].astype(str)
    mask = (fallback_df["date"] >= str(start)) & (fallback_df["date"] <= str(end))
    fallback_df = fallback_df[mask].reset_index(drop=True)
    if not fallback_df.empty:
        st.warning("Live data unavailable — showing cached data from local file.")
        df = fallback_df
    else:
        st.warning("No data for the selected period.")
        st.stop()

# project filter in sidebar
with st.sidebar:
    projects = sorted(df.project.unique())
    selected_project = st.selectbox("Project", ["All"] + projects)

filtered = df if selected_project == "All" else df[df.project == selected_project]

# export button in sidebar
with st.sidebar:
    st.divider()
    def _to_xlsx(df):
        buf = BytesIO()
        df.to_excel(buf, index=False, sheet_name="Usage")
        return buf.getvalue()

    st.download_button("Export XLSX", data=_to_xlsx(filtered),
                       file_name=f"openai_usage_{start}_{end}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       width="stretch")

# metrics row
c1, c2, c3 = st.columns(3)
c1.metric("Total Cost", f"${filtered.cost.sum():,.2f}")
c2.metric("Requests", f"{filtered.requests.sum():,}")
c3.metric("Days", str(filtered.date.nunique()))

# -- by date --
st.header("By Date")
by_date = agg(filtered, "date")
col1, col2 = st.columns(2)
col1.plotly_chart(bar_chart(by_date, "date", "cost", "Cost by Date"), width="stretch")
col2.plotly_chart(bar_chart(by_date, "date", "requests", "Requests by Date"), width="stretch")

col3, col4 = st.columns(2)
col3.plotly_chart(bar_chart(by_date, "date", "inp", "Input Tokens by Date"), width="stretch")
col4.plotly_chart(stacked_chart(by_date, "date", "Tokens by Date"), width="stretch")

with st.expander("Date table"):
    st.dataframe(fmt_table(by_date.sort_values("date")), width="stretch", hide_index=True)

# -- by project --
if selected_project == "All":
    st.header("By Project")
    by_proj = agg(filtered, "project")
    col1, col2 = st.columns(2)
    col1.plotly_chart(bar_chart(by_proj, "project", "cost", "Cost by Project", True), width="stretch")
    col2.plotly_chart(bar_chart(by_proj, "project", "requests", "Requests by Project", True), width="stretch")

    col3, col4 = st.columns(2)
    col3.plotly_chart(timeline(filtered, "project", "cost", "Cost by Date — by Project"), width="stretch")
    col4.plotly_chart(stacked_chart(by_proj, "project", "Tokens by Project", True), width="stretch")

    with st.expander("Project table"):
        st.dataframe(fmt_table(by_proj.sort_values("cost", ascending=False)), width="stretch", hide_index=True)

# -- by model --
st.header("By Model")
by_fam = agg(filtered, "family")
col1, col2 = st.columns(2)
col1.plotly_chart(bar_chart(by_fam, "family", "cost", "Cost by Model", True), width="stretch")
col2.plotly_chart(bar_chart(by_fam, "family", "requests", "Requests by Model", True), width="stretch")

col3, col4 = st.columns(2)
col3.plotly_chart(timeline(filtered, "family", "cost", "Cost by Date — by Model"), width="stretch")
col4.plotly_chart(stacked_chart(by_fam, "family", "Tokens by Model", True), width="stretch")

with st.expander("Model table"):
    st.dataframe(fmt_table(by_fam.sort_values("cost", ascending=False)), width="stretch", hide_index=True)

# -- by user --
st.header("By User / Use Case")
by_user = agg(filtered, "user")
col1, col2 = st.columns(2)
col1.plotly_chart(bar_chart(by_user, "user", "cost", "Cost by User", True), width="stretch")
col2.plotly_chart(bar_chart(by_user, "user", "requests", "Requests by User", True), width="stretch")

col3, col4 = st.columns(2)
col3.plotly_chart(timeline(filtered, "user", "cost", "Cost by Date — by User"), width="stretch")
col4.plotly_chart(stacked_chart(by_user, "user", "Tokens by User", True), width="stretch")

with st.expander("User table"):
    st.dataframe(fmt_table(by_user.sort_values("cost", ascending=False)), width="stretch", hide_index=True)
