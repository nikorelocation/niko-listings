# Niko 房源池自动化 · 总览

一页看懂整套系统：哪些东西在跑、在哪里、出了问题去哪看。最后更新 2026-10-23（房源池从 Supabase 搬到 GitHub，零成本）。

## 日常使用（只需要做两件事）

1. 每天 **09:00 / 12:00 / 15:00 / 18:00** 收到邮件「房源池动态 · M月D日 早/午/下/晚」，里面每套房源带编号 #01、#02…
2. 看中哪几套，**直接回复那封邮件**：`做卡片 3、7、12`
   → 一小时内自动出卡片、写进房源池，并回一封确认邮件。

不用开 Claude，不用开 Chrome，不用 NikoCards，不用登录房源池。

## 系统组成

```
Rightmove / Zoopla
      │  ① 定时任务「房源池动态 · 监控」 每天4次
      ▼
Gmail 邮件（带编号）  ◄──►  Airtable「Rightmove监控」表（去重 + 编号 → 链接）
      │  你回复「做卡片 3 7 12」
      ▼
② 定时任务「做卡片 · 回复邮件自动入池」 每小时
      │  编号 → 链接，触发 ↓
      ▼
③ GitHub Action「做卡片 → 房源池」（本仓库 .github/workflows/make-cards.yml）
      │  链接 → Heroku 爬虫出 PDF → generate_cards 出卡片 JPG
      ├──► 卡片存回仓库 cards/out/<日期-时间>/
      └──► 写入房源池：仓库里的 pool/pool.json + 缩略图 pool/thumbs/
                 │
                 ▼
④ 房源池页面 pool.html（GitHub Pages）读 pool/pool.json 显示——全部免费托管，没有数据库
   https://nikorelocation.github.io/niko-listings/pool.html
```

| 编号 | 东西 | 在哪里 | 怎么改 |
|---|---|---|---|
| ① | 监控定时任务 | Claude → 定时任务「房源池动态 · Rightmove/Zoopla 监控」 | 在 Claude 里说「把监控改成…」 |
| ② | 回复触发任务 | Claude → 定时任务「做卡片 · 回复邮件自动入池」 | 同上 |
| ③ | 出卡片 + 入池 | 本仓库 `cards/make_cards.py` + `.github/workflows/make-cards.yml` | 改代码推上来；手动跑：Actions → Run workflow |
| ④ | 房源池页面 | 本仓库 `pool.html` | 改完上传到仓库根目录即生效 |
| — | 房源池数据 | 本仓库 `pool/pool.json`（每套一行）、`pool/thumbs/`（列表缩略图）、`pool/img/`（页面上手动上传的原图）；自动入池的原图就是 `cards/out/` 里的卡片 | 一般不用手改；改完推上来约 1 分钟生效 |
| — | 房源池清理 | 同一个 Action：`delete_ids`（删指定记录）、`delete_oldest`（删最早 N 条）、`delete_older_than`（删超过 N 天的）；**每月 1 号自动删上传超过 90 天的**，被删记录备份在 `cards/out/<日期>/deleted-*.json` | 改 workflow 里 `OLDER=90` 或 cron |
| — | 页面上手动上传/删除 | 「管理」登录后第一次操作时粘贴 GitHub 令牌（Fine-grained，只给 niko-listings 的 Contents 读写），只存在那台设备的浏览器里 | 令牌过期了页面会再提示粘贴 |
| — | 旧 Supabase | 2026-10-23 起不再使用。11 月 3 日额度恢复后跑一次 Actions「import_supabase」把以前手动上传的卡片搬过来，之后可以在 Supabase 后台暂停/删除项目 | — |
| — | 爬虫 | Heroku `rightmove-webapp-fcc61ef51410` | 不用动；③ 自动调用它 |
| — | 库存 / 去重 | Airtable base `appsoihhy4aVnT0Ao`：Inventory、Leads、Rightmove监控 | 免费版上限 1000 条；① 每次自动清 30 天前的监控记录 |

## 出了问题去哪看

- **没收到监控邮件**：可能当天没变动（没变动不发）。连续两天没有 → 在 Claude 里问「监控任务最近跑了吗」。
- **回复了「做卡片」但一小时内没回信**：看 Gmail 里那条回复有没有被打上标签「已做卡片」。没有 → 任务没跑或没识别到，在 Claude 里说「做卡片 MMDD早 3 7 12」手动走一遍。
- **确认邮件说「写库失败」**：看 Action 的「卡片存回仓库 + 更新房源池」那一步，多半是 push 冲突重试 5 次仍失败，Re-run 即可。
- **确认邮件说「没找到 #NN」**：编号对不上，复制邮件里的 Rightmove 链接，去 Actions 页面手动跑。
- **Action 红叉**：仓库 Actions 页面点进去看哪一步红；最常见是 Heroku 爬虫没返回（Heroku 休眠/挂了），过几分钟 Re-run。
- **卡片样式不对**：模板在 `cards/generate_cards.py`（和 Mac 上 NikoCards 的是同一个文件），改完推上来。

## 手动兜底（任何一环坏了都还能用）

- 手动出卡片 + 入池：Actions → 「做卡片 → 房源池」 → Run workflow → 粘链接。
- 完全手动：Heroku 爬虫出 PDF → Mac 上 `python3 generate_cards.py *.pdf` → 页面「管理」登录 → 拖图上传（老流程，仍然可用；首次需要粘贴 GitHub 令牌）。

## 已知限制

- 同一个 Rightmove 房源 ID 不会重复入池（脚本和回复任务都会查 `cards/out/*/cards.json`）；2026-10-09 之前手动上传的卡片不在这个记录里，可能和自动入池的重复，看到就用 `delete_ids` 删。
- Zoopla 房源只能靠 Zoopla 的提醒邮件发现，做卡片暂时只支持 Rightmove 链接。
- 2026-10-07 之前上传的卡片，入住月是旧格式（如「10+」），在新版页面按月份筛选时可能分到 10 月；点开卡片改一下标签即可。
- Rightmove 会拦 GitHub 的 IP，所以 ③ 走 Heroku 爬虫取数据；Heroku 不可用时会尝试直接抓，但大概率也被拦。
- 免费额度：GitHub Pages 建议每月流量 100GB 以内、网站 1GB 以内。列表页只加载约 100KB 的缩略图，正常使用远远用不完；卡片原件每月约增加 200MB，大约半年后可以把很早的 cards/out 文件夹清掉。
- 页面上手动上传/删除后，所有人看到更新大约要等 1 分钟（GitHub Pages 重新发布）。
