#!/usr/bin/env python3
"""
Sleep Dashboard 自動更新腳本
每天由 Mac 排程執行，讀取 iCloud 的 HealthAutoExport JSON 檔案
支持原始 HealthAutoExport 格式與 Shortcut 扁平化格式
"""

import json
import os
import glob
import subprocess
import re
from datetime import datetime, timedelta

# ─── 設定區（只需修改這裡）───────────────────────────────────────────────
ICLOUD_FOLDER = os.path.expanduser(
    "/Users/tinayu/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/Daily Sleep Update"
)
# 優先讀本機 cache（由 run_update.sh 複製而來，避免 iCloud EAGAIN）
JSON_CACHE = "/Users/tinayu/sleep-dashboard/json_cache"
DATA_FOLDER = JSON_CACHE if os.path.isdir(JSON_CACHE) and os.listdir(JSON_CACHE) else ICLOUD_FOLDER
DASHBOARD_V2_PATH = "/Users/tinayu/sleep-dashboard/sleep_dashboard_v2.html"
# 舊版 sleep_dashboard.html（v1）已於 2026-07-17 archive 至 archive/，
# 沒有任何頁面引用它，不再自動更新，移到 archive/ 保留當歷史快照
GITHUB_REPO_DIR   = "/Users/tinayu/sleep-dashboard"
# 2026-08-09：0值資料被靜默continue沒人發現過（8/8事件），近期0值改用本機通知提醒，
# 這個狀態檔記錄「已經通知過的日期」避免LaunchAgent一天跑4次重複跳通知
ZERO_ALERT_STATE_PATH = "/Users/tinayu/sleep-dashboard/.zero_data_alerted.json"
# ────────────────────────────────────────────────────────────────────────

def clean_json_content(content):
    """移除 JSON 中可能導致解析錯誤的控制字元"""
    # 移除不可見字元，但保留換行與標準空白
    return re.sub(r"[\x00-\x1F\x7F]", "", content)

def hr2min(v):
    """單位是 hr，轉成分鐘"""
    try:
        return round(float(v) * 60)
    except:
        return 0

def parse_time(s):
    """解析入睡/起床時間字串"""
    if not s or not isinstance(s, str):
        return "00:00"
    s = s.strip()
    try:
        # 處理 T 分隔格式: 2026-05-11T00:54:51
        if "T" in s:
            dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        # 處理標準空白格式: 2026-05-11 00:54:51
        else:
            dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%H:%M")
    except:
        return "00:00"

def load_alerted_dates():
    try:
        with open(ZERO_ALERT_STATE_PATH, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_alerted_dates(dates):
    try:
        with open(ZERO_ALERT_STATE_PATH, "w") as f:
            json.dump(sorted(dates), f)
    except Exception:
        pass

def notify_zero_data(dates):
    """近期（今天/昨天）睡眠資料是0值/未同步時本機通知提醒；已通知過的日期不重複跳"""
    if not dates:
        return
    alerted = load_alerted_dates()
    new_dates = [d for d in dates if d not in alerted]
    if not new_dates:
        return
    msg = "、".join(new_dates) + " 睡眠資料是0值，iCloud可能還沒同步完成，建議稍後重跑 run_update.sh 或手動確認"
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{msg}" with title "⚠️ Sleep Dashboard 資料異常" sound name "Basso"'],
            timeout=10
        )
    except Exception as e:
        print(f"  ⚠ 通知發送失敗：{e}")
    save_alerted_dates(alerted | set(new_dates))

def parse_json_files():
    """讀取所有 JSON/TXT 檔案，轉成 summary 列表"""
    pattern = os.path.join(DATA_FOLDER, "*.*")
    files = sorted(glob.glob(pattern))
    print(f"找到 {len(files)} 個資料檔案")

    summary = []
    zero_alert_dates = []
    cutoff_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    for fpath in files:
        # 只處理 .json 和 .txt
        if not (fpath.endswith(".json") or fpath.endswith(".txt")):
            continue

        try:
            # 使用 utf-8-sig 自動處理 BOM 頭
            with open(fpath, "r", encoding="utf-8-sig") as f:
                content = f.read()
                clean_raw = clean_json_content(content)
                raw = json.loads(clean_raw)

            entries = []
            # --- 模式 A: 原始 HealthAutoExport 格式 (多層級) ---
            if isinstance(raw, dict) and "data" in raw and "metrics" in raw["data"]:
                metrics = raw.get("data", {}).get("metrics", [])
                sleep_metric = next((m for m in metrics if m.get("name") == "sleep_analysis"), None)
                if sleep_metric:
                    entries = sleep_metric.get("data", [])

            # --- 模式 B: Shortcut 扁平化格式 (直接是大括號) ---
            elif isinstance(raw, dict) and "date" in raw:
                entries = [raw]

            # 開始解析提取出的 entries
            for entry in entries:
                date_str = entry.get("date", "").strip()[:10]
                if not date_str or date_str < "2026-01-01":
                    continue

                deep_min  = hr2min(entry.get("deep", 0))
                rem_min   = hr2min(entry.get("rem", 0))
                core_min  = hr2min(entry.get("core", 0))
                awake_min = hr2min(entry.get("awake", 0))
                total_min = deep_min + rem_min + core_min

                if total_min < 60:
                    if date_str >= cutoff_str:
                        zero_alert_dates.append(date_str)
                    continue

                bedtime = parse_time(entry.get("sleepStart", ""))
                wake    = parse_time(entry.get("sleepEnd", ""))

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

    # 去重與排序
    seen = {}
    for s in summary:
        seen[s["date"]] = s
    summary = sorted(seen.values(), key=lambda x: x["date"])
    print(f"解析完成：{len(summary)} 筆有效夜晚數據")
    notify_zero_data(sorted(set(zero_alert_dates)))
    return summary

