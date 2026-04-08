_COL_NAMES = {
    "date": "Date", "project": "Project", "family": "Model", "user": "User",
    "cost": "Cost", "requests": "Requests", "inp": "Input Tokens",
    "cached": "Cached", "uncached": "Uncached", "out": "Output Tokens",
    "cache_hit": "Cache Hit %", "cost_per_req": "$/Request",
}


def agg(df, dim):
    g = df.groupby(dim, as_index=False).agg(
        cost=("cost", "sum"), requests=("requests", "sum"),
        inp=("inp", "sum"), cached=("cached", "sum"),
        uncached=("uncached", "sum"), out=("out", "sum"))
    g["cache_hit"] = (g.cached / g.inp * 100).where(g.inp > 0, 0).round(1)
    g["cost_per_req"] = (g.cost / g.requests).where(g.requests > 0, 0)
    return g


def timeline_data(data, color_dim, metric, top_n=8):
    """Return (dates, cats, grouped_df) ready for chart rendering."""
    tops = data.groupby(color_dim)[metric].sum().nlargest(top_n).index.tolist()
    df2 = data.copy()
    df2[color_dim] = df2[color_dim].where(df2[color_dim].isin(tops), "Others")
    g = df2.groupby(["date", color_dim], as_index=False)[metric].sum()
    dates = sorted(df2.date.unique())
    cats = tops + (["Others"] if "Others" in g[color_dim].values else [])
    return dates, cats, g


def fmt_table(data):
    df = data.rename(columns={k: v for k, v in _COL_NAMES.items() if k in data.columns})
    fmt = {"Cost": "${:,.4f}", "$/Request": "${:.5f}", "Cache Hit %": "{:.1f}%",
           **{c: "{:,.0f}" for c in ["Requests", "Input Tokens", "Cached", "Uncached", "Output Tokens"]}}
    return df.style.format({k: v for k, v in fmt.items() if k in df.columns})
