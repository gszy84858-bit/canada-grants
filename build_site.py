#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
加拿大补助库 · 静态站点构建

输入：data/programs.json, data/changes.json
输出：docs/index.html（单页，含筛选与搜索）、docs/meta.json、docs/.nojekyll

零第三方依赖。所有筛选在前端完成（数据量小，不必请求接口）。
"""

import json
import os
import re
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "docs")
BUILD = str(int(datetime.now().timestamp()))

BRAND = "加拿大补助库"
NAV_BG = "#1f3a5f"
DISCLAIMER = ("本页只是索引与摘要，不是官方文件。金额、资格与截止日以政府原文为准；"
              "申请前请点开官方页面核对。")


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
        d = date.fromisoformat(p["deadline"])
    except ValueError:
        return None
    return (d - date.today()).days


def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def card(p):
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
        tags.append('<span class="b share">要求配比 %d%%</span>' % p["cost_share"])
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
    level_cn = "省级" if p["level"] == "provincial" else (
        "市级" if p["level"] == "municipal" else "联邦")
    return """
<div class="card" data-level="{level}" data-status="{status}" data-amt="{amt}"
     data-aud="{biz}" data-text="{search}" data-dl="{dlv}">
  <div class="tags">{tags}<span class="b lv">{lv} · {region}</span></div>
  <h3>{zhname}</h3>
  {enname}
  <div class="org">{org}</div>
  <p class="sum">{summary}</p>
  <div class="foot">
    <a href="{url}" target="_blank" rel="noopener">查看官方详情 ↗</a>
    <span class="ver">核对于 {verified}</span>
  </div>
