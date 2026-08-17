#!/usr/bin/env python3
"""
Titan Task Poller — polls Supabase for tasks queued by Mac Claude,
runs the exact matching script, writes results back. No dynamic execution.
"""

import os, time, json, subprocess, datetime
import requests
from dotenv import load_dotenv

load_dotenv("C:/titan/.env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

SCRIPTS = {
    "permit_scraper":              r"C:\titan\venv\Scripts\python.exe C:\titan\scripts\permit_scraper.py",
    "storm_scraper":               r"C:\titan\venv\Scripts\python.exe C:\titan\scripts\storm_scraper.py",
    "neighborhood_scorer":         r"C:\titan\venv\Scripts\python.exe C:\titan\neighborhood_scorer.py",
    "dubuque_permit_scraper":      r"C:\titan\venv\Scripts\python.exe C:\titan\scripts\dubuque_permit_scraper.py",
    "council_bluffs_permit_scraper": r"C:\titan\venv\Scripts\python.exe C:\titan\scripts\council_bluffs_permit_scraper.py",
}

POLL_INTERVAL = 60  # seconds


def claim_task():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/claude_tasks?status=eq.pending&order=created_at.asc&limit=1",
        headers=HEADERS, timeout=10
    )
    rows = r.json()
    if not rows:
        return None
    task = rows[0]
    # Mark as running
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/claude_tasks?id=eq.{task['id']}",
        headers={**HEADERS, "Prefer": "return=minimal"},
        data=json.dumps({"status": "running", "started_at": datetime.datetime.utcnow().isoformat()}),
        timeout=10
    )
    return task


def run_script(script_name):
    cmd = SCRIPTS.get(script_name)
    if not cmd:
        return "", f"unknown script: {script_name}", 1
    try:
        result = subprocess.run(
            cmd.split(), shell=False, capture_output=True, text=True, timeout=180
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "timed out after 180s", 1
    except Exception as e:
        return "", str(e), 1


def complete_task(task_id, stdout, stderr, returncode):
    status = "done" if returncode == 0 else "error"
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/claude_tasks?id=eq.{task_id}",
        headers={**HEADERS, "Prefer": "return=minimal"},
        data=json.dumps({
            "status": status,
            "result_stdout": stdout[-4000:] if stdout else "",
            "result_stderr": stderr[-2000:] if stderr else "",
            "completed_at": datetime.datetime.utcnow().isoformat()
        }),
        timeout=10
    )


def poll():
    print(f"[{datetime.datetime.now():%H:%M:%S}] Titan Task Poller running (interval: {POLL_INTERVAL}s)")
    while True:
        try:
            task = claim_task()
            if task:
                script = task["script"]
                print(f"  Running: {script}")
                stdout, stderr, code = run_script(script)
                complete_task(task["id"], stdout, stderr, code)
                print(f"  Done: {script} — exit {code}")
            else:
                print(f"  [{datetime.datetime.now():%H:%M:%S}] No tasks pending")
        except Exception as e:
            print(f"  Poller error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    poll()
