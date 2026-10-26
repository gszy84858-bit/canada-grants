#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
加拿大补助库 · 静态站点构建

输入：data/programs.json, data/changes.json
输出：docs/index.html（单页）、docs/meta.json、docs/.nojekyll

四个体验要点：
  1. 顶部目录：一屏看完全部项目名，点一下直达该条（锚点）
  2. 搜索：标题 / 机构 / 摘要 / 详情 / 关键词全索引
  3. 热门关键词：一键填入搜索框
  4. 每条有摘要 + 可展开的详细说明
"""

import json
import os
import re
from collections import Counter
from datetime import date, datetime
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "docs")
BUILD = str(int(datetime.now().timestamp()))

BRAND = "加拿大补助库"
NAV_BG = "#1f3a5f"
DISCLAIMER = ("本页是索引与摘要，不是官方文件。金额、资格与截止日以政府原文为准；"
              "申请前请点开「官方详情」核对。")


def money(v):
    if not v:
        return ""
    if v >= 1_000_000:
        s = ("%.1f" % (v / 1_000_000)).rstrip("0").rstrip(".")
        return "$%sM" % s
    if v >= 1000:
        return "$%sK" % ("%.0f" % (v / 1000))
    return "$%d" % v


def days_left(p):
    if not p.get("deadline"):
        return None
    try:
        return (date.fromisoformat(p["deadline"]) - date.today()).days
    except ValueError:
        return None


def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def clip(text, n=200):
    """按句末标点截断，避免出现「buying machiner」这种半句。"""
    t = (text or "").strip()
    if len(t) <= n:
        return t
    head = t[:n]
    cut = max(head.rfind("。"), head.rfind("！"), head.rfind("？"),
              head.rfind(". "), head.rfind("; "))
    return (head[:cut + 1] if cut > n * 0.5 else head).strip() + "…"


def anchor(p):
    return "p-" + re.sub(r"[^a-z0-9]+", "-", p["id"].lower()).strip("-")[-48:]


def card(p, idx=0):
    dl = days_left(p)
    status = p.get("status") or "unknown"
    tags = []
    if status == "open":
        tags.append('<span class="b open">开放申请</span>')
    elif status == "restricted":
        tags.append('<span class="b rest">限特定对象</span>')
    if p.get("amount_max"):
        tags.append('<span class="b amt">上限 %s</span>' % money(p["amount_max"]))
    if p.get("cost_share"):
        tags.append('<span class="b share">需自付 %d%%</span>' % (100 - int(p["cost_share"])))
    if dl is not None:
        if dl < 0:
            tags.append('<span class="b over">已过期</span>')
        elif dl <= 14:
            tags.append('<span class="b soon">还剩 %d 天</span>' % dl)
        else:
            tags.append('<span class="b ddl">截止 %s</span>' % p["deadline"])
    elif p.get("deadline_kind") == "rolling":
        tags.append('<span class="b ddl">滚动受理</span>')

    aud = p.get("audience_type") or "unknown"
    if aud in ("municipal", "police", "institution", "indigenous"):
        tags.append('<span class="b other">限机构/团体</span>')
    elif aud == "nonprofit":
        tags.append('<span class="b other">限非营利</span>')

    level_cn = {"provincial": "省级", "municipal": "市级"}.get(p["level"], "联邦")

    kw = "".join('<span class="k" data-k="%s">%s</span>' % (esc(k), esc(k))
                 for k in (p.get("keywords") or [])[:5])

    detail = (p.get("zh_detail") or "").strip()
    if not detail:
        raw = (p.get("detail") or p.get("summary") or "").strip()
        detail = raw[:900]

    # 分段：优先按换行；没有换行就每 2 句一段
    parts = [x.strip() for x in re.split(r"\n+", detail) if x.strip()]
    if len(parts) <= 1 and len(detail) > 120:
        sents = re.split(r"(?<=[。！？])", detail)
        parts, buf = [], ""
        for sen in sents:
            buf += sen
            if len(buf) >= 110:
                parts.append(buf.strip()); buf = ""
        if buf.strip():
            parts.append(buf.strip())
    detail_html = "".join("<p>%s</p>" % esc(x) for x in parts) or "<p>%s</p>" % esc(detail)
    how = (p.get("how_to_apply") or "").strip()

    rows = []
    if p.get("amount_max"):
        rows.append(("金额", "最高 %s" % money(p["amount_max"])))
    if p.get("cost_share"):
        rows.append(("自付比例", "至少 %d%%（政府承担 %d%%）" % (
            100 - int(p["cost_share"]), int(p["cost_share"]))))
    if p.get("deadline"):
        rows.append(("截止", "%s（%s）" % (p["deadline"], p.get("deadline_text", "")[:60])))
    elif p.get("deadline_kind") == "rolling":
        rows.append(("截止", "滚动受理，随时可申请"))
    if p.get("eligibility"):
        rows.append(("资格", p["eligibility"][:220]))
    if how:
        rows.append(("怎么申请", how[:220]))
    if not p.get("url"):
        rows.append(("链接说明", "该项目在安省资金页上没有独立详情页；"
                               "点下方「搜索官方页面」可在 ontario.ca 内找到相关页面。"))
    rows.append(("核对日期", p.get("last_verified", "")))

    rows_html = "".join("<tr><th>%s</th><td>%s</td></tr>" % (esc(k), esc(v))
                        for k, v in rows)

    if p.get("url"):
        links = ('<a href="%s" target="_blank" rel="noopener">官方详情 ↗</a>'
                 % esc(p["url"]))
    else:
        links = ('<a href="%s" target="_blank" rel="noopener">搜索官方页面 ↗</a>'
                 % esc(p.get("search_url") or p.get("source_url") or "#"))
        if p.get("source_url"):
            links += (' <a class="sec" href="%s" target="_blank" rel="noopener">'
                      '资金列表页 ↗</a>' % esc(p["source_url"]))

    return """
