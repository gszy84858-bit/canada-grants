#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
加拿大补助库 · 抓取与结构化

数据源（第一版只做两个官方源，稳定、可抓、权威）：
  1. 安省 · Available funding opportunities（单页汇总，h2 分块）
  2. 多伦多市 · Business Grants, Incentives & Rebates（表格）

输出：
  data/programs.json   结构化项目库（带 first_seen / last_verified）
  data/changes.json    与上一版对比出的变更（新增 / 截止日变化 / 状态变化）

零第三方依赖，只用标准库。
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, date
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
RAW = os.path.join(HERE, "raw")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SOURCES = [
    {
        "id": "on-available-funding",
        "level": "provincial",
        "region": "Ontario",
        "org_default": "Government of Ontario",
        "url": "https://www.ontario.ca/page/available-funding-opportunities-ontario-government",
        "file": "on.html",
    },
    {
        "id": "toronto-incentives",
        "level": "municipal",
        "region": "Toronto",
        "org_default": "City of Toronto",
        "url": "https://www.toronto.ca/business-incentives",
        "file": "to.html",
    },
]

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "en-CA,en;q=0.9",
        "Accept-Encoding": "gzip, identity"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
            import gzip
            raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def strip_tags(s, limit=None):
    s = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", s or "")
    s = re.sub(r"<br\s*/?>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] if limit else s


def fetch_detail_text(url, name="", limit=1600):
    """抓详情页正文并清洗：去掉导航、面包屑、页脚样板文字。"""
    try:
        html = http_get(url, timeout=25)
    except Exception:
        return ""
    m = re.search(r"<main[\s\S]*?</main>", html, re.I)
    body = m.group(0) if m else html
    body = re.sub(r"<(nav|footer|header|script|style|form)[\s\S]*?</\1>", " ", body, flags=re.I)
    body = re.sub(r'<[^>]+class="[^"]*(breadcrumb|menu|nav|skip|share|related|newsletter)[^"]*"[\s\S]{0,400}?>',
                  " ", body, flags=re.I)
    txt = strip_tags(body)

    # 从项目名第一次出现处开始，砍掉前面整段站点导航
    if name:
        key = name[:40].lower()
        i = txt.lower().find(key)
        if 0 < i < 600:
            txt = txt[i:]

    # 去掉「项目名 – 站点名」这种标题残留
    txt = re.sub(r"^.{0,90}?\s[–—|-]\s(City of Toronto|Government of Ontario)\s*", " ", txt)

    noise = ["skip to content", "français", "search", "menu", "sign in",
             "you are here", "home >", "share this page", "was this page helpful"]
    for n in noise:
        txt = re.sub(re.escape(n), " ", txt, flags=re.I)
    txt = re.sub(r"\s{2,}", " ", txt).strip()
    return txt[:limit]


def parse_amount(text):
    """从描述里抽「单个申请人能拿多少」，不是基金总规模。

    踩过的坑：
      · "up to 90 percent of eligible costs" → 90 被当成金额
      · "a $500 million program that provides funding to..." → 总规模被当成单笔上限
    所以按优先级找「per project / maximum / 上限」句式，并排除后面跟 program/fund 的数字。
    """
    t = (text or "").replace("\u00a0", " ")
    flat = t.replace(",", "")
    low = flat.lower()

    def to_val(num, unit):
        v = float(num)
        return v * 1000000 if unit else v

    def is_total(i, tail):
        """数字后面紧跟 program/fund/investment → 是总规模，不是单笔。"""
        seg = flat[i:i + 40].lower()
        return bool(re.search(r"(program|fund|initiative|investment|envelope)", seg))

    mn = mx = None
    share = None

    # 配比（cost-share）：只认明确写 costs 的比例
    for ms in re.finditer(r"(\d{1,3})\s*(?:per cent|%)", low):
        tail = low[ms.end():ms.end() + 45]
        if "cost" in tail:
            share = int(ms.group(1))
            break

    # ① 区间：from $A to $B / between $A and $B
    m = re.search(r"(?:from|between)\s*\$\s*([\d.]+)\s*(million)?\s*(?:to|and)\s*\$\s*([\d.]+)\s*(million)?", low)
    if m:
        a, b = to_val(m.group(1), m.group(2)), to_val(m.group(3), m.group(4))
        # 前面说的是「项目成本区间」而不是「补助金额」→ 不采信（宁缺勿错）
        ctx = low[max(0, m.start() - 90):m.start()]
        if not re.search(r"(cost|costs|project size|capital projects)", ctx):
            mn, mx = min(a, b), max(a, b)

    # ② 单笔上限（最可靠的几种写法）
    if mx is None:
        cands = []
        for pat in (
            r"maximum\s+(?:amount\s+)?(?:of\s+)?(?:funding\s+)?(?:is\s+|of\s+)?\$\s*([\d.]+)\s*(million)?",
            r"up\s+to\s+(?:a\s+maximum\s+of\s+)?\$\s*([\d.]+)\s*(million)?",
            r"\$\s*([\d.]+)\s*(million)?\s*(?:per|for\s+each)\s+(?:road\s+|bridge\s+)?(?:project|applicant|recipient|business|loan|property)",
            r"(?:micro-?grant|grant|loan|rebate|funding)\s+of\s+\$\s*([\d.]+)\s*(million)?",
        ):
            for mm in re.finditer(pat, low):
                if is_total(mm.start(), flat[mm.start():]):
                    continue
                cands.append(to_val(mm.group(1), mm.group(2) if mm.lastindex and mm.lastindex >= 2 else None))
        if cands:
            mn, mx = 0.0, max(cands)

    # ③ 不再兜底：只信「up to / maximum / per project / grant of」这类明确句式。
    #    宁可显示「见详情」，也不能把项目成本当作补助上限。

    if mx is not None and mx < 100:      # $90 这种明显是百分比/笔误
        mn = mx = None
    return mn, mx, share, ""


def fmt_money(v):
    if v is None:
        return ""
    if v >= 1000000:
        s = ("%.1f" % (v / 1000000)).rstrip("0").rstrip(".")
        return s + "M"
    if v >= 1000:
        s = ("%.0f" % (v / 1000))
        return s + "K"
    return ("%.0f" % v)


def parse_deadline(text):
    """把 'Monday, November 2, 2026, at 4:00 p.m.' 变成 2026-11-02。"""
    t = strip_tags(text)
    low = t.lower()
    if any(k in low for k in ("ongoing", "any time", "continuous", "rolling")):
        return "", "rolling"
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),?\s*(\d{4})", t)
    if m and m.group(1).lower() in MONTHS:
        try:
            d = date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
            return d.isoformat(), "fixed"
        except ValueError:
            pass
    return "", "unknown"


