#!/usr/bin/env python3
"""
一次性（2026-10-23 已跑）：用仓库里 cards/out/*/cards.json 的入池记录重建 pool/pool.json。
- 保留原来的 id，所以已经发出去的单套链接 pool.html#/p/<id> 继续有效
- 排除已知删过的：deleted-*.json 里的，以及 EXCLUDE（Action 日志里 delete_ids 删掉的）
- --include <文件夹> ：把因 Supabase 402 没入池的那批也入池（直接写回那批 cards.json 的 saved/supabase_id）
"""
import argparse, datetime as dt, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool_store

EXCLUDE = {'card-1791537870855-d1e', 'card-1791555750947-64c', 'card-1791566359587-72c'}


def ts_of(rec_id, folder):
    try:
        ms = int(rec_id.split('-')[1])
        return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat(timespec='seconds')
    except Exception:
        d = dt.datetime.strptime(folder, '%Y%m%d-%H%M')
        return d.replace(tzinfo=dt.timezone.utc).isoformat(timespec='seconds')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--include', action='append', default=[])
    a = ap.parse_args()
    root = pool_store.ROOT
    deleted = set(EXCLUDE)
    for f in glob.glob(os.path.join(root, 'cards/out/*/deleted-*.json')):
        deleted |= {r['id'] for r in json.load(open(f, encoding='utf-8'))}
    rows, seen, migrated = [], set(), set()
    for cj in sorted(glob.glob(os.path.join(root, 'cards/out/*/cards.json'))):
        folder = os.path.basename(os.path.dirname(cj))
        data = json.load(open(cj, encoding='utf-8'))
        changed = False
        for r in data:
            fresh = False
            if folder in a.include and not r.get('saved') and r.get('card') and not r.get('error') and not r.get('skipped'):
                r['supabase_id'] = pool_store.new_id()
                r['saved'] = True; r.pop('save_error', None); changed = True; fresh = True
            rid = r.get('supabase_id')
            if not (r.get('saved') and rid) or rid in deleted or rid in seen or r.get('duplicate'):
                continue
            jpg = os.path.join(root, 'cards/out', folder, r['card'])
            if not os.path.exists(jpg):
                print('缺图', jpg); continue
            row = pool_store.build_row(jpg, r['tags'], rec_id=rid, created_at=ts_of(rid, folder),
                                       rm_id=r.get('rm_id'), address=r.get('address'), weekly=r.get('weekly'), folder=folder)
            if folder in a.include:
                r['image_url'] = row['image']
            rows.append(row); seen.add(rid)
            if not fresh:
                migrated.add(rid)  # 只有原本在 Supabase 里的才参与 11 月 3 日的对齐删除
        if changed:
            json.dump(data, open(cj, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    pool_store.save(rows)
    meta = {'migrated_from_supabase_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
            'migrated_ids': sorted(migrated),
            'note': '从仓库记录重建；Supabase 里手动上传的房源等 11 月 3 日额度恢复后用 import_supabase 搬入'}
    json.dump(meta, open(os.path.join(root, 'pool', 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'房源池重建完成：{len(rows)} 套')


if __name__ == '__main__':
    main()
