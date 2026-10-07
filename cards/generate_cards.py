#!/usr/bin/env python3
"""
Niko Relocation - PDF Card Generator
支持格式：Niko爬虫PDF / Unihood中介PDF / 其他中介PDF
Usage:  python3 generate_cards.py *.pdf
Output: 单个HTML文件，含所有卡片，一键打包下载
"""
import base64, subprocess, re, os, sys, tempfile
from PIL import Image
from io import BytesIO
from datetime import datetime

# ── TRANSLATIONS ─────────────────────────────────────────────
TRANS = {
    'twenty-four-hour concierge service': '24h礼宾服务',
    'west facing views towards the thames': '西向泰晤士河景',
    'easterly views towards the shard': '东向The Shard景观',
    'luxury fitted kitchen with miele appliances': 'Miele厨电豪华厨房',
    'expansive leisure facilities including swimming pool': '豪华休闲设施含游泳池',
    'south east facing': '东南朝向', 'south west facing': '西南朝向',
    'south facing views': '南向景观', 'south facing': '南向',
    'north facing': '北向', 'west facing': '西向', 'east facing': '东向',
    'floor-to-ceiling windows': '落地窗', 'floor to ceiling windows': '落地窗',
    'double aspect': '双面采光', 'dual aspect': '双面采光',
    'open plan kitchen/living': '开放式厨房客厅',
    'open-plan reception/kitchen': '开放式客厅厨房',
    'open plan kitchen': '开放式厨房', 'open plan': '开放式',
    'two-bedroom apartment': '两室两卫公寓',
    'one bedroom': '一室', 'two bedroom': '两室',
    'three bedroom': '三室', 'four bedroom': '四室',
    'studio': 'Studio', 'sq ft': 'sq ft', 'sq m': 'sq m', 'approx.': '约',
    'furnished': '带家具', 'unfurnished': '不带家具',
    'private balcony': '私人阳台', 'juliet balcony': '朱丽叶阳台',
    'balcony': '阳台', 'roof terrace': '屋顶露台', 'terrace': '露台',
    'winter garden': '冬季花园',
    'hotel style reception': '酒店式大堂',
    '24 hour concierge': '24h礼宾服务', '24-hour concierge': '24h礼宾服务',
    'concierge': '礼宾服务',
    'private gym': '私人健身房', "residents' gym": '住客健身房',
    'residents gym': '住客健身房', 'gym': '健身房',
    'health club': '健康俱乐部', 'swimming pool': '游泳池',
    'luxury residents facilities': '豪华住客设施',
    'residents facilities': '住客设施', 'access to facilities': '住客设施',
    'residents lounge': '住客休息室',
    'miele appliances': 'Miele厨电', 'integrated appliances': '嵌入式厨电',
    'comfort cooling': '冷却系统', 'underfloor heating': '地暖',
    'excellent transport links': '交通便利',
    'close to public transport': '近公共交通',
    '0.2 mile from waterloo station': '近Waterloo站',
    'waterloo station': '近Waterloo站',
    'kings cross': '近Kings Cross', 'canary wharf': '近Canary Wharf',
    'thames views': '泰晤士河景', 'river views': '河景',
    'city views': '城市景观', 'views': '景观',
    'new build': '全新楼盘', 'new development': '全新开发',
    'spacious living area': '宽敞客厅',
    'parking': '停车位', 'storage': '储物间',
    'epc rating = b': 'EPC评级B',
    '1 reception room': '独立客厅',
}

def translate(text):
    r = text.strip().lstrip('•').strip()
    lower = r.lower()
    for eng, chn in sorted(TRANS.items(), key=lambda x: -len(x[0])):
        if eng in lower:
            r = re.sub(re.escape(eng), chn, r, flags=re.IGNORECASE)
            lower = r.lower()
    r = r.replace(' & ', '·').replace(' and ', '·')
    return re.sub(r'\s+', ' ', r).strip(' -–·')

