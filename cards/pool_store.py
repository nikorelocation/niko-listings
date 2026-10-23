#!/usr/bin/env python3
"""
房源池数据存储（GitHub 版，替代 Supabase，零成本）

数据：pool/pool.json  —— 一个数组，每套房源一行，字段：
  id          card-<毫秒>-<3位hex>（和以前 Supabase 的 id 格式一样，单套链接 pool.html#/p/<id> 不变）
  area/beds/price/month   筛选标签（和以前一样）
  image       原图相对路径（自动入池的指向 cards/out/<文件夹>/<卡片>.jpg；手动上传的在 pool/img/）
  thumb       缩略图相对路径 pool/thumbs/<id>.jpg（列表页用，约 40KB）
  created_at  入池时间 ISO
  rm_id/address/weekly/folder   参考信息（可选）

图片和数据都由 GitHub Pages 免费托管，房源池页面 pool.html 直接读 pool/pool.json。

命令行：
  python cards/pool_store.py apply <ops.json>     把一次操作（新增/删除）应用到当前 pool.json（Action 提交前用）
"""
import datetime as dt, json, os, random, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOL_JSON = os.path.join(ROOT, 'pool', 'pool.json')
THUMB_DIR = os.path.join(ROOT, 'pool', 'thumbs')
IMG_DIR = os.path.join(ROOT, 'pool', 'img')
THUMB_W = 720


def new_id():
    return f'card-{int(time.time()*1000)}-{random.randbytes(2).hex()[:3]}'


def rel(p):
    return os.path.relpath(os.path.abspath(p), ROOT).replace(os.sep, '/')


def load():
    if not os.path.exists(POOL_JSON):
        return []
    with open(POOL_JSON, encoding='utf-8') as f:
        return json.load(f)


def save(rows):
    """一行一套，最新的在前；这样 git diff 清楚、冲突少"""
    rows = sorted(rows, key=lambda r: r.get('created_at') or '', reverse=True)
    os.makedirs(os.path.dirname(POOL_JSON), exist_ok=True)
    body = ',\n'.join(json.dumps(r, ensure_ascii=False, separators=(',', ':')) for r in rows)
    with open(POOL_JSON, 'w', encoding='utf-8') as f:
        f.write('[\n' + body + ('\n' if rows else '') + ']\n')


def make_thumb(src, rec_id):
    from PIL import Image
    os.makedirs(THUMB_DIR, exist_ok=True)
    dst = os.path.join(THUMB_DIR, f'{rec_id}.jpg')
    im = Image.open(src).convert('RGB')
    if im.width > THUMB_W:
        im = im.resize((THUMB_W, round(im.height * THUMB_W / im.width)), Image.LANCZOS)
    im.save(dst, 'JPEG', quality=72, optimize=True, progressive=True)
    return dst


def build_row(jpg_path, tags, rec_id=None, created_at=None, **extra):
    """生成一条房源记录 + 缩略图（不写 pool.json；写入用 apply_ops）"""
    rec_id = rec_id or new_id()
    thumb = make_thumb(jpg_path, rec_id)
    row = {'id': rec_id, 'area': tags['area'], 'beds': int(tags['beds']), 'price': tags['price'],
           'month': tags['month'], 'image': rel(jpg_path), 'thumb': rel(thumb),
           'created_at': created_at or dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}
    row.update({k: v for k, v in extra.items() if v not in (None, '')})
    return row


def apply_ops(ops):
    """ops = {'add': [row, ...], 'remove': [id, ...]}；返回 (新增数, 删除数)"""
    rows = load()
    have = {r['id'] for r in rows}
    rm = set(ops.get('remove') or [])
    removed = [r for r in rows if r['id'] in rm]
    rows = [r for r in rows if r['id'] not in rm]
    added = 0
    for r in ops.get('add') or []:
        if r['id'] not in have:
            rows.append(r); added += 1
    for r in removed:  # 删掉缩略图和手动上传的原图；cards/out 里的卡片原件保留
        for k in ('thumb', 'image'):
            p = r.get(k) or ''
            if p.startswith('pool/') and os.path.exists(os.path.join(ROOT, p)):
                os.remove(os.path.join(ROOT, p))
    save(rows)
    return added, len(removed)


def select_old(n=0, older_than_days=0):
    """要清理的旧记录：最早的 n 条，或入池超过 older_than_days 天的全部"""
    rows = sorted(load(), key=lambda r: r.get('created_at') or '')
    if older_than_days > 0:
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=older_than_days)).isoformat()
        return [r for r in rows if (r.get('created_at') or '') < cutoff]
    return rows[:int(n)] if n > 0 else []


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'apply':
        ops = json.load(open(sys.argv[2], encoding='utf-8'))
        a, d = apply_ops(ops)
        print(f'房源池：新增 {a} 套，删除 {d} 套，现共 {len(load())} 套')
    else:
        print(__doc__); sys.exit(1)
