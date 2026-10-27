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
import urllib.parse
import urllib.request
from datetime import datetime, date
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "config")
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
    # 用空格代替标签，避免 "<li>a</li><li>b</li>" 拼成 "ab"
    s = re.sub(r"<[^>]+>", " ", s)
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


# ---------------------------------------------------------------------------
# 指向「这个项目自己的官方页面」
# ---------------------------------------------------------------------------
# 旧做法：拿不到详情页就把用户丢给 Google 搜索——等于随便给一个页面。
# 现在按优先级：
#   ① 项目块里自己的官方链接（ontario.ca/page、ontario.ca/document、
#      forms.mgcs.gov.on.ca 的 Program Guidelines 数据集、tpon 申请系统）
#   ② 猜 ontario.ca/page/<slug> 并校验页面标题（命中率低，但中的就是对的）
#   ③ 都没有：官方资金列表页 + 文本片段（#:~:text=项目名前几个词），
#      浏览器会自动滚到那一条，落地就是该项目的原文
# 每个链接都做一次可达性检查，死链（如已停用的 grants.gov.on.ca）不会上线。

OK_HOSTS = ("ontario.ca", "gov.on.ca")   # 含 forms.mgcs.gov.on.ca、tpon.gov.on.ca

NOISE_TOKENS = {"program", "programs", "fund", "funds", "grant", "grants",
                "initiative", "initiatives", "stream", "the", "of", "for", "and",
                "in", "to", "on", "ontario", "provincial", "ministry", "support",
                "designation", "2026", "2027"}


def _host_ok(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(host == h or host.endswith("." + h) for h in OK_HOSTS)


def _tokens(text):
    return {t for t in re.findall(r"[a-z]{4,}", (text or "").lower())
            if t not in NOISE_TOKENS}


def verify_url(url, timeout=10):
    """链接必须真能打开。踩过的坑：Ontario Grants Portal 已停用，
    官方页面里还留着旧链接，直接给用户就是 502 死链。"""
    if not url:
        return False
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA}, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return 200 <= r.status < 400
        except Exception:
            continue
    return False


def pick_program_link(body, title, base_url=""):
    """从项目块里挑出该项目自己的官方页面。

    踩过的坑：Apply 按钮所有项目都指向同一个 TPON 登录页（信息量为零）；
    真正的项目页常常是 forms.mgcs.gov.on.ca 上的 Program Guidelines 数据集——
    旧代码只认 ontario.ca，把这些全漏了，于是退化成「搜索官方页面」。
    """
    cands = []
    nt = _tokens(title)
    for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>([\s\S]{0,90}?)</a>', body):
        href = unescape(m.group(1)).strip()
        if href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        # 相对链接（/page/xxx）先补全域名，否则会被当成外站丢掉
        if base_url:
            href = urllib.parse.urljoin(base_url, href)
        # 去掉 #section-5 这类中段锚点：链接应从标题开始展示
        href = href.split("#")[0]
        if "get-funding-ontario-government" in href or "/search/" in href:
            continue
        if not _host_ok(href):
            continue
        txt = strip_tags(m.group(2))
        low = txt.lower()
        score = 0
        if "guidelin" in low:
            score += 5
        if "/dataset/" in href:
            score += 4
        if re.search(r"(program guide|guide|criteria|how to apply|application form)", low):
            score += 3
        if re.search(r"(learn more|more information|program|funding)", low):
            score += 2
        if "/document/" in href:
            score += 2
        if "/page/" in href:
            score += 1
        score += min(3, len(nt & _tokens(txt + " " + href.replace("-", " "))))
        if score >= 4:
            cands.append((score, href, "项目指南" if "/dataset/" in href else "官方详情"))
    # 分数由高到低逐个试，第一个能打开的就是它
    for score, href, label in sorted(cands, key=lambda x: -x[0])[:5]:
        if verify_url(href):
            return href, label
    return "", ""