# ── FILENAME ADDRESS PARSER ───────────────────────────────────
# UK postcode area codes used to split address from postcode in filename
POSTCODE_AREAS = re.compile(
    r'^(sw\d+[a-z]?|se\d+[a-z]?|nw\d+[a-z]?|ec\d+[a-z]?|wc\d+[a-z]?|'
    r'e\d+[a-z]?|w\d+[a-z]?|n\d+[a-z]?|ne\d+[a-z]?|'
    r'wd\d+|ha\d+|ub\d+|tw\d+|kt\d+|sm\d+|cr\d+|br\d+|da\d+|'
    r'ig\d+|rm\d+|en\d+|al\d+|sg\d+|sl\d+|hp\d+|ox\d+|'
    r'rh\d+|tn\d+|me\d+|ss\d+|co\d+|ip\d+|cb\d+|pe\d+|le\d+|'
    r'cv\d+|b\d+|bs\d+|ba\d+|gl\d+|sn\d+|rg\d+|gu\d+|po\d+|'
    r'so\d+|bh\d+|dt\d+|ex\d+|pl\d+|tr\d+|ta\d+|cf\d+|sa\d+|'
    r'ls\d+|bd\d+|s\d+|sk\d+|m\d+|l\d+|st\d+|ws\d+|dy\d+|wv\d+|'
    r'ts\d+|yo\d+|hu\d+|nn\d+|mk\d+|lu\d+|fy\d+|bb\d+|pr\d+|la\d+)$',
    re.IGNORECASE
)

def parse_address_from_filename(fname):
    """
    Parse building name and postcode from PDF filename.
    e.g. 'riverlight-four-riverlight-quay-london-sw11' ->
         title='Riverlight Four Riverlight Quay', postcode='SW11'
    e.g. 'hand-axe-yard-gray-s-inn-road-london' ->
         title='Hand Axe Yard Grays Inn Road', postcode='London'
    """
    name = fname.replace('.pdf', '').strip()
    parts = name.split('-')

    # ── FIX 1: Restore apostrophe-s that became "-s-" in filenames ──
    # e.g. ["gray", "s", "inn"] → ["grays", "inn"]
    # A lone "s" after a word (not a postcode) is a possessive fragment
    merged = []
    i = 0
    while i < len(parts):
        if (parts[i].lower() == 's'
                and merged
                and not POSTCODE_AREAS.fullmatch(merged[-1])):
            merged[-1] = merged[-1] + 's'   # gray + s → grays
        else:
            merged.append(parts[i])
        i += 1
    parts = merged

    # ── Find postcode area at the end ──
    postcode = ''
    pc_idx = None
    for i in range(len(parts) - 1, -1, -1):
        if POSTCODE_AREAS.fullmatch(parts[i]):
            postcode = parts[i].upper()
            pc_idx = i
            break

    # Strip trailing stop words before postcode
    stop_words = {'london', 'city', 'of', 'westminster', 'greater'}
    end = pc_idx if pc_idx is not None else len(parts)
    while end > 0 and parts[end - 1].lower() in stop_words:
        end -= 1

    title_parts = parts[:end]
    title = ' '.join(p.capitalize() for p in title_parts)

    return title, postcode if postcode else ''   # empty string = no postcode found in filename


# ── FORMAT DETECTION ──────────────────────────────────────────
def detect_format(text):
    """返回 'niko' / 'unihood' / 'generic'"""
    if 'NIKO RELOCATION' in text or 'nikoinlondon' in text:
        return 'niko'
    if 'unihood' in text.lower() or 'Sales | Lettings | Management' in text:
        return 'unihood'
    return 'generic'

# ── NIKO FORMAT PARSER ────────────────────────────────────────
def parse_niko(text):
    d = {}
    am = re.search(
        r'(\d*\s*[A-Z][a-zA-Z\s,]+(?:Gardens?|Square|Place|Road|Street|'
        r'House|Tower|Building|Wharf|Park|Lane|Court|Way|Gate|Point|'
        r'Heights|Mews|Apartments?)[^\n£]{0,60})', text)
    if am:
        addr = am.group(1).strip().replace('  ', ' ').rstrip(', ')
        d['address'] = re.sub(r'\bSe(\d)', lambda m: 'SE'+m.group(1), addr)

    pm = re.search(r'£([\d,]+)\s*\|', text)
    if pm: d['weekly'] = pm.group(1).replace(',', '')

    bm  = re.search(r'(\d)\s*Bedroom', text, re.I)
    bam = re.search(r'(\d)\s*Bathroom', text, re.I)
    if bm: d['beds'] = bm.group(1)
    if bam: d['baths'] = bam.group(1)

    dm = re.search(r'Let available date[:\s]+([^\n•]+)', text, re.I)
    if dm: d['avail'] = dm.group(1).strip()

    depm = re.search(r'Deposit[:\s]+([\d,]+)', text, re.I)
    if depm: d['deposit'] = depm.group(1).replace(',', '')

    fm = re.search(r'Furnish type[:\s]+([^\n•]+)', text, re.I)
    d['furnish'] = '不带家具' if fm and 'unfurnished' in fm.group(1).lower() else '带家具'

    postm = re.search(r'\b([A-Z]{1,2}\d[\dA-Z]?\s*\d[A-Z]{2})\b', text)
    if postm: d['postcode'] = postm.group(1).strip()
    else:
        am2 = re.search(r'\b(S[Ee]\d+|EC\d|E\d+|SW\d+|W\d+|N\d+|NW\d+|WC\d+)\b', text, re.I)
        d['postcode'] = am2.group(1).upper() if am2 else 'London'

    fi = text.lower().find('key features:')
    if fi > -1:
        block = text[fi+13:fi+800]
        raw = [s.strip().lstrip('•').strip() for s in block.split('\n')
               if s.strip() and len(s.strip()) > 2
               and 'NIKO' not in s and 'nikoin' not in s and 'www.' not in s]
        d['features'] = [translate(f) for f in raw[:8]]

    beds  = d.get('beds', '')
    baths = d.get('baths', '')
    feats_lower = ' '.join(d.get('features', [])).lower()
    # 只有床位数为0/缺失时才算Studio（避免 'Yoga Studio' 等设施把2室误判成Studio）
    if beds == '0' or not beds:
        d['bed_label'] = 'Studio'
    else:
        d['bed_label'] = f"{beds} Bed {baths} Bath" if baths else f"{beds} Bed"
    return d

