#!/usr/bin/env python3
"""
一次性：把旧 Supabase 房源池对齐到 GitHub 房源池（pool/pool.json）。
11 月 3 日 Supabase 免费额度恢复后，在 Actions 里勾选 import_supabase 跑一次即可，之后不再需要 Supabase。

做两件事：
  1) Supabase 里有、仓库没有的（以前在页面上手动上传的卡片）→ 下载图片到 pool/img/<id>.jpg，生成缩略图，加进房源池
  2) 搬迁时从仓库记录重建的房源，如果 Supabase 里已经没有了（以前在页面上手动删掉的）→ 从房源池删除
结果写进 <out>/pool_ops.json（和本次其他操作合并），由 workflow 应用到 pool.json；明细写 <out>/import-supabase.json。
"""
import argparse, json, os, sys
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool_store

# pool.html 里公开的只读 anon key（和以前页面用的一样），没有配置 secrets 时用它
ANON = ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImltaGxvemRsb2h0amtkdnJzeWx1Iiwicm9sZSI6ImFub24i'
        'LCJpYXQiOjE3ODA1MDA0OTIsImV4cCI6MjA5NjA3NjQ5Mn0.r-lN5wPk5WbmED1uUyq-76c5aX_IDTlNpt4vFmexqCo')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    url = (os.environ.get('SUPABASE_URL') or 'https://imhlozdlohtjkdvrsylu.supabase.co').rstrip('/')
    key = os.environ.get('SUPABASE_KEY') or ANON
    h = {'apikey': key, 'Authorization': 'Bearer ' + key}
    r = requests.get(f'{url}/rest/v1/properties?select=*&order=created_at.asc&limit=5000', headers=h, timeout=60)
    if r.status_code != 200:
        print(f'✗ 读取 Supabase 失败 {r.status_code}: {r.text[:200]}（额度可能还没恢复）'); sys.exit(1)
    sb = r.json()
    if not sb:
        print('✗ Supabase 返回 0 条，为安全起见不做任何删除'); sys.exit(1)
    meta = json.load(open(os.path.join(pool_store.ROOT, 'pool', 'meta.json'), encoding='utf-8'))
    migrated = set(meta.get('migrated_ids') or [])
    pool = {p['id']: p for p in pool_store.load()}
    sb_ids = {x['id'] for x in sb}

    ops_path = os.path.join(a.out, 'pool_ops.json')
    ops = json.load(open(ops_path, encoding='utf-8')) if os.path.exists(ops_path) else {'add': [], 'remove': []}
    report = {'added': [], 'removed': [], 'failed': []}
    os.makedirs(pool_store.IMG_DIR, exist_ok=True)
    for x in sb:
        if x['id'] in pool:
            continue
        try:
            img = requests.get(x['image_url'], timeout=60)
            img.raise_for_status()
            dst = os.path.join(pool_store.IMG_DIR, f"{x['id']}.jpg")
            from PIL import Image
            from io import BytesIO
            im = Image.open(BytesIO(img.content)).convert('RGB')
            im.save(dst, 'JPEG', quality=85, optimize=True, progressive=True)
            row = pool_store.build_row(dst, x, rec_id=x['id'], created_at=x.get('created_at'), source='manual')
            ops['add'].append(row); report['added'].append(x['id'])
        except Exception as e:
            report['failed'].append({'id': x['id'], 'error': str(e)})
    for pid in pool:
        if pid in migrated and pid not in sb_ids:
            ops['remove'].append(pid); report['removed'].append(pid)
    os.makedirs(a.out, exist_ok=True)
    json.dump(ops, open(ops_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(report, open(os.path.join(a.out, 'import-supabase.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"Supabase 共 {len(sb)} 条；新搬入 {len(report['added'])} 套（手动上传的），"
          f"删除 {len(report['removed'])} 套（Supabase 里已删），失败 {len(report['failed'])} 套")


if __name__ == '__main__':
    main()
