#!/usr/bin/env python3
"""
Niko Relocation — Rightmove 链接 → 房源卡片 JPG → （可选）写入房源池 Supabase
云端版本，不需要 Mac。数据来源两条路：
  1）Niko 的 Heroku 爬虫（和手动流程完全一样：链接 → PDF → generate_cards 解析）——默认
  2）直接打开 Rightmove 页面读 PAGE_MODEL——备用（GitHub 机器常被 Rightmove 拦）

用法：
  python3 make_cards.py --urls urls.txt --out out/ [--save]
  python3 make_cards.py --url https://www.rightmove.co.uk/properties/94020657 --out out/

  --save      同时写入 Supabase（需要环境变量 SUPABASE_URL / SUPABASE_KEY）
  --month-format legacy|ym   房源池 month 字段格式：legacy = now/7/8/9/10+（当前线上 pool.html）
                                                    ym = now/YYYY-MM（新版 pool.html，带月份筛选）
输出：out/niko-<slug>-<postcode>.jpg + out/cards.json（每套的数据和写库结果）
"""
import argparse, glob, asyncio, base64, datetime as dt, json, os, re, sys, time, random, mimetypes
from io import BytesIO
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import generate_cards as gc  # Niko 自己的卡片模板 / 翻译表 / 文件名解析

ASSETS = os.path.join(HERE, 'assets')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')


# ── 0. Heroku 爬虫：链接 → PDF（和 Niko 手动流程一模一样） ──
HEROKU = os.environ.get('HEROKU_SCRAPER', 'https://rightmove-webapp-fcc61ef51410.herokuapp.com/')

def fetch_via_heroku(urls, workdir):
    """POST 链接到 Niko 的 Django 爬虫，拿回 zip，解出 PDF；返回 [pdf_path]。"""
    import requests, zipfile
    s = requests.Session()
    s.headers['User-Agent'] = UA
    r = s.get(HEROKU, timeout=60); r.raise_for_status()
    m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', r.text)
    token = m.group(1) if m else s.cookies.get('csrftoken', '')
    r = s.post(HEROKU, data={'csrfmiddlewaretoken': token, 'urlInput': '\n'.join(urls)},
               headers={'Referer': HEROKU}, timeout=900, stream=True)
    r.raise_for_status()
    body = r.content
    if not body[:2] == b'PK':
        raise RuntimeError(f'爬虫没有返回 zip（{r.headers.get("Content-Type")}，{len(body)} bytes）')
    zpath = os.path.join(workdir, 'scraper.zip')
    open(zpath, 'wb').write(body)
    pdfs = []
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            if n.lower().endswith('.pdf') and '/' not in n.strip('/'):
                z.extract(n, workdir); pdfs.append(os.path.join(workdir, n))
    if not pdfs:
        raise RuntimeError('zip 里没有 PDF')
    return pdfs

def entry_from_pdf(pdf_path, tmp_dir):
    """用 Niko 原版 generate_cards 解析 PDF + 抽图，得到 (d, images, fname)。"""
    d = gc.parse_pdf(pdf_path)
    images = gc.extract_images(pdf_path, tmp_dir, d.get('format', 'niko'))
    fname = os.path.basename(pdf_path).replace('.pdf', '')
    # 文件名没带邮编时（爬虫偶尔这样），补上 PDF 里解析到的邮编，房源池靠文件名兜底识别区域
    pc = (d.get('postcode') or '').split()[0].lower()
    if pc and pc != 'london' and not fname.lower().endswith('-' + pc):
        fname = f'{fname}-{pc}'
    d['rm_id'] = ''
    d['beds'] = 0 if d.get('bed_label', '').lower().startswith('studio') else int(re.match(r'(\d)', d.get('bed_label', '0') or '0').group(1) or 0)
    d['link'] = ''
    d['agent'] = ''
    return d, images, fname