# ── UNIHOOD FORMAT PARSER ─────────────────────────────────────
def parse_unihood(text):
    d = {}
    pages = text.split('\x0c')

    # Page 2: postcode + building name
    p2 = pages[1] if len(pages) > 1 else ''
    postm = re.search(r'\b([A-Z]{1,2}\d[\dA-Z]?\s*\d[A-Z]{2})\b', p2)
    if postm: d['postcode'] = postm.group(1).strip()

    # Building name: scan all pages for "414 Agar House" style
    # Pattern: number + capitalised words ending in House/Court/etc
    building_pattern = re.compile(
        r'(\d+\s+[A-Z][a-zA-Z\s]+(?:Court|House|Road|Street|'
        r'Place|Square|Building|Apartments?|Tower|Mews))', re.MULTILINE)
    for pg in pages:
        nm = building_pattern.search(pg)
        if nm:
            candidate = nm.group(1).strip()
            # Prefer names that look like unit+building (e.g. "414 Agar House")
            # over generic matches; take the first good hit
            d['building'] = candidate
            break

    # Page 3: price, date, type, floor, bills
    p3 = pages[2] if len(pages) > 2 else ''
    pm = re.search(r'£([\d,]+)\s*pw', p3, re.I)
    if pm: d['weekly'] = pm.group(1).replace(',', '')

    # Full date e.g. '03 SEP 2026'
    dm = re.search(r'(\d{1,2}\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{4})', p3, re.I)
    if dm: d['avail'] = dm.group(1).strip()

    # Bed label: Studio / Chinese '2室1厅2卫' or '2 室 1 厅 2 卫浴 1 阳台' (with spaces) / English 'X Bed'
    if re.search(r'\bStudio\b', p3, re.I):
        d['bed_label'] = 'Studio'
    else:
        # Match with optional spaces: "2 室 1 厅 2 卫浴 1 阳台"
        zh_m = re.search(r'(\d\s*室[\s\S]{0,40}?(?:阳台|卫浴?\s*\d?\s*阳台?|卫\s*\d?))', p3)
        if zh_m:
            # Compact: remove spaces between CJK/number sequences
            raw = zh_m.group(1).strip()
            raw = re.sub(r'(\d)\s+([室厅卫浴阳台])', r'\1\2', raw)
            raw = re.sub(r'([室厅卫浴阳台])\s+(\d)', r'\1\2', raw)
            d['bed_label'] = raw.strip()
        else:
            # Simpler fallback: any line with 室
            zh_m2 = re.search(r'(\d[\s]*室[^\n]{0,30})', p3)
            if zh_m2:
                raw = zh_m2.group(1).strip()
                raw = re.sub(r'(\d)\s+([室厅卫浴阳台])', r'\1\2', raw)
                raw = re.sub(r'([室厅卫浴阳台])\s+(\d)', r'\1\2', raw)
                d['bed_label'] = raw.strip()
            else:
                bm = re.search(r'(\d)\s*(?:Bed|bedroom)', p3, re.I)
                d['bed_label'] = f"{bm.group(1)} Bed" if bm else '—'

    flm = re.search(r'(\d+(?:st|nd|rd|th)?\s*Floor)', p3, re.I)
    if flm: d['floor'] = flm.group(1)

    # Bills: '包含热水暖气' or '不包含'
    bills_m = re.search(r'((?:不)?包含[^\n]{0,30})', p3)
    if bills_m:
        d['bills'] = bills_m.group(1).strip()
        d['furnish'] = '不含Bills' if '不包含' in d['bills'] else '含Bills'
    else:
        d['furnish'] = '带家具'

    # Page 4: nearest stations
    p4 = pages[3] if len(pages) > 3 else ''
    stations = re.findall(r'步行\s*(\d+)\s*分钟\s*[-–]\s*([^\n]+)', p4)
    if stations:
        d['stations'] = [
            f'步行{t}分 {s.strip().replace(" Station","").strip()}'
            for t, s in sorted(stations, key=lambda x: int(x[0]))[:2]
        ]

    # Page 5: UCL walk time
    p5 = pages[4] if len(pages) > 4 else ''
    um = re.search(r'UCL\s*\n步行\s*[-–]\s*(\d+)\s*分钟', p5)
    if um: d['ucl'] = f'步行{um.group(1)}分钟至UCL'

    # Build features - floor and bills shown as feat tags, not duplicating spec row
    feats = []
    if d.get('floor'): feats.append(f'{d["floor"]}')
    if d.get('bills'): feats.append(d['bills'])
    if d.get('ucl'): feats.append(d['ucl'])
    feats.extend(d.get('stations', []))
    d['features'] = feats[:6]

    building  = d.get('building', '')
    postcode  = d.get('postcode', '')
    d['address'] = f"{building}, London, {postcode}" if building else f"London, {postcode}"
    if not d.get('furnish'): d['furnish'] = '带家具'  # only set if not already parsed
    d['deposit']  = ''
    return d

