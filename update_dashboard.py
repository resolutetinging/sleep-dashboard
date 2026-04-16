#!/usr/bin/env python3
"""
Sleep Dashboard 自動更新腳本
每天由 Mac 排程執行，讀取 iCloud 的 HealthAutoExport JSON 檔案
重新生成 sleep_dashboard.html 並 push 到 GitHub
"""

import json
import os
import glob
import subprocess
from datetime import datetime, timedelta

# ─── 設定區（只需修改這裡）───────────────────────────────────────────────
ICLOUD_FOLDER = os.path.expanduser(
    "/Users/tinayu/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/Daily Sleep Update"
)
DASHBOARD_PATH = os.path.expanduser("~/sleep-dashboard/sleep_dashboard.html")
GITHUB_REPO_DIR = os.path.expanduser("~/sleep-dashboard")
# ────────────────────────────────────────────────────────────────────────


def parse_json_files():
    """讀取所有 HealthAutoExport JSON，轉成 summary 列表"""
    pattern = os.path.join(ICLOUD_FOLDER, "HealthAutoExport-*.json")
    files = sorted(glob.glob(pattern))
    print(f"找到 {len(files)} 個 JSON 檔案")

    summary = []
    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw = json.load(f)

            metrics = raw.get("data", {}).get("metrics", [])
            sleep_metric = next((m for m in metrics if m.get("name") == "sleep_analysis"), None)
            if not sleep_metric:
                continue

            for entry in sleep_metric.get("data", []):
                # 日期（取 date 欄位的日期部分）
                date_str = entry.get("date", "")[:10]  # "2026-04-10"
                if not date_str or date_str < "2026-01-01":
                    continue

                # 單位是 hr，轉成分鐘
                def hr2min(v):
                    try:
                        return round(float(v) * 60)
                    except:
                        return 0

                deep_min  = hr2min(entry.get("deep", 0))
                rem_min   = hr2min(entry.get("rem", 0))
                core_min  = hr2min(entry.get("core", 0))
                awake_min = hr2min(entry.get("awake", 0))
                total_min = deep_min + rem_min + core_min

                if total_min < 60:  # 排除太短的紀錄
                    continue

                # 入睡 / 起床時間
                def parse_time(s):
                    try:
                        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
                        return dt.strftime("%H:%M")
                    except:
                        return "00:00"

                bedtime = parse_time(entry.get("sleepStart", ""))
                wake    = parse_time(entry.get("sleepEnd", ""))

                # 睡眠效率
                total_in_bed = total_min + awake_min
                efficiency = round(total_min / total_in_bed * 100, 1) if total_in_bed > 0 else 100.0

                summary.append({
                    "date":       date_str,
                    "bedtime":    bedtime,
                    "wake":       wake,
                    "total_min":  total_min,
                    "deep_min":   deep_min,
                    "rem_min":    rem_min,
                    "core_min":   core_min,
                    "awake_min":  awake_min,
                    "efficiency": efficiency,
                })

        except Exception as e:
            print(f"  ⚠ 跳過 {os.path.basename(fpath)}: {e}")

    # 依日期排序、去重（同日取最後一筆）
    seen = {}
    for s in summary:
        seen[s["date"]] = s
    summary = sorted(seen.values(), key=lambda x: x["date"])
    print(f"解析完成：{len(summary)} 筆有效夜晚數據")
    return summary


def update_html(summary):
    """讀取現有 HTML，只替換 RAW 數據部分"""
    if not os.path.exists(DASHBOARD_PATH):
        print(f"❌ 找不到 dashboard 檔案：{DASHBOARD_PATH}")
        return False

    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # 找到 RAW data 的開頭與結尾位置
    marker_start = 'const RAW = '
    marker_end   = ';\n\nconst COLORS'

    idx_start = html.find(marker_start)
    idx_end   = html.find(marker_end)

    if idx_start == -1 or idx_end == -1:
        print("❌ 找不到 RAW 數據標記，請確認 dashboard HTML 格式正確")
        return False

    # 最近 90 天的數據保留 segments（空的，因為 Health Auto Export 沒有 segment 細節）
    # summary only 模式：detail 取最後 90 筆（無 segments）
    detail = [dict(d, segments=[]) for d in summary[-90:]]

    new_raw = json.dumps({"summary": summary, "detail": detail},
                         ensure_ascii=False, separators=(',', ':'))

    new_html = html[:idx_start + len(marker_start)] + new_raw + html[idx_end:]

    with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(new_html)

    last_date = summary[-1]["date"] if summary else "?"
    print(f"✅ HTML 更新完成，最新數據：{last_date}")
    return True


def git_push():
    """Commit 並 push 到 GitHub"""
    try:
        os.chdir(GITHUB_REPO_DIR)
        today = datetime.now().strftime("%Y-%m-%d")

        subprocess.run(["git", "add", "sleep_dashboard.html"], check=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True
        )
        if result.returncode == 0:
            print("ℹ️  沒有新變更，不需要 push")
            return

        subprocess.run(
            ["git", "commit", "-m", f"auto update: {today}"],
            check=True
        )
        subprocess.run(["git", "push"], check=True)
        print(f"✅ 已 push 到 GitHub")

    except subprocess.CalledProcessError as e:
        print(f"❌ Git 操作失敗：{e}")


if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"Sleep Dashboard 更新 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print('='*50)

    summary = parse_json_files()
    if not summary:
        print("❌ 沒有讀取到任何數據，中止")
        exit(1)

    if update_html(summary):
        git_push()

    print("完成\n")
