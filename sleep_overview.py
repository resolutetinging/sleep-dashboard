#!/usr/bin/env python3
# 每日睡眠總覽統計（給 Claude routine 讀取後寫白話總結）
# 只讀 sleep_v3_history.json，輸出 JSON 到 stdout；不寫任何檔案、不連網
# 口徑：睡眠時數＝deep+rem+core（不含清醒）；日期鍵＝醒來日期；今天以台北時間為準
import argparse, json, statistics as st, sys
from datetime import date, datetime, timedelta, timezone

TPE = timezone(timedelta(hours=8))
BASELINE = ('2026-09-01', '2026-10-18')  # 10-19 睡眠評估的基準期


def onset_min(iso):
    # 以 18:00 為起點的分鐘數，跨午夜入睡才能正確取中位與標準差
    t = datetime.fromisoformat(iso)
    return (t.hour * 60 + t.minute - 18 * 60) % 1440


def fmt_onset(m):
    m = int(round((m + 18 * 60) % 1440))
    return f'{m // 60:02d}:{m % 60:02d}'


def sleep_min(n):
    return n['deep_min'] + n['rem_min'] + n['core_min']


def window_stats(nights):
    if not nights:
        return None
    sl = [sleep_min(n) for n in nights]
    on = [onset_min(n['bedtime']) for n in nights if n.get('bedtime')]
    return {
        'nights': len(nights),
        'sleep_h_median': round(st.median(sl) / 60, 2),
        'under_7h': sum(x < 420 for x in sl),
        'under_6h': sum(x < 360 for x in sl),
        'efficiency_median': round(st.median([n['efficiency'] for n in nights]), 1),
        'deep_min_median': round(st.median([n['deep_min'] for n in nights]), 1),
        'deep_pct_median': round(st.median([n['deep_min'] / s * 100 for n, s in zip(nights, sl)]), 1),
        'rem_pct_median': round(st.median([n['rem_min'] / s * 100 for n, s in zip(nights, sl)]), 1),
        'awake_min_median': round(st.median([n['awake_min'] for n in nights]), 1),
        'onset_median': fmt_onset(st.median(on)) if on else None,
        'onset_sd_min': round(st.pstdev(on)) if len(on) > 1 else None,
        'onset_latest': fmt_onset(max(on)) if on else None,
    }


def night_row(k, n):
    return {
        'date': k,
        'bedtime': (n.get('bedtime') or '')[11:16],
        'wake': (n.get('wake') or '')[11:16],
        'sleep_h': round(sleep_min(n) / 60, 2),
        'deep': n['deep_min'], 'rem': n['rem_min'], 'core': n['core_min'], 'awake': n['awake_min'],
        'efficiency': n['efficiency'],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--history', default='sleep_v3_history.json')
    ap.add_argument('--today', help='YYYY-MM-DD（預設台北今天）')
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else datetime.now(TPE).date()
    try:
        N = json.load(open(a.history, encoding='utf-8'))['nights']
    except Exception as e:
        print(json.dumps({'status': 'error', 'message': f'讀不到睡眠歷史：{e}'}, ensure_ascii=False))
        return 1
    valid = {k: v for k, v in N.items() if isinstance(v, dict) and all(
        isinstance(v.get(f), (int, float)) for f in ('deep_min', 'rem_min', 'core_min', 'awake_min', 'efficiency'))
        and sleep_min(v) > 0}
    keys = sorted(k for k in valid if k <= today.isoformat())
    latest = keys[-1] if keys else None
    t = today.isoformat()
    if latest is None:
        status, gap = 'error', None
    else:
        gap = (today - date.fromisoformat(latest)).days
        status = 'ok' if gap == 0 else 'missing_last_night'
    end = today
    d7 = (end - timedelta(days=6)).isoformat()
    d14 = (end - timedelta(days=13)).isoformat()
    w7 = [valid[k] for k in keys if d7 <= k <= t]
    w14 = [valid[k] for k in keys if d14 <= k <= t]
    wb = [valid[k] for k in keys if BASELINE[0] <= k <= BASELINE[1]]
    out = {
        'status': status,
        'today': t,
        'latest_night': latest,
        'days_since_latest': gap,
        'last_night': night_row(latest, valid[latest]) if latest else None,
        'last7_rows': [night_row(k, valid[k]) for k in keys if d7 <= k <= t],
        'windows': {
            'baseline_0901_1018': window_stats(wb),
            'last14': window_stats(w14),
            'last7': window_stats(w7),
        },
    }
    if out['last7_rows']:
        short = 0
        for r in reversed(out['last7_rows']):
            if r['sleep_h'] < 6.5:
                short += 1
            else:
                break
        out['consecutive_short_nights_lt_6_5h'] = short
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