# ── GENERIC PARSER (other agents) ────────────────────────────
def parse_generic(text):
    """Best-effort parse for unknown agent PDF formats"""
    d = {}
    # Try common price patterns
    pm = re.search(r'£([\d,]+)\s*(?:pw|per week|pcm)', text, re.I)
    if pm:
        val = int(pm.group(1).replace(',',''))
        if 'pcm' in pm.group(0).lower():
            d['weekly'] = str(round(val * 12 / 52))
        else:
            d['weekly'] = str(val)

    # Address
    am = re.search(
        r'(\d+[A-Za-z]?\s+[A-Z][a-zA-Z\s,]+(?:Road|Street|Place|Square|'
        r'Court|House|Tower|Lane|Way|Drive|Avenue|Gardens?)[^\n]{0,40})', text)
    if am: d['address'] = am.group(1).strip()

    # Beds
    bm = re.search(r'(\d)\s*(?:bed|bedroom)', text, re.I)
    if bm: d['bed_label'] = f"{bm.group(1)} Bed"
    elif re.search(r'\bstudio\b', text, re.I): d['bed_label'] = 'Studio'

    # Date
    dm = re.search(r'(?:available|from)[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', text, re.I)
    if dm: d['avail'] = dm.group(1)

    # Postcode
    postm = re.search(r'\b([A-Z]{1,2}\d[\dA-Z]?\s*\d[A-Z]{2})\b', text)
    if postm: d['postcode'] = postm.group(1).strip()

    d['furnish']  = '带家具'
    d['features'] = []
    if not d.get('address'): d['address'] = 'London Property'
    if not d.get('bed_label'): d['bed_label'] = '—'
    return d

# ── MASTER PARSER ─────────────────────────────────────────────
def parse_pdf(pdf_path):
    fname = os.path.basename(pdf_path).replace('.pdf', '')
    result = subprocess.run(['pdftotext', '-layout', pdf_path, '-'],
                            capture_output=True, text=True)
    text = result.stdout
    fmt  = detect_format(text)

    if fmt == 'niko':
        d = parse_niko(text)
    elif fmt == 'unihood':
        d = parse_unihood(text)
    else:
        d = parse_generic(text)

    # ── ADDRESS & POSTCODE: filename first, PDF text as fallback ──
    # Filename is most reliable for title; PDF text fills postcode gaps.
    fn_title, fn_postcode = parse_address_from_filename(fname)
    d['fn_title']    = fn_title    # building name from filename
    d['fn_postcode'] = fn_postcode # postcode from filename (may be empty)

    # Postcode priority:
    #   1. Filename postcode (if found)
    #   2. PDF-text postcode (already in d['postcode'] from parser)
    #   3. 'London' as last resort
    if fn_postcode:
        d['postcode'] = fn_postcode          # filename wins
    elif not d.get('postcode'):
        d['postcode'] = 'London'             # nothing found anywhere
    # else: keep d['postcode'] from PDF text parser (e.g. WC1X from floorplan)
    # ────────────────────────────────────────────────────────────

    d['format'] = fmt
    d['monthly'] = str(round(int(d['weekly']) * 52 / 12)) if d.get('weekly') else ''
    if not d.get('avail'):    d['avail']    = '—'
    if not d.get('deposit'):  d['deposit']  = ''
    return d