# ── 1. 备用：直接抓 Rightmove ──────────────────────────────
async def fetch_rightmove(pw, url):
    """用真实 Chromium 打开详情页，读 window.PAGE_MODEL.propertyData，下载前 4 张图。"""
    browser = await pw.chromium.launch()
    ctx = await browser.new_context(user_agent=UA, locale='en-GB')
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(1500)
        pd = await page.evaluate('() => (window.PAGE_MODEL && window.PAGE_MODEL.propertyData) || null')
        if not pd:
            html = await page.content()
            m = re.search(r'window\.PAGE_MODEL\s*=\s*(\{.*?\})\s*</script>', html, re.S)
            if m:
                pd = json.loads(m.group(1)).get('propertyData')
        if not pd:
            raise RuntimeError('页面里没有 PAGE_MODEL（可能被反爬拦了）')
        imgs = []
        for im in (pd.get('images') or [])[:4]:
            src = im.get('url') or im.get('srcUrl')
            if not src:
                continue
            try:
                r = await ctx.request.get(src, headers={'Referer': url}, timeout=30000)
                if r.ok:
                    b = await r.body()
                    imgs.append('data:image/jpeg;base64,' + base64.b64encode(b).decode())
            except Exception:
                pass
        return pd, imgs
    finally:
        await browser.close()


def parse_price(s):
    m = re.search(r'£\s*([\d,]+)', s or '')
    return int(m.group(1).replace(',', '')) if m else None


def build_record(pd, url):
    """把 PAGE_MODEL.propertyData 整理成 generate_cards.build_card 需要的 dict。"""
    addr = (pd.get('address') or {}).get('displayAddress', '') or ''
    outcode = ((pd.get('address') or {}).get('outcode') or '').upper()
    if not outcode:
        m = re.search(r'\b([A-Z]{1,2}\d[\dA-Z]?)\b', addr.upper().split(',')[-1])
        outcode = m.group(1) if m else 'LONDON'
    prices = pd.get('prices') or {}
    primary = parse_price(prices.get('primaryPrice'))
    secondary = parse_price(prices.get('secondaryPrice'))
    ptxt = (prices.get('primaryPrice') or '').lower()
    if 'pw' in ptxt or 'week' in ptxt:
        weekly, monthly = primary, secondary
    else:
        monthly, weekly = primary, secondary
    if not weekly and monthly:
        weekly = round(monthly * 12 / 52)
    if not monthly and weekly:
        monthly = round(weekly * 52 / 12)
    beds = pd.get('bedrooms')
    baths = pd.get('bathrooms')
    if not beds:
        bed_label = 'Studio'
    else:
        bed_label = f'{beds} Bed {baths} Bath' if baths else f'{beds} Bed'
    let = pd.get('lettings') or {}
    avail_raw = (let.get('letAvailableDate') or 'Ask agent').strip()
    # Rightmove 给的是 dd/mm/yyyy 或 Now / Ask agent
    furnish = '不带家具' if 'unfurnished' in (let.get('furnishType') or '').lower() else '带家具'
    dep = let.get('deposit')
    deposit = str(int(dep)) if isinstance(dep, (int, float)) and dep else ''
    feats = [gc.translate(f) for f in (pd.get('keyFeatures') or [])[:8]]
    agent = ((pd.get('customer') or {}).get('branchDisplayName')
             or (pd.get('customer') or {}).get('companyName') or '')
    # slug：和 Heroku 爬虫的文件名风格一致，邮编放最后（房源池靠这个兜底识别区域）
    slug_src = addr
    if outcode and outcode.lower() in slug_src.lower():
        slug_src = re.sub(re.escape(outcode), '', slug_src, flags=re.I)
    slug = re.sub(r'[^a-z0-9]+', '-', slug_src.lower()).strip('-')
    slug = re.sub(r'-(london|uk)$', '', slug)
    fname = f'{slug}-{outcode.lower()}'
    fn_title, fn_pc = gc.parse_address_from_filename(fname)
    d = {
        'address': addr, 'postcode': outcode, 'weekly': str(weekly or 0),
        'monthly': str(monthly or ''), 'avail': avail_raw, 'deposit': deposit,
        'furnish': furnish, 'bed_label': bed_label, 'beds': beds or 0,
        'features': feats, 'format': 'niko', 'fn_title': fn_title,
        'agent': agent, 'link': url, 'rm_id': str(pd.get('id') or ''),
    }
    return d, fname


# ── 2. 渲染卡片（苹果 emoji 内嵌，和 Mac Chrome 出的卡片一致） ──
def _b64file(p):
    return base64.b64encode(open(p, 'rb').read()).decode()

def _emoji_img(name, h):
    return (f'<img src="data:image/png;base64,{_b64file(os.path.join(ASSETS, "emoji", f"emoji_{name}.png"))}" '
            f'style="height:{h}px;width:auto;vertical-align:middle;display:inline-block">')

