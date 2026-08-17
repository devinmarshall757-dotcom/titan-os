# Operations Script Audit
Generated: 2026-08-16

## Summary

On the Mac repo (`/Users/devinmarshall/titan/`), all operational scripts live under
`scripts/` and are tracked in git. The mini PC (`C:\titan\`) has both the tracked
`scripts\` copies (pulled via `git pull`) and **untracked root-level copies** that
were created before the `scripts\` directory existed.

**The untracked root copies are the operational risk.** Windows Task Scheduler and
`run_daily.bat` on the mini PC likely reference `C:\titan\permit_scraper.py` (root),
not `C:\titan\scripts\permit_scraper.py`. Since the root copies are untracked, they
receive no git updates and will silently diverge.

---

## File Inventory

| File | Root (C:\titan\) | scripts\ (tracked) | Status |
|------|----------|-------------|--------|
| permit_scraper.py | Yes — untracked | Yes — tracked | **DIVERGE RISK** |
| storm_scraper.py | Yes — untracked | Yes — tracked | **DIVERGE RISK** |
| task_poller.py | Yes — untracked | Yes — tracked | **DIVERGE RISK** |
| dubuque_permit_scraper.py | Yes — untracked | Yes — tracked | **DIVERGE RISK** |
| council_bluffs_permit_scraper.py | Yes — untracked | Yes — tracked | **DIVERGE RISK** |
| neighborhood_scorer.py | Yes — untracked | **NOT IN SCRIPTS/** | MISSING — task_poller will fail if queued |

---

## Which Files Are Called by Task Scheduler / run_daily.bat

`run_daily.bat` (untracked, root of mini PC) calls:
- `C:\titan\permit_scraper.py` — the **untracked root copy**

`scripts\task_poller.py` (tracked) calls via its SCRIPTS allowlist:
- `C:\titan\scripts\permit_scraper.py`
- `C:\titan\scripts\storm_scraper.py`
- `C:\titan\scripts\neighborhood_scorer.py` ← **file does not exist**
- `C:\titan\scripts\dubuque_permit_scraper.py`
- `C:\titan\scripts\council_bluffs_permit_scraper.py`

**Divergence**: `run_daily.bat` runs the untracked root copy. Any fix committed to
`scripts\permit_scraper.py` will NOT be picked up by the bat file until the bat file
is updated to point at the scripts\ copy.

---

## Differences Between Root and scripts\ Copies

The Mac repo has no root copies (they are on the mini PC only). The differences are
inferred from the git history and the tracked `scripts\` versions:

| File | Known Difference |
|------|-----------------|
| permit_scraper.py | Root copy uses `load_dotenv()` without explicit path; scripts\ copy likely identical or very close — confirm with `diff` on mini PC |
| storm_scraper.py | Same as above |
| task_poller.py | Root copy may use an older SCRIPTS allowlist (predating scripts\ directory) |
| dubuque_permit_scraper.py | Unknown — compare on mini PC |
| council_bluffs_permit_scraper.py | Unknown — compare on mini PC |

**Run this on the mini PC to confirm:**
```powershell
diff C:\titan\permit_scraper.py C:\titan\scripts\permit_scraper.py
diff C:\titan\storm_scraper.py C:\titan\scripts\storm_scraper.py
diff C:\titan\task_poller.py C:\titan\scripts\task_poller.py
diff C:\titan\dubuque_permit_scraper.py C:\titan\scripts\dubuque_permit_scraper.py
diff C:\titan\council_bluffs_permit_scraper.py C:\titan\scripts\council_bluffs_permit_scraper.py
```

---

## Canonical Operational Entry Point

The canonical, tracked operational entry point is `scripts\task_poller.py`.

All scripts are called through its allowlist. Task Scheduler should be configured to
run the task poller as the single scheduled process, rather than calling individual
scripts directly.

**One-liner to start the task poller:**
```
C:\titan\venv\Scripts\python.exe C:\titan\scripts\task_poller.py
```

---

## Migration Plan (Manual — Do Not Apply Automatically)

### Step 1: Verify differences on the mini PC
```powershell
diff C:\titan\permit_scraper.py C:\titan\scripts\permit_scraper.py
```
If identical: safe to proceed. If different: review changes and decide which is correct.

### Step 2: Back up root copies before any change
```powershell
mkdir C:\titan\backup_root_scripts_20260816
copy C:\titan\permit_scraper.py C:\titan\backup_root_scripts_20260816\
copy C:\titan\storm_scraper.py C:\titan\backup_root_scripts_20260816\
copy C:\titan\task_poller.py C:\titan\backup_root_scripts_20260816\
copy C:\titan\dubuque_permit_scraper.py C:\titan\backup_root_scripts_20260816\
copy C:\titan\council_bluffs_permit_scraper.py C:\titan\backup_root_scripts_20260816\
```

### Step 3: Update run_daily.bat to call the tracked scripts\ copy
Current (do not change automatically):
```bat
C:\titan\venv\Scripts\python.exe C:\titan\permit_scraper.py
```
Change to:
```bat
C:\titan\venv\Scripts\python.exe C:\titan\scripts\permit_scraper.py
```

### Step 4: Update Windows Task Scheduler if it points to root copies
Open Task Scheduler → find Titan tasks → update action to point at `scripts\` copies.

### Step 5: Verify the task poller is scheduled (not just run_daily.bat)
The task poller polls Supabase for queued tasks, which is how Mac Claude dispatches
work to the mini PC. Ensure it is running as a scheduled or persistent service.

### Rollback
If anything breaks, restore from the backup:
```powershell
copy C:\titan\backup_root_scripts_20260816\permit_scraper.py C:\titan\permit_scraper.py
```
And revert run_daily.bat to its original content.

---

## Missing: neighborhood_scorer.py

`scripts\task_poller.py` has `neighborhood_scorer` in its SCRIPTS allowlist, but
`C:\titan\scripts\neighborhood_scorer.py` does not exist in the repo.

**Impact**: If a task with `script: "neighborhood_scorer"` is queued in Supabase,
the poller will return `"unknown script: neighborhood_scorer"` and mark the task
as error. No actual harm — the allowlist blocks execution safely.

**Resolution**: Either create `scripts\neighborhood_scorer.py` or remove
`neighborhood_scorer` from the SCRIPTS allowlist in `scripts\task_poller.py`.

---

## Schema / Environment Conventions

All tracked scripts under `scripts\` share:
- `load_dotenv("C:/titan/.env")` — explicit path, works on Windows
- `SUPABASE_URL = os.environ["SUPABASE_URL"]` — required env var
- `SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]` — service role key, never logged
- Output: stdout for progress, stderr for errors; no credentials in any output
- All DB writes use `Prefer: resolution=ignore-duplicates,return=minimal` to be idempotent

---

## Health / Status Output (Per Run)

Each script should print (and currently does for permit_scraper):
```
[2026-08-16 06:00:01] permit_scraper started
  Source: Cedar Rapids XLS (August 2026)
  Rows parsed: 312
  New permits inserted: 14
  Duplicate permits skipped: 298
[2026-08-16 06:00:08] permit_scraper finished — 14 new, 0 errors
```

`storm_scraper` and the PDF scrapers have similar structured output. Confirm on
mini PC — if any script lacks structured status output, add it before relying on
Task Scheduler logs for monitoring.
