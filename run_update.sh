#!/bin/bash
SRC="/Users/tinayu/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/Daily Sleep Update"
DEST="/Users/tinayu/sleep-dashboard/json_cache"
mkdir -p "$DEST"
rm -f "$DEST"/*.json "$DEST"/*.txt

# 觸發 iCloud 下載，等待最多 60 秒直到今天的檔案有實際內容（非空殼）
/usr/bin/brctl download "$SRC" 2>/dev/null || true
TODAY=$(date +%Y-%m-%d)
for i in $(seq 1 12); do
    TODAY_FILE=$(ls "$SRC"/*"$TODAY"* 2>/dev/null | head -1)
    if [ -n "$TODAY_FILE" ] && [ -s "$TODAY_FILE" ]; then
        echo "✓ 今日檔案已就緒（${i}×5s）"
        break
    fi
    # 若 stub 已出現但內容未下載，對該檔案再觸發一次下載
    [ -n "$TODAY_FILE" ] && /usr/bin/brctl download "$TODAY_FILE" 2>/dev/null || true
    echo "⏳ 等待 iCloud 同步... (${i}/12)"
    sleep 5
done

for f in "$SRC"/*.json "$SRC"/*.txt; do
    [ -f "$f" ] || continue
    fname=$(basename "$f")
    # 用暫存檔避免 iCloud stub 造成 dest 空檔殘留
    cat "$f" > "$DEST/$fname.tmp" 2>/dev/null
    if [ -s "$DEST/$fname.tmp" ]; then
        mv "$DEST/$fname.tmp" "$DEST/$fname"
        echo "✓ 複製 $fname"
    else
        rm -f "$DEST/$fname.tmp"
        /usr/bin/brctl download "$f" 2>/dev/null || true
        echo "⚠ 跳過 $fname（iCloud stub 尚未下載）"
    fi
done

python3 /Users/tinayu/sleep-dashboard/update_dashboard.py