def apple_emoji(html):
    rep = {
        '<div class="si">&#128719;</div>': f'<div class="si">{_emoji_img("bed", 10)}</div>',
        '<div class="si">&#128197;</div>': f'<div class="si">{_emoji_img("cal", 12)}</div>',
        '<div class="si">&#127968;</div>': f'<div class="si">{_emoji_img("house", 12.5)}</div>',
        '<div class="si">&#127963;</div>': f'<div class="si">{_emoji_img("bank", 13)}</div>',
        '<div class="avail">&#128197; ': f'<div class="avail">{_emoji_img("badgecal", 9.5)} ',
    }
    for k, v in rep.items():
        html = html.replace(k, v)
    return html

def page_html(card_blocks):
    src = open(os.path.join(HERE, 'generate_cards.py'), encoding='utf-8').read()
    css = re.search(r'    css = """(.*?)"""', src, re.S).group(1)
    css = css.replace('.si{font-size:.82rem}', '.si{font-size:.82rem;height:16px;line-height:16px}')
    ff = ''
    for w in (300, 400, 600):
        ff += (f"@font-face{{font-family:'Cormorant Garamond';font-weight:{w};"
               f"src:url('file://{ASSETS}/fonts/cormorant-garamond-latin-{w}-normal.woff2') format('woff2')}}\n")
    for w in (300, 400, 500):
        ff += (f"@font-face{{font-family:'DM Sans';font-weight:{w};"
               f"src:url('file://{ASSETS}/fonts/dm-sans-latin-{w}-normal.woff2') format('woff2')}}\n")
    return (f'<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">'
            f'<style>{ff}{css}</style></head><body><div class="grid">{card_blocks}</div></body></html>')

async def render_cards(pw, entries, out_dir):
    blocks = ''.join(apple_emoji(gc.build_card(d, imgs, i, fname))
                     for i, (d, imgs, fname) in enumerate(entries))
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, "_page.html")
    open(tmp, 'w', encoding='utf-8').write(page_html(blocks))
    browser = await pw.chromium.launch()
    page = await browser.new_page(viewport={'width': 1400, 'height': 1000}, device_scale_factor=3)
    await page.goto('file://' + os.path.abspath(tmp))
    await page.wait_for_timeout(1200)
    await page.evaluate('document.fonts.ready')
    cards = await page.query_selector_all('.card')
    paths = []
    for c, (d, imgs, fname) in zip(cards, entries):
        p = os.path.join(out_dir, f'niko-{fname}.jpg')
        await c.scroll_into_view_if_needed()
        await c.screenshot(path=p, type='jpeg', quality=95)
        paths.append(p)
    await browser.close()
    os.remove(tmp)
    return paths


# ── 3. 房源池标签（照 pool.html 的 pc2area / priceRange / availMonth） ──
def pc2area(pc):
    pc = (pc or '').upper()
    if re.match(r'^(EC|WC)', pc): return 'city'
    if re.match(r'^W1[A-Z]', pc): return 'city'
    if re.match(r'^SW1[A-Z]', pc): return 'city'
    if re.match(r'^SE1($|[A-Z])', pc): return 'city'
    if re.match(r'^(N|NW)', pc): return 'north'
    if re.match(r'^E', pc): return 'east'
    if re.match(r'^(SW|SE)', pc): return 'south'
    return 'west'

def price_range(w):
    if not w: return 'mid'
    return 'low' if w <= 700 else ('mid' if w <= 1000 else 'high')

MONTHS = {m: i + 1 for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july',
                                            'august', 'september', 'october', 'november', 'december'])}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})


def month_from_text(text):
    """「Available early November」「from mid-Nov」这类写在描述/特点里的入住月 → date（当月 1 号）"""
    m = re.search(r'\bavailable\b[^.\n]{0,40}?\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b',
                  text or '', re.I)
    if not m:
        return None
    mon = MONTHS.get(m.group(1).lower()[:3])
    today = dt.date.today()
    y = today.year if mon >= today.month else today.year + 1
    return dt.date(y, mon, 1)


