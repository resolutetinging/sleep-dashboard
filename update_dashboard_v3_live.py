#!/usr/bin/env python3
"""
Sleep Dashboard v3-live 更新腳本（09-30建置，migration monitor period用）

設計原則：不重新解析原始樣本——那是update_dashboard_v3.py的工作，這裡只單純
讀取它已經算好、驗證過的sleep_v3_history.json，轉成跟sleep_dashboard_v2.html
完全相同的RAW格式（summary/detail），注入sleep_dashboard_v3_live.html
（v2頁面的逐位元組複製，下游所有圖表/戰力公式/localStorage寫入邏輯完全不變，
只換餵進去的資料來源）。避免同一套解析邏輯維護兩份。

10/1-15為migration monitor period：v2（sleep_dashboard_v2.html）照舊跑它
自己獨立的排程與計算，完全不受這支腳本影響；update_dashboard_v3.py裡的
compare_v2_v3()持續拿v2/v3各自獨立算出的數字互相比對，是監控期的比對基準。
10/15若v3狀況良好，才會決定讓下游（SAS Hub等）改讀這份v3-live資料、
v2進入封存。

必須排在update_dashboard_v3.py之後執行（依賴它先把history.json更新好），
建議接在run_update.sh現有排程尾端呼叫。
"""

import json
import os
import subprocess
from datetime import datetime

HISTORY_PATH = "/Users/tinayu/sleep-dashboard/sleep_v3_history.json"
DASHBOARD_V3_LIVE_PATH = "/Users/tinayu/sleep-dashboard/sleep_dashboard_v3_live.html"
GITHUB_REPO_DIR = "/Users/tinayu/sleep-dashboard"


def load_summary():
    """把sleep_v3_history.json的nights轉成v2格式的summary陣列。
    bedtime/wake從v3的完整ISO時間戳轉成v2慣用的HH:MM字串（v2下游JS
    只認HH:MM，不是完整timestamp），deep/rem/core/awake/efficiency直接沿用。"""
    with open(HISTORY_PATH, encoding='utf-8') as f:
        history = json.load(f)
    nights = history.get('nights', {})
    summary = []
    for date in sorted(nights.keys()):
        n = nights[date]
        bedtime_dt = datetime.fromisoformat(n['bedtime'])
        wake_dt = datetime.fromisoformat(n['wake'])
        summary.append({
            'date': date,
            'bedtime': bedtime_dt.strftime('%H:%M'),
            'wake': wake_dt.strftime('%H:%M'),
            'total_min': n['total_min'],
            'deep_min': n['deep_min'],
            'rem_min': n['rem_min'],
            'core_min': n['core_min'],
            'awake_min': n['awake_min'],
            'efficiency': n['efficiency'],
        })
    return summary


def update_html(summary):
    """比照update_dashboard.py的update_html()，同一套RAW格式跟注入方式，
    只是目標檔案換成sleep_dashboard_v3_live.html。"""
    detail = [dict(d, segments=[]) for d in summary[-90:]]
    new_raw = json.dumps({"summary": summary, "detail": detail}, ensure_ascii=False, separators=(',', ':'))
    marker_start = 'const RAW = '
    marker_end = ';\n\nconst COLORS'
    if not os.path.exists(DASHBOARD_V3_LIVE_PATH):
        print(f"❌ 找不到檔案：{DASHBOARD_V3_LIVE_PATH}")
        return False
    with open(DASHBOARD_V3_LIVE_PATH, 'r', encoding='utf-8') as f:
        html = f.read()
    idx_start = html.find(marker_start)
    idx_end = html.find(marker_end)
    if idx_start == -1 or idx_end == -1:
        print(f"❌ 找不到 RAW 標記：{os.path.basename(DASHBOARD_V3_LIVE_PATH)}")
        return False
    new_html = html[:idx_start + len(marker_start)] + new_raw + html[idx_end:]
    with open(DASHBOARD_V3_LIVE_PATH, 'w', encoding='utf-8') as f:
        f.write(new_html)
    print(f"✅ {os.path.basename(DASHBOARD_V3_LIVE_PATH)} 更新完成")
    last_date = summary[-1]['date'] if summary else '?'
    print(f"   最新數據：{last_date}")
    return True


def git_push():
    """比照update_dashboard.py的git_push()同一套SSH/timeout/push後驗證機制，
    但一次commit三個v3相關檔案（history.json＋純驗證頁＋這份v3-live頁），
    因為這支腳本固定排在update_dashboard_v3.py之後執行，一起commit最單純。"""
    try:
        os.chdir(GITHUB_REPO_DIR)
        today = datetime.now().strftime("%Y-%m-%d")
        subprocess.run(
            ["git", "add", "sleep_v3_history.json", "sleep_dashboard_v3.html", "sleep_dashboard_v3_live.html"],
            check=True
        )
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if result.returncode == 0:
            print("ℹ️  v3相關檔案無新變更，略過 commit")
            return
        subprocess.run(["git", "commit", "-m", f"auto update: {today} (v3)"], check=True)

        ssh_env = dict(os.environ)
        ssh_env["GIT_SSH_COMMAND"] = (
            "ssh -i /Users/tinayu/.ssh/github_ed25519 -o IdentitiesOnly=yes "
            "-o ConnectTimeout=15 -o ServerAliveInterval=5 -o ServerAliveCountMax=3"
        )
        push_url = "origin"
        GIT_TIMEOUT = 30

        stash_result = subprocess.run(['git', 'stash'], capture_output=True, text=True, timeout=GIT_TIMEOUT)
        stashed = 'No local changes' not in stash_result.stdout
        try:
            subprocess.run(['git', 'pull', '--rebase', push_url, 'main'], check=True, env=ssh_env, timeout=GIT_TIMEOUT)
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
    print(f"Sleep Dashboard v3-live 更新 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print('='*50)
    summary = load_summary()
    if summary:
        if update_html(summary):
            git_push()
    else:
        print("⚠ sleep_v3_history.json 目前無夜晚記錄，略過")
    print("完成\n")