def norm_url(base, href):
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        host = re.match(r"https?://[^/]+", base)
        return (host.group(0) if host else "https://www.ontario.ca") + href
    return base.rsplit("/", 1)[0] + "/" + href


def parse_ontario(html, src):
    """安省页面：每个项目是一个 h2 分块，块内含 Status / Ministry / h3 小节。"""
    out = []
    chunks = html.split("<h2>")
    for ch in chunks[1:]:
        title = strip_tags(ch.split("</h2>", 1)[0])
        body = ch[:6000]
        if not title or "Status:" not in body[:900]:
            continue
        status_m = re.search(r"Status:\s*<span[^>]*>([A-Za-z ]+)</span>", body)
        status = (status_m.group(1).strip().lower() if status_m else "")
        org_m = re.search(r"<p>(Ministry[^<]{0,80})</p>", body)
        org = org_m.group(1).strip() if org_m else src["org_default"]
        dl_m = re.search(r"<h3>Deadline</h3>\s*<p>(.*?)</p>", body, re.S)
        dl_text = strip_tags(dl_m.group(1)) if dl_m else ""
        desc_m = re.search(r"<h3>Description</h3>([\s\S]*?)(?=<h3>|$)", body)
        desc = strip_tags(desc_m.group(1), 1200) if desc_m else ""
        how_m = re.search(r"<h3>How to apply</h3>([\s\S]*?)(?=<h3>|$)", body)
        how = strip_tags(how_m.group(1), 500) if how_m else ""
        elig_m = re.search(r"<h3>Eligibility</h3>([\s\S]*?)(?=<h3>|$)", body)
        elig = strip_tags(elig_m.group(1), 600) if elig_m else ""
        apply_m = re.search(r'<a class="button" href="([^"]+)"', body)
        # 优先给「项目指南/详情页」，通用申请页被所有项目共用、信息量为零
        guide_m = re.search(r'Program guidelines[\s\S]{0,80}?href="([^"]+)"', body)
        detail = norm_url(src["url"], guide_m.group(1)) if guide_m else ""
        url = detail or norm_url(src["url"], apply_m.group(1) if apply_m else "")
        d_iso, d_kind = parse_deadline(dl_text)
        mn, mx, share, _ = parse_amount(desc + " " + elig)
        out.append({
            "id": "%s/%s" % (src["id"], re.sub(r"[^a-z0-9]+", "-", title.lower())[:60].strip("-")),
            "name": title,
            "level": src["level"],
            "region": src["region"],
            "org": org,
            "status": status or "unknown",
            "deadline": d_iso,
            "deadline_kind": d_kind,
            "deadline_text": dl_text,
            "amount_min": mn,
            "amount_max": mx,
            "cost_share": share,
            "summary": desc[:600],
            "detail": desc,
            "how_to_apply": how,
            "eligibility": elig,
            "url": url or src["url"],
            "source": src["id"],
            "source_url": src["url"],
            "audience": "",
        })
    return out


