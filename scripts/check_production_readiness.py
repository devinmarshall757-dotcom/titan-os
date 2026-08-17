#!/usr/bin/env python3
"""
Titan OS — Production Readiness Checker
Read-only. Never mutates data, applies migrations, or reveals secret values.

Run from the repo root:
  python scripts/check_production_readiness.py

On Windows mini PC:
  C:\\titan\\venv\\Scripts\\python.exe C:\\titan\\scripts\\check_production_readiness.py
"""

import importlib
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parent.parent
PASS = "\u2705"
FAIL = "\u274c"
WARN = "\u26a0\ufe0f"
INFO = "\u2139\ufe0f"

results = []


def check(label, passed, detail=""):
    status = PASS if passed else FAIL
    results.append((status, label, detail))
    print(f"  {status}  {label}" + (f" — {detail}" if detail else ""))


def warn(label, detail=""):
    results.append((WARN, label, detail))
    print(f"  {WARN}  {label}" + (f" — {detail}" if detail else ""))


def section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ── 1. REQUIRED ENV VAR NAMES ────────────────────────────────────────────────
section("1. Required environment variable names")

REQUIRED_PROD_VARS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "ADMIN_PASSWORD",
    "ADMIN_TOKEN_SECRET",
    "RESEND_API_KEY",
    "REGRID_API_KEY",
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN",
]

OPTIONAL_PROD_VARS = [
    "ADMIN_PRODUCTION_MODE",
    "RATE_LIMIT_MEASURE",
    "RATE_LIMIT_CONTACT",
    "RATE_LIMIT_ADMIN_AUTH",
    "RATE_LIMIT_MEASURE_LIDAR",
    "CORS_ALLOWED_ORIGINS",
    "PRODUCTION_URL",
]

for var in REQUIRED_PROD_VARS:
    present = bool(os.environ.get(var))
    check(f"{var} present", present, "" if present else "NOT SET — required in production")

for var in OPTIONAL_PROD_VARS:
    present = bool(os.environ.get(var))
    if not present:
        warn(f"{var} not set", "optional — check default is acceptable")

admin_mode = os.environ.get("ADMIN_PRODUCTION_MODE", "")
check(
    "ADMIN_PRODUCTION_MODE is explicit",
    admin_mode in ("true", "false", ""),
    f"current: '{admin_mode}'" if admin_mode else "not set (defaults to demo mode)",
)

# ── 2. PYTHON RUNTIME IMPORTS ────────────────────────────────────────────────
section("2. Python runtime dependency imports")

RUNTIME_DEPS = [
    "numpy", "laspy", "lazrs", "scipy", "sklearn",
    "shapely", "pyproj", "requests",
]

for mod in RUNTIME_DEPS:
    try:
        importlib.import_module(mod)
        check(f"import {mod}", True)
    except ImportError as e:
        check(f"import {mod}", False, f"{e} — run: pip install -r requirements.txt")

# ── 3. TEST SUITE ────────────────────────────────────────────────────────────
section("3. Test suite")

try:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    lines = (result.stdout + result.stderr).strip().splitlines()
    summary = next((l for l in reversed(lines) if l.startswith("Ran ")), "")
    passed = result.returncode == 0
    check("Test suite passes", passed, summary or f"exit {result.returncode}")
    if not passed:
        for l in lines[-10:]:
            if l.strip():
                print(f"       {l}")
except subprocess.TimeoutExpired:
    check("Test suite", False, "timed out after 120s")
except Exception as e:
    check("Test suite", False, str(e))

# ── 4. JAVASCRIPT SYNTAX ─────────────────────────────────────────────────────
section("4. JavaScript syntax (node --check)")

JS_FILES = [
    "api/contact.js",
    "api/measure.js",
    "api/admin-auth.js",
    "api/admin-logout.js",
    "api/_rate-limit.js",
    "api/_admin-verify.js",
    "api/_supabase-admin.js",
    "api/admin/config.js",
    "api/admin/leads.js",
    "api/admin/permits.js",
    "api/admin/storm.js",
    "api/admin/measurements.js",
    "api/admin/reviews.js",
    "api/admin/jobs.js",
    "api/admin/job-activity.js",
]

for f in JS_FILES:
    path = ROOT / f
    if not path.exists():
        check(f"node --check {f}", False, "file not found")
        continue
    try:
        r = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        check(f"node --check {f}", r.returncode == 0, r.stderr.strip()[:80] if r.returncode else "")
    except FileNotFoundError:
        warn(f"node --check {f}", "node not found — skip on mini PC if Node not installed")
    except Exception as e:
        check(f"node --check {f}", False, str(e))

# ── 5. PYTHON SYNTAX ─────────────────────────────────────────────────────────
section("5. Python syntax (compileall)")

try:
    r = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "api", "scripts"],
        cwd=ROOT,
        capture_output=True, text=True, timeout=30,
    )
    check("compileall api/ scripts/", r.returncode == 0, r.stderr.strip()[:120] if r.returncode else "")
except Exception as e:
    check("compileall", False, str(e))

# ── 6. DEMO / PRODUCTION MODE CONFIG ────────────────────────────────────────
section("6. Admin mode configuration")

token_secret = os.environ.get("ADMIN_TOKEN_SECRET", "")
prod_mode = os.environ.get("ADMIN_PRODUCTION_MODE", "") == "true"

check(
    "ADMIN_TOKEN_SECRET set (not falling back to service key)",
    bool(token_secret),
    "NOT SET — admin auth will return 503" if not token_secret else "set",
)

if prod_mode:
    check(
        "Production mode: ADMIN_TOKEN_SECRET required",
        bool(token_secret),
        "ADMIN_PRODUCTION_MODE=true but ADMIN_TOKEN_SECRET missing — will fail closed",
    )
