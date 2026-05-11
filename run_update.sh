#!/bin/bash
SRC="/Users/tinayu/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/Daily Sleep Update"
DEST="/Users/tinayu/sleep-dashboard/json_cache"
mkdir -p "$DEST"
rm -f "$DEST"/*.json
for f in "$SRC"/*.json; do
    fname=$(basename "$f")
    cat "$f" > "$DEST/$fname"
done
python3 /Users/tinayu/sleep-dashboard/update_dashboard.py