def parse_toronto(html, src):
    """多伦多页面：表格 <tr><td><a>名称</a></td><td>描述</td><td>适用对象</td></tr>"""
    out = []
    pat = re.compile(
        r"<tr>\s*<td><a href=\"([^\"]+)\"[^>]*>(.*?)</a></td>\s*"
        r"<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", re.S)
    for m in pat.finditer(html):
        url, name, desc, aud = m.group(1), strip_tags(m.group(2)), strip_tags(m.group(3)), strip_tags(m.group(4))
        if not name or len(desc) < 15:
            continue
        mn, mx, share, _ = parse_amount(desc + " " + aud)
        out.append({
            "id": "%s/%s" % (src["id"], re.sub(r"[^a-z0-9]+", "-", name.lower())[:60].strip("-")),
            "name": name,
            "level": src["level"],
            "region": src["region"],
            "org": src["org_default"],
            "status": "unknown",
            "deadline": "",
            "deadline_kind": "unknown",
            "deadline_text": "",
            "amount_min": mn,
            "amount_max": mx,
            "cost_share": share,
            "summary": desc[:600],
            "detail": fetch_detail_text(url, name) if url else desc,
            "how_to_apply": "",
            "eligibility": "",
            "url": url,
            "source": src["id"],
            "source_url": src["url"],
            "audience": aud,
        })
    return out


PARSERS = {"on-available-funding": parse_ontario, "toronto-incentives": parse_toronto}


def load_prev():
    p = os.path.join(DATA, "programs.json")
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                return {x["id"]: x for x in json.load(f).get("programs", [])}
        except Exception:
            pass
    return {}