def avail_month(avail, fmt, text=''):
    d = None
    if re.search(r'\bnow\b|immediate', avail or '', re.I):
        return 'now'
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', avail or '')
    if m:
        d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    else:
        # Rightmove 写「Ask agent」时，常在 Key features/描述里写「Available early November」
        d = month_from_text(text)
    if not d:
        return 'now'
    if d <= dt.date.today():
        return 'now'
    if fmt == 'ym':
        return f'{d.year}-{d.month:02d}'
    # legacy: 7/8/9/10+（线上旧版只有这几档）
    if d.month in (7, 8, 9) and d.year == dt.date.today().year:
        return str(d.month)
    return '10+'


# ── 4. 写 Supabase（照 pool.html 的 uploadImage + sbSave） ──
def supabase_save(jpg_path, tags):
    import requests
    url = os.environ.get('SUPABASE_URL', 'https://imhlozdlohtjkdvrsylu.supabase.co').rstrip('/')
    key = os.environ.get('SUPABASE_KEY', '')
    if not key:
        raise RuntimeError('没有 SUPABASE_KEY，跳过写库')
    h = {'apikey': key, 'Authorization': 'Bearer ' + key}
    fn = f'{int(time.time()*1000)}-{random.randbytes(2).hex()}.jpg'
    r = requests.post(f'{url}/storage/v1/object/property-images/{fn}',
                      headers={**h, 'Content-Type': 'image/jpeg', 'x-upsert': 'false'},
                      data=open(jpg_path, 'rb').read(), timeout=60)
    r.raise_for_status()
    image_url = f'{url}/storage/v1/object/public/property-images/{fn}'
    rec_id = f'card-{int(time.time()*1000)}-{random.randbytes(2).hex()[:3]}'
    body = {'id': rec_id, 'area': tags['area'], 'beds': tags['beds'], 'price': tags['price'],
            'month': tags['month'], 'image_url': image_url,
            'created_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    r = requests.post(f'{url}/rest/v1/properties',
                      headers={**h, 'Content-Type': 'application/json', 'Prefer': 'return=representation'},
                      json=body, timeout=60)
    r.raise_for_status()
    return rec_id, image_url


