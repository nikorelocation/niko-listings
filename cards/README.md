# 做卡片 → 房源池（全自动版）

把 Rightmove 链接变成 Niko 风格房源卡片，并直接写进房源池（Supabase），不再需要 Heroku 爬虫 PDF 和 Mac 上的 NikoCards。

## 怎么跑

**方式一：GitHub 页面手动跑**
Actions → 「做卡片 → 房源池」 → Run workflow → 粘贴链接（每行一个）→ Run。
跑完：卡片在 `cards/out/<日期-时间>/`，房源池里自动多出这几套；Summary 里有每套的结果。

**方式二：回复监控邮件（由 Claude 定时任务触发）**
收到「房源池动态」邮件后，直接回复：`做卡片 3 7 12`（或 `做卡片 1008午 3 7 12`）。
Claude 的定时任务每小时查一次回复，把编号换成链接，触发上面的 workflow。

**方式三：本地跑（调试用）**
```
pip install playwright requests pillow && python -m playwright install chromium
python cards/make_cards.py --url https://www.rightmove.co.uk/properties/94020657 --out out/
# 加 --save 并设置环境变量 SUPABASE_URL / SUPABASE_KEY 才会写库
```

## 一次性设置（只做一次）
仓库 Settings → Secrets and variables → Actions → New repository secret：
- `SUPABASE_URL` = `https://imhlozdlohtjkdvrsylu.supabase.co`
- `SUPABASE_KEY` = 能写 `properties` 表和 `property-images` 桶的 key（pool.html 里页面用的那把 anon key 本来就有写权限，直接用它也可以；更稳妥是在 Supabase 后台另建一把只给这两个权限的）

没设 `SUPABASE_KEY` 时 workflow 照样出卡片，只是不写库。

## 卡片和以前有什么不同
- 模板、翻译表、文件名规则全部复用 `generate_cards.py`（Niko 原版），只是数据直接来自 Rightmove 页面（`PAGE_MODEL`），不经过 PDF。
- 云端渲染时 emoji 会变成 Google 风格，所以 `assets/emoji/` 里内嵌了苹果 emoji 图（从以前的卡片上截的），渲染结果和 Mac Chrome 一致。
- 修了一个老 bug：Key features 里出现「Yoga Studio」会把 2 室误判成 Studio。

## 房源池标签怎么打
照 pool.html 的规则：
- 位置：EC/WC/W1x/SW1x/SE1 = 市中心；N/NW = 北伦敦；E = 东伦敦；SW/SE = 南伦敦；其余 W = 西伦敦
- 价格：周租 ≤700 低 / 700–1000 中 / ≥1000 高
- 入住：`legacy`（默认）= 现在/7/8/9/10+，对应线上旧版页面；换成新版 pool.html 后把 workflow 的 month_format 选 `ym`

## 文件
- `make_cards.py` — 主脚本
- `generate_cards.py` — Niko 原版卡片模板（含 Studio 修正）
- `assets/fonts/` — Cormorant Garamond / DM Sans（离线）
- `assets/emoji/` — 苹果 emoji 图
- `out/` — 每次跑出来的卡片
