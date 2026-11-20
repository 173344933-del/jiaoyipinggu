# -*- coding: utf-8 -*-
"""13F 双源校验：SEC EDGAR 自解析 vs GitHub 开源数据集（holdingsintel-open-data）。

对每家被追踪基金，取 GitHub 数据集 2026-Q2 给出的 accession_number（同一份原始文件），
分别用我们的解析器和参考数据比对：持仓条目数、Top1、Top5 重叠度。
输出 data/validation.json，供大师动态 Widget 与人工核对。
"""
import csv
import json
import os
import re
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
UA = {"User-Agent": "JiaoYiPingGu research@example.com"}
QUARTER = "2026-Q2"

STOP = {"INC", "CO", "CORP", "CORPORATION", "LTD", "LLC", "LP", "THE", "PLC", "SA", "NV", "HOLDINGS", "CLASS", "COM", "CL", "A"}


def norm_name(s):
    s = re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())
    toks = [t for t in s.split() if t not in STOP and len(t) > 1]
    return " ".join(toks)


def token_overlap(a, b):
    ta, tb = set(norm_name(a).split()), set(norm_name(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def load_reference():
    funds, tops = {}, {}
    with open(os.path.join(DATA, "funds.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["quarter"] == QUARTER:
                funds[row["cik"]] = row
    with open(os.path.join(DATA, "fund_top_holdings.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["quarter"] == QUARTER and row["cik"] in funds:
                tops.setdefault(row["cik"], []).append(row)
    for rows in tops.values():
        rows.sort(key=lambda r: int(r["rank"]))
    return funds, tops


def parse_xml_rows(xml):
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except Exception:
        return []
    rows = []
    for info in root.iter():
        if info.tag.split("}")[-1] != "infoTable":
            continue
        name, cusip, val = None, None, 0.0
        for el in info.iter():
            tag = el.tag.split("}")[-1]
            if tag == "nameOfIssuer":
                name = (el.text or "").strip()
            elif tag == "cusip":
                cusip = (el.text or "").strip()
            elif tag == "value":
                try:
                    val = float((el.text or "0").replace(",", ""))
                except ValueError:
                    pass
        if name and val > 0:
            rows.append({"name": name, "cusip": cusip or name, "value": val})
    return rows


def fetch_and_parse(cik_padded, acc_dashed):
    """合并申报包内全部 infoTable（联合申报含多个manager子表），按 CUSIP 聚合价值。"""
    acc = acc_dashed.replace("-", "")
    cik_int = str(int(cik_padded))
    idx = json.loads(urllib.request.urlopen(urllib.request.Request(
        f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/index.json", headers=UA), timeout=30).read())
    cands = [i["name"] for i in idx["directory"]["item"] if i["name"].lower().endswith(".xml")]
    merged = {}
    for fn in cands:
        try:
            xml = urllib.request.urlopen(urllib.request.Request(
                f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/{fn}", headers=UA), timeout=60).read()
            for r in parse_xml_rows(xml):
                key = r["cusip"]
                if key in merged:
                    merged[key]["value"] += r["value"]
                else:
                    merged[key] = dict(r)
        except Exception:
            continue
    best = sorted(merged.values(), key=lambda r: -r["value"])
    return best


def main():
    # 复用 fetch_13f 的基金清单
    ns = {"__file__": os.path.join(BASE, "fetch_13f.py"), "__name__": "fetch_13f_lib"}
    lib = os.path.join(BASE, "fetch_13f.py")
    exec(compile(open(lib, encoding="utf-8").read(), lib, "exec"), ns)
    filers = ns["FILERS"]

    funds, tops = load_reference()
    checks, passed = [], 0
    for display, cik, kw in filers:
        row = funds.get(cik)
        if not row:
            checks.append({"name": display, "status": "ref_missing", "note": "GitHub参考集未收录该机构"})
            continue
        try:
            ours = fetch_and_parse(cik, row["accession_number"])
            time.sleep(0.25)
            ref_top = [t["issuer"] for t in tops.get(cik, [])[:5]]
            ours_top = [r["name"] for r in ours[:5]]
            # 参考集的 positions 按唯一证券计数；我们也按唯一发行人归一化后比对
            ours_unique = len(set(r["cusip"] for r in ours))
            cnt_match = ours_unique == int(row["positions"])
            t1 = token_overlap(ours_top[0] if ours_top else "", ref_top[0] if ref_top else "") >= 0.6
            top5_any = sum(1 for a in ours_top if any(token_overlap(a, b) >= 0.6 for b in ref_top))
            ok = cnt_match and t1
            if ok:
                passed += 1
            checks.append({
                "name": display, "status": "ok" if ok else "diff",
                "ours_rows": len(ours), "ours_unique": ours_unique, "ref_positions": int(row["positions"]),
                "count_match": cnt_match,
                "ours_top1": ours_top[0] if ours_top else "-",
                "ref_top1": ref_top[0] if ref_top else "-",
                "top1_match": t1, "top5_overlap": f"{top5_any}/5",
                "filed": row["filed_date"],
            })
            print(("PASS " if ok else "DIFF "), display, f"rows {len(ours)} / unique {ours_unique} vs ref {row['positions']}",
                  "| top1", "✓" if t1 else "✗", ours_top[0] if ours_top else "-")
        except Exception as e:
            checks.append({"name": display, "status": "error", "note": str(e)[:100]})
            print("ERR  ", display, str(e)[:80])
    out = {
        "quarter": QUARTER, "generated": time.strftime("%Y-%m-%d %H:%M"),
        "reference": "GitHub: holdingsintel/holdingsintel-open-data（独立解析，同accession比对）",
        "checked": len([c for c in checks if c["status"] in ("ok", "diff")]),
        "passed": passed,
        "checks": checks,
    }
    with open(os.path.join(DATA, "validation.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"summary: {passed}/{out['checked']} 一致")


if __name__ == "__main__":
    main()
