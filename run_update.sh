#!/bin/bash
SRC="/Users/tinayu/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/Daily Sleep Update"
DEST="/Users/tinayu/sleep-dashboard/json_cache"
mkdir -p "$DEST"

# 觸發整個資料夾下載
/usr/bin/brctl download "$SRC" 2>/dev/null || true

# 等待今天的檔案（最多 60 秒）
TODAY=$(date +%Y-%m-%d)
for i in $(seq 1 12); do
    TODAY_FILE=$(ls "$SRC"/*"$TODAY"* 2>/dev/null | head -1)
    if [ -n "$TODAY_FILE" ] && [ -s "$TODAY_FILE" ]; then
        echo "✓ 今日檔案已就緒（${i}×5s）"
        break
    fi
    [ -n "$TODAY_FILE" ] && /usr/bin/brctl download "$TODAY_FILE" 2>/dev/null || true
    echo "⏳ 等待 iCloud 同步... (${i}/12)"
    sleep 5
done

# 複製 iCloud 檔案到 cache（只補缺失或空白的，保留已有的）
for f in "$SRC"/*.json "$SRC"/*.txt; do
    [ -f "$f" ] || continue
    fname=$(basename "$f")
    cached="$DEST/$fname"

    # 已有非空 cache 就跳過，不重複讀 iCloud
    if [ -s "$cached" ]; then
        continue
    fi

    # 觸發單檔下載
    /usr/bin/brctl download "$f" 2>/dev/null || true

    cat "$f" > "$cached.tmp" 2>/dev/null
    if [ -s "$cached.tmp" ]; then
        mv "$cached.tmp" "$cached"
        echo "✓ 複製 $fname"
    else
        rm -f "$cached.tmp"
        echo "⚠ 跳過 $fname（iCloud stub 尚未下載）"
    fi
done

python3 /Users/tinayu/sleep-dashboard/update_dashboard.py

# 09-30新增：v3 migration monitor period排程，跟v2共用同一份run_update.sh
# 已經抓好的json_cache/sleep_raw_*.txt，不重複打iCloud。update_dashboard_v3.py
# 算完history.json後，update_dashboard_v3_live.py接手轉格式注入v3-live頁，
# 兩者各自獨立git commit+push（v2/v3互不注入鐵律：這裡只是共用排程時機，
# 不是共用計算邏輯）。v2本身的排程與計算完全不受這兩行影響。
python3 /Users/tinayu/sleep-dashboard/update_dashboard_v3.py
python3 /Users/tinayu/sleep-dashboard/update_dashboard_v3_live.py