</div>""".format(
        level=esc(p["level"]), status=esc(status),
        amt=("hi" if (p.get("amount_max") or 0) >= 250000 else (
            "mid" if (p.get("amount_max") or 0) >= 50000 else (
                "lo" if p.get("amount_max") else "none"))),
        search=esc((p["name"] + " " + p.get("org", "") + " " + p.get("summary", "")).lower()[:600]),
        dlv=("" if dl is None else dl),
        tags="".join(tags),
        lv=level_cn, region=esc(p.get("region", "")), name=esc(p["name"]),
        biz=("biz" if aud in ("business", "mixed", "unknown") else "other"),
        zhname=esc(p.get("zh_name") or p["name"]),
        enname=('<div class="en">%s</div>' % esc(p["name"])) if p.get("zh_name") else "",
        org=esc(p.get("org", "")),
        summary=esc(p.get("zh_summary") or (p.get("summary") or "")[:260]),
        url=esc(p.get("url") or p.get("source_url") or "#"),
        verified=esc(p.get("last_verified", "")),
    )


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

    # 默认排序：还开着的在前 → 截止日近的在前 → 金额大的在前
    progs = sorted(progs, key=lambda p: (
        0 if p.get("status") == "open" else 1,
        days_left(p) if days_left(p) is not None and days_left(p) >= 0 else 9999,
        -(p.get("amount_max") or 0)))

    cards = "\n".join(card(p) for p in progs)
    new_names = (ch.get("new") or [])[:6]
    new_html = ""
    if new_names:
        new_html = ('<div class="newbox"><b>最近新增 %d 项</b><br>%s</div>'
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
--acc:#1f3a5f;--ok:#1f6f4a;--warn:#a8551a;--bad:#a32d2d}
@media(prefers-color-scheme:dark){:root{--bg:#141413;--card:#1f1f1e;--fg:#eceae4;
--mut:#a5a29b;--line:#33322f;--acc:#8ab4e0;--ok:#5dcaa5;--warn:#e0a458;--bad:#e2645c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif}
.bar{position:sticky;top:0;z-index:9;background:__NAV_BG__;color:#fff;padding:10px 14px;
font:14px/1.4 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}
.wrap{max-width:720px;margin:0 auto;padding:16px 16px 60px}
h1{font-size:21px;margin:6px 0 6px;line-height:1.35}
.sub{color:var(--mut);font-size:13px;margin-bottom:14px}
input[type=search]{width:100%;padding:11px 14px;font-size:16px;border-radius:11px;
border:1px solid var(--line);background:var(--card);color:var(--fg);outline:none;font-family:inherit}
input[type=search]:focus{border-color:var(--acc)}
details.f{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:10px 14px;margin:12px 0 6px}
details.f summary{cursor:pointer;font-size:14px;color:var(--acc);list-style:none}
details.f summary::-webkit-details-marker{display:none}
.fg{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.fg .lb{font-size:12px;color:var(--mut);width:100%;margin-top:4px}
.btn{font-size:13px;padding:5px 11px;border-radius:999px;border:1px solid var(--line);
background:transparent;color:var(--mut);cursor:pointer;font-family:inherit}
.btn.on{background:var(--acc);border-color:var(--acc);color:#fff}
.count{color:var(--mut);font-size:13px;margin:12px 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:15px 16px;margin-bottom:11px}
.card h3{margin:6px 0 4px;font-size:16.5px;line-height:1.45}
.org{color:var(--mut);font-size:12.5px;margin-bottom:8px}
.sum{font-size:14.5px;color:var(--fg);opacity:.9;margin:0 0 10px}
.foot{display:flex;justify-content:space-between;align-items:center;gap:10px;
border-top:1px solid var(--line);padding-top:10px;font-size:12.5px}
.foot a{color:var(--acc);text-decoration:none}
.ver{color:var(--mut);font-size:11.5px}
.tags{display:flex;flex-wrap:wrap;gap:6px}
.en{color:var(--mut);font-size:12.5px;margin-bottom:6px;line-height:1.5}
.b.other{color:var(--mut);opacity:.75}
.b{font-size:11.5px;padding:2px 8px;border-radius:6px;border:1px solid var(--line);color:var(--mut)}
.b.open{color:var(--ok);border-color:var(--ok)}
.b.rest{color:var(--warn);border-color:var(--warn)}
.b.soon{color:var(--bad);border-color:var(--bad)}
.b.over{color:var(--mut);text-decoration:line-through}
.b.amt{color:var(--acc);border-color:var(--acc);font-weight:500}
.newbox{background:rgba(31,111,74,.08);border-left:3px solid var(--ok);
border-radius:0 8px 8px 0;padding:10px 14px;font-size:13.5px;margin:12px 0}
footer{color:var(--mut);font-size:12px;margin-top:26px;line-height:1.7}
.hide{display:none}
</style></head><body>
<div class="bar">__BRAND__ · 大多伦多小企业补助索引</div>
<div class="wrap">
<h1>加拿大补助库</h1>
<div class="sub">共 <b>__N__</b> 个项目（开放 __NOPEN__ · 有金额 __NAMT__ · 有截止日 __NDDL__）<br>
数据源：安省政府资金门户、多伦多市政府商务激励页 · 更新于 __BUILT__</div>

<input id="q" type="search" placeholder="搜项目名、机构、关键词…（如 培训 / 数字化 / 出口）"
 autocomplete="off" autocorrect="off" spellcheck="false">

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
<br><br>本页由程序自动生成，只收录「小企业可申请」的项目；<br>
每条都标注核对日期，数据源均为官方页面。</footer>
</div>
<script>
var F={level:"",status:"",amt:"",aud:"biz"}, Q="";
function render(){
  var q=Q.trim().toLowerCase(), n=0;
  document.querySelectorAll(".card").forEach(function(c){
    var ok=true;
    if(F.level && c.dataset.level!==F.level) ok=false;
    if(F.status && c.dataset.status!==F.status) ok=false;
    if(F.amt && c.dataset.amt!==F.amt) ok=false;
    if(F.aud && c.dataset.aud!==F.aud) ok=false;
    if(ok && q && c.dataset.text.indexOf(q)<0) ok=false;
    c.classList.toggle("hide", !ok);
    if(ok) n++;
  });
  document.getElementById("count").textContent = n + " 个项目";
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
var t=null;
document.getElementById("q").addEventListener("input",function(e){
  clearTimeout(t); var v=e.target.value;
  t=setTimeout(function(){Q=v; render();},120);
});
render();
</script>
</body></html>"""

    html = (html.replace("__NAV_BG__", NAV_BG).replace("__BRAND__", BRAND)
                .replace("__N__", str(len(progs))).replace("__NOPEN__", str(n_open))
                .replace("__NAMT__", str(n_amt)).replace("__NDDL__", str(n_ddl))
                .replace("__BUILT__", d.get("built_at", "")[:16])
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
