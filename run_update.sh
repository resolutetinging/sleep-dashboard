#!/bin/bash
SRC="/Users/tinayu/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/Daily Sleep Update"
DEST="/Users/tinayu/sleep-dashboard/json_cache"
mkdir -p "$DEST"
rm -f "$DEST"/*.json "$DEST"/*.txt

# 先觸發 iCloud 下載
/usr/bin/brctl download "$SRC" 2>/dev/null || true
sleep 5

for f in "$SRC"/*.json "$SRC"/*.txt; do
    [ -f "$f" ] || continue
    fname=$(basename "$f")
    cat "$f" > "$DEST/$fname" 2>/dev/null && echo "✓ 複製 $fname" || echo "⚠ 跳過 $fname（無法讀取）"
done

python3 /Users/tinayu/sleep-dashboard/update_dashboard.py
