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
    rows.append(("核对日期", p.get("last_verified", "")))

    rows_html = "".join("<tr><th>%s</th><td>%s</td></tr>" % (esc(k), esc(v))
                        for k, v in rows)

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
    <a href="{url}" target="_blank" rel="noopener">官方详情 ↗</a>
    <a class="top" href="#toc">回到目录 ↑</a>
  </div>
</article>""".format(
        aid=anchor(p), num=idx, level=esc(p["level"]), status=esc(status),
        amt=("hi" if (p.get("amount_max") or 0) >= 250000 else (
            "mid" if (p.get("amount_max") or 0) >= 50000 else (
                "lo" if p.get("amount_max") else "none"))),
        biz=("biz" if aud in ("business", "mixed", "unknown") else "other"),
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
        summary=esc(p.get("zh_summary") or (p.get("summary") or "")[:200]),
        kwhtml=('<div class="kws">%s</div>' % kw) if kw else "",
        detail=detail_html, rows=rows_html,
        url=esc(p.get("url") or p.get("source_url") or "#"),
    )


def toc_block(progs, progs_index):
    """目录：按层级分组，每项一个锚点。"""
    groups = [("省级（安大略）", "provincial"), ("市级（多伦多）", "municipal")]
    out = []
    for label, key in groups:
        items = [p for p in progs if p["level"] == key]
        if not items:
            continue
        lis = "".join(
            '<li><a href="#%s"><span class="tnum">%d</span>%s</a>%s</li>' % (
                anchor(p), progs_index[p["id"]] + 1,
                esc(p.get("zh_name") or p["name"]),
                '<span class="mini">%s</span>' % money(p["amount_max"]) if p.get("amount_max") else "")
            for p in items)
        out.append('<div class="tocg"><div class="toch">%s · %d 个</div><ul>%s</ul></div>'
                   % (esc(label), len(items), lis))
    return "".join(out)


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
    progs = sorted(progs, key=lambda p: (
        LV.get(p["level"], 3),
        0 if p.get("status") == "open" else 1,
        days_left(p) if days_left(p) is not None and days_left(p) >= 0 else 9999,
        -(p.get("amount_max") or 0)))

    # 热门关键词：出现频次最高的 8 个
    freq = Counter(k for p in progs for k in (p.get("keywords") or []))
    hot = "".join('<span class="hk" data-k="%s">%s</span>' % (esc(k), esc(k))
                  for k, _ in freq.most_common(8))

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
--acc:#1f3a5f;--ok:#1f6f4a;--warn:#a8551a;--bad:#a32d2d;--soft:#eef2f7}
@media(prefers-color-scheme:dark){:root{--bg:#141413;--card:#1f1f1e;--fg:#eceae4;
--mut:#a5a29b;--line:#33322f;--acc:#8ab4e0;--ok:#5dcaa5;--warn:#e0a458;--bad:#e2645c;--soft:#242628}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif}
.bar{position:sticky;top:0;z-index:20;background:__NAV_BG__;color:#fff;padding:10px 14px;
font:14px/1.4 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;
display:flex;justify-content:space-between;align-items:center}
.bar a{color:#fff;text-decoration:none;font-size:13px;border:1px solid rgba(255,255,255,.5);
border-radius:6px;padding:2px 9px}
.wrap{max-width:760px;margin:0 auto;padding:16px 16px 70px}
h1{font-size:21px;margin:4px 0 6px}
.sub{color:var(--mut);font-size:13px;margin-bottom:14px;line-height:1.7}
input[type=search]{width:100%;padding:11px 14px;font-size:16px;border-radius:11px;
border:1px solid var(--line);background:var(--card);color:var(--fg);outline:none;font-family:inherit}
input[type=search]:focus{border-color:var(--acc)}
.toolrow{display:flex;align-items:center;gap:8px;margin:10px 0 0}
.tiny{font-size:12px;color:var(--mut)}
.hot{display:none;flex-wrap:wrap;gap:6px;margin:9px 0 0}
.hot.open{display:flex}
.hk{font-size:12.5px;padding:4px 10px;border-radius:999px;background:var(--soft);
color:var(--acc);cursor:pointer;user-select:none}
details.f{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:10px 14px;margin:12px 0 0}
details.f summary,details.toc summary{cursor:pointer;font-size:14px;color:var(--acc);list-style:none}
details.f summary::-webkit-details-marker,details.toc summary::-webkit-details-marker{display:none}
.fg{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.fg .lb{font-size:12px;color:var(--mut);width:100%;margin-top:4px}
.btn{font-size:13px;padding:5px 11px;border-radius:999px;border:1px solid var(--line);
background:transparent;color:var(--mut);cursor:pointer;font-family:inherit}
.btn.on{background:var(--acc);border-color:var(--acc);color:#fff}
details.toc{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:12px 16px;margin:14px 0}
.tocg{margin-top:10px}
.toch{font-size:12.5px;color:var(--mut);margin:10px 0 6px;letter-spacing:.03em}
details.toc ul{margin:0;padding-left:0;list-style:none;columns:2;column-gap:20px}
@media(max-width:560px){details.toc ul{columns:1}}
.tochint{font-size:12.5px;color:var(--mut);line-height:1.7;margin:8px 0 4px;
background:var(--soft);border-radius:8px;padding:8px 10px}
.tochint .btn{padding:3px 9px;font-size:12px}
details.toc li{font-size:13.5px;padding:3px 0;break-inside:avoid}
details.toc a{color:var(--fg);text-decoration:none;border-bottom:1px dotted var(--line)}
details.toc a:hover{color:var(--acc)}
.mini{color:var(--acc);font-size:11.5px;margin-left:6px}
.count{color:var(--mut);font-size:13px;margin:14px 0 10px}
.newbox{background:rgba(31,111,74,.08);border-left:3px solid var(--ok);
border-radius:0 8px 8px 0;padding:10px 14px;font-size:13px;margin:12px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:15px 16px;margin-bottom:11px;scroll-margin-top:60px}
.card:target{border-color:var(--acc);box-shadow:0 0 0 2px rgba(31,58,95,.15)}
.card h3{margin:6px 0 4px;font-size:17px;line-height:1.45}
h3 .num{color:var(--acc);font-weight:500}
.tnum{display:inline-block;min-width:22px;color:var(--acc);font-size:12px}
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
<div class="bar"><span>__BRAND__</span><a href="#toc">目录</a></div>
<div class="wrap">
<h1>加拿大补助库</h1>
<div class="sub">共 <b>__N__</b> 个项目 · 开放 <b>__NOPEN__</b> · 有金额 <b>__NAMT__</b> · 有截止日 <b>__NDDL__</b><br>
数据源：安省政府资金门户、多伦多市政府商务激励 · 更新于 __BUILT__</div>

<input id="q" type="search" placeholder="搜项目名、机构、关键词…（如 培训 / 数字化 / 出口 / 零售）"
 autocomplete="off" autocorrect="off" spellcheck="false">
<div class="toolrow"><button class="btn" id="ktog" type="button">关键词 ▾</button>
<span class="tiny">按行业/用途快速筛选</span></div>
<div class="hot" id="hot">__HOT__</div>

<details class="toc" id="toc"><summary>目录 · 点击任一项目查看详情</summary>
<div class="tochint">目录展开时，下面的项目列表会自动收起；点任意项目，或再点一次「目录」标题，就会显示正文。　<button class="btn" id="showall" type="button">显示项目列表</button></div>
__TOC__
</details>

<details class="f"><summary>筛选 ▾</summary>
  <div class="fg" data-g="level"><span class="lb">层级</span>
    <button class="btn on" data-v="">全部</button>
    <button class="btn" data-v="provincial">省级</button>
    <button class="btn" data-v="municipal">市级</button></div>
  <div class="fg" data-g="status"><span class="lb">状态</span>
    <button class="btn on" data-v="">全部</button>
    <button class="btn" data-v="open">仅看开放</button></div>
  <div class="fg" data-g="aud"><span class="lb">适合谁</span>
    <button class="btn on" data-v="biz">小企业可申请</button>
    <button class="btn" data-v="">全部项目</button></div>
  <div class="fg" data-g="amt"><span class="lb">金额</span>
    <button class="btn on" data-v="">不限</button>
    <button class="btn" data-v="lo">5 万以下</button>
    <button class="btn" data-v="mid">5–25 万</button>
    <button class="btn" data-v="hi">25 万以上</button></div>
</details>

<div class="count" id="count"></div>
__NEWBOX__
__CARDS__
<footer>__DISC__
<br><br>只收录「小企业可申请」的项目；每条标注核对日期，数据源均为官方页面。</footer>
</div>
<script>
var F={level:"",status:"",amt:"",aud:"biz"}, Q="", TOTAL=__TOTAL__;
var toc=document.getElementById("toc"), VIEW_HIDDEN=toc.open;
var hotBox=document.getElementById("hot"), ktog=document.getElementById("ktog");
function render(){
  var q=Q.trim().toLowerCase(), n=0;
  document.querySelectorAll(".card").forEach(function(c){
    var ok=true;
    if(F.level && c.dataset.level!==F.level) ok=false;
    if(F.status && c.dataset.status!==F.status) ok=false;
    if(F.amt && c.dataset.amt!==F.amt) ok=false;
    if(F.aud && c.dataset.aud!==F.aud) ok=false;
    if(ok && q && c.dataset.text.indexOf(q)<0) ok=false;
    c.classList.toggle("hide", !ok || VIEW_HIDDEN);
    if(ok) n++;
  });
  document.getElementById("count").textContent = VIEW_HIDDEN
    ? "目录模式 · 共 "+TOTAL+" 个项目，点目录项查看"
    : (n<TOTAL ? "显示 "+n+" / "+TOTAL+" 个项目" : TOTAL+" 个项目");
}
document.querySelectorAll(".fg").forEach(function(g){
  g.querySelectorAll(".btn").forEach(function(b){
    b.onclick=function(){
      F[g.dataset.g]=b.dataset.v;
      g.querySelectorAll(".btn").forEach(function(x){x.classList.toggle("on",x===b);});
      render();
    };
  });
});
var box=document.getElementById("q"), t=null;
function setQ(v){
  box.value=v; Q=v; render();
  window.scrollTo({top: box.getBoundingClientRect().top+window.scrollY-70, behavior:"smooth"});
}
box.addEventListener("input",function(e){
  clearTimeout(t); var v=e.target.value;
  t=setTimeout(function(){Q=v; render();},120);
});
ktog.addEventListener("click", function(){
  var open = hotBox.classList.toggle("open");
  ktog.textContent = open ? "关键词 ▴" : "关键词 ▾";
});
hotBox.addEventListener("click",function(e){
  if(e.target.classList.contains("hk")) setQ(e.target.dataset.k);
});
document.body.addEventListener("click",function(e){
  if(e.target.classList.contains("k")) setQ(e.target.dataset.k);
});
// 一律默认收起：打开就是正文，想浏览目录再点
toc.removeAttribute("open"); VIEW_HIDDEN=false;
toc.addEventListener("toggle", function(){ VIEW_HIDDEN = toc.open; render(); });
document.getElementById("showall").addEventListener("click", function(e){
  e.preventDefault(); e.stopPropagation();
  toc.open = false; VIEW_HIDDEN = false; render();
  window.scrollTo({top: document.getElementById("count").offsetTop - 80, behavior:"smooth"});
});
// 点目录项：关掉目录 → 恢复列表 → 浏览器跳到锚点
toc.querySelectorAll('a[href^="#p-"]').forEach(function(a){
  a.addEventListener("click", function(){ toc.open = false; VIEW_HIDDEN = false; render(); });
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
