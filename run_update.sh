#!/bin/bash
# 10-07新增：log 輪替。update.log 從 04-11 起從未清理（685KB、13k 行），除錯時真正的錯誤被雜訊淹沒。
# 只保留最近 30 天，更舊的段落搬到 update_archive.log（gitignore）；update_error.log 只留最後 2000 行。
# launchd 的 stdout 指向舊檔，輪替後用 exec 重新以 append 開啟新的 update.log，避免寫進已被取代的檔案。
SD=/Users/tinayu/sleep-dashboard
LOG="$SD/update.log"; ARCH="$SD/update_archive.log"; ERR="$SD/update_error.log"
CUTOFF=$(date -v-30d +%Y-%m-%d)
if [ -f "$LOG" ]; then
  CUT=$(awk -v c="$CUTOFF" '
    /run_update 開始 [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/ || /更新 — [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/ {
      match($0,/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/); d=substr($0,RSTART,RLENGTH)
      if (d>=c) { if ($0 ~ /run_update 開始/) print NR; else print (NR>2?NR-2:1); exit }
    }' "$LOG")
  if [ -n "$CUT" ] && [ "$CUT" -gt 1 ]; then
    head -n $((CUT-1)) "$LOG" >> "$ARCH"
    tail -n +"$CUT" "$LOG" > "$LOG.new" && mv "$LOG.new" "$LOG"
  fi
fi
if [ -f "$ERR" ] && [ "$(wc -l < "$ERR")" -gt 2000 ]; then
  tail -n 2000 "$ERR" > "$ERR.new" && mv "$ERR.new" "$ERR"
fi
exec >>"$LOG" 2>>"$ERR"
echo ""
echo "▶ run_update 開始 $(date '+%Y-%m-%d %H:%M')"
# 10-06新增：Mac 休眠時 macOS 會短暫背景喚醒（DarkWake，常只醒 2–20 秒）補跑錯過的排程，
# 網路還沒起來就又睡回去，造成 git push 失敗（09-05後 140 次中 42 次）。開頭先確認連得到
# GitHub，連不到就整次略過、不產生半套 commit，交給下一個排程時段處理。
NET_OK=0
for i in 1 2 3; do
    if /usr/bin/curl -s -m 5 -o /dev/null "${NET_CHECK_URL:-https://github.com}"; then NET_OK=1; break; fi
    sleep 5
done
if [ "$NET_OK" != 1 ]; then
    echo "⏸ $(date '+%Y-%m-%d %H:%M') 網路未就緒（可能是休眠中的背景喚醒），本次略過，交給下一個排程時段"
    exit 0
fi
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

# 複製 iCloud 檔案到 cache：缺失、空白，或 iCloud 版本比 cache 新時才複製
# 10-05修正：原本「已有非空 cache 就跳過」，Shortcut 同一天重新匯出（如 10-04 早上
# 先出 28KB、22:18 再出完整 31KB）時新版永遠進不了 cache，導致那晚資料漏掉。
for f in "$SRC"/*.json "$SRC"/*.txt; do
    [ -f "$f" ] || continue
    fname=$(basename "$f")
    cached="$DEST/$fname"

    # 已有非空 cache 且 iCloud 版本沒有比較新，就跳過
    if [ -s "$cached" ] && [ ! "$f" -nt "$cached" ]; then
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

# 10-07新增：結尾補推。網路前置檢查擋不住「檢查時有網路、跑到一半又睡著」（10-06 22:38 案例），
# 任何一步推送失敗留下的本機 commit，在這裡最多重試 3 次；仍失敗就留給下一個排程時段。
cd "$SD" || exit 0
if git status -sb | head -1 | grep -q 'ahead'; then
  PUSHED=0
  for i in 1 2 3; do
    if git push -q origin main 2>/dev/null; then echo "✅ 結尾補推成功（第 ${i} 次）"; PUSHED=1; break; fi
    sleep 10
  done
  [ "$PUSHED" = 1 ] || echo "⏸ 結尾補推失敗，仍有未推送 commit，交給下一個排程時段"
fi