def main():
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(RAW, exist_ok=True)
    prev = load_prev()
    today = date.today().isoformat()
    programs, errors = [], []

    for src in SOURCES:
        try:
            html = http_get(src["url"])
            with open(os.path.join(RAW, src["file"]), "w", encoding="utf-8") as f:
                f.write(html)
            got = PARSERS[src["id"]](html, src)
            print("  + %-22s %3d 个项目" % (src["id"], len(got)))
            programs.extend(got)
        except Exception as e:
            errors.append({"source": src["id"], "error": "%s: %s" % (type(e).__name__, str(e)[:120])})
            print("  ! %-22s 抓取失败 %s" % (src["id"], e))

    # 去重（同名同机构保留信息更全的一条）
    seen, uniq = {}, []
    for p in programs:
        key = re.sub(r"[^a-z0-9]+", "", (p["name"] + p["org"]).lower())[:80]
        if key in seen:
            old = seen[key]
            if len(p["summary"]) > len(old["summary"]):
                uniq[uniq.index(old)] = p
                seen[key] = p
            continue
        seen[key] = p
        uniq.append(p)

    for p in uniq:
        p.setdefault("detail", p.get("summary", ""))
        p.setdefault("how_to_apply", "")
        p.setdefault("keywords", [])

    # 受众判定 + 可选中文
    for p in uniq:
        p["audience_type"] = classify_audience(p)
    from collections import Counter
    print("  · 受众分布:", dict(Counter(p["audience_type"] for p in uniq)))

    for p in uniq:
        if not p.get("keywords"):
            p["keywords"] = extract_keywords(p)

    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if key and uniq:
        n = translate(uniq, key)
        print("  · 中文：%d/%d 条" % (n, len(uniq)))
    else:
        print("  · 未配置 GEMINI_API_KEY，保持英文（页面仍可正常浏览）")

    # 与上一版对比，产出变更
    changes = {"date": today, "new": [], "deadline": [], "status": [], "removed": []}
    for p in uniq:
        old = prev.get(p["id"])
        p["first_seen"] = old.get("first_seen", today) if old else today
        p["last_verified"] = today
        if not old:
            changes["new"].append(p["name"])
        else:
            if old.get("deadline") and p.get("deadline") and old["deadline"] != p["deadline"]:
                changes["deadline"].append({"name": p["name"], "from": old["deadline"], "to": p["deadline"]})
            if old.get("status") and p.get("status") and old["status"] != p["status"]:
                changes["status"].append({"name": p["name"], "from": old["status"], "to": p["status"]})
    cur_ids = {p["id"] for p in uniq}
    changes["removed"] = [{"name": v["name"], "id": k} for k, v in prev.items() if k not in cur_ids]

    uniq.sort(key=lambda x: (x["level"], x["region"], x["name"]))
    with open(os.path.join(DATA, "programs.json"), "w", encoding="utf-8") as f:
        json.dump({"built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "count": len(uniq), "errors": errors, "programs": uniq},
                  f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATA, "changes.json"), "w", encoding="utf-8") as f:
        json.dump(changes, f, ensure_ascii=False, indent=1)

    n_open = sum(1 for p in uniq if p["status"] == "open")
    n_amt = sum(1 for p in uniq if p["amount_max"])
    print("\n合计 %d 个项目（开放 %d，有金额 %d）" % (len(uniq), n_open, n_amt))
    if changes["new"]:
        print("新增: %d 个" % len(changes["new"]))
    return 0 if uniq else 1




# ---------------------------------------------------------------------------
# 受众判定：只保留「小企业能申请」的，其余打标签但不默认展示
# ---------------------------------------------------------------------------

AUDIENCE_RULES = [
    ("municipal", ["municipalit", "city of", "town of", "region of", "local services board"]),
    ("police", ["police service", "police services", "solicitor general"]),
    ("nonprofit", ["not-for-profit", "non-profit", "charit", "nonprofit"]),
    ("indigenous", ["indigenous communit", "first nation", "métis", "metis"]),
    ("institution", ["university", "college", "hospital", "school board"]),
]

BUSINESS_HINTS = ["business", "sme", "enterprise", "employer", "company",
                  "corporation", "entrepreneur", "retail", "manufactur"]


def classify_audience(p):
    """返回 business / mixed / nonprofit / municipal / police / indigenous / institution。

    判定顺序：先看「明确排除小企业」的信号，再看有没有企业向表述。
    宁可标成 mixed（让人自己看详情），也不要漏掉真能申请的项目。
    """
    blob = ((p.get("eligibility") or "") + " " + (p.get("summary") or "") + " "
            + (p.get("audience") or "")).lower()
    if not blob.strip():
        return "unknown"
    hits = [tag for tag, kws in AUDIENCE_RULES if any(k in blob for k in kws)]
    biz = any(k in blob for k in BUSINESS_HINTS)

    # 多伦多表格自带「适用对象」列，最权威
    aud = (p.get("audience") or "").lower()
    if "business owner" in aud or "business" in aud:
        return "business"
    if "bia" in aud or "not-for-profit" in aud or "charity" in aud:
        return "nonprofit"

    if "police" in hits or "institution" in hits:
        return "police" if "police" in hits else "institution"
    if "municipal" in hits and not biz:
        return "municipal"
    if "indigenous" in hits and not biz:
        return "indigenous"
    if biz and len(hits) <= 1:
        return "business"
    if biz:
        return "mixed"
    return "nonprofit" if "nonprofit" in hits else "unknown"


# ---------------------------------------------------------------------------
# 中文（可选）：有 GEMINI_API_KEY 就翻译，没有就保持英文
# ---------------------------------------------------------------------------

GEMINI_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-latest"]


