#!/bin/bash
# 10-07新增：log 輪替。update.log 從 04-11 起從未清理（685KB、13k 行），除錯時真正的錯誤被雜訊淹沒。
# 只保留最近 30 天，更舊的段落搬到 update_archive.log（gitignore）；update_error.log 只留最後 2000 行。
# launchd 的 stdout 指向舊檔，輪替後用 exec 重新以 append 開啟新的 update.log，避免寫進已被取代的檔案。
SD="${SD_OVERRIDE:-/Users/tinayu/sleep-dashboard}"  # SD_OVERRIDE 僅供測試用，預設行為不變
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
SRC="${SRC_OVERRIDE:-/Users/tinayu/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/Daily Sleep Update}"
DEST="$SD/json_cache"
mkdir -p "$DEST"
# 以下三個時間參數僅測試時用環境變數覆寫，預設值即正式行為
WAIT_TODAY_MAX="${WAIT_TODAY_MAX:-300}"   # 等今日檔「實際可讀」的上限（秒）
WAIT_STEP="${WAIT_STEP:-10}"              # 每輪間隔（秒）
COPY_RETRY_MAX="${COPY_RETRY_MAX:-120}"   # 複製階段所有重試共用的總時間上限（秒）

# 11-04新增：就緒判斷改為「實際可讀」。iCloud 尚未下載的 dataless 佔位檔 [ -s ] 也會回報完整
# 大小，但真的讀（head）會丟 Resource deadlock avoided，所以不能只看大小。
# 真實 iCloud 佔位檔的讀取可能阻塞到下載完成，macOS 沒有 timeout 指令，用 perl alarm 包逾時（逾時視為不可讀）。
tmo() { local t="$1"; shift; perl -e 'alarm shift; exec @ARGV' "$t" "$@"; }
READ_PROBE_TMO="${READ_PROBE_TMO:-15}"   # 就緒探測讀檔逾時（秒）
COPY_READ_TMO="${COPY_READ_TMO:-60}"     # 複製讀檔逾時（秒）
readable() { [ -s "$1" ] && tmo "$READ_PROBE_TMO" head -c 1 "$1" >/dev/null 2>&1; }

# 觸發整個資料夾下載
/usr/bin/brctl download "$SRC" 2>/dev/null || true

# 等待今天的檔案「可讀」（最多 WAIT_TODAY_MAX 秒；正本或「 2.txt」等重複副本任一可讀即可）
# 10-31 v2 封存：只等 v3 的 sleep_raw_TODAY*.txt（不碰 v2 的 sleep_TODAY.txt）
TODAY=$(date +%Y-%m-%d)
START_TS=$(date +%s)
READY=0; ROUND=0
while :; do
    ROUND=$((ROUND+1))
    EXIST=0
    for f in "$SRC"/sleep_raw_"$TODAY"*.txt "$SRC"/.sleep_raw_"$TODAY"*.txt.icloud; do
        [ -e "$f" ] || continue
        EXIST=1
        case "$f" in *.icloud) ;; *) readable "$f" && READY=1 ;; esac
        [ "$READY" = 1 ] && break
    done
    if [ "$READY" = 1 ]; then
        echo "✓ 今日檔案已就緒且可讀（第 ${ROUND} 輪，約 $(( $(date +%s) - START_TS )) 秒）"
        break
    fi
    ELAPSED=$(( $(date +%s) - START_TS ))
    if [ "$ELAPSED" -ge "$WAIT_TODAY_MAX" ]; then
        if [ "$EXIST" = 1 ]; then
            echo "⚠ 等待 ${ELAPSED} 秒仍放棄：今日檔已上傳到 iCloud，但 Mac 尚未下載完成（不可讀）"
        else
            echo "⚠ 等待 ${ELAPSED} 秒仍放棄：iCloud 尚未上傳今日檔（找不到 sleep_raw_${TODAY}*.txt）"
        fi
        break
    fi
    for f in "$SRC"/sleep_raw_"$TODAY"*.txt; do
        [ -e "$f" ] && /usr/bin/brctl download "$f" 2>/dev/null || true
    done
    if [ "$EXIST" = 1 ]; then
        echo "⏳ 今日檔已上傳、等待 Mac 下載完成... (第 ${ROUND} 輪，${ELAPSED}s/${WAIT_TODAY_MAX}s)"
    else
        echo "⏳ iCloud 尚未出現今日檔，等待上傳/同步... (第 ${ROUND} 輪，${ELAPSED}s/${WAIT_TODAY_MAX}s)"
    fi
    sleep "$WAIT_STEP"
done

# 複製 iCloud 檔案到 cache：缺失、空白，或 iCloud 版本比 cache 新時才複製
# 10-05修正：原本「已有非空 cache 就跳過」，Shortcut 同一天重新匯出（如 10-04 早上
# 先出 28KB、22:18 再出完整 31KB）時新版永遠進不了 cache，導致那晚資料漏掉。
# 11-04修正：讀取失敗（stub 尚未下載）的檔案有限次重試，所有重試共用 COPY_RETRY_MAX 總時間上限。
COPY_START=$(date +%s)
for f in "$SRC"/*.json "$SRC"/*.txt; do
    [ -f "$f" ] || continue
    fname=$(basename "$f")
    cached="$DEST/$fname"

    # 已有非空 cache 且 iCloud 版本沒有比較新，就跳過
    if [ -s "$cached" ] && [ ! "$f" -nt "$cached" ]; then
        continue
    fi

    TRY=0; OK=0
    while :; do
        TRY=$((TRY+1))
        # 觸發單檔下載
        /usr/bin/brctl download "$f" 2>/dev/null || true
        # 逾時被 alarm 殺掉時 cat 可能已寫出部分內容：必須同時看 exit code，否則殘缺檔會進 cache
        tmo "$COPY_READ_TMO" cat "$f" > "$cached.tmp" 2>/dev/null
        RC=$?
        if [ "$RC" -eq 0 ] && [ -s "$cached.tmp" ]; then OK=1; break; fi
        rm -f "$cached.tmp"
        [ $(( $(date +%s) - COPY_START )) -ge "$COPY_RETRY_MAX" ] && break
        [ "$TRY" -ge 6 ] && break
        sleep "$WAIT_STEP"
    done
    if [ "$OK" = 1 ]; then
        mv "$cached.tmp" "$cached"
        echo "✓ 複製 ${fname}（第 ${TRY} 次嘗試）"
    else
        rm -f "$cached.tmp"
        echo "⚠ 跳過 ${fname}（iCloud stub 尚未下載，已嘗試 ${TRY} 次）"
    fi
done

# 10-31 v2 封存：停跑 v2 管線（update_dashboard.py 保留不刪；回復點 git tag v2-final-20261031）
# python3 /Users/tinayu/sleep-dashboard/update_dashboard.py

# 09-30新增：v3 migration monitor period排程，跟v2共用同一份run_update.sh
# 已經抓好的json_cache/sleep_raw_*.txt，不重複打iCloud。update_dashboard_v3.py
# 算完history.json後，update_dashboard_v3_live.py接手轉格式注入v3-live頁，
# 兩者各自獨立git commit+push（v2/v3互不注入鐵律：這裡只是共用排程時機，
# 不是共用計算邏輯）。v2本身的排程與計算完全不受這兩行影響。
python3 "$SD/update_dashboard_v3.py"
# RU_SKIP_LIVE_PUSH=1 僅供測試：跳過會 commit/push 的 live 步驟與結尾補推
[ "${RU_SKIP_LIVE_PUSH:-}" = 1 ] && exit 0
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