# ── IMAGE EXTRACTION ──────────────────────────────────────────
# Category priority for Unihood PDFs
UNIHOOD_CATS = [
    (['studio', 'living room', 'lounge', '室内实拍'], 'living'),
    (['kitchen', '厨房'],                              'kitchen'),
    (['bedroom', '卧室'],                              'bedroom'),
    (['bathroom', '浴室'],                             'bathroom'),
    (['outside', 'entrance', 'hallway', '外观'],       'exterior'),
]

def _best_image_from_page(pdf_path, page_num, tmp_dir):
    """Extract the best landscape image from a single PDF page."""
    prefix = os.path.join(tmp_dir, f'p{page_num}')
    subprocess.run(['pdfimages', '-j', '-f', str(page_num), '-l', str(page_num),
                    pdf_path, prefix], capture_output=True)
    best, best_px = None, 0
    for f in sorted(os.listdir(tmp_dir)):
        if not f.startswith(f'p{page_num}-'): continue
        fpath = os.path.join(tmp_dir, f)
        try:
            img = Image.open(fpath)
            w, h = img.size
            if w < 600 or h < 300 or h >= w: continue
            if w * h > best_px:
                best_px = w * h
                best = fpath
        except: continue
    if not best: return None
    if best.endswith('.ppm'):
        buf = BytesIO()
        Image.open(best).convert('RGB').save(buf, 'JPEG', quality=93)
        return f'data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}'
    with open(best, 'rb') as fp:
        return f'data:image/jpeg;base64,{base64.b64encode(fp.read()).decode()}'

def extract_images(pdf_path, tmp_dir, fmt='niko'):
    if fmt == 'unihood':
        return _extract_unihood_images(pdf_path, tmp_dir)

    # Niko & generic: extract all landscape images from page 1
    prefix = os.path.join(tmp_dir, 'img')
    subprocess.run(['pdfimages', '-j', '-f', '1', '-l', '1',
                    pdf_path, prefix], capture_output=True)
    images = []
    for f in sorted(os.listdir(tmp_dir)):
        fpath = os.path.join(tmp_dir, f)
        try:
            img = Image.open(fpath)
            w, h = img.size
            if w < 400 or h < 250 or h > w: continue
            if fpath.endswith('.ppm'):
                buf = BytesIO()
                img.convert('RGB').save(buf, 'JPEG', quality=93)
                b64 = base64.b64encode(buf.getvalue()).decode()
            else:
                with open(fpath, 'rb') as fp:
                    b64 = base64.b64encode(fp.read()).decode()
            images.append(f'data:image/jpeg;base64,{b64}')
        except: continue
    return images

def _extract_unihood_images(pdf_path, tmp_dir):
    """
    Extract 4 images from Unihood PDF by room category:
    Living/Studio → Kitchen → Bedroom → Bathroom → Exterior (fallback)
    """
    result = subprocess.run(['pdftotext', '-layout', pdf_path, '-'],
                            capture_output=True, text=True)
    pages = result.stdout.split('\x0c')

    # Map page number -> category based on first line of page text
    page_cat = {}
    for i, page in enumerate(pages):
        pg = i + 1
        first = page.strip().split('\n')[0].lower() if page.strip() else ''
        for terms, cat in UNIHOOD_CATS:
            if any(t in first for t in terms):
                page_cat[pg] = cat
                break

    # Group pages by category (preserving page order)
    cat_pages = {}
    for pg, cat in sorted(page_cat.items()):
        cat_pages.setdefault(cat, []).append(pg)

    images = []
    used = set()

    # Extract one image per category in priority order
    for _, cat in UNIHOOD_CATS:
        if len(images) >= 4: break
        for pg in cat_pages.get(cat, []):
            if pg in used: continue
            img = _best_image_from_page(pdf_path, pg, tmp_dir)
            if img:
                images.append(img)
                used.add(pg)
                break
            used.add(pg)  # mark as tried even if no good image

    # Pad to 4 with any remaining uncategorised pages
    if len(images) < 4:
        for pg in sorted(page_cat.keys()):
            if len(images) >= 4: break
            if pg in used: continue
            img = _best_image_from_page(pdf_path, pg, tmp_dir)
            if img:
                images.append(img)
                used.add(pg)

    return images[:4]