def _gemini_models(key):
    try:
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
            headers={"x-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        out = []
        for m in data.get("models") or []:
            n = (m.get("name") or "").split("/")[-1]
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            if "flash" not in n.lower() or any(x in n.lower() for x in ("image", "tts", "vision", "embedding")):
                continue
            out.append(n)
        return out
    except Exception:
        return []


KW_VOCAB = {
    "零售": ["retail", "storefront", "shop"],
    "制造": ["manufactur", "factory", "production"],
    "科技": ["technolog", "software", "digital", "ai ", "artificial intelligence"],
    "餐饮": ["restaurant", "food service", "cafe", "hospitality"],
    "农业": ["agri", "farm", "food processing"],
    "旅游": ["tourism", "visitor", "hospitality"],
    "培训": ["training", "skills", "workforce"],
    "设备": ["equipment", "capital", "machinery"],
    "数字化": ["digital", "e-commerce", "online", "automation"],
    "出口": ["export", "international market", "trade"],
    "研发": ["research", "r&d", "innovation", "prototype"],
    "能效": ["energy efficien", "retrofit", "emission", "clean"],
    "租金": ["rent", "lease", "property tax"],
    "新创": ["startup", "start-up", "new business", "entrepreneur"],
    "青年": ["youth", "student", "young"],
    "女性": ["women", "woman"],
    "原住民": ["indigenous", "first nation"],
    "非营利": ["not-for-profit", "charit"],
    "雇佣": ["hire", "hiring", "wage", "job"],
}


def extract_keywords(p):
    """规则兜底：没有 AI 也能给出可检索的标签。"""
    blob = ((p.get("name") or "") + " " + (p.get("summary") or "") + " "
            + (p.get("eligibility") or "") + " " + (p.get("detail") or "")).lower()
    out = []
    for kw, needles in KW_VOCAB.items():
        if any(n in blob for n in needles):
            out.append(kw)
    return out[:5]


def translate(items, key, batch=8):
    """给 name / summary 生成中文。失败无妨，页面回退英文。"""
    prompt_tpl = (
        "把下面加拿大政府补助项目改写成中文，供中文读者快速判断是否值得申请。\n"
        "输出三部分：\n"
        "n = 中文名称（意译，保留英文缩写）\n"
        "s = 一句话摘要，50-70 字，说清「谁能申请 + 钱做什么」\n"
        "d = 详细说明，180-260 字，依次覆盖：适用对象（行业/规模/地区）、资金用途、"
        "金额与自付比例、申请门槛或需要准备的材料；只依据给定信息，不要编造金额与日期，"
        "信息不足就写「以官方指南为准」\n"
        "t = 3-5 个中文检索关键词（如：零售、数字化、培训、出口、女性创业）\n"
        "只输出 JSON 数组：{\"i\":序号,\"n\":..,\"s\":..,\"d\":..,\"t\":[..]}\n\n")
    order = _gemini_models(key) or GEMINI_MODELS
    ok = 0
    for start in range(0, len(items), batch):
        chunk = items[start:start + batch]
        body = prompt_tpl + "\n".join(
            "[%d] %s\n机构:%s\n摘要:%s\n资格:%s" % (
                i, it["name"], it.get("org", ""),
                (it.get("summary") or "")[:400], (it.get("eligibility") or "")[:300])
            for i, it in enumerate(chunk))
        payload = {"contents": [{"role": "user", "parts": [{"text": body}]}],
                   "generationConfig": {"temperature": 0.2,
                                        "responseMimeType": "application/json",
                                        "maxOutputTokens": 4096}}
        for model in order:
            try:
                req = urllib.request.Request(
                    "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json", "x-goog-api-key": key},
                    method="POST")
                with urllib.request.urlopen(req, timeout=90) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
                txt = "".join(p.get("text", "") for p in
                              (data["candidates"][0]["content"]["parts"]))
                txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
                rows = json.loads(txt)
                for row in rows:
                    i = int(row.get("i", -1))
                    if 0 <= i < len(chunk):
                        chunk[i]["zh_name"] = (row.get("n") or "").strip()
                        chunk[i]["zh_summary"] = (row.get("s") or "").strip()
                        chunk[i]["zh_detail"] = (row.get("d") or "").strip()
                        tags = row.get("t") or []
                        if isinstance(tags, list):
                            chunk[i]["keywords"] = [str(x).strip() for x in tags if str(x).strip()][:6]
                        if chunk[i]["zh_name"]:
                            ok += 1
                break
            except Exception as e:
                print("    ! 中文失败(%s) %s" % (model, type(e).__name__))
    return ok


if __name__ == "__main__":
    sys.exit(main())
