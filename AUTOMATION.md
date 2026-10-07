# Niko 房源池自动化 · 总览

一页看懂整套系统：哪些东西在跑、在哪里、出了问题去哪看。最后更新 2026-10-07。

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
      └──► 写入 Supabase（properties 表 + property-images 桶）
                 │
                 ▼
④ 房源池页面 pool.html（GitHub Pages）读 Supabase 显示
   https://nikorelocation.github.io/niko-listings/pool.html
```

| 编号 | 东西 | 在哪里 | 怎么改 |
|---|---|---|---|
| ① | 监控定时任务 | Claude → 定时任务「房源池动态 · Rightmove/Zoopla 监控」 | 在 Claude 里说「把监控改成…」 |
| ② | 回复触发任务 | Claude → 定时任务「做卡片 · 回复邮件自动入池」 | 同上 |
| ③ | 出卡片 + 入池 | 本仓库 `cards/make_cards.py` + `.github/workflows/make-cards.yml` | 改代码推上来；手动跑：Actions → Run workflow |
| ④ | 房源池页面 | 本仓库 `pool.html` | 改完上传到仓库根目录即生效 |
| — | 房源池数据库 | Supabase `imhlozdlohtjkdvrsylu`，表 `properties`，桶 `property-images` | Supabase 后台 |
| — | 入池用的 key | 本仓库 Settings → Secrets → `SUPABASE_URL` / `SUPABASE_KEY` | 换 key 时在这里改 |
| — | 爬虫 | Heroku `rightmove-webapp-fcc61ef51410` | 不用动；③ 自动调用它 |
| — | 库存 / 去重 | Airtable base `appsoihhy4aVnT0Ao`：Inventory、Leads、Rightmove监控 | 免费版上限 1000 条；① 每次自动清 30 天前的监控记录 |

## 出了问题去哪看

- **没收到监控邮件**：可能当天没变动（没变动不发）。连续两天没有 → 在 Claude 里问「监控任务最近跑了吗」。
- **回复了「做卡片」但一小时内没回信**：看 Gmail 里那条回复有没有被打上标签「已做卡片」。没有 → 任务没跑或没识别到，在 Claude 里说「做卡片 MMDD早 3 7 12」手动走一遍。
- **确认邮件说「写库失败」**：仓库 Settings → Secrets 里的 `SUPABASE_KEY` 失效或被改了。
- **确认邮件说「没找到 #NN」**：编号对不上，复制邮件里的 Rightmove 链接，去 Actions 页面手动跑。
- **Action 红叉**：仓库 Actions 页面点进去看哪一步红；最常见是 Heroku 爬虫没返回（Heroku 休眠/挂了），过几分钟 Re-run。
- **卡片样式不对**：模板在 `cards/generate_cards.py`（和 Mac 上 NikoCards 的是同一个文件），改完推上来。

## 手动兜底（任何一环坏了都还能用）

- 手动出卡片 + 入池：Actions → 「做卡片 → 房源池」 → Run workflow → 粘链接。
- 完全手动：Heroku 爬虫出 PDF → Mac 上 `python3 generate_cards.py *.pdf` → 页面「管理」登录 → 拖图上传（老流程，仍然可用）。

## 已知限制

- Zoopla 房源只能靠 Zoopla 的提醒邮件发现，做卡片暂时只支持 Rightmove 链接。
- 2026-10-07 之前上传的卡片，入住月是旧格式（如「10+」），在新版页面按月份筛选时可能分到 10 月；点开卡片改一下标签即可。
- Rightmove 会拦 GitHub 的 IP，所以 ③ 走 Heroku 爬虫取数据；Heroku 不可用时会尝试直接抓，但大概率也被拦。