# ── CARD HTML BLOCK ───────────────────────────────────────────
def build_card(d, images, card_id, fname):
    imgs = images[:4]
    while len(imgs) < 4: imgs.append('')

    weekly    = d.get('weekly', '0')
    monthly   = d.get('monthly', '')
    avail     = d.get('avail', '—')
    deposit   = d.get('deposit', '')
    furnish   = d.get('furnish', '带家具')
    postcode  = d.get('postcode', 'London')
    bed_label = d.get('bed_label', 'Studio')
    features  = d.get('features', [])
    fmt       = d.get('format', 'niko')

    # Title: ALWAYS use filename-derived title (most reliable)
    # Falls back to PDF-parsed address -> fname if fn_title missing
    fn_title = d.get('fn_title', '')
    if fn_title:
        title = fn_title
    else:
        addr = d.get('address', fname.replace('-', ' ').title())
        title = addr.split(',')[0].strip()

    # Area line: "LONDON · SW11"  (postcode area only, clean)
    pc_short  = postcode.split()[0].upper()
    area_disp = f'LONDON · {pc_short}'

    # Monthly / deposit extras
    monthly_str = f'约 £{int(monthly):,}/月' if monthly else ''
    deposit_str = f'押金 £{int(deposit):,}' if deposit else ''
    extra = ' · '.join(filter(None, [monthly_str, deposit_str]))

    # Bed label short: "2室1厅" — strip trailing 卫浴/阳台 for the spec box
    bed_short = bed_label
    m = re.match(r'(\d+室\d+厅)', bed_label)
    if m:
        bed_short = m.group(1)

    # Avail short: "03 SEP"
    if avail != '—':
        av_parts = avail.strip().split()
        avail_short = ' '.join(av_parts[:2]) if len(av_parts) >= 2 else avail[:6]
    else:
        avail_short = '—'

    # Bills label in spec box
    bills_short = furnish  # e.g. "不含Bills" / "含Bills" / "带家具"

    # Hero image
    hero_img = f'<img src="{imgs[0]}" alt="">' if imgs[0] else '<div class="hero-ph"></div>'

    # Gallery: 3 thumbnails
    gallery_html = ''.join([
        f'<img src="{s}" alt="">' if s else '<div class="gph"></div>'
        for s in imgs[1:4]
    ])

    # Feature tags
    feats_html = ''.join([f'<span class="feat">✦ {f}</span>' for f in features[:6]])

    return f"""
<div class="card-wrap">
  <div class="card" id="card-{card_id}">
    <div class="hero">
      {hero_img}
      <div class="badge">London Living</div>
      <div class="avail">&#128197; {avail}</div>
    </div>
    <div class="gallery">{gallery_html}</div>
    <div class="body">
      <div class="area">{area_disp}</div>
      <div class="title">{title}</div>
      <div class="divider"></div>
      <div class="specs">
        <div class="spec">
          <div class="si">&#128719;</div>
          <span class="sv">{bed_short}</span>
          <span class="sl">户型</span>
        </div>
        <div class="spec">
          <div class="si">&#128197;</div>
          <span class="sv">{avail_short}</span>
          <span class="sl">入住</span>
        </div>
        <div class="spec">
          <div class="si">&#127968;</div>
          <span class="sv">{bills_short}</span>
          <span class="sl">家具</span>
        </div>
        <div class="spec">
          <div class="si">&#127963;</div>
          <span class="sv">{pc_short}</span>
          <span class="sl">邮编</span>
        </div>
      </div>
      <div class="price-row">
        <span class="pb">£{int(weekly):,}</span>
        <span class="pu">/ 周</span>
        <span class="pm">{extra}</span>
      </div>
      <div class="feats">{feats_html}</div>
    </div>
    <div class="footer">
      <div class="fb">Niko Relocation<span class="dot"></span>Ltd</div>
      <div class="fc">vx: nikoinlondon<br>nikorelocation.co.uk</div>
    </div>
  </div>
  <button class="btn-single" onclick="dlSingle('card-{card_id}','{fname}',this)">&#11015; 单独下载</button>
</div>"""

