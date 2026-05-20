# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A personal sleep analytics dashboard. Sleep data is exported from the iPhone via the **HealthAutoExport** app to an iCloud folder, then a Python script parses the JSON files and injects the data directly into a self-contained HTML file. That HTML file is committed to GitHub and served via GitHub Pages.

## Key commands

**Manually trigger a full update (parse data → update HTML → git push):**
```bash
python3 ~/sleep-dashboard/update_dashboard.py
```

**Run the shell wrapper (copies iCloud JSONs to local cache first, then runs the Python script):**
```bash
bash ~/sleep-dashboard/run_update.sh
```

**After editing `sleep_dashboard.html` manually, commit and push:**
```bash
cd ~/sleep-dashboard
git add sleep_dashboard.html
git commit -m "your message"
git push
```

## Data pipeline

1. HealthAutoExport app writes daily JSON files to:
   `/Users/tinayu/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/Daily Sleep Update/`
2. `run_update.sh` copies those files into `json_cache/`
3. `update_dashboard.py` reads all `.json`/`.txt` files from the iCloud folder, parses them, and overwrites the `const RAW = …` data block inside `sleep_dashboard.html`
4. The script then does `git add sleep_dashboard.html && git commit && git push`
5. GitHub Actions (`.github/workflows/static.yml`) deploys the updated HTML to GitHub Pages on every push to `main`

This runs automatically every day at **9:30 AM** via the macOS LaunchAgent at `~/Library/LaunchAgents/com.sleep.dashboard.update.plist`.

## Architecture of `sleep_dashboard.html`

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

When editing the dashboard's visuals or logic, only `sleep_dashboard.html` needs to change. Do not touch the `const RAW = …` block by hand — it is always overwritten by `update_dashboard.py`.

## Two supported JSON input formats

`update_dashboard.py` handles both:
- **HealthAutoExport format**: `raw.data.metrics` array; find the entry with `name == "sleep_analysis"`, then iterate its `data` array
- **Shortcut flattened format**: a single `{ "date": "…", "deep": …, … }` object at the top level

All time fields (e.g. `sleepStart`, `sleepEnd`) may be either `"2026-05-11T00:54:51"` or `"2026-05-11 00:54:51"`. Sleep values are in **hours** and converted to minutes by `hr2min()`. Records with fewer than 60 minutes of total sleep are skipped, as are dates before 2026-01-01.
