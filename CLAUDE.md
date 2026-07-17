# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A personal sleep analytics dashboard. Sleep data is exported from the iPhone via the **HealthAutoExport** app to an iCloud folder, then a Python script parses the JSON files and injects the data directly into a self-contained HTML file. That HTML file is committed to GitHub and served via GitHub Pages.

**⚠️ Three-file split (updated 2026-07-17, don't confuse these):**
- `index.html` — the actual page served at the repo root on GitHub Pages ("SAS Hub"). Contains **no embedded RAW data**; reads sleep stats purely from `localStorage` (`sas_sleep_latest`, `sas_combat_*`), which gets populated by opening `sleep_dashboard_v2.html`.
- `sleep_dashboard_v2.html` — the file with the embedded `const RAW = …` data block. This is the one `update_dashboard.py` writes to and the one that matters for data pipeline work.
- `archive/sleep_dashboard.html` — the original (v1) version of the RAW-data page. **Archived 2026-07-17**: nothing references it anymore, `update_dashboard.py` no longer writes or commits it. Kept only as a historical snapshot; do not resume updating it.

## Key commands

**Manually trigger a full update (parse data → update HTML → git push):**
```bash
python3 ~/sleep-dashboard/update_dashboard.py
```

**Run the shell wrapper (copies iCloud JSONs to local cache first, then runs the Python script):**
```bash
bash ~/sleep-dashboard/run_update.sh
```

**After editing `sleep_dashboard_v2.html` manually, commit and push:**
```bash
cd ~/sleep-dashboard
git add sleep_dashboard_v2.html
git commit -m "your message"
git push
```

## Data pipeline

1. HealthAutoExport app writes daily JSON files to:
   `/Users/tinayu/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/Daily Sleep Update/`
2. `run_update.sh` copies those files into `json_cache/`
3. `update_dashboard.py` reads all `.json`/`.txt` files from the iCloud folder, parses them, and overwrites the `const RAW = …` data block inside `sleep_dashboard_v2.html`
4. The script then commits and pushes to the `origin` remote via SSH, with a post-push verification step (fetch + compare HEAD) added 2026-07-17 after a silent-push-failure incident
5. GitHub Pages serves the repo directly on every push to `main` (no separate build step)

This runs automatically via the macOS LaunchAgent at `~/Library/LaunchAgents/com.sleep.dashboard.update.plist`. As of 2026-07-17 it fires at four times a day (09:30 / 13:00 / 18:00 / 22:00) plus on every login/reload (`RunAtLoad`), so a missed run (laptop asleep) gets caught up later the same day. The underlying script is idempotent (skips the commit if there's no new data), so multiple runs per day are harmless.

## Architecture of `sleep_dashboard_v2.html`

The dashboard is a **single self-contained HTML file** — all CSS, JavaScript, chart logic, and data live inside it. Chart.js (v4.4.0) is loaded from a CDN.

The data injection point the Python script targets:
```
const RAW = {…JSON…};

const COLORS
```

The `RAW` object has two keys:
- `summary` — full history array (all nights), used for trend charts
- `detail` — last 90 nights (same records but with an empty `segments` array added)

Each record: `{ date, bedtime, wake, total_min, deep_min, rem_min, core_min, awake_min, efficiency }`

When editing the dashboard's visuals or logic, only `sleep_dashboard_v2.html` needs to change. Do not touch the `const RAW = …` block by hand — it is always overwritten by `update_dashboard.py`.

## Two supported JSON input formats

`update_dashboard.py` handles both:
- **HealthAutoExport format**: `raw.data.metrics` array; find the entry with `name == "sleep_analysis"`, then iterate its `data` array
- **Shortcut flattened format**: a single `{ "date": "…", "deep": …, … }` object at the top level

All time fields (e.g. `sleepStart`, `sleepEnd`) may be either `"2026-05-11T00:54:51"` or `"2026-05-11 00:54:51"`. Sleep values are in **hours** and converted to minutes by `hr2min()`. Records with fewer than 60 minutes of total sleep are skipped, as are dates before 2026-01-01.