def guess_official_page(title):
    """没有链接时，按标题猜 ontario.ca/page/<slug>，并用页面标题验证。

    实测命中率很低（8 个里只中 1 个），所以**必须验证**：
    猜中的页面标题要覆盖项目名 60% 以上的实词，否则宁可不用。
    """
    words = re.findall(r"[a-z0-9]+", re.sub(r"\([^)]*\)", " ",
                     re.sub(r"\b(19|20)\d\d([-/]\d\d)?\b", " ", (title or "").lower())))
    if not words:
        return "", ""
    cands = []
    for drop in (set(), {"program", "fund", "grant", "initiative", "stream",
                         "the", "of", "for", "and", "ontario"}):
        slug = "-".join(w for w in words if w not in drop)
        if slug and slug not in cands:
            cands.append(slug)
    nt = _tokens(title)
    for slug in cands[:3]:
        url = "https://www.ontario.ca/page/" + slug
        try:
            html = http_get(url, timeout=10)
        except Exception:
            continue
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        t = strip_tags(m.group(1)) if m else ""
        if not t or "not found" in t.lower():
            continue
        if nt and len(nt & _tokens(t)) / len(nt) < 0.6:
            continue
        return url, "官方详情"
    return "", ""


def listing_anchor(base_url, title, page_text=""):
    """官方列表页没有每条项目的锚点，只能用文本片段（#:~:text=）定位。

    片段必须是页面上**连续出现**的原文：项目名带括号（BCWA）或冒号时整段匹配不上，
    所以先截到括号/冒号之前，再从 6 个词逐级缩到 3 个词，直到页面上确实有这段。
    """
    base = re.split(r"[(（:]", title or "", 1)[0].strip()
    words = base.split()
    for n in (6, 5, 4, 3):
        if len(words) < n:
            continue
        phrase = " ".join(words[:n])
        if not page_text or phrase.lower() in page_text:
            return base_url + "#:~:text=" + urllib.parse.quote(phrase)
    return base_url


def first_email(html):
    m = re.search(r"mailto:([A-Za-z0-9._%+@-]+\.[A-Za-z]{2,})", html or "")
    if not m:
        return ""
    return urllib.parse.unquote(m.group(1)).strip().strip("<>,;")


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
    """把 'Monday, November 2, 2026, at 4:00 p.m.' 变成 2026-11-02。

    返回 (iso 日期, 类型)，类型只有四种：
      fixed     有明确截止日
      rolling   官方明说没有截止日 / 常年受理
      periodic  分轮次受理（如「每年两轮」），日期见官方页
      unknown   原文没写

    踩过的坑：
      · 序数词被 <sup> 拆成「November 12 th , 2026」→ 先把空格补回去再匹配
      · 明写「There are no funding deadlines」要判 rolling，不能留空
      · 「There are two application intake periods each year」是分轮次，不是无期限
    """
    t = strip_tags(text)
    t = re.sub(r"(\d)\s+(st|nd|rd|th)\b", r"\1\2", t, flags=re.I)

    # ① 先找明确日期——有日期就以日期为准，别被后面的 intake 说明盖掉
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})", t)
    if m and m.group(1).lower() in MONTHS:
        try:
            d = date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
            return d.isoformat(), "fixed"
        except ValueError:
            pass

    low = t.lower()
    # ② 官方说没有截止日
    if any(k in low for k in ("no funding deadline", "no deadline", "no closing",
                              "no application deadline", "ongoing", "continuous intake",
                              "continuous", "rolling", "year-round", "any time",
                              "first come")):
        return "", "rolling"
    # ③ 分轮次受理
    if "intake period" in low or "intake periods" in low or "intakes" in low:
        return "", "periodic"
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
    page_text = strip_tags(html).lower()
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
        if not desc:
            # 少数项目没有 <h3>Description</h3>，正文就是 Ministry 那段之后的 <p>
            paras = [strip_tags(x) for x in re.findall(r"<p>(.*?)</p>", body, re.S)]
            paras = [x for x in paras if x.strip()
                     and not x.lower().startswith(("status:", "ministry"))]
            desc = " ".join(paras)[:1200]
        how_m = re.search(r"<h3>How to apply</h3>([\s\S]*?)(?=<h3>|$)", body)
        how = strip_tags(how_m.group(1), 500) if how_m else ""
        elig_m = re.search(r"<h3>Eligibility</h3>([\s\S]*?)(?=<h3>|$)", body)
        elig = strip_tags(elig_m.group(1), 600) if elig_m else ""
        # 这个项目自己的官方页面；实在没有，就定位到官方资金页里的那一条
        url, link_label = pick_program_link(body, title, src["url"])
        if not url:
            url, link_label = guess_official_page(title)
        anchor_url = listing_anchor(src["url"], title, page_text)
        contact = first_email(body)
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
            "url": url,
            "link_label": link_label,
            "anchor_url": anchor_url,
            "contact": contact,
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
            # 多伦多表格只有 Incentive / Description / Recipient type，没有状态列。
            # 这些项目出现在「现行激励」页上，按受理中处理，并在页面注明以官网为准。
            "status": "open",
            "status_note": "市级项目按官网在列视为受理中",
            "deadline": "",
            "deadline_note": "市府项目多数全年受理，具体以官网为准",
            "deadline_kind": "ongoing",   # 官网没给截止日：按常年受理展示
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

    today_iso = datetime.now().strftime("%Y-%m-%d")
    for p in uniq:
        if p.get("deadline") and p["deadline"] < today_iso and p.get("status") != "closed":
            p["prev_status"] = p.get("status")
            p["status"] = "closed"

    # 受众判定 + 可选中文
    for p in uniq:
        p["audience_type"] = classify_audience(p)
    from collections import Counter
    print("  · 受众分布:", dict(Counter(p["audience_type"] for p in uniq)))

    for p in uniq:
        if not p.get("keywords"):
            p["keywords"] = norm_tags(extract_keywords(p))
        else:
            p["keywords"] = norm_tags(p["keywords"])

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

