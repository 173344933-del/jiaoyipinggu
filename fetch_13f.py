# -*- coding: utf-8 -*-
"""13F 持仓采集器：SEC EDGAR 官方数据源。

用法：python3 fetch_13f.py
流程：对每个候选基金，取 data.sec.gov/submissions 校验机构名 → 找最新 13F-HR
→ 下载 information table XML → 解析 Top 持仓 → 输出 data/13f.json。
合规：SEC 要求声明式 User-Agent；访问频率 < 10 次/秒，这里 sleep 0.25。
"""
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "JiaoYiPingGu Platform research@jiaoyipinggu.example.com"}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "13f.json")

# (基金显示名, 候选CIK, 名称校验关键词)
FILERS = [
    ("Duquesne Family Office（德鲁肯米勒）", "0001536411", "DUQUESNE"),
    ("Berkshire Hathaway（巴菲特）", "0001067983", "BERKSHIRE"),
    ("Bridgewater（达里奥）", "0001350694", "BRIDGEWATER"),
    ("Scion Asset Management（Michael Burry）", "0001649339", "SCION"),
    ("Pershing Square（Ackman）", "0001336528", "PERSHING"),
    ("HHLR Advisors（高瓴）", "0001762304", "HHLR"),
    ("Greenwoods Asset Management（景林）", "0001577133", "GREENWOODS"),
    ("Tiger Global", "0001167483", "TIGER GLOBAL"),
    ("Soros Fund Management（索罗斯）", "0001029160", "SOROS"),
    ("ARK Investment Management（木头姐）", "0001697748", "ARK INVESTMENT"),
    ("Appaloosa LP（Tepper）", "0001656456", "APPALOOSA"),
    ("Daily Journal（芒格生前持仓载体）", "0000783412", "DAILY JOURNAL"),
    ("Renaissance Technologies", "0001037389", "RENAISSANCE"),
    ("Lone Pine Capital", "0001061165", "LONE PINE"),
    ("Himalaya Capital（李录）", "0001709323", "HIMALAYA"),
    ("Baupost Group（Seth Klarman）", "0001061768", "BAUPOST"),
    ("Coatue Management", "0001135730", "COATUE"),
]


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_two_13f(cik_padded):
    """返回 [(accession_nodash, report_date), ...]（最近两期，去重报告期）+ 机构名。"""
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    try:
        data = json.loads(get(url).decode("utf-8"))
    except Exception as e:
        return [], f"submissions失败: {e}"
    name = data.get("name", "")
    recent = data["filings"]["recent"]
    out, seen_dates = [], set()
    for form, acc, fdate, rdate in zip(
            recent["form"], recent["accessionNumber"], recent["filingDate"], recent["reportDate"]):
        if form in ("13F-HR", "13F-HR/A"):
            rd = rdate or fdate
            if rd in seen_dates:
                continue
            seen_dates.add(rd)
            out.append((acc.replace("-", ""), rd))
            if len(out) >= 2:
                break
    return out, name


def diff_holdings(cur, prev):
    """按 CUSIP 对比两期持仓：新进/清仓/加减仓（按价值变化百分比）。"""
    pm = {r["cusip"]: r for r in prev}
    cm = {r["cusip"]: r for r in cur}
    new = [cm[c] for c in cm if c not in pm]
    exited = [pm[c] for c in pm if c not in cm]
    inc, dec = [], []
    for c in cm:
        if c in pm and pm[c]["value"] > 0:
            pct = (cm[c]["value"] - pm[c]["value"]) / pm[c]["value"] * 100
            if pct >= 20:
                inc.append({**cm[c], "pct": round(pct)})
            elif pct <= -20:
                dec.append({**cm[c], "pct": round(pct)})
    key = lambda r: -abs(r.get("pct", 0) or r["value"])
    return {
        "new": [r["name"] for r in sorted(new, key=lambda r: -r["value"])[:5]],
        "exited": [r["name"] for r in sorted(exited, key=lambda r: -r["value"])[:5]],
        "increased": [{ "name": r["name"], "pct": r["pct"] } for r in sorted(inc, key=key)[:5]],
        "decreased": [{ "name": r["name"], "pct": r["pct"] } for r in sorted(dec, key=key)[:5]],
    }


def latest_13f(cik_padded):
    """兼容旧调用：返回最近一期。"""
    two, name = latest_two_13f(cik_padded)
    if two:
        return two[0][0], two[0][1], name
    return None, None, name


