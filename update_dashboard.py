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
DASHBOARD_PATH = "/Users/tinayu/sleep-dashboard/sleep_dashboard.html"
GITHUB_REPO_DIR = "/Users/tinayu/sleep-dashboard"
# ────────────────────────────────────────────────────────────────────────

def clean_json_content(content):
    """移除 JSON 中可能導致解析錯誤的控制字元"""
    # 移除不可見字元，但保留換行與標準空白
    return "".join(c for c in content if c.isprintable() or c in "\n\r\t")

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

def parse_json_files():
    """讀取所有 JSON/TXT 檔案，轉成 summary 列表"""
    pattern = os.path.join(ICLOUD_FOLDER, "*.*")
    files = sorted(glob.glob(pattern))
    print(f"找到 {len(files)} 個資料檔案")

    summary = []
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

                if total_min < 60: continue

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
    return summary

# (其餘 update_html, git_push, main 函數保持不變，直接沿用你原有的即可)