else:
    warn("ADMIN_PRODUCTION_MODE not 'true'", "Admin is in demo mode — expected for pitch")

# ── 7. RATE LIMITER CONFIGURATION ────────────────────────────────────────────
section("7. Rate limiter configuration")

upstash_url = os.environ.get("UPSTASH_REDIS_REST_URL", "")
upstash_token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
is_vercel_prod = os.environ.get("VERCEL_ENV") == "production"

check("UPSTASH_REDIS_REST_URL set", bool(upstash_url), "NOT SET — rate limiter will fail closed in production" if not upstash_url else "set")
check("UPSTASH_REDIS_REST_TOKEN set", bool(upstash_token), "NOT SET" if not upstash_token else "set")

if is_vercel_prod and (not upstash_url or not upstash_token):
    check("Rate limiter will not fail open in production", False, "Upstash missing — endpoints will return 429/503 until configured")
else:
    check("Rate limiter config complete", bool(upstash_url and upstash_token), "configure Upstash before public traffic")

# ── 8. SECURITY SCANS ────────────────────────────────────────────────────────
section("8. Security scans — prohibited patterns in browser assets")

BROWSER_ASSETS = [
    "index.html",
    "pitch.html",
    "quote.html",
    "admin/reviews.html",
    "leave-review.html",
]

SERVICE_KEY_PATTERN = re.compile(r'eyJ[A-Za-z0-9_-]{100,}')  # JWT-like service key
PROHIBITED_PHRASES = [
    ("AI-scored",              "pitch.html prohibited phrase"),
    ("24/7",                   "pitch.html prohibited phrase (check stat line)"),
    ("entire business, running", "pitch.html prohibited phrase"),
    ("Access-Control-Allow-Origin: *", "CORS wildcard"),
    ("SUPABASE_SERVICE_KEY",   "service key env name in browser asset"),
]

for asset in BROWSER_ASSETS:
    path = ROOT / asset
    if not path.exists():
        continue
    content = path.read_text(encoding="utf-8", errors="replace")

    # Check for service role key (JWT pattern)
    matches = SERVICE_KEY_PATTERN.findall(content)
    # Exclude the OIDC token in .env.local (not a browser asset), but flag any JWT in HTML
    if matches:
        check(f"No service-key JWT in {asset}", False, f"found {len(matches)} JWT-like token(s) — verify they are not the service key")
    else:
        check(f"No service-key JWT in {asset}", True)

    # Check prohibited phrases
    for phrase, label in PROHIBITED_PHRASES:
        found = phrase in content
        if asset == "admin/reviews.html" and phrase == "SUPABASE_SERVICE_KEY":
            # The env var name appears in comments/docs — flag but don't fail
            if found:
                warn(f"'{phrase}' in {asset}", "verify it is only in comments, not in live code paths")
            continue
        check(f"No '{phrase}' in {asset}", not found, f"found in {asset}" if found else "")

# ── 9. ADMIN ROUTE PROTECTION ────────────────────────────────────────────────
section("9. Admin API route protection (static analysis)")

ADMIN_ROUTES = [
    "api/admin/leads.js",
    "api/admin/permits.js",
    "api/admin/storm.js",
    "api/admin/measurements.js",
    "api/admin/reviews.js",
    "api/admin/jobs.js",
    "api/admin/job-activity.js",
]

for route in ADMIN_ROUTES:
    path = ROOT / route
    if not path.exists():
        check(f"{route} — requireAdmin called", False, "file not found")
        continue
    content = path.read_text(encoding="utf-8")
    check(f"{route} — requireAdmin called", "requireAdmin" in content)
    if "PATCH" in content or "POST" in content or "DELETE" in content:
        check(f"{route} — requireCsrf on mutations", "requireCsrf" in content)

# ── 10. CORS WILDCARD ABSENT FROM PYTHON ENDPOINTS ──────────────────────────
section("10. CORS wildcard check")

PYTHON_ENDPOINTS = ["api/measure_lidar.py"]
for f in PYTHON_ENDPOINTS:
    path = ROOT / f
    if not path.exists():
        continue
    content = path.read_text(encoding="utf-8")
    check(f"No CORS wildcard in {f}", "Access-Control-Allow-Origin: *" not in content)
    check(f"CORS allowlist in {f}", "_ALLOWED_ORIGINS" in content or "_cors_origin" in content)

# ── 11. .env.example PRESENT ─────────────────────────────────────────────────
section("11. Documentation")

check(".env.example present", (ROOT / ".env.example").exists(), "create .env.example to document required vars")
check("PITCH_READY_REPORT.md present", (ROOT / "PITCH_READY_REPORT.md").exists())
check("OPERATIONS_SCRIPT_AUDIT.md present", (ROOT / "OPERATIONS_SCRIPT_AUDIT.md").exists())

# ── SUMMARY ──────────────────────────────────────────────────────────────────
section("SUMMARY")

total = len(results)
passes = sum(1 for s, _, _ in results if s == PASS)
fails = sum(1 for s, _, _ in results if s == FAIL)
warns = sum(1 for s, _, _ in results if s == WARN)

print(f"\n  {passes}/{total} checks passed   {fails} failed   {warns} warnings")

blockers = [(l, d) for s, l, d in results if s == FAIL]
if blockers:
    print("\n  BLOCKERS:")
    for l, d in blockers:
        print(f"    {FAIL} {l}" + (f" — {d}" if d else ""))
    sys.exit(1)
else:
    print(f"\n  {PASS} All checks passed.")
    sys.exit(0)
