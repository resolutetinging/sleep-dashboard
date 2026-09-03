#!/usr/bin/env python3
"""
Sleep v3 驗證用腳本

讀取「Sleep Export 2」iOS捷徑產出的原始睡眠分期樣本檔（非合法JSON，需正則解析），
用新的 Duration 算法重新計算每晚各睡眠分期時長，寫入 sleep_dashboard_v3.html 的
RAW_V3 資料區，純粹用來跟舊版（sleep_dashboard_v2.html / update_dashboard.py 產出的
v2舊軌資料）並排比較新算法準不準。

只做本機資料處理：不 git commit/push、不動 LaunchAgent 排程，也不修改
update_dashboard.py / sleep_dashboard_v2.html / index.html / run_update.sh 這幾個既有檔案。

09-03補：Sleep Export 2捷徑每次只抓「過去1週」樣本（滾動視窗），單次執行本身
不會累積歷史——原設計每次都整批重算、整份覆蓋RAW_V3，超出視窗的舊資料會直接
消失（例如09-03跑完，08-26就從畫面上掉了），也沒有任何機制比對「這次算出來的
某一晚數字，跟上次算出來的是否一致」。這支script現在改成維護一份本機持久化
的 sleep_v3_history.json，每晚資料一旦進來就永久保留（不受Shortcut滾動視窗
影響），且每次執行都會拿新算出的數字跟歷史紀錄比對，只有真的變動（超過
CHANGE_TOLERANCE_MIN容忍值，排除duration本身30秒捨入造成的正常誤差）才更新
並記錄異動細節，沒變動的維持原樣不動。

09-03再補：history.json原本只存「算出來的結果」（分鐘數），不存原始樣本，等於
還是依賴iCloud端的sleep_raw_*.txt保留原始證據——但那份檔案每天都是「過去1週」
滾動視窗，跟前一天的內容有6/7重疊，若iCloud端被清掉或視窗滾過去，之前算過的
夜晚就永遠沒有原始樣本可重算，一旦日後發現算法本身有bug（這正是這次Duration
遷移debug的實際經歷），沒有原始樣本就只能將錯就錯。改成每晚第一次出現時，把
該晚的原始樣本（value/start/duration）一併存進history.json的raw_samples欄位，
不依賴iCloud端保留舊檔，也不像iCloud每日滾動視窗那樣有6/7重疊的浪費（每晚只
存一次）。

09-03三補：每次執行同時唯讀v2的sleep_dashboard_v2.html，把重疊日期的四項分期
數字跟v3自己算出的互相比對（理論上該收斂到接近的數字，因為v2/v3都是拿Duration
算的），差距超過V2_V3_DIVERGENCE_TOLERANCE_MIN才記錄進history.json的
v2_v3_divergence，用來及早發現任一邊出問題，不用等正式切換後才踩雷。**只讀
v2的檔案，絕對不寫入。**

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
HISTORY_PATH = Path(__file__).resolve().parent / "sleep_v3_history.json"
RAW_V3_LINE = re.compile(r"const RAW_V3 = \[.*?\];", re.DOTALL)

# v2的資料頁，這支script只會「讀」這個檔案做交叉比對，絕對不寫入／不修改。
V2_HTML_PATH = Path(__file__).resolve().parent / "sleep_dashboard_v2.html"
V2_RAW_LINE = re.compile(r"const RAW = (\{.*?\});\s*\n\s*const COLORS", re.DOTALL)

# 判定「這一晚的數字真的變了」而非duration捨入誤差的門檻（分鐘）。
# 已驗證duration本身以30秒為單位捨入，正常誤差約1-2分鐘，門檻設3分鐘留餘裕。
CHANGE_TOLERANCE_MIN = 3
STAGE_FIELDS = ('deep_min', 'rem_min', 'core_min', 'awake_min')

# v2/v3理論上都是拿Duration算出來的，長期該收斂到幾乎一樣的數字。這個門檻是
# 「v2跟v3同一晚差距多少分鐘，才算兩邊系統性分歧、值得留意」，比CHANGE_TOLERANCE_MIN
# 稍寬鬆一點，因為v2走的是Shortcut端自己彙總（自己的捨入方式），跟v3的Python端
# 彙總本來就可能有些微差異。
V2_V3_DIVERGENCE_TOLERANCE_MIN = 4


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


def serialize_session(session):
    """把session內的原始樣本（datetime物件）轉成可存進JSON的格式，
    供history.json的raw_samples欄位使用，日後重算不必依賴iCloud端的原始檔。"""
    return [
        {'value': s['value'], 'start': s['start'].isoformat(), 'dur_sec': s['dur_sec']}
        for s in session
    ]


def load_history():
    if not HISTORY_PATH.exists():
        return {'nights': {}, 'changelog': []}
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        print(f"⚠ {HISTORY_PATH.name} 讀取失敗或損毀，視為空歷史重新開始")
        return {'nights': {}, 'changelog': []}
    data.setdefault('nights', {})
    data.setdefault('changelog', [])
    return data


def save_history(history):
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def merge_records(history, new_records, raw_samples_by_date):
    """拿新算出的每晚記錄跟歷史比對：新日期直接收錄（含當晚原始樣本，供日後
    重算用）；已存在的日期若四項分期數字都在容許誤差內視為無異動、保留舊
    記錄；超出誤差才覆蓋（含更新原始樣本）並記一筆異動。
    回傳 (new_dates, changed_dates, unchanged_dates) 供列印報告用。"""
    nights = history['nights']
    now = datetime.now().isoformat(timespec='seconds')
    new_dates, changed_dates, unchanged_dates = [], [], []

    for rec in new_records:
        date = rec['date']
        raw_samples = raw_samples_by_date.get(date, [])
        old = nights.get(date)
        if old is None:
            nights[date] = {**rec, 'raw_samples': raw_samples, 'first_seen': now, 'last_updated': now}
            new_dates.append(date)
            continue

        diffs = {
            f: round(rec[f] - old[f], 1)
            for f in STAGE_FIELDS
            if abs(rec[f] - old[f]) > CHANGE_TOLERANCE_MIN
        }
        if not diffs:
            # 09-03功能上線前存進history的舊資料沒有raw_samples欄位；數字沒變
            # 就不當成「異動」，但趁原始檔還在Shortcut視窗內，順手補回原始樣本，
            # 不然視窗一滾過去就永久補不回來了。
            if not old.get('raw_samples') and raw_samples:
                old['raw_samples'] = raw_samples
                old['last_updated'] = now
            unchanged_dates.append(date)
            continue

        history['changelog'].append({
            'date': date, 'detected_at': now,
            'diffs': {f: {'old': old[f], 'new': rec[f], 'delta': d} for f, d in diffs.items()},
        })
        nights[date] = {
            **rec, 'raw_samples': raw_samples,
            'first_seen': old.get('first_seen', now), 'last_updated': now,
        }
        changed_dates.append(date)

    return new_dates, changed_dates, unchanged_dates


def load_v2_records():
    """唯讀解析sleep_dashboard_v2.html裡的const RAW={...}區塊，回傳{date: record}。
    這個函式絕對不寫入v2的檔案，只讀取供交叉比對用。抓不到就回傳空dict，
    不中斷v3自己的流程（v2/v3交叉比對是加分功能，不是v3能不能跑的前提）。"""
    if not V2_HTML_PATH.exists():
        print(f"⚠ 找不到 {V2_HTML_PATH.name}，略過v2/v3交叉比對")
        return {}
    try:
        html = V2_HTML_PATH.read_text(encoding='utf-8')
        m = V2_RAW_LINE.search(html)
        if not m:
            print("⚠ 在v2頁裡找不到 const RAW = {...}，略過v2/v3交叉比對")
            return {}
        raw = json.loads(m.group(1))
        return {r['date']: r for r in raw.get('summary', [])}
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠ 讀取v2資料失敗（{e}），略過v2/v3交叉比對")
        return {}


def compare_v2_v3(history, v2_by_date):
    """拿v2跟v3同一晚的四項分期數字互相比對（理論上該收斂到接近的數字，
    因為兩邊都是拿Duration算的），只在差距超過V2_V3_DIVERGENCE_TOLERANCE_MIN時
    才記錄，避免把正常的捨入方式差異也當成警訊。
    回傳本次比對到、且超出容許誤差的日期清單，供列印報告用。"""
    now = datetime.now().isoformat(timespec='seconds')
    divergence = history.setdefault('v2_v3_divergence', {})
    flagged_dates = []

    for date, v3_rec in history['nights'].items():
        v2_rec = v2_by_date.get(date)
        if v2_rec is None:
            continue
        diffs = {
            f: round(v3_rec[f] - v2_rec[f], 1)
            for f in STAGE_FIELDS
            if abs(v3_rec[f] - v2_rec[f]) > V2_V3_DIVERGENCE_TOLERANCE_MIN
        }
        if not diffs:
            continue
        divergence[date] = {
            'v2': {f: v2_rec[f] for f in STAGE_FIELDS},
            'v3': {f: v3_rec[f] for f in STAGE_FIELDS},
            'diffs': diffs,
            'detected_at': now,
        }
        flagged_dates.append(date)

    return flagged_dates


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

    fresh_records = []
    raw_samples_by_date = {}
    for session in sessions:
        rec = build_record(session)
        if rec['total_min'] < MIN_SESSION_TOTAL_MIN:
            continue
        fresh_records.append(rec)
        raw_samples_by_date[rec['date']] = serialize_session(session)
    fresh_records.sort(key=lambda r: r['date'])

    print(f"\n本次raw檔算出 {len(fresh_records)} 夜（total_min >= {MIN_SESSION_TOTAL_MIN} 分鐘）")

    history = load_history()
    new_dates, changed_dates, unchanged_dates = merge_records(history, fresh_records, raw_samples_by_date)

    print(f"🆕 新增 {len(new_dates)} 夜：{', '.join(new_dates) or '（無）'}")
    print(f"= 無異動 {len(unchanged_dates)} 夜")
    if changed_dates:
        print(f"⚠ 異動 {len(changed_dates)} 夜（超過{CHANGE_TOLERANCE_MIN}分鐘容許誤差，已覆蓋並記錄）：")
        for entry in history['changelog'][-len(changed_dates):]:
            diff_txt = '、'.join(
                f"{f}: {d['old']}→{d['new']}（{d['delta']:+.1f}）"
                for f, d in entry['diffs'].items()
            )
            print(f"  {entry['date']}  {diff_txt}")
    else:
        print("⚠ 異動 0 夜")

    v2_by_date = load_v2_records()
    if v2_by_date:
        overlap = sorted(set(history['nights']) & set(v2_by_date))
        flagged = compare_v2_v3(history, v2_by_date)
        print(f"\nv2/v3交叉比對：{len(overlap)} 晚重疊日期")
        if flagged:
            print(f"⚠ {len(flagged)} 晚差距超過{V2_V3_DIVERGENCE_TOLERANCE_MIN}分鐘，值得留意：")
            for date in flagged:
                d = history['v2_v3_divergence'][date]
                diff_txt = '、'.join(f"{f}: v2={d['v2'][f]} v3={d['v3'][f]}（{v:+.1f}）" for f, v in d['diffs'].items())
                print(f"  {date}  {diff_txt}")
        else:
            print(f"= 重疊日期皆在容許誤差內，無系統性分歧")

    save_history(history)
    total_raw_samples = sum(len(n.get('raw_samples', [])) for n in history['nights'].values())
    print(f"\n歷史已存至 {HISTORY_PATH.name}（累計 {len(history['nights'])} 夜、"
          f"{total_raw_samples} 筆原始樣本，變更紀錄 {len(history['changelog'])} 筆，"
          f"檔案大小 {HISTORY_PATH.stat().st_size/1024:.1f}KB）")

    all_records = sorted(history['nights'].values(), key=lambda r: r['date'])
    # HTML畫圖不需要changelog等額外欄位，只留圖表用得到的欄位
    chart_records = [
        {k: r[k] for k in ('date', 'bedtime', 'wake', 'total_min',
                            'deep_min', 'rem_min', 'core_min', 'awake_min', 'efficiency')}
        for r in all_records
    ]

    if inject_html(chart_records):
        print(f"\n已寫入 {HTML_PATH}（圖表顯示累計全部 {len(chart_records)} 夜，"
              f"不再受Shortcut過去1週視窗限制）")


if __name__ == '__main__':
    main()