<article class="card" id="{aid}" data-level="{level}" data-status="{status}"
 data-amt="{amt}" data-aud="{biz}" data-dl="{dlv}" data-text="{search}">
  <div class="tags">{tags}<span class="b lv">{lv} · {region}</span></div>
  <h3><span class="num">{num}.</span> {zhname}</h3>
  {enname}
  <div class="org">{org}</div>
  <p class="sum">{summary}</p>
  {kwhtml}
  <details class="more"><summary>详情 / 资格 / 怎么申请</summary>
    <div class="detail">{detail}</div>
    <table class="meta">{rows}</table>
  </details>
  <div class="foot">
    {links}
    <a class="top" href="#toc">回到目录 ↑</a>
  </div>
</article>""".format(
        aid=anchor(p), num=idx, level=esc(p["level"]), status=esc(status),
        amt=("hi" if (p.get("amount_max") or 0) >= 250000 else (
            "mid" if (p.get("amount_max") or 0) >= 50000 else (
                "lo" if p.get("amount_max") else "none"))),
        biz=esc(aud),
        dlv=("" if dl is None else dl),
        search=esc(" ".join([
            p.get("name", ""), p.get("zh_name", ""), p.get("org", ""),
            p.get("summary", ""), p.get("zh_summary", ""), p.get("zh_detail", ""),
            p.get("eligibility", ""), p.get("region", ""), " ".join(p.get("keywords") or [])]
        ).lower()[:1200]),
        tags="".join(tags), lv=level_cn, region=esc(p.get("region", "")),
        zhname=esc(p.get("zh_name") or p["name"]),
        enname=('<div class="en">%s</div>' % esc(p["name"])) if p.get("zh_name") else "",
        org=esc(p.get("org", "")),
        summary=esc(p.get("zh_summary") or clip(p.get("summary") or "", 220)),
        kwhtml=('<div class="kws">%s</div>' % kw) if kw else "",
        detail=detail_html, rows=rows_html,
        links=links,
    )


def toc_block(progs, progs_index):
    """目录：一条连续编号，和正文编号完全对应；层级用小标签表示。"""
    lis = []
    for p in progs:
        lv = {"provincial": "省", "municipal": "市"}.get(p["level"], "联")
        lis.append(
            '<li><a href="#%s"><span class="tnum">%d</span>'
            '<span class="tlv">%s</span>%s</a>%s</li>' % (
                anchor(p), progs_index[p["id"]] + 1, lv,
                esc(p.get("zh_name") or p["name"]),
                '<span class="mini">%s</span>' % money(p["amount_max"]) if p.get("amount_max") else ""))
    return '<div class="tocg"><ul>%s</ul></div>' % "".join(lis)


def main():
    with open(os.path.join(DATA, "programs.json"), encoding="utf-8") as f:
        d = json.load(f)
    progs = d["programs"]
    try:
        with open(os.path.join(DATA, "changes.json"), encoding="utf-8") as f:
            ch = json.load(f)
    except Exception:
        ch = {}

    n_open = sum(1 for p in progs if p.get("status") == "open")
    n_amt = sum(1 for p in progs if p.get("amount_max"))
    n_ddl = sum(1 for p in progs if p.get("deadline"))

    LV = {"provincial": 0, "municipal": 1, "federal": 2}
    # 小企业能申请的排最前 → 默认视图编号从 1 连续
    def aud_rank(p):
        return 0 if (p.get("audience_type") or "unknown") in ("business", "mixed", "unknown") else 1
    progs = sorted(progs, key=lambda p: (
        aud_rank(p),
        LV.get(p["level"], 3),
        0 if p.get("status") == "open" else 1,
        days_left(p) if days_left(p) is not None and days_left(p) >= 0 else 9999,
        -(p.get("amount_max") or 0)))

    # 热门关键词：出现频次最高的 8 个
    freq = Counter(k for p in progs for k in (p.get("keywords") or []))
    hot = "".join(
        '<span class="hk" data-k="%s">%s<span class="cnt">%d</span></span>'
        % (esc(k), esc(k), n) for k, n in freq.most_common(12))

    cards = "\n".join(card(p, i + 1) for i, p in enumerate(progs))
    progs_index = {p["id"]: i for i, p in enumerate(progs)}
    toc = toc_block(progs, progs_index)

    new_names = (ch.get("new") or [])[:5]
    new_html = ""
    if new_names:
        new_html = ('<div class="newbox"><b>最近新增 %d 项</b>　%s</div>'
                    % (len(ch.get("new") or []), "、".join(esc(x) for x in new_names)))

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="__NAV_BG__">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="加拿大补助库">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>加拿大补助库 · 大多伦多小企业</title>
<style>
:root{--bg:#f7f6f3;--card:#fff;--fg:#1c1c1a;--mut:#6b6a66;--line:#e4e2dc;
--barfg:#1f3a5f;--acc:#1f3a5f;--ok:#1f6f4a;--warn:#a8551a;--bad:#a32d2d;--soft:#eef2f7}
@media(prefers-color-scheme:dark){:root{--bg:#141413;--card:#1f1f1e;--fg:#eceae4;
--mut:#a5a29b;--line:#33322f;--acc:#8ab4e0;--ok:#5dcaa5;--warn:#e0a458;--bad:#e2645c;--soft:#242628}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif}
.bar{position:sticky;top:0;z-index:20;background:__NAV_BG__;color:#fff;
padding:7px 10px;font:14px/1.4 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;
display:flex;align-items:center;gap:6px;flex-wrap:nowrap}
.brand{font-size:13.5px;font-weight:500;white-space:nowrap;flex:0 0 auto}
.bshort{display:none}
@media(max-width:470px){
  .bar{padding:6px 8px;gap:5px}
  .bfull{display:none}
  .bshort{display:inline}
  .bar .btn{padding:5px 6px;font-size:11.5px}
  .bar input[type=search]{font-size:14px;padding:6px 8px}
  .upd,.subsrc{display:none}
  .sub{font-size:12.5px;margin-bottom:10px}
}
.bar input[type=search]{flex:1 1 90px;min-width:0;padding:6px 9px;font-size:15px;
border-radius:8px;border:1px solid rgba(255,255,255,.35);background:rgba(255,255,255,.92);
color:#1c1c1a;outline:none;font-family:inherit}
.bar input[type=search]::placeholder{color:#7a7a76;font-size:13px}
.bar .btn{flex:0 0 auto;color:#fff;background:transparent;
border:1px solid rgba(255,255,255,.5);border-radius:7px;padding:5px 8px;
font-size:12px;line-height:1.2;white-space:nowrap}
.bar .btn.on{background:#fff;color:var(--barfg);border-color:#fff}
.bar .btn{color:#fff;background:transparent;border:1px solid rgba(255,255,255,.55);
border-radius:6px;padding:3px 10px;font-size:13px}
.wrap{max-width:760px;margin:0 auto;padding:16px 16px 70px}
h1{font-size:21px;margin:4px 0 6px}
.sub{color:var(--mut);font-size:13px;margin-bottom:14px;line-height:1.7}
.tools{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:12px 0 0}
input[type=search]{flex:1 1 160px;min-width:0;padding:9px 13px;font-size:16px;
border-radius:10px;border:1px solid var(--line);background:var(--card);
color:var(--fg);outline:none;font-family:inherit}
.tools .btn{white-space:nowrap;padding:6px 11px}
.panel{display:none;margin-top:10px}
.panel.open{display:block}
input[type=search]:focus{border-color:var(--acc)}
.toolrow{display:flex;align-items:center;gap:8px;margin:10px 0 0}
.tiny{font-size:12px;color:var(--mut)}
.hot{display:flex;flex-wrap:wrap;gap:7px;margin:0}
.hk{font-size:13px;padding:5px 11px;border-radius:999px;background:var(--soft);
color:var(--acc);cursor:pointer;user-select:none;display:inline-flex;gap:5px;align-items:center;
border:1px solid transparent}
.hk:hover{border-color:var(--acc)}
.hk .cnt{font-size:11px;opacity:.65}
.hk.on{background:var(--acc);color:#fff}
#tocPanel,#filterPanel,#hotPanel{background:var(--card);border:1px solid var(--line);
border-radius:12px;padding:12px 14px}
.fg{display:flex;flex-wrap:nowrap;gap:6px;align-items:center;
margin-top:8px;overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.fg::-webkit-scrollbar{display:none}
.fg .lb{font-size:11.5px;color:var(--mut);flex:0 0 auto;width:40px;margin:0}
.fg .btn{flex:0 0 auto;white-space:nowrap;padding:3px 7px;font-size:11.5px}
.btn{font-size:13px;padding:5px 11px;border-radius:999px;border:1px solid var(--line);
background:transparent;color:var(--mut);cursor:pointer;font-family:inherit}
.btn.on{background:var(--acc);border-color:var(--acc);color:#fff}

.tocg{margin-top:10px}
.toch{font-size:12.5px;color:var(--mut);margin:10px 0 6px;letter-spacing:.03em}
.panel ul{margin:0;padding-left:0;list-style:none;columns:2;column-gap:20px}
@media(max-width:560px){.panel ul{columns:1}}
.tocbar{position:sticky;top:46px;z-index:18;display:flex;align-items:center;gap:8px;
flex-wrap:wrap;background:#1f3a5f;color:#fff;padding:9px 12px;border-radius:10px;
margin:10px 0 0;box-shadow:0 3px 10px rgba(0,0,0,.18)}
.tocbar[hidden]{display:none}
.tocbar .txt{font-size:14px;font-weight:600;letter-spacing:.02em;flex:1 1 auto;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tocbar .btn{padding:5px 10px;font-size:12.5px;color:#fff;background:rgba(255,255,255,.16);
border:1px solid rgba(255,255,255,.7);border-radius:7px;font-weight:500}
.tocbar .btn:active{background:rgba(255,255,255,.3)}
.panel li{font-size:13.5px;padding:3px 0;break-inside:avoid}
.panel a{color:var(--fg);text-decoration:none;border-bottom:1px dotted var(--line)}
.panel a:hover{color:var(--acc)}
.mini{color:var(--acc);font-size:11.5px;margin-left:6px}
.count{color:var(--mut);font-size:13px;margin:14px 0 10px}
.newbox{background:rgba(31,111,74,.08);border-left:3px solid var(--ok);
border-radius:0 8px 8px 0;padding:10px 14px;font-size:13px;margin:12px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:15px 16px;margin-bottom:11px;scroll-margin-top:60px}
.card:target{border-color:var(--acc);box-shadow:0 0 0 2px rgba(31,58,95,.15)}
.card.flash{border-color:var(--acc);box-shadow:0 0 0 3px rgba(31,58,95,.28)}
.card h3{margin:6px 0 4px;font-size:17px;line-height:1.45}
h3 .num{color:var(--acc);font-weight:500}
.tnum{display:inline-block;min-width:22px;color:var(--acc);font-size:12px}
.tlv{display:inline-block;font-size:10.5px;color:var(--mut);border:1px solid var(--line);
border-radius:4px;padding:0 3px;margin-right:5px;vertical-align:1px}
.detail p{margin:0 0 8px;font-size:14px;opacity:.94;line-height:1.75}
.en{color:var(--mut);font-size:12.5px;margin-bottom:6px;line-height:1.5}
.org{color:var(--mut);font-size:12.5px;margin-bottom:8px}
.sum{font-size:14.5px;margin:0 0 8px}
.kws{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 10px}
.k{font-size:11.5px;padding:2px 8px;border-radius:6px;background:var(--soft);
color:var(--acc);cursor:pointer}
details.more{margin:2px 0 10px}
details.more summary{font-size:13px;color:var(--acc);cursor:pointer;list-style:none}
details.more summary::-webkit-details-marker{display:none}
details.more summary::before{content:"＋ ";}
details.more[open] summary::before{content:"− ";}
.detail{font-size:14px;color:var(--fg);opacity:.92;margin:8px 0 10px;
border-left:2px solid var(--line);padding-left:12px}
table.meta{width:100%;border-collapse:collapse;font-size:13px}
table.meta th{text-align:left;color:var(--mut);font-weight:400;width:74px;
padding:5px 8px 5px 0;vertical-align:top;border-top:1px solid var(--line)}
table.meta td{padding:5px 0;border-top:1px solid var(--line)}
.foot{display:flex;justify-content:space-between;align-items:center;gap:10px;
border-top:1px solid var(--line);padding-top:10px;font-size:12.5px}
.foot a{color:var(--acc);text-decoration:none}
.foot a.sec{color:var(--mut);font-size:12px}
.b{font-size:11.5px;padding:2px 8px;border-radius:6px;border:1px solid var(--line);color:var(--mut)}
.b.open{color:var(--ok);border-color:var(--ok)}
.b.rest,.b.share{color:var(--warn);border-color:var(--warn)}
.b.soon{color:var(--bad);border-color:var(--bad)}
.b.over{color:var(--mut);text-decoration:line-through}
.b.amt{color:var(--acc);border-color:var(--acc);font-weight:500}
.b.other{opacity:.7}
.tags{display:flex;flex-wrap:wrap;gap:6px}
footer{color:var(--mut);font-size:12px;margin-top:26px;line-height:1.7}
.hide{display:none}
</style></head><body>
<div class="bar">
  <span class="brand"><span class="bfull">🍁 __BRAND__</span><span class="bshort">🍁 补助库</span></span>
  <input id="q" type="search" placeholder="搜索项目 / 关键词"
   autocomplete="off" autocorrect="off" spellcheck="false">
  <button class="btn" id="ktog" type="button">关键词</button>
  <button class="btn" id="ttog" type="button">目录</button>
  <button class="btn" id="ftog" type="button">筛选</button>
</div>
<div class="wrap">
<div class="sub">共 <b>__N__</b> 个项目 · 开放 <b>__NOPEN__</b> · 有金额 <b>__NAMT__</b> · 有截止日 <b>__NDDL__</b><span class="upd">　更新于 __BUILT__</span><span class="subsrc"><br>数据源：安省资金门户 · 多伦多商务激励</span></div>

<div class="panel" id="hotPanel"><div class="hot" id="hot">__HOT__</div></div>

<div class="tocbar" id="tocbar" hidden>
  <span class="txt">点任一项目跳到该条</span>
  <button class="btn" id="showall" type="button">显示全部项目</button>
  <button class="btn" id="hideall" type="button">收起目录</button>
</div>

<div class="panel" id="tocPanel"><a id="toc"></a>
  __TOC__
</div>

<div class="panel" id="filterPanel">
  <div class="fg" data-g="level"><span class="lb">层级</span>
    <button class="btn on" data-v="">全部</button>
    <button class="btn" data-v="provincial">省级</button>
    <button class="btn" data-v="municipal">市级</button></div>
  <div class="fg" data-g="status"><span class="lb">状态</span>
    <button class="btn on" data-v="">全部</button>
    <button class="btn" data-v="open">仅看开放</button></div>
  <div class="fg" data-g="aud"><span class="lb">对象</span>
    <button class="btn" data-v="">全部</button>
    <button class="btn on" data-v="biz">小企业</button>
    <button class="btn" data-v="nonprofit">非营利</button>
    <button class="btn" data-v="gov">机构</button></div>
  <div class="fg" data-g="amt"><span class="lb">金额</span>
    <button class="btn on" data-v="">不限</button>
    <button class="btn" data-v="lo">≤5万</button>
    <button class="btn" data-v="mid">5-25万</button>
    <button class="btn" data-v="hi">&gt;25万</button></div>
</div>

<div class="count" id="count"></div>
__NEWBOX__
__CARDS__
<footer>__DISC__
<br><br>只收录「小企业可申请」的项目；每条标注核对日期，数据源均为官方页面。</footer>
</div>
<script>
var F={level:"",status:"",amt:"",aud:"biz"}, Q="", TOTAL=__TOTAL__;
var AUD_SET = {
  biz: ["business","mixed","unknown"],
  nonprofit: ["nonprofit"],
  gov: ["municipal","police","institution"]
};
var VIEW_HIDDEN=false;
var hotPanel=document.getElementById("hotPanel"),
    tocPanel=document.getElementById("tocPanel"),
    filterPanel=document.getElementById("filterPanel"),
    ktog=document.getElementById("ktog"), ttog=document.getElementById("ttog"),
    ftog=document.getElementById("ftog"), box=document.getElementById("q");
var PANELS=[[ktog,hotPanel],[ttog,tocPanel],[ftog,filterPanel]];
var tocBar=document.getElementById("tocbar");
function showBar(v){ tocBar.hidden = !v; }
showBar(false);

function render(){
  var q=Q.trim().toLowerCase(), n=0;
  document.querySelectorAll(".card").forEach(function(c){
    var ok=true;
    if(F.level && c.dataset.level!==F.level) ok=false;
    if(F.status && c.dataset.status!==F.status) ok=false;
    if(F.amt && c.dataset.amt!==F.amt) ok=false;
    if(F.aud && AUD_SET[F.aud] && AUD_SET[F.aud].indexOf(c.dataset.aud)<0) ok=false;
    if(ok && q && c.dataset.text.indexOf(q)<0) ok=false;
    c.classList.toggle("hide", !ok || VIEW_HIDDEN);
    if(ok) n++;
  });
  document.getElementById("count").textContent = VIEW_HIDDEN
    ? "目录模式 · 共 "+TOTAL+" 个项目，点目录项查看"
    : (n<TOTAL ? "显示 "+n+" / "+TOTAL+" 个项目" : TOTAL+" 个项目");
}

function togglePanel(btn, panel){
  var open = !panel.classList.contains("open");
  PANELS.forEach(function(p){ p[1].classList.remove("open"); p[0].classList.remove("on"); });
  if(open){ panel.classList.add("open"); btn.classList.add("on"); }
  VIEW_HIDDEN = tocPanel.classList.contains("open");
  showBar(VIEW_HIDDEN);
  render();
}
ktog.onclick=function(){ togglePanel(ktog, hotPanel); };
ttog.onclick=function(){ togglePanel(ttog, tocPanel); };
ftog.onclick=function(){ togglePanel(ftog, filterPanel); };
document.querySelectorAll('a[href="#toc"]').forEach(function(a){
  a.addEventListener("click", function(){ togglePanel(ttog, tocPanel); });
});

document.querySelectorAll(".fg").forEach(function(g){
  g.querySelectorAll(".btn").forEach(function(b){
    b.onclick=function(){
      F[g.dataset.g]=b.dataset.v;
      g.querySelectorAll(".btn").forEach(function(x){x.classList.toggle("on",x===b);});
      render();
    };
  });
});

var t=null;
box.addEventListener("input",function(e){
  clearTimeout(t); var v=e.target.value;
  t=setTimeout(function(){Q=v; render();},120);
});

function setQ(v){
  box.value=v; Q=v; render();
  window.scrollTo({top: box.getBoundingClientRect().top+window.scrollY-70, behavior:"smooth"});
}
document.getElementById("hot").addEventListener("click",function(e){
  var chip = e.target.closest ? e.target.closest(".hk") : null;
  if(!chip) return;
  var same = chip.classList.contains("on");
  document.querySelectorAll("#hot .hk").forEach(function(c){ c.classList.remove("on"); });
  if(same){ setQ(""); return; }              // 再点一次取消
  chip.classList.add("on");
  setQ(chip.dataset.k);
});
document.body.addEventListener("click",function(e){
  if(e.target.classList.contains("k")) { setQ(e.target.dataset.k); }
});
document.getElementById("hideall").addEventListener("click", function(e){
  e.preventDefault(); e.stopPropagation();
  tocPanel.classList.remove("open"); ttog.classList.remove("on");
  VIEW_HIDDEN = false; showBar(false); render();
  window.scrollTo(0, 0);
});
document.getElementById("showall").addEventListener("click", function(e){
  e.preventDefault(); e.stopPropagation();
  tocPanel.classList.remove("open"); ttog.classList.remove("on");
  VIEW_HIDDEN=false; showBar(false); render();
});
// 点目录项：先清空筛选与搜索（否则目标被筛掉、页面无落点），再滚动过去
tocPanel.querySelectorAll('a[href^="#p-"]').forEach(function(a){
  a.addEventListener("click", function(ev){
    ev.preventDefault();
    var id = a.getAttribute("href").slice(1);

    // 重置筛选：每个筛选组都回到「全部」
    F = {level:"",status:"",amt:"",aud:""};
    document.querySelectorAll(".fg").forEach(function(g){
      g.querySelectorAll(".btn").forEach(function(b){
        b.classList.toggle("on", b.dataset.v === "");
      });
    });
    // 清空搜索
    Q = ""; box.value = "";

    // 只收起目录列表，吸顶提示条保留（用户还能一键回到目录）
    tocPanel.classList.remove("open"); ttog.classList.remove("on");
    VIEW_HIDDEN = false;
    showBar(true);
    render();

    var el = document.getElementById(id);
    if (el) {
      // 不用 requestAnimationFrame：PWA 独立窗口/后台标签页里可能不触发。
      // 读一次 offsetHeight 强制完成布局，再同步滚动，最稳。
      void el.offsetHeight;
      var y = el.getBoundingClientRect().top + window.scrollY - 64;
      window.scrollTo(0, y);
      el.classList.add("flash");
      setTimeout(function(){ el.classList.remove("flash"); }, 1600);
    }
  });
});
render();
</script>
</body></html>"""

    html = (html.replace("__NAV_BG__", NAV_BG).replace("__BRAND__", BRAND)
                .replace("__N__", str(len(progs))).replace("__NOPEN__", str(n_open))
                .replace("__NAMT__", str(n_amt)).replace("__NDDL__", str(n_ddl))
                .replace("__TOTAL__", str(len(progs)))
                .replace("__BUILT__", d.get("built_at", "")[:16])
                .replace("__HOT__", hot).replace("__TOC__", toc)
                .replace("__NEWBOX__", new_html).replace("__CARDS__", cards)
                .replace("__DISC__", DISCLAIMER))

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"build": BUILD, "count": len(progs),
                   "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False)
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    print("站点已构建：%s（%d 个项目）" % (OUT, len(progs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
