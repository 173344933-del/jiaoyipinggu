# -*- coding: utf-8 -*-
"""13F 披露监测：发现跟踪基金有新的 13F-HR 提交时触发提醒。

should_fire：比对 SEC submissions 的 filingDate 与本地 state（data/watch_state.json）。
run：重新拉取 13F（复用 fetch_13f.main），更新 state，输出披露摘要 artifact。
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "data", "watch_state.json")
UA = {"User-Agent": "JiaoYiPingGu research@jiaoyipinggu.example.com"}

WATCH = [  # (显示名, CIK)
    ("德鲁肯米勒 Duquesne", "0001536411"),
    ("巴菲特 Berkshire", "0001067983"),
    ("李录 Himalaya", "0001709323"),
    ("Klarman Baupost", "0001061768"),
    ("高瓴 HHLR", "0001762304"),
    ("景林 Greenwoods", "0001577133"),
    ("达里奥 Bridgewater", "0001350694"),
    ("Burry Scion", "0001649339"),
]


def _latest_filing_date(cik):
    try:
        req = urllib.request.Request(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        recent = data["filings"]["recent"]
        for form, fdate in zip(recent["form"], recent["filingDate"]):
            if form in ("13F-HR", "13F-HR/A"):
                return fdate
    except Exception:
        pass
    return None


def _load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def should_fire(ctx):
    try:
        state = _load_state()
        for name, cik in WATCH:
            fd = _latest_filing_date(cik)
            time.sleep(0.2)
            if fd and fd > state.get(cik, ""):
                return True
    except Exception:
        return False
    return False


def run(ctx):
    ns = {"__file__": os.path.join(BASE, "fetch_13f.py"), "__name__": "fetch_13f_lib"}
    lib = os.path.join(BASE, "fetch_13f.py")
    exec(compile(open(lib, encoding="utf-8").read(), lib, "exec"), ns)
    ns["main"]()  # 重新拉取并保存 data/13f.json
    state = _load_state()
    fresh = []
    for name, cik in WATCH:
        fd = _latest_filing_date(cik)
        if fd and fd > state.get(cik, ""):
            fresh.append({"name": name, "cik": cik, "filed": fd})
            state[cik] = fd
        time.sleep(0.2)
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(state, open(STATE, "w", encoding="utf-8"))
    except Exception:
        pass
    # 从 13f.json 提取这些机构的变动摘要
    try:
        data = json.load(open(os.path.join(BASE, "data", "13f.json"), encoding="utf-8"))
    except Exception:
        data = {"filers": []}
    summaries = []
    for f in data.get("filers", []):
        for n in fresh:
            if n["name"].split()[-1].upper() in f.get("entity", "").upper() or n["name"].split()[0] in f.get("name", ""):
                chg = f.get("changes") or {}
                summaries.append({"name": f["name"], "asOf": f.get("reportDate", ""),
                                  "positions": f.get("positions", 0),
                                  "top1": f["top"][0]["name"] if f.get("top") else "-",
                                  "changes": chg})
    return {"artifact": {"freshFilings": fresh, "summaries": summaries,
                         "asOf": time.strftime("%Y-%m-%d %H:%M")}}