# (其餘 update_html, git_push, main 函數保持不變，直接沿用你原有的即可)

def update_html(summary):
    """讀取現有 HTML，只替換 RAW 數據部分（同時更新現行版與 v2）"""
    detail = [dict(d, segments=[]) for d in summary[-90:]]
    new_raw = json.dumps({"summary": summary, "detail": detail}, ensure_ascii=False, separators=(',', ':'))
    marker_start = 'const RAW = '
    marker_end   = ';\n\nconst COLORS'
    success = False
    for path in [DASHBOARD_V2_PATH]:
        if not os.path.exists(path):
            print(f"⚠  找不到檔案，略過：{os.path.basename(path)}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        idx_start = html.find(marker_start)
        idx_end   = html.find(marker_end)
        if idx_start == -1 or idx_end == -1:
            print(f"❌ 找不到 RAW 標記：{os.path.basename(path)}")
            continue
        new_html = html[:idx_start + len(marker_start)] + new_raw + html[idx_end:]
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_html)
        print(f"✅ {os.path.basename(path)} 更新完成")
        success = True
    if success:
        last_date = summary[-1]["date"] if summary else "?"
        print(f"   最新數據：{last_date}")
    return success

def git_push():
    """Commit 並 push 到 GitHub"""
    try:
        os.chdir(GITHUB_REPO_DIR)
        today = datetime.now().strftime("%Y-%m-%d")
        subprocess.run(["git", "add", "sleep_dashboard_v2.html"], check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if result.returncode == 0:
            print("ℹ️  HTML 無新變更，略過 commit")
        else:
            subprocess.run(["git", "commit", "-m", f"auto update: {today}"], check=True)

        # 2026-07-07 改走 SSH key（Git Push SOP：本機一律 SSH，禁 PAT 嵌 URL）
        # 舊機制（~/.sleep_dashboard_pat 明文 PAT 嵌 HTTPS URL）於 PAT 輪替後失效且不安全
        # 2026-07-19：加 ConnectTimeout/ServerAlive，網路卡住時讓 SSH 自己斷線，
        # 不要無限期掛著（見下方 GIT_TIMEOUT 註解，此為第一層防線）
        ssh_env = dict(os.environ)
        ssh_env["GIT_SSH_COMMAND"] = (
            "ssh -i /Users/tinayu/.ssh/github_ed25519 -o IdentitiesOnly=yes "
            "-o ConnectTimeout=15 -o ServerAliveInterval=5 -o ServerAliveCountMax=3"
        )
        # 2026-07-17：改用已設定好的 origin（跟寫死網址指向同一個repo），
        # 寫死完整網址 push 不會更新本機 origin/main 追蹤紀錄，導致每天 log 都誤報「ahead of origin」
        push_url = "origin"
        # 2026-07-19：git pull/push/fetch 曾在 SSH 連線卡住時無限期掛住（無 timeout），
        # 導致 launchd 認定上一次還在跑而跳過後續所有排程時段，卡了超過24小時都沒人發現。
        # GIT_TIMEOUT 是第二層防線：即使 SSH 自己的 ConnectTimeout 沒生效，Python 這層也會
        # 強制中斷並拋出 TimeoutExpired，讓外層 except 印出❌讓腳本正常結束，不再永久卡住。
        GIT_TIMEOUT = 30

        stash_result = subprocess.run(['git', 'stash'], capture_output=True, text=True, timeout=GIT_TIMEOUT)
        stashed = 'No local changes' not in stash_result.stdout
        try:
            subprocess.run(['git', 'pull', '--rebase', push_url, 'main'], check=True, env=ssh_env, timeout=GIT_TIMEOUT)
            # 2026-07-17：push 指令回傳 0 不保證真的送達 GitHub（2026-07-12 曾發生 push 回報成功
            # 但 origin 實際沒收到，連續好幾天靜默沒被發現）。push 完一律 fetch 遠端最新 HEAD
            # 跟本機 HEAD 比對，對不上就重試一次；兩次都對不上才視為真失敗，丟例外讓下面的
            # except 印出 ❌（不再無條件印✅）。
            local_head = None
            for attempt in range(2):
                subprocess.run(['git', 'push', push_url, 'main'], check=True, env=ssh_env, timeout=GIT_TIMEOUT)
                subprocess.run(['git', 'fetch', push_url, 'main'], check=True, env=ssh_env, timeout=GIT_TIMEOUT)
                local_head = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True, timeout=GIT_TIMEOUT).stdout.strip()
                remote_head = subprocess.run(['git', 'rev-parse', 'FETCH_HEAD'], capture_output=True, text=True, check=True, timeout=GIT_TIMEOUT).stdout.strip()
                if local_head == remote_head:
                    break
                print(f"⚠️ push 後驗證不一致（本機 {local_head[:7]} ≠ 遠端 {remote_head[:7]}），重試中…")
            else:
                raise RuntimeError(f"push 驗證失敗：重試後本機仍與遠端不一致（本機 {local_head[:7] if local_head else '?'}）")
        finally:
            if stashed:
                subprocess.run(['git', 'stash', 'pop'], check=False, timeout=GIT_TIMEOUT)
        print(f"✅ 已 push 到 GitHub 並驗證成功")
    except Exception as e:
        print(f"❌ Git 操作失敗：{e}")

if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"Sleep Dashboard 更新 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print('='*50)
    summary = parse_json_files()
    if summary:
        if update_html(summary):
            git_push()
    print("完成\n")