def supabase_delete(rec_id):
    """按 properties.id 删除一条记录及其图片（用于清理重复）"""
    import requests
    url = os.environ.get('SUPABASE_URL', 'https://imhlozdlohtjkdvrsylu.supabase.co').rstrip('/')
    key = os.environ.get('SUPABASE_KEY', '')
    if not key:
        raise RuntimeError('没有 SUPABASE_KEY')
    h = {'apikey': key, 'Authorization': 'Bearer ' + key}
    r = requests.get(f'{url}/rest/v1/properties?id=eq.{rec_id}&select=id,image_url', headers=h, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return False
    r = requests.delete(f'{url}/rest/v1/properties?id=eq.{rec_id}', headers=h, timeout=30)
    r.raise_for_status()
    img = rows[0].get('image_url') or ''
    m = re.search(r'/property-images/([^/?]+)$', img)
    if m:
        requests.delete(f'{url}/storage/v1/object/property-images/{m.group(1)}', headers=h, timeout=30)
    return True


def supabase_delete_oldest(n, out_dir, older_than_days=0):
    """删除房源池里最早上传的 n 条（按 created_at 升序）；或 older_than_days>0 时删除上传超过该天数的全部记录。先把被删的记录存成 JSON 备份"""
    import requests
    url = os.environ.get('SUPABASE_URL', 'https://imhlozdlohtjkdvrsylu.supabase.co').rstrip('/')
    key = os.environ.get('SUPABASE_KEY', '')
    if not key:
        raise RuntimeError('没有 SUPABASE_KEY')
    h = {'apikey': key, 'Authorization': 'Bearer ' + key}
    if older_than_days > 0:
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=older_than_days)).isoformat()
        q = f'{url}/rest/v1/properties?select=*&created_at=lt.{cutoff}&order=created_at.asc&limit=1000'
        tag = f'older-than-{older_than_days}d'
    else:
        q = f'{url}/rest/v1/properties?select=*&order=created_at.asc.nullsfirst&limit={int(n)}'
        tag = 'oldest'
    r = requests.get(q, headers=h, timeout=60)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        print('  没有需要清理的旧房源'); return 0
    os.makedirs(out_dir, exist_ok=True)
    json.dump(rows, open(os.path.join(out_dir, f'deleted-{tag}-{len(rows)}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    done = 0
    for row in rows:
        rid = row['id']
        rr = requests.delete(f'{url}/rest/v1/properties?id=eq.{rid}', headers=h, timeout=30)
        if rr.status_code >= 300:
            print(f'  ✗ 删 {rid} 失败 {rr.status_code}'); continue
        img = row.get('image_url') or ''
        m = re.search(r'/property-images/([^/?]+)$', img)
        if m:
            requests.delete(f'{url}/storage/v1/object/property-images/{m.group(1)}', headers=h, timeout=30)
        done += 1
    r = requests.get(f'{url}/rest/v1/properties?select=id', headers={**h, 'Prefer': 'count=exact', 'Range': '0-0'}, timeout=30)
    total = r.headers.get('content-range', '?').split('/')[-1]
    print(f'  🗑 已删除最早的 {done} 条（备份在 {out_dir}），房源池现剩 {total} 条')
    return done


def already_in_pool(repo_root):
    """扫描仓库里所有 cards/out/*/cards.json，返回 {rm_id: (supabase_id, 文件夹)}：已经入池的房源不再重复上传"""
    seen = {}
    for cj in sorted(glob.glob(os.path.join(repo_root, 'cards', 'out', '*', 'cards.json'))):
        try:
            for r in json.load(open(cj, encoding='utf-8')):
                if r.get('saved') and r.get('rm_id'):
                    seen.setdefault(str(r['rm_id']), (r.get('supabase_id'), os.path.basename(os.path.dirname(cj))))
        except Exception:
            pass
    return seen


# ── main ─────────────────────────────────────────────────────
async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--urls', help='文件，每行一个 Rightmove 链接')
    ap.add_argument('--url', action='append', default=[])
    ap.add_argument('--out', default='out')
    ap.add_argument('--save', action='store_true', help='写入 Supabase 房源池')
    ap.add_argument('--month-format', default=os.environ.get('MONTH_FORMAT', 'ym'))
    ap.add_argument('--delete', default='', help='要从房源池删除的 properties.id（空格分隔），用于清理重复')
    ap.add_argument('--force', action='store_true', help='已入池的也重新上传（默认跳过重复）')
    ap.add_argument('--delete-oldest', type=int, default=0, help='删除房源池里最早上传的 N 条（清理旧房源）')
    ap.add_argument('--delete-older-than', type=int, default=0, help='删除上传超过 N 天的全部记录（定期清理）')
    a = ap.parse_args()
    if a.delete_oldest > 0 or a.delete_older_than > 0:
        try:
            supabase_delete_oldest(a.delete_oldest, a.out, a.delete_older_than)
        except Exception as e:
            print(f'  ✗ 清理旧房源失败: {e}')
    if a.delete.strip():
        for rid in a.delete.split():
            try:
                print(f'  🗑 {rid}: ' + ('已删除' if supabase_delete(rid) else '不存在'))
            except Exception as e:
                print(f'  ✗ 删除 {rid} 失败: {e}')
    urls = list(a.url)
    if a.urls:
        urls += [l.strip() for l in open(a.urls) if l.strip()]
    # 每行可以是「链接」或「链接 邮编」（邮编用于 PDF 里没写邮编的情况，例如 Maine Tower, Canary Wharf）
    outcode_of = {}
    clean = []
    for line in urls:
        parts = line.split()
        u = re.sub(r'#.*$', '', parts[0].split('?')[0])
        if '/properties/' not in u:
            continue
        if len(parts) > 1 and re.fullmatch(r'[A-Za-z]{1,2}\d[\dA-Za-z]?', parts[1]):
            outcode_of[u] = parts[1].upper()
        clean.append(u)
    urls = list(dict.fromkeys(clean))
    if not urls:
        if a.delete.strip() or a.delete_oldest > 0 or a.delete_older_than > 0:
            sys.exit(0)
        print('没有有效的 Rightmove 链接'); sys.exit(1)
    os.makedirs(a.out, exist_ok=True)
    pool = {} if a.force else already_in_pool(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dup = [u for u in urls if re.search(r'/properties/(\d+)', u).group(1) in pool]
    for u in dup:
        rid = re.search(r'/properties/(\d+)', u).group(1)
        print(f'  ⟳ {u} 已在房源池（{pool[rid][1]}），跳过')
    urls = [u for u in urls if u not in dup]
    results = [{'link': u, 'rm_id': re.search(r'/properties/(\d+)', u).group(1), 'duplicate': True,
                'supabase_id': pool[re.search(r'/properties/(\d+)', u).group(1)][0],
                'first_folder': pool[re.search(r'/properties/(\d+)', u).group(1)][1]} for u in dup]
    if not urls:
        json.dump(results, open(os.path.join(a.out, 'cards.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('全部已在房源池，无需上传'); sys.exit(0)

    from playwright.async_api import async_playwright
    import tempfile
    entries = []
    work = tempfile.mkdtemp(prefix='nikocards-')
    # 路线 1：Heroku 爬虫 → PDF → generate_cards 解析（和手动流程一致）
    try:
        pdfs = fetch_via_heroku(urls, work)
        print(f'Heroku 爬虫返回 {len(pdfs)} 个 PDF')
        for p in pdfs:
            try:
                d, imgs, fname = entry_from_pdf(p, tempfile.mkdtemp(dir=work))
                # 把链接对回去：按 PDF 里的房源 ID
                txt = __import__('subprocess').run(['pdftotext', p, '-'], capture_output=True, text=True).stdout
                for u in urls:
                    rid = re.search(r'/properties/(\d+)', u)
                    if rid and rid.group(1) in txt:
                        d['link'] = u; d['rm_id'] = rid.group(1); break
                oc = outcode_of.get(d.get('link'))
                if oc and (not d.get('postcode') or d['postcode'].lower() == 'london'):
                    d['postcode'] = oc
                    if not fname.lower().endswith('-' + oc.lower()):
                        fname = f'{fname}-{oc.lower()}'
                entries.append((d, imgs, fname))
                print(f'✓ [pdf] {fname} | {d["bed_label"]} | £{d["weekly"]}/周 | 起租 {d["avail"]} | {len(imgs)}图')
            except Exception as e:
                print(f'✗ {p}: {e}')
                results.append({'pdf': os.path.basename(p), 'error': str(e)})
    except Exception as e:
        print(f'Heroku 爬虫不可用：{e}，改为直接抓 Rightmove')
    done_links = {d['link'] for d, _, _ in entries if d.get('link')}
    missing = [] if len(entries) >= len(urls) else [u for u in urls if u not in done_links]

    async with async_playwright() as pw:
        # 路线 2：剩下没拿到的直接抓 Rightmove
        for u in missing:
            try:
                pd, imgs = await fetch_rightmove(pw, u)
                d, fname = build_record(pd, u)
                entries.append((d, imgs, fname))
                print(f'✓ [rm] {d["address"]} | {d["bed_label"]} | £{d["weekly"]}/周 | 起租 {d["avail"]} | {len(imgs)}图')
            except Exception as e:
                print(f'✗ {u}: {e}')
                results.append({'link': u, 'error': str(e)})
        if not entries:
            sys.exit(2)
        paths = await render_cards(pw, entries, a.out)

    for (d, imgs, fname), p in zip(entries, paths):
        tags = {'area': pc2area(d.get('postcode')), 'beds': int(d.get('beds') or 0),
                'price': price_range(int(d.get('weekly') or 0)), 'month': avail_month(d.get('avail'), a.month_format, ' '.join(d.get('features') or []))}
        row = {'link': d.get('link', ''), 'rm_id': d.get('rm_id', ''),
               'address': d.get('address') or d.get('fn_title') or fname, 'postcode': d.get('postcode', ''),
               'bed_label': d.get('bed_label', ''), 'weekly': int(d.get('weekly') or 0), 'monthly': d.get('monthly', ''),
               'avail': d.get('avail', '—'), 'furnish': d.get('furnish', ''), 'agent': d.get('agent', ''),
               'card': os.path.basename(p), 'tags': tags}
        if a.save:
            try:
                rec_id, image_url = supabase_save(p, tags)
                row.update(saved=True, supabase_id=rec_id, image_url=image_url)
                print(f'  ↑ 已写入房源池 {rec_id}')
            except Exception as e:
                row.update(saved=False, save_error=str(e))
                print(f'  ✗ 写库失败: {e}')
        results.append(row)
    json.dump(results, open(os.path.join(a.out, 'cards.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print(f'\n完成：{len(paths)} 张卡片 → {a.out}/')

if __name__ == '__main__':
    asyncio.run(main())
