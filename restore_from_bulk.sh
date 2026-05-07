#!/bin/bash
# Restore json_cache from bulk Sleep_Analysis.json export
# Run this from the directory containing Sleep_Analysis.json

CACHE="/Users/tinayu/sleep-dashboard/json_cache"
mkdir -p "$CACHE"

python3 << 'EOF'
import json, os
from collections import defaultdict

# Find the file
import glob
candidates = glob.glob(os.path.expanduser("~/Downloads/Sleep_Analysis*.json")) + \
             glob.glob(os.path.expanduser("~/Desktop/Sleep_Analysis*.json"))

if not candidates:
    print("❌ 找不到 Sleep_Analysis.json，請確認檔案在 Downloads 或 Desktop")
    exit(1)

fpath = candidates[0]
print(f"✓ 找到檔案：{fpath}")

with open(fpath, 'r') as f:
    raw = json.load(f)

entries = raw['data']['metrics'][0]['data']
nights = defaultdict(list)
for e in entries:
    nights[e['endDate'][:10]].append(e)

out_dir = '/Users/tinayu/sleep-dashboard/json_cache'
count = 0
for date, segs in nights.items():
    payload = {"data": {"metrics": [{"name": "sleep_analysis", "units": "hr", "data": segs}]}}
    with open(os.path.join(out_dir, f"HealthAutoExport-{date}.json"), 'w') as f:
        json.dump(payload, f, ensure_ascii=False)
    count += 1

print(f"✅ 已建立 {count} 個 JSON 檔案（{sorted(nights.keys())[0]} 至 {sorted(nights.keys())[-1]}）")
EOF

echo ""
echo "現在執行更新："
python3 /Users/tinayu/sleep-dashboard/update_dashboard.py
