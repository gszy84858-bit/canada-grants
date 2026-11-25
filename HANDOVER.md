# 交接文档 · 加拿大补助库

> **给接手的人 / 新会话的 AI**：先读完这一页，再按需翻 `notes/` 里的四份详细文档。
> 不要一上来通读代码——这两个脚本加起来 1700 行，读文档十分钟能省掉两小时。

---

## 1. 这是什么

把散落在安省政府和多伦多市政府网站上的补助项目，整理成**中文、可筛选、带截止日**的索引页。
每天自动更新一次，免费、免注册、不用装 App，手机加到主屏就能用。

| 项 | 值 |
|---|---|
| 线上地址 | https://gszy84858-bit.github.io/canada-grants/ |
| 仓库 | https://github.com/gszy84858-bit/canada-grants （**公开**，Pages 免费版只支持公开仓库） |
| 本地路径 | `~/Documents/GitHub/canada-grants` |
| 运行方式 | GitHub Actions 每天 **10:00 UTC**（配置为多伦多 5-6 点）+ push 到 `main` 自动触发。**实际常延迟 6-10 小时**，多伦多时间下午才更新完，详见第 6 节 |
| 数据源 | 安省 Available funding opportunities、多伦多 Business Incentives，+ 约克/荷顿/皮尔 5 个精选官方项目页，+ 联邦 ISED 贷款基金页（共 8 个 source，均为官方页） |
| 依赖 | **零第三方库**，只用 Python 3 标准库 |
| 成本 | 0 元（免费 Pages + 免费 Actions + Gemini 免费层） |
| 用户 | 一个做跨境电商（ShopNorth，加拿大+美国市场）的华人卖家，主要用**手机**看 |

## 2. 现状快照（2026-11-25 核实）

| 指标 | 值 |
|---|---|
| 数据源 | **8 个**：安省 26 + 多伦多 28 + 约克 2 + 荷顿 1 + 皮尔 2 + 联邦 ISED 1（区级是人工核对的精选官方项目页，不是总表；条数每天在变） |
| 收录总数 | **每天波动**。11-25 扩源上线后线上 `count=57`（本地全量抓取 60 条，差 3 条为过期项） |
| 在架（首页展示） | **57**（11-25 15:20 线上实测） |
| 已过期（自动过滤） | 3（11-25 线上实测） |
| 提交数 | 43（含本次扩信源、关键词/翻译修复与文档更新） |
| 最近一次线上构建 | 2026-11-25 15:20:28（多伦多时间，扩源上线后；判断更新只看 `built_at`） |

**条数以线上 `meta.json` 为准**，别拿本地 `data/programs.json` 判断线上状态——本地快照停在 11-17。

线上 `/expired.html` 已返回 **404**——过期页在 10-28 按用户要求删掉了，那是预期行为，不是故障。

## 3. 八条铁律（违反任何一条都会出事）

1. **零第三方依赖。** 只用 Python 3 标准库。加 `requests` / `bs4` / `pandas` 就破坏了这个项目的可维护性（用户电脑和 CI 都不用装东西）。
2. **宁缺勿错，尤其是金额。** 只在 `up to` / `maximum` / `per project` / `grant of $X` 这类明确句式下才展示金额。项目成本区间、基金总规模**绝不能**当成单笔补助上限。错一个数字比不写糟糕得多。
3. **每条链接必须指向「这个项目自己」的官方页。** 不许给搜索结果页、不许给通用申请入口（TPON 登录页）、不许给相似页面糊弄。做不到就明说「官方原文 · 定位到该条」+ 给出官方咨询邮箱。
4. **每条必须有截止信息。** 五种写法之一：明确日期 / 滚动受理 / 常年受理 / 分轮次受理 / 截止日见官方页。**不允许留空白**。
5. **`docs/` 和 `data/` 不进 git。** 它们由 CI 每天重建（`data/` 靠 Actions 缓存传递）。所以「删一个页面」「改一次数据」**不能靠删文件提交**，必须改生成器 + 让 CI 重跑。Pages 部署是整站替换，旧文件会自动消失。
6. **时区锁死 `America/Toronto`。** CI runner 是 UTC，页面上的「数据更新于」必须显式按多伦多时间算。
7. **推送：本机现在可以直接推。** 2026-11-24 实测：`gh` CLI + git 共用同一令牌，**已含 `workflow` scope**，所以连 `.github/workflows/*.yml` 也能直接推（当天通过设备码授权补上的）。改完**自己直接推**，别再让用户手动点。只有报 `could not read Username` / 权限被拒时才退回老办法：让用户在 VS Code 点 Push，或按 `⌘⇧P` → `Git: Push`。
8. **改 `HTML_TPL` 里的 JS 要小心 Python 转义。** 模板是 Python 三引号字符串，里面的 `\n` 会被 Python 吃掉，要用 `String.fromCharCode(10)`。改完必须本地构建一次看结果。

## 4. 三条命令（全部工作都从这儿开始）

```bash
cd ~/Documents/GitHub/canada-grants
python3 fetch_grants.py     # 抓取 → data/programs.json + changes.json（约 2-4 分钟，取决于翻译）
python3 build_site.py       # 生成 → docs/index.html
open docs/index.html        # 看效果
```

没有 `GEMINI_API_KEY` 也能跑，只是页面全英文。
本地验证**不需要**联网跑抓取——仓库里已有 `data/programs.json`，直接 `build_site.py` 就能看页面效果。

## 5. 想改东西，去哪儿

