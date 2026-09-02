#!/usr/bin/env python3
"""
Sleep v3 驗證用腳本

讀取「Sleep Export 2」iOS捷徑產出的原始睡眠分期樣本檔（非合法JSON，需正則解析），
用新的 Duration 算法重新計算每晚各睡眠分期時長，寫入 sleep_dashboard_v3.html 的
RAW_V3 資料區，純粹用來跟舊版（sleep_dashboard_v2.html / update_dashboard.py 產出的
v2舊軌資料）並排比較新算法準不準。

只做本機資料處理：不 git commit/push、不動 LaunchAgent 排程，也不修改
update_dashboard.py / sleep_dashboard_v2.html / index.html / run_update.sh 這幾個既有檔案。

執行方式：
    python3 update_dashboard_v3.py
"""
import re
import json
from datetime import datetime, timedelta
from pathlib import Path

RAW_DIR = Path(
    "/Users/tinayu/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/"
    "Documents/Daily Sleep Update"
)
HTML_PATH = Path(__file__).resolve().parent / "sleep_dashboard_v3.html"
RAW_V3_LINE = re.compile(r"const RAW_V3 = \[.*?\];", re.DOTALL)


def latest_raw_path():
    """sleep_raw_<date>.txt 的檔名是捷徑執行當天日期，每天不同，
    不能寫死檔名，改抓資料夾裡最新的一份。"""
    candidates = sorted(RAW_DIR.glob("sleep_raw_*.txt"))
    return candidates[-1] if candidates else None

# 抓取單筆樣本的 value / startDate / duration（endDate 恆等於 startDate，是舊 bug
# 殘留欄位，不拿來算時長；raw檔本身不是合法JSON，陣列元素缺{}分隔，只能用正則抓）
SAMPLE_PATTERN = re.compile(
    r'"value":"([^"]*)","startDate":"([^"]*)","endDate":"([^"]*)\s*,"duration":([\d:]+)'
)

VALID_STAGES = ("Deep", "REM", "Core", "Awake")

# 同一晚睡眠session切分門檻（分鐘）。已驗證60分鐘會把中間醒60-75分鐘的情況誤切成
# 兩筆睡眠，跟iPhone Health App官方顯示的「一晚」對不上，90分鐘才對得上。
GAP_THRESHOLD_MIN = 90

MIN_SESSION_TOTAL_MIN = 60  # 濾掉白天小睡等雜訊


def parse_dur(s):
    """duration字串轉秒數。支援三種格式：純秒數／M:SS／H:MM:SS。"""
    parts = s.split(':')
    if len(parts) == 1:
        return float(parts[0])
    elif len(parts) == 2:
        m, sec = parts
        return int(m) * 60 + float(sec)
    elif len(parts) == 3:
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + float(sec)
    return None


def load_samples(path):
    text = path.read_text(encoding='utf-8')
    samples = []
    for m in SAMPLE_PATTERN.finditer(text):
        value_raw, start_raw, _end_raw, dur_raw = m.groups()
        value = value_raw.strip()
        if value not in VALID_STAGES:
            continue
        try:
            start = datetime.fromisoformat(start_raw)
        except ValueError:
            continue
        dur_sec = parse_dur(dur_raw)
        if dur_sec is None:
            continue
        samples.append({'value': value, 'start': start, 'dur_sec': dur_sec})
    samples.sort(key=lambda s: s['start'])
    return samples


def split_sessions(samples):
    """依startDate排序後，跟下一筆間隔 > GAP_THRESHOLD_MIN 分鐘就切成新session。"""
    sessions = []
    current = []
    for s in samples:
        if current and (s['start'] - current[-1]['start']).total_seconds() > GAP_THRESHOLD_MIN * 60:
            sessions.append(current)
            current = []
        current.append(s)
    if current:
        sessions.append(current)
    return sessions


def build_record(session):
    totals = {'Deep': 0.0, 'REM': 0.0, 'Core': 0.0, 'Awake': 0.0}
    for s in session:
        totals[s['value']] += s['dur_sec']

    first = session[0]
    last = session[-1]
    bedtime = first['start']
    # 最後一筆本身也有時長，真正醒來時間 = 最後一筆起點 + 它自己的duration
    wake = last['start'] + timedelta(seconds=last['dur_sec'])

    deep_min = totals['Deep'] / 60
    rem_min = totals['REM'] / 60
    core_min = totals['Core'] / 60
    awake_min = totals['Awake'] / 60
    total_min = deep_min + rem_min + core_min + awake_min

    return {
        'date': wake.strftime('%Y-%m-%d'),  # 以「醒來日期」為準，對齊iPhone Health App邏輯
        'bedtime': bedtime.isoformat(),
        'wake': wake.isoformat(),
        'total_min': round(total_min, 1),
        'deep_min': round(deep_min, 1),
        'rem_min': round(rem_min, 1),
        'core_min': round(core_min, 1),
        'awake_min': round(awake_min, 1),
        'efficiency': 0,
    }


def inject_html(records):
    if not HTML_PATH.exists():
        print(f"找不到 HTML 模板：{HTML_PATH}")
        return False
    html = HTML_PATH.read_text(encoding='utf-8')
    new_line = "const RAW_V3 = " + json.dumps(records, ensure_ascii=False) + ";"
    if not RAW_V3_LINE.search(html):
        print("找不到 const RAW_V3 = [...]; 這一行，HTML 模板格式可能被改過")
        return False
    injected = RAW_V3_LINE.sub(new_line, html, count=1)
    HTML_PATH.write_text(injected, encoding='utf-8')
    return True


def main():
    raw_path = latest_raw_path()
    if raw_path is None:
        print(f"在 {RAW_DIR} 找不到任何 sleep_raw_*.txt 檔案")
        return
    print(f"使用原始資料檔：{raw_path.name}")

    samples = load_samples(raw_path)
    print(f"解析出 {len(samples)} 筆原始樣本")

    sessions = split_sessions(samples)
    print(f"切出 {len(sessions)} 個睡眠 session（門檻 {GAP_THRESHOLD_MIN} 分鐘）")

    records = []
    for session in sessions:
        rec = build_record(session)
        if rec['total_min'] < MIN_SESSION_TOTAL_MIN:
            continue
        records.append(rec)
    records.sort(key=lambda r: r['date'])

    print(f"\n保留 {len(records)} 夜（total_min >= {MIN_SESSION_TOTAL_MIN} 分鐘）：")
    for r in records:
        print(
            f"  {r['date']}  total={r['total_min']}min  "
            f"deep={r['deep_min']}  rem={r['rem_min']}  "
            f"core={r['core_min']}  awake={r['awake_min']}"
        )

    if inject_html(records):
        print(f"\n已寫入 {HTML_PATH}")


if __name__ == '__main__':
    main()
