# -*- coding: utf-8 -*-
"""大师动态采集器：每日自动抓取公开资讯源 + 汇总13F快照 + 人工导入收件箱。

数据源（全部公开、免费）：
  - 新浪财经滚动快讯（lid=2516 全球 / 2517 国内）：公开 JSON 接口
  - SEC EDGAR 13F 快照：由 fetch_13f.py 生成的 data/13f.json（本脚本内嵌精简版逻辑可直接复用其产出）
  - data/inbox/*.md|txt：人工导入源（猫笔刀公众号、大摩周报等付费/封闭内容，导入模板见 inbox/README）
分类：宏观策略 / 大师观点 / 持仓变动 / 市场动态；自动检测大师/机构提及。
"""
import glob
import json
import os
import re
import time
import urllib.request
from datetime import datetime

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
BASE = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.join(BASE, "data", "inbox")
FILE_13F = os.path.join(BASE, "data", "13f.json")

SINA_LIDS = [("新浪·全球", "2516"), ("新浪·国内", "2517")]

MASTERS = ["德鲁肯米勒", "Druckenmiller", "Duquesne", "巴菲特", "Berkshire", "芒格", "Munger",
           "索罗斯", "Soros", "达里奥", "Dalio", "桥水", "Bridgewater", "冯柳", "高毅", "高瓴", "Hillhouse",
           "景林", "Greenwoods", "段永平", "李录", "但斌", "林园", "猫笔刀", "付鹏", "洪灝", "任泽平",
           "大摩", "摩根士丹利", "Morgan Stanley", "摩根大通", "JPMorgan", "高盛", "Goldman", "瑞银", "UBS",
           "巴克莱", "Barclays", "德意志银行", "Burry", "Scion", "Ackman", "Pershing", "Tepper", "Appaloosa",
           "ARK", "木头姐", "Cathie Wood", "凯西·伍德"]

CAT_RULES = [
    ("持仓变动", ["13F", "增持", "减持", "清仓", "建仓", "自购", "回购", "举牌", "要约收购"]),
    ("宏观策略", ["美联储", "加息", "降息", "FOMC", "CPI", "通胀", "GDP", "非农", "PMI", "央行", "降准", "降息",
              "国债", "美债", "收益率", "汇率", "人民币", "财政", "货币政策", "关税", "地缘", "油价", "黄金"]),
    ("大师观点", []),  # 由 MASTERS 命中自动归类
]
FALLBACK_CAT = "市场动态"


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_sina(lid, num=25):
    url = (f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid={lid}"
           f"&num={num}&page=1&r={time.time()}")
    data = json.loads(get(url))
    out = []
    for it in (data.get("result", {}).get("data") or []):
        title = re.sub(r"<[^>]+>", "", it.get("title") or "").strip()
        ts = it.get("ctime")
        if not title:
            continue
        try:
            t = datetime.fromtimestamp(int(ts)).strftime("%m-%d %H:%M")
        except Exception:
            t = ""
        out.append({"t": t, "title": title[:110], "src": "新浪财经"})
    return out


def classify(title):
    masters = [m for m in MASTERS if m in title]
    for cat, kws in CAT_RULES:
        if cat == "大师观点":
            continue
        if any(k in title for k in kws):
            return (cat, masters)
    if masters:
        return ("大师观点", masters)
    return (FALLBACK_CAT, masters)



def _get_direct(url, timeout=20):
    """经环境代理请求（本机外网依赖代理出口）。"""
    return get(url, timeout=timeout)


def fetch_maobidao():
    """猫笔刀公众号备份站 RSS（第三方备份，非官方渠道），多镜像兜底。"""
    import xml.etree.ElementTree as ET
    urls = ["http://www.maobidao.net/?feed=rss2", "https://moomoocat.net/feed/",
            "https://www.maobidao.net/?feed=rss2"]
    xml = None
    for u in urls:
        try:
            xml = _get_direct(u, timeout=20)
            if xml and (b"<rss" in xml[:500] or b"<feed" in xml[:500]):
                break
            xml = None
        except Exception:
            continue
    try:
        root = ET.fromstring(xml)
        out = []
        for item in root.iter("item"):
            def t(tag):
                el = item.find(tag)
                return (el.text or "").strip() if el is not None and el.text else ""
            title = t("title")
            link = t("link")
            pub = t("pubDate")  # e.g. Thu, 16 Oct 2026 22:14:00 +0000
            m = re.search(r"(\d{1,2}) (\w{3}) (\d{4})", pub)
            months = {"Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
                      "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"}
            ts = ""
            if m and m.group(2) in months:
                ts = f"{m.group(3)}-{months[m.group(2)]}-{int(m.group(1)):02d}"
            if title:
                out.append({"t": ts or datetime.now().strftime("%Y-%m-%d"),
                            "title": title[:110], "src": "猫笔刀备份站",
                            "force": {"cat": "大师观点", "m": "猫笔刀"}})
        return out
    except Exception:
        return []