| 想改 | 动哪里 | 怎么验 |
|---|---|---|
| 加一个信源 | `fetch_grants.py` 顶部 `SOURCES` + 写一个 `parse_xxx()` + 注册到 `PARSERS` | 跑一遍看条数，抽查 3 条字段 |
| 改某个项目的受众归属 | `config/audience.json` 的 `overrides`（**不用碰代码**） | 重建后看卡片标签 |
| 改筛选档位 | `build_site.py` 里 `<div class="fg" data-g="...">` 那段 HTML | 看每个按钮上的数字是否等于真实条数 |
| 改页面样式 | `build_site.py` 的 `HTML_TPL`（CSS 在 `<style>` 里） | 本地构建 + 手机宽度看一遍 |
| 改卡片内容 | `build_site.py` 的 `card()` | 同上 |
| 改金额解析规则 | `fetch_grants.py` 的 `parse_amount()` | 用历史数据回归：看有多少条金额变了 |
| 改截止日解析 | `fetch_grants.py` 的 `parse_deadline()` | 同上，重点看 `deadline_kind` 分布 |
| 改翻译提示词 | `fetch_grants.py` 的 `translate()` 里 `prompt_tpl` | 需要 API key，本地没有就等 CI |
| 改定时 | `.github/workflows/daily.yml` 的 `cron` | 只能等下一次跑或手动 Run workflow |

## 6. 待办（按优先级）

0. ~~**站点连续两天停更**~~ **已修复（2026-11-24，提交 340f32e）**：11-23/11-24 的 CI 抓取和构建都成功，但 `deploy-pages` 报 `No artifacts named "github-pages"`——产物其实已上传成功，是 GitHub API 列表短暂滞后。现在上传后先轮询确认产物可见（最多 2 分钟）再发布，推送触发的 CI 已验证通过。线上 `meta.json` 的 `built_at` 是判断更新是否正常的唯一标准。
1. ~~**扩信源**~~ **已完成（2026-11-25，本次提交）**：约克 2 + 荷顿 1（11-17 已上线）+ 皮尔 2（Major Office Incentives、Development Charges Deferral and Grant）+ 联邦 1（ISED 的 Black Entrepreneurship Loan Fund），共 8 个 source。区级 SBEC 页面上的 Starter Company Plus / Summer Company / Futurpreneur 与省级重复，不收；Tourism Signage 是收费安装路牌，非补助；皮尔 CIP 各基金当前全 Closed、Circular Economy Initiatives Fund 已公布 2026 获奖名单，均不收。**联邦旧结论已推翻**：不是「BBF 需浏览器渲染」，而是试错域名——`www.canada.ca` 超时，同一项目在 `ised-isde.canada.ca` 是静态页，标准库可直接抓。详见 `notes/03` A8。
2. **⚠️ 定时不准时**：cron 配的是 10:00 UTC，但实际运行时间长期落在 16-20 UTC（多伦多中午到下午），晚 6-10 小时。GitHub 免费层的 schedule 排队/降级所致，**不是配置错误，也不要当成故障去修**。要真准时，得用外部定时服务（如 cron-job.org）打 `workflow_dispatch` 接口。
3. ~~**关键词覆盖率**~~ **已修复（2026-11-25，本次提交）**：根因是 `KW_VOCAB` 的键用了「设备/研发/能效/租金/新创/雇佣」这些词表外别名，规则兜底结果过 `norm_tags()` 时被全部丢掉。改为受控词表内的键并补「建筑地产/基础设施/交通物流/文化艺术」等命中词；本地全量抓取 60 条，空关键词 **0 条**。
4. **中文质量抽检**：CI 里翻译失败会静默降级成英文，页面不报错。11-25 扩源上线后线上抽检 57/57 条中文名+摘要+四段详情齐全；但发现模型会自行补写原文没有的限制（联邦贷款卡片出现「不能用于个人消费开支」），已在 `translate()` 提示词里明令禁止推断未写明的限制，并重新推送验证。以后抽检重点看「不能用于 / 不包括 / 必须注册」这类句子。同日第二次 CI 因 Gemini 免费层限流整批失败 5 条（页面静默退回英文），已给 `translate()` 加「延时 8 秒 + 拆小批」自愈重试；判断翻译是否齐全看 CI 摘要的「有中文」条数。
5. **本地无法测中文**：本机没有 `GEMINI_API_KEY`，中文效果只能看线上。

## 7. 文档索引

| 文件 | 讲什么 | 什么时候读 |
|---|---|---|
| [notes/01-架构与数据流.md](notes/01-架构与数据流.md) | 数据从网页到卡片的全过程、每个函数的职责、`programs.json` 字段表 | 要动抓取或解析逻辑时 |
| [notes/02-功能清单与需求演变.md](notes/02-功能清单与需求演变.md) | 用户提过的 50+ 条需求，每条最终落成了什么 | **改交互之前必读**，很多"怪设计"都是有原因的 |
| [notes/03-踩坑与修复记录.md](notes/03-踩坑与修复记录.md) | 历次提交踩过的坑：症状 → 根因 → 修法 | 遇到奇怪 bug 先在这里搜 |
| [notes/04-操作手册.md](notes/04-操作手册.md) | 本地跑、验证、提交推送、CI 机制、从零复现步骤 | 每次动手前 |

## 8. 一句话总结给新会话

> 「加拿大补助库」是个零依赖 Python 项目，抓安省+多伦多+约克+荷顿+皮尔+联邦 ISED 的项目做中文索引页，
> 线上 `gszy84858-bit.github.io/canada-grants`，本地在 `~/Documents/GitHub/canada-grants`。
> 数据源 5 个，条数每天波动，以线上 meta.json 为准。定时实际晚 6-10 小时，属正常。
> 改完 `build_site.py` 要本地重建验证；本机可直接 `git push origin main`（凭据已具备）。
> 详细交接在仓库根目录 `HANDOVER.md` + `notes/`。
