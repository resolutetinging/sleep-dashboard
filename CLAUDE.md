# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A personal sleep analytics dashboard. An iPhone Shortcut exports raw Apple Health sleep samples (`sleep_raw_YYYY-MM-DD.txt`) to iCloud; Python scripts on the Mac compute per-night stages and inject the data into self-contained HTML pages, which are committed and served via GitHub Pages.

**Since 2026-10-31 the v2 pipeline is archived. v3 is the only live pipeline.** Spec: `/Users/tinayu/Desktop/Claude Project/Spec/sleep-dashboard-spec-v1.0.md`.

## Files (don't confuse these)

- `sleep_dashboard_v3_live.html` — **the live dashboard.** Writes the 7 shared `sas_*` localStorage keys (`SAS_KEY_SUFFIX=''`) that SAS Hub, Daily Optimizer and the Control Center Guard read for 戰力.
- `index.html` — SAS Hub. No embedded data; reads `sas_*` from localStorage.
- `sleep_v3_history.json` — permanent per-night v3 results + raw samples, keyed by wake date. Merge rules: changes ≤3 min are rounding noise; a narrower raw-file time span never overwrites (`_raw_span()`).
- `sleep_v2_frozen_pre1001.json` — the only source of the 259 nights before 2026-10-01. `update_dashboard_v3_live.py` `load_summary()` merges it with v3 history by `V3_CUTOFF = "2026-10-01"`. **Never delete or regenerate it.**
- Archived (2026-10-31, banner on page, do not resume updating): `sleep_dashboard_v2.html` (v2 page, writes only `sas_*_v2` keys, data stops at 10-31), `sleep_dashboard_v3.html` (early v3 verification page), `update_dashboard.py` (v2 script, no longer called). Restore point: git tag `v2-final-20261031`.
- `archive/sleep_dashboard.html` — v1 snapshot, archived 2026-07-17.

## Pipeline

1. iPhone Shortcut writes `sleep_raw_DATE.txt` to `/Users/tinayu/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/Daily Sleep Update/`
2. `run_update.sh` waits up to 60 s for `sleep_raw_TODAY.txt`, copies iCloud files into `json_cache/` (skips stubs; re-copies when iCloud is newer)
3. `update_dashboard_v3.py` splits sessions (gap ≥90 min starts a new session; sessions <60 min are dropped), computes stages, merges into `sleep_v3_history.json`
4. `update_dashboard_v3_live.py` injects `const RAW` / `V3_NIGHTS` into `sleep_dashboard_v3_live.html`, commits and pushes via SSH (`~/.ssh/github_ed25519`) with post-push verification
5. End of `run_update.sh`: retries any unpushed commit up to 3 times (laptop sleeping mid-run is common; a "⏸" in the log is normal)

LaunchAgent `~/Library/LaunchAgents/com.sleep.dashboard.update.plist`: 09:30 and 22:00 plus `RunAtLoad`. Idempotent; no new data → no commit.

Manual run: `bash ~/sleep-dashboard/run_update.sh` (logs: `update.log`, `update_error.log`).

## Rules

- Do not hand-edit the injected `const RAW = …` block in any page.
- The disabled v2/v3 comparison (`load_v2_records()` / `compare_v2_v3()` in `update_dashboard_v3.py`) is kept for reference; existing `v2_v3_divergence` records in history are kept as-is.
- Git troubleshooting: `git_troubleshooting_sop.txt`.