AUD_KEYS = ("business", "nonprofit", "gov", "indigenous", "mixed", "unknown")

# 卡片上的受众标签（business 是默认视图，不加标签）
AUD_LABEL = {
    "business": "",
    "nonprofit": "限非营利",
    "gov": "限机构 / 协会",
    "indigenous": "限原住民",
    "mixed": "多方均可",
    "unknown": "受众未标注",
}


def load_aud_overrides():
    """读 config/audience.json 的人工覆盖表（按项目名子串匹配）。"""
    path = os.path.join(CFG, "audience.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        out = {}
        for k, v in (data.get("overrides") or {}).items():
            if not k.startswith("_") and v in AUD_KEYS:
                out[k.strip().lower()] = v
        return out
    except Exception as e:
        print("  ! 读取 config/audience.json 失败:", type(e).__name__)
        return {}


AUD_OVERRIDES = load_aud_overrides()


def audience_from_recipient(recipient):
    """多伦多表格的 Recipient type 列 → 受众桶。

    先算「允许谁申请」的四个标记，再决定归属：
      · 同时允许企业与其它主体 → mixed（多方均可）
      · 只给 BIA / 协会 → gov；只给非营利/慈善 → nonprofit；只给原住民 → indigenous
    注意 "business association" / "business improvement" 是协会不是企业，
    判 has_biz 前先剔除，否则 "BIA, business association" 会被当成小企业。
    """
    a = (recipient or "").lower().strip()
    if not a:
        return "unknown"
    a2 = (a.replace("business association", "")
            .replace("business improvement area", "")
            .replace("business improvement", ""))
    has_bia = ("bia" in a2) or ("business association" in a)
    has_bia = has_bia or ("business improvement" in a) or ("chamber of commerce" in a)
    has_npo = any(k in a for k in ("not-for-profit", "non-profit", "nonprofit", "charit"))
    has_ind = "indigenous" in a
    has_biz = any(k in a2 for k in ("business owner", "business operator", "business",
                                    "developer", "property owner", "land owner",
                                    "enterprise", "commercial"))
    if has_biz and (has_npo or has_bia or has_ind):
        return "mixed"
    if has_bia:
        return "gov"
    if has_npo:
        return "nonprofit"
    if has_ind:
        return "indigenous"
    if has_biz:
        return "business"
    return "unknown"


def audience_from_text(p):
    """安省项目没有 Recipient type 列，只能从资格原文粗判；精确的靠 overrides 兜底。"""
    blob = ((p.get("eligibility") or "") + " " + (p.get("summary") or "")).lower()
    if not blob.strip():
        return "unknown"
    biz = any(k in blob for k in ("for-profit", "for profit", "business", "employer",
                                  "corporation", "manufactur"))
    gov = any(k in blob for k in ("municipalit", "city of", "town of", "region of",
                                  "police", "public library", "school board"))
    npo = any(k in blob for k in ("not-for-profit", "non-profit", "charit", "ngo",
                                  "non-government"))
    ind = any(k in blob for k in ("indigenous", "first nation", "métis", "metis"))
    if biz and (gov or npo or ind):
        return "mixed"
    if gov:
        return "gov"
    if npo:
        return "nonprofit"
    if ind:
        return "indigenous"
    return "business" if biz else "unknown"


def classify_audience(p):
    """谁能申请：人工覆盖 → Recipient type → 资格原文 → 未知。"""
    name = (p.get("name") or "").lower()
    for key, bucket in AUD_OVERRIDES.items():
        if key and key in name:
            return bucket
    if (p.get("audience") or "").strip():
        return audience_from_recipient(p["audience"])
    return audience_from_text(p)


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


TAG_VOCAB = [
    "零售", "餐饮", "制造", "科技", "农业", "旅游", "建筑地产", "交通物流",
    "培训", "设备采购", "数字化", "出口", "研发创新", "节能环保", "租金房产税",
    "初创企业", "青年", "女性", "原住民", "非营利", "雇工补贴", "基础设施",
    "社区发展", "文化艺术", "医疗健康", "能源",
]

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


TAG_ALIAS = {
    "基建": "基础设施", "基础设施": "基础设施", "社区": "社区发展",
    "非营利组织": "非营利", "房产税": "租金房产税", "退税": "租金房产税",
    "培训教育": "培训", "数字": "数字化", "创新": "研发创新", "研发": "研发创新",
    "创业": "初创企业", "雇佣": "雇工补贴", "招聘": "雇工补贴",
    "节能": "节能环保", "环保": "节能环保", "减排": "节能环保",
    "文化": "文化艺术", "艺术": "文化艺术", "地产": "建筑地产", "建筑": "建筑地产",
    "设备": "设备采购", "交通": "交通物流", "农业食品": "农业",
}


def norm_tags(tags):
    """把模型给的标签压进受控词表：同义归并 → 丢弃词表外 → 去重保序。"""
    out = []
    for raw in tags:
        t = str(raw).strip().strip("、，, ")
        t = TAG_ALIAS.get(t, t)
        if t in TAG_VOCAB and t not in out:
            out.append(t)
    return out[:4]


def extract_keywords(p):
    """规则兜底：没有 AI 也能给出可检索的标签。"""
    blob = ((p.get("name") or "") + " " + (p.get("summary") or "") + " "
            + (p.get("eligibility") or "") + " " + (p.get("detail") or "")).lower()
    out = []
    for kw, needles in KW_VOCAB.items():
        if any(n in blob for n in needles):
            out.append(kw)
    return out[:5]


def translate(items, key, batch=5):
    """给 name / summary 生成中文。失败无妨，页面回退英文。"""
    prompt_tpl = (
        "把下面加拿大政府补助项目改写成中文，供中文读者快速判断是否值得申请。\n"
        "输出三部分：\n"
        "n = 中文名称（意译，保留英文缩写）\n"
        "s = 一句话摘要，50-70 字，说清「谁能申请 + 钱做什么」\n"
        "d = 详细说明，300-450 字，用换行分成四段（每段以「适用对象：」「资金用途：」"
        "「金额与自付：」「申请准备：」开头）：\n"
        "   · 适用对象：行业、企业规模、地区、是否必须注册/盈利\n"
        "   · 资金用途：钱能花在什么上、不能花在什么上\n"
        "   · 金额与自付：最高多少、政府承担比例、是否需先垫付\n"
        "   · 申请准备：需要哪些材料、有哪些常见门槛或注意事项\n"
        "只依据给定信息；不准编造金额、日期、机构名。某段信息不足时写"
        "「以官方指南为准」，不要省略该段。\n"
        "t = 2-4 个中文标签，**必须从下面词表中选，不要自创新词，不要写地区名**：" 
        + "、".join(TAG_VOCAB) + "\n"
        "只输出 JSON 数组：{\"i\":序号,\"n\":..,\"s\":..,\"d\":..,\"t\":[..]}\n\n")
    order = _gemini_models(key) or GEMINI_MODELS
    ok = 0
    for start in range(0, len(items), batch):
        chunk = items[start:start + batch]
        body = prompt_tpl + "\n".join(
            "[%d] %s\n机构:%s\n地区:%s\n原文摘要:%s\n资格:%s\n原文正文:%s" % (
                i, it["name"], it.get("org", ""), it.get("region", ""),
                (it.get("summary") or "")[:500], (it.get("eligibility") or "")[:500],
                (it.get("detail") or "")[:1800])
            for i, it in enumerate(chunk))
        payload = {"contents": [{"role": "user", "parts": [{"text": body}]}],
                   "generationConfig": {"temperature": 0.2,
                                        "responseMimeType": "application/json",
                                        "maxOutputTokens": 8192}}
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
                            chunk[i]["keywords"] = norm_tags(tags)
                        if chunk[i]["zh_name"]:
                            ok += 1
                break
            except Exception as e:
                print("    ! 中文失败(%s) %s" % (model, type(e).__name__))
    return ok


if __name__ == "__main__":
    sys.exit(main())