# ── BATCH HTML ────────────────────────────────────────────────
def generate_batch(pdf_paths, output_path):
    today = datetime.now().strftime('%Y-%m-%d')
    cards_data = []

    for i, pdf_path in enumerate(pdf_paths):
        fname = os.path.basename(pdf_path).replace('.pdf', '')
        print(f'  [{i+1}/{len(pdf_paths)}] {fname}...', end=' ', flush=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                d      = parse_pdf(pdf_path)
                images = extract_images(pdf_path, tmp, d.get('format', 'niko'))
            cards_data.append((d, images, i, fname))
            print(f'✓  [{d["format"]}] {d.get("address","")} | {d.get("bed_label","")} | £{d.get("weekly","?")}/周 | {len(images)}张图')
        except Exception as e:
            print(f'✗  错误: {e}')

    card_blocks  = '\n'.join([build_card(d, imgs, cid, fn) for d, imgs, cid, fn in cards_data])
    filenames_js = ', '.join([f"'{fn}'" for _, _, _, fn in cards_data])
    count = len(cards_data)

    css = """*{margin:0;padding:0;box-sizing:border-box}:root{--ink:#1a1a1a;--cream:#f7f4ef;--gold:#c9a96e;--gold-light:#e8d5b0;--muted:#8a8078;--white:#fff;--bg:#eeeae3;--green:#1a6640}body{background:var(--bg);font-family:'DM Sans',sans-serif;padding:0 0 60px}.header{background:var(--ink);padding:0 40px;height:64px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}.header-brand{font-family:'Cormorant Garamond',serif;font-size:1.1rem;font-weight:400;color:#fff;letter-spacing:.08em}.header-brand span{display:inline-block;width:4px;height:4px;background:var(--gold);border-radius:50%;margin:0 5px;vertical-align:middle}.hright{display:flex;align-items:center;gap:16px}.hcount{font-size:.7rem;color:rgba(255,255,255,.5);letter-spacing:.1em}.btn-all{padding:10px 24px;background:var(--gold);color:#fff;border:none;border-radius:8px;font-family:'DM Sans',sans-serif;font-size:.75rem;letter-spacing:.1em;text-transform:uppercase;cursor:pointer;font-weight:500}.btn-all:hover{background:#b8925a}.btn-all:disabled{background:#888;cursor:not-allowed}.pbar{height:3px;background:var(--gold);width:0%;transition:width .2s;position:fixed;top:64px;left:0;z-index:200}.grid{display:flex;flex-wrap:wrap;gap:32px;padding:36px 40px}.card-wrap{display:flex;flex-direction:column;align-items:center;gap:10px}.card{width:380px;background:var(--white);border-radius:20px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.15),0 4px 16px rgba(0,0,0,.08)}.hero{width:100%;height:220px;position:relative;overflow:hidden;background:#1a2744}.hero img{width:100%;height:100%;object-fit:cover;display:block}.hero-ph{width:100%;height:100%;background:#1a2744}.badge{position:absolute;top:14px;left:14px;background:var(--ink);color:#fff;font-size:.58rem;letter-spacing:.15em;text-transform:uppercase;padding:5px 11px;border-radius:20px;font-weight:500}.avail{position:absolute;top:14px;right:14px;background:rgba(255,255,255,.93);color:var(--green);font-size:.6rem;padding:5px 10px;border-radius:20px;font-weight:500}.gallery{display:grid;grid-template-columns:repeat(3,1fr);gap:2px;height:72px}.gallery img{width:100%;height:100%;object-fit:cover;display:block}.gph{background:#e0dbd2}.body{padding:18px 20px 14px}.area{font-size:.58rem;letter-spacing:.22em;text-transform:uppercase;color:var(--gold);font-weight:500;margin-bottom:4px}.title{font-family:'Cormorant Garamond',serif;font-size:1.15rem;font-weight:600;line-height:1.25;margin-bottom:12px;color:var(--ink)}.divider{height:1px;background:linear-gradient(to right,var(--gold-light),transparent);margin-bottom:13px}.specs{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:13px}.spec{text-align:center;padding:9px 4px;background:var(--cream);border-radius:9px}.si{font-size:.82rem}.sv{display:block;font-size:.65rem;font-weight:500;margin-top:3px;line-height:1.2;color:var(--ink)}.sl{display:block;font-size:.48rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-top:1px}.price-row{display:flex;align-items:baseline;gap:5px;margin-bottom:9px}.pb{font-family:'Cormorant Garamond',serif;font-size:1.9rem;font-weight:600;line-height:1;color:var(--ink)}.pu{font-size:.68rem;color:var(--muted)}.pm{font-size:.62rem;color:var(--muted);margin-left:auto}.feats{display:flex;flex-wrap:wrap;gap:5px}.feat{background:var(--cream);border:1px solid var(--gold-light);border-radius:5px;font-size:.58rem;padding:3px 7px;color:#5a4a35}.footer{border-top:1px solid #ede9e0;padding:11px 20px;display:flex;align-items:center;justify-content:space-between;background:var(--cream)}.fb{font-family:'Cormorant Garamond',serif;font-size:.88rem;font-weight:600;letter-spacing:.04em;color:var(--ink)}.dot{display:inline-block;width:5px;height:5px;background:var(--gold);border-radius:50%;margin:0 5px;vertical-align:middle}.fc{font-size:.58rem;color:var(--muted);text-align:right;line-height:1.7}.btn-single{width:380px;padding:12px;background:var(--ink);color:#fff;border:none;border-radius:10px;font-family:'DM Sans',sans-serif;font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;cursor:pointer;font-weight:500}.btn-single:hover{background:#333}"""

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Niko · 批量房源卡片 {today}</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;600&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>

<div class="header">
  <div class="header-brand">Niko Relocation<span></span>Ltd</div>
  <div class="hright">
    <div class="hcount">共 {count} 个房源 · {today}</div>
    <button class="btn-all" id="btnAll" onclick="dlAll()">⬇ 一键下载全部 {count} 张</button>
  </div>
</div>
<div class="pbar" id="pbar"></div>

<div class="grid">
{card_blocks}
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
<script>
const FN = [{filenames_js}];

async function render(id) {{
  return html2canvas(document.getElementById(id),
    {{scale:3, useCORS:true, backgroundColor:'#ffffff', logging:false}})
    .then(c => c.toDataURL('image/jpeg', 0.95).split(',')[1]);
}}

async function dlSingle(cardId, fname, btn) {{
  btn.textContent = '生成中...'; btn.disabled = true;
  const b64 = await render(cardId);
  const a = document.createElement('a');
  a.download = 'niko-' + fname + '.jpg';
  a.href = 'data:image/jpeg;base64,' + b64;
  a.click();
  btn.textContent = '✓ 已下载';
  setTimeout(() => {{ btn.textContent = '⬇ 单独下载'; btn.disabled = false; }}, 2000);
}}

async function dlAll() {{
  const btn = document.getElementById('btnAll');
  const bar = document.getElementById('pbar');
  btn.disabled = true;
  const zip = new JSZip();
  const cards = document.querySelectorAll('.card');
  for (let i = 0; i < cards.length; i++) {{
    btn.textContent = `打包中 ${{i+1}} / ${{cards.length}}...`;
    bar.style.width = ((i+1) / cards.length * 95) + '%';
    const b64 = await render(cards[i].id);
    zip.file('niko-' + FN[i] + '.jpg', b64, {{base64: true}});
  }}
  btn.textContent = '压缩中...';
  const blob = await zip.generateAsync({{type:'blob'}});
  const a = document.createElement('a');
  a.download = 'niko-listings-{today}.zip';
  a.href = URL.createObjectURL(blob);
  a.click();
  bar.style.width = '100%';
  btn.textContent = '✓ 全部完成！';
  setTimeout(() => {{
    btn.textContent = '⬇ 一键下载全部 {count} 张';
    btn.disabled = false;
    bar.style.width = '0%';
  }}, 3000);
}}
</script>
</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n✓ 完成！→ {os.path.basename(output_path)}')
    print(f'  浏览器打开后点「一键下载全部」')

# ── MAIN ──────────────────────────────────────────────────────
if __name__ == '__main__':
    pdfs = sys.argv[1:]
    if not pdfs:
        print('用法: python3 generate_cards.py *.pdf')
        print('支持: Niko爬虫PDF / Unihood PDF / 其他中介PDF')
        sys.exit(0)

    pdf_paths = [os.path.abspath(p) for p in pdfs if p.endswith('.pdf')]
    if not pdf_paths:
        print('没有找到PDF文件')
        sys.exit(1)

    output_dir  = os.path.dirname(pdf_paths[0])
    today_str   = datetime.now().strftime('%Y%m%d_%H%M')
    output_path = os.path.join(output_dir, f'niko-cards-{today_str}.html')

    print(f'处理 {len(pdf_paths)} 个PDF...\n')
    generate_batch(pdf_paths, output_path)