def fetch_infotable(cik_int, acc_nodash):
    """下载申报包内全部 infoTable XML 并按 CUSIP 合并（联合申报含多个 manager 子表）。
    返回合并后的持仓行（按价值降序）。"""
    idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/index.json"
    idx = json.loads(get(idx_url).decode("utf-8"))
    files = [i["name"] for i in idx["directory"]["item"] if i["name"].lower().endswith(".xml")]
    if not files:
        raise RuntimeError("no xml in filing")
    merged = {}
    for fn in files:
        try:
            root = ET.fromstring(get(f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{fn}"))
        except Exception:
            continue
        for info in root.iter():
            if localname(info) != "infoTable":
                continue
            name, cusip, val, cls = None, None, 0.0, ""
            for el in info.iter():
                tag = localname(el)
                if tag == "nameOfIssuer":
                    name = (el.text or "").strip()
                elif tag == "cusip":
                    cusip = (el.text or "").strip()
                elif tag == "value":
                    try:
                        val = float((el.text or "0").replace(",", ""))
                    except ValueError:
                        pass
                elif tag == "titleOfClass":
                    cls = (el.text or "").strip()
            if name and val > 0:
                key = cusip or name
                if key in merged:
                    merged[key]["value"] += val
                else:
                    merged[key] = {"name": name, "cusip": key, "value": val, "cls": cls}
    rows = sorted(merged.values(), key=lambda r: -r["value"])
    return rows


def localname(el):
    return el.tag.split("}")[-1]


def parse_infotable(xml_bytes):
    root = ET.fromstring(xml_bytes)
    rows = []
    for info in root.iter():
        if localname(info) != "infoTable":
            continue
        row = {}
        for el in info.iter():
            tag = localname(el)
            if tag == "nameOfIssuer":
                row["name"] = (el.text or "").strip()
            elif tag == "cusip":
                row["cusip"] = (el.text or "").strip()
            elif tag == "value":
                row["value"] = float((el.text or "0").replace(",", ""))
            elif tag in ("sshPrnamt", "shrsOrPrnAmt"):
                if el.text and el.text.strip().isdigit():
                    row["shares"] = int(el.text.strip())
            elif tag == "titleOfClass":
                row["cls"] = (el.text or "").strip()
        if row.get("name") and row.get("value"):
            rows.append(row)
    rows.sort(key=lambda r: -r["value"])
    return rows


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out = {"generated": time.strftime("%Y-%m-%d"), "source": "SEC EDGAR 13F-HR（公开披露）", "filers": []}
    for display, cik, kw in FILERS:
        cik_int = str(int(cik))
        try:
            two, name = latest_two_13f(cik)
            if not two:
                out["filers"].append({"name": display, "status": "skipped", "note": f"未找到13F记录（机构名: {name}）"})
                print(f"[skip] {display} -> {name}")
                continue
            if kw not in str(name).upper():
                out["filers"].append({"name": display, "status": "mismatch", "note": f"CIK对应机构为 {name}"})
                print(f"[mismatch] {display} -> {name}")
                continue
            acc, rdate = two[0]
            rows = fetch_infotable(cik_int, acc)
            prev_rows, changes, prev_date = [], None, None
            if len(two) > 1:
                prev_rows = fetch_infotable(cik_int, two[1][0])
                prev_date = two[1][1]
                changes = diff_holdings(rows, prev_rows)
            top = []
            for r in rows[:30]:
                top.append({"name": r["name"], "value": r["value"]})
            rec = {
                "name": display, "status": "ok", "entity": name,
                "reportDate": rdate, "prevDate": prev_date,
                "positions": len(rows), "top": top,
            }
            if changes:
                rec["changes"] = changes
            out["filers"].append(rec)
            chg_s = ""
            if changes:
                chg_s = f" | 变动: 新进{len(changes['new'])}/清仓{len(changes['exited'])}/加仓{len(changes['increased'])}/减仓{len(changes['decreased'])}"
            print(f"[ok] {display} | {name} | asOf {rdate} | {len(rows)}只 | Top1 {rows[0]['name'] if rows else '-'}{chg_s}")
        except Exception as e:
            out["filers"].append({"name": display, "status": "error", "note": str(e)[:120]})
            print(f"[err] {display}: {str(e)[:100]}")
        time.sleep(0.25)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("saved", OUT)


if __name__ == "__main__":
    main()
