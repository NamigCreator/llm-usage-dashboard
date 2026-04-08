import json, logging, os, time
from datetime import datetime, timezone

import requests as req
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

KEY = os.getenv("OPENAI_ADMIN_KEY")
BASE = "https://api.openai.com/v1/organization"
_session = req.Session()
_session.headers["Authorization"] = f"Bearer {KEY}"


def _get(url, retries=5):
    for i in range(retries):
        try:
            r = _session.get(url, timeout=90)
            d = r.json()
        except (req.RequestException, json.JSONDecodeError):
            logger.warning("  [WARN] request failed, retry %d/%d...", i + 1, retries)
            time.sleep(2); continue
        if "error" not in d: return d
        if d["error"].get("type") == "server_error":
            logger.warning("  [WARN] server_error, retry %d/%d...", i + 1, retries)
            time.sleep(min(6, 2**i)); continue
        raise RuntimeError(d["error"]["message"])
    return {"data": []}


def _pages(path, qs):
    out, pg = [], ""
    while True:
        d = _get(f"{BASE}/{path}?{qs}&page={pg}" if pg else f"{BASE}/{path}?{qs}")
        out.extend(d.get("data", []))
        if not d.get("has_more"): break
        pg = d.get("next_page", "")
    return out


def _all(path):
    out, after = [], ""
    while True:
        d = _get(f"{BASE}/{path}?limit=100&after={after}" if after else f"{BASE}/{path}?limit=100")
        out.extend(d.get("data", []))
        if not d.get("has_more"): break
        after = d.get("last_id", "")
    return out


def _ts(d):
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def _date(b):
    return datetime.fromtimestamp(b["start_time"], tz=timezone.utc).strftime("%Y-%m-%d")


def _fetch_names():
    """Load project and user/service-account name mappings."""
    user_map = {u["id"]: u.get("name") or u.get("email", u["id"]) for u in _all("users")}
    proj_map = {p["id"]: p["name"] for p in _all("projects")}
    for pid in proj_map:
        for sa in _all(f"projects/{pid}/service_accounts"):
            user_map[sa["id"]] = sa.get("name", sa["id"])
    return proj_map, user_map


def _fetch_costs(bqs):
    """Load real costs grouped by (date, user_id, model). Also collects project names."""
    cost_map = {}
    proj_names = {}
    for b in _pages("costs", f"{bqs}&group_by[]=user_id"):
        date = _date(b)
        for r in b.get("results", []):
            li = r.get("line_item") or ""
            model = li.split(",")[0].strip() if "," in li else li
            uid = r.get("user_id") or ""
            key = (date, uid, model)
            cost_map[key] = cost_map.get(key, 0) + float(r.get("amount", {}).get("value", 0) or 0)
            pid = r.get("project_id") or ""
            if pid and r.get("project_name"):
                proj_names[pid] = r["project_name"]
    return cost_map, proj_names


def _fetch_usage(bqs, cost_map, proj_map, proj_names, user_map):
    """Load token usage and join with costs. Returns list of row dicts."""
    rows = []
    for b in _pages("usage/completions", f"{bqs}&group_by[]=model&group_by[]=project_id&group_by[]=user_id"):
        date = _date(b)
        for r in b.get("results", []):
            m = r.get("model") or "?"
            pid = r.get("project_id") or ""
            uid = r.get("user_id") or ""
            i0 = r.get("input_uncached_tokens", 0) or 0
            ic = r.get("input_cached_tokens", 0) or 0
            o = r.get("output_tokens", 0) or 0
            rows.append({
                "date": date,
                "project": proj_map.get(pid) or proj_names.get(pid) or pid or "—",
                "user": user_map.get(uid, uid or "—"),
                "model": m, "family": m.split("-202")[0].split("-20")[0],
                "requests": r.get("num_model_requests", 0) or 0,
                "inp": i0 + ic, "cached": ic, "uncached": i0, "out": o,
                "cost": cost_map.get((date, uid, m), 0),
            })
    return rows


def fetch(start, end):
    """Fetch usage data from OpenAI API. Returns a pandas DataFrame."""
    import pandas as pd

    bqs = f"start_time={_ts(start)}&end_time={_ts(end)}&bucket_width=1d&limit=31"
    proj_map, user_map = _fetch_names()
    cost_map, proj_names = _fetch_costs(bqs)
    rows = _fetch_usage(bqs, cost_map, proj_map, proj_names, user_map)
    return pd.DataFrame(rows)