def fetch_xueqiu_hot():
    """雪球热股榜（用户关注度情绪样本，Cookie 流程）。"""
    import http.cookiejar
    try:
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.addheaders = [("User-Agent", UA["User-Agent"])]
        opener.open("https://xueqiu.com/", timeout=15).read()
        d = json.loads(opener.open(
            "https://stock.xueqiu.com/v5/stock/hot_stock/list.json?size=10&_type=10&type=10",
            timeout=15).read().decode())
        out = []
        for i, it in enumerate(d.get("data", {}).get("items", [])[:10], 1):
            pct = it.get("percent")
            pct_s = f"{'+' if (pct or 0) >= 0 else ''}{pct:.2f}%" if isinstance(pct, (int, float)) else ""
            out.append({"t": datetime.now().strftime("%m-%d %H:%M"),
                        "title": f"热股#{i} {it.get('name','')}{(' ' + pct_s) if pct_s else ''}（雪球关注度）",
                        "src": "雪球热股", "force": {"cat": "市场动态"}})
        return out
    except Exception:
        return []


def load_inbox():
    items = []
    os.makedirs(INBOX, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(INBOX, "*.md")) + glob.glob(os.path.join(INBOX, "*.txt"))):
        if os.path.basename(path) == "README.md":
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except Exception:
            continue
        # 格式：每行一条「YYYY-MM-DD｜来源｜标题或内容」；或整篇为一篇（文件名=标题）
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        parsed = 0
        for l in lines:
            m = re.match(r"^(\d{4}-\d{2}-\d{2})[｜|]([^｜|]+)[｜|](.+)$", l)
            if m:
                items.append({"t": m.group(1)[5:], "title": m.group(3)[:110],
                              "src": m.group(2).strip(), "inbox": os.path.basename(path)})
                parsed += 1
        if parsed == 0 and lines:
            items.append({"t": datetime.now().strftime("%m-%d"), "title": lines[0][:110],
                          "src": "人工导入", "inbox": os.path.basename(path)})
    return items


def load_13f_summary():
    # 13F 快照：缺失或超过50天未更新时，先运行 fetch_13f.py 刷新（13F每季度披露一次）
    try:
        if (not os.path.exists(FILE_13F)) or (time.time() - os.path.getmtime(FILE_13F) > 50 * 86400):
            import subprocess
            import sys
            subprocess.run([sys.executable, os.path.join(BASE, "fetch_13f.py")],
                           timeout=240, capture_output=True)
    except Exception:
        pass
    if not os.path.exists(FILE_13F):
        return []
    try:
        data = json.load(open(FILE_13F, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for f in data.get("filers", []):
        if f.get("status") == "ok" and f.get("top"):
            rec = {"name": f["name"], "asOf": f.get("reportDate", ""),
                   "positions": f.get("positions", 0), "top1": f["top"][0]["name"]}
            chg = f.get("changes")
            if chg:
                rec["chg"] = f"新{len(chg['new'])}/清{len(chg['exited'])}/加{len(chg['increased'])}/减{len(chg['decreased'])}"
                rec["prev"] = f.get("prevDate", "")
            out.append(rec)
    return out


def run(ctx=None):
    items, sources, errors = [], [], []
    for name, lid in SINA_LIDS:
        try:
            got = fetch_sina(lid)
            sources.append({"name": name, "count": len(got)})
            items.extend(got)
        except Exception as e:
            errors.append(f"{name}: {str(e)[:80]}")
        time.sleep(0.4)
    for name, fn in [("猫笔刀备份", fetch_maobidao), ("雪球热股", fetch_xueqiu_hot)]:
        try:
            got = fn()
            if got:
                sources.append({"name": name, "count": len(got)})
                items.extend(got)
        except Exception as e:
            errors.append(f"{name}: {str(e)[:80]}")
        time.sleep(0.4)
    inbox = load_inbox()
    if inbox:
        sources.append({"name": "人工导入收件箱", "count": len(inbox)})
    items.extend(inbox)

    seen, out_items = set(), []
    for it in items:
        key = it["title"][:40]
        if key in seen:
            continue
        seen.add(key)
        cat, masters = classify(it["title"])
        if it.get("force"):
            cat = it["force"].get("cat", cat)
            if it["force"].get("m"):
                masters = [it["force"]["m"]]
        rec = {"t": it["t"], "title": it["title"], "cat": cat, "src": it["src"]}
        if masters:
            rec["m"] = "、".join(masters[:3])
        out_items.append(rec)
    # 排序：大师观点/持仓变动优先，其后按时间
    w = {"大师观点": 0, "持仓变动": 1, "宏观策略": 2, "市场动态": 3}
    out_items.sort(key=lambda r: (w.get(r["cat"], 9), r["t"]))
    out_items = out_items[:60]

    artifact = {
        "asOf": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sources": sources,
        "filers": load_13f_summary(),
        "items": out_items,
    }
    # 13F 双源校验摘要（如存在）
    try:
        vpath = os.path.join(BASE, "data", "validation.json")
        if os.path.exists(vpath):
            v = json.load(open(vpath, encoding="utf-8"))
            artifact["validation"] = f"13F双源校验({v.get('quarter','?')}，vs GitHub holdingsintel-open-data)：{v.get('passed',0)}/{v.get('checked',0)}家完全一致"
    except Exception:
        pass
    if errors:
        artifact["errors"] = errors
    # 本地留档（便于调试与人工核对）
    try:
        os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
        with open(os.path.join(BASE, "data", "feed.json"), "w", encoding="utf-8") as fp:
            json.dump(artifact, fp, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return {"artifact": artifact}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=1)[:3000])
