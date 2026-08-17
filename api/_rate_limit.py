"""
Rate limiter for Python serverless functions using Upstash Redis REST API.

Required env vars:
  UPSTASH_REDIS_REST_URL    — Upstash Redis REST URL
  UPSTASH_REDIS_REST_TOKEN  — Upstash REST token

Per-endpoint limit env var (format: "requests,windowSeconds"):
  RATE_LIMIT_MEASURE_LIDAR  — /api/measure_lidar (default: 10,60)

In production (VERCEL_ENV=production):
  Missing config → fail closed.
In development:
  Missing config → warn + allow.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Optional

UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
IS_PROD = os.environ.get("VERCEL_ENV") == "production" or os.environ.get("NODE_ENV") == "production"

_dev_warned = False
_dev_buckets: dict[str, dict] = {}


def _parse_limit(env_key: str, default_reqs: int, default_sec: int) -> tuple[int, int]:
    raw = os.environ.get(env_key, f"{default_reqs},{default_sec}")
    parts = raw.split(",")
    try:
        r = int(parts[0])
        s = int(parts[1]) if len(parts) > 1 else default_sec
    except (ValueError, IndexError):
        return default_reqs, default_sec
    return (r if r > 0 else default_reqs), (s if s > 0 else default_sec)


LIMITS: dict[str, tuple[int, int]] = {
    "measure_lidar": _parse_limit("RATE_LIMIT_MEASURE_LIDAR", 10, 60),
}


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:20]


def _extract_ip(handler) -> str:
    xff = handler.headers.get("X-Forwarded-For", "")
    raw = xff.split(",")[0].strip() if xff else (
        getattr(handler.client_address, "__iter__", None) and handler.client_address[0] or "0.0.0.0"
    )
    return _hash_ip(raw)


def _dev_check(key: str, max_reqs: int, window_sec: int) -> dict:
    now = time.time()
    entry = _dev_buckets.get(key, {"count": 0, "reset_at": now + window_sec})
    if now > entry["reset_at"]:
        entry = {"count": 0, "reset_at": now + window_sec}
    entry["count"] += 1
    _dev_buckets[key] = entry
    remaining = max(0, max_reqs - entry["count"])
    retry_after = max(0, int(entry["reset_at"] - now))
    return {"allowed": entry["count"] <= max_reqs, "remaining": remaining, "retry_after": retry_after}


def _upstash_check(key: str, max_reqs: int, window_sec: int) -> dict:
    now_ms = int(time.time() * 1000)
    window_start_ms = now_ms - window_sec * 1000
    pipeline = [
        ["ZADD", key, "NX", str(now_ms), str(now_ms)],
        ["ZREMRANGEBYSCORE", key, "0", str(window_start_ms)],
        ["ZCARD", key],
        ["PEXPIRE", key, str(window_sec * 1000)],
    ]
    req = urllib.request.Request(
        f"{UPSTASH_URL}/pipeline",
        data=json.dumps(pipeline).encode(),
        headers={
            "Authorization": f"Bearer {UPSTASH_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        data = json.loads(resp.read())
    card_result = data[2]
    count = card_result.get("result", max_reqs + 1) if isinstance(card_result, dict) else (
        card_result if isinstance(card_result, int) else max_reqs + 1
    )
    remaining = max(0, max_reqs - count)
    return {"allowed": count <= max_reqs, "remaining": remaining, "retry_after": window_sec}


def check_rate_limit(handler, endpoint: str) -> dict:
    """Check rate limit. Returns dict with allowed, remaining, retry_after, config_missing."""
    global _dev_warned
    limit = LIMITS.get(endpoint)
    if not limit:
        raise ValueError(f"Unknown rate-limit endpoint: {endpoint}")
    max_reqs, window_sec = limit
    ip_key = _extract_ip(handler)
    key = f"rl:titan:{endpoint}:{ip_key}"

    if not UPSTASH_URL or not UPSTASH_TOKEN:
        if IS_PROD:
            print(f"[rate-limit] UPSTASH not configured in production — failing closed ({endpoint})", file=sys.stderr)
            return {"allowed": False, "remaining": 0, "retry_after": 60, "config_missing": True}
        if not _dev_warned:
            _dev_warned = True
            print("[rate-limit] DEV: Upstash not configured — using in-memory fallback", file=sys.stderr)
        return _dev_check(key, max_reqs, window_sec)

    try:
        return _upstash_check(key, max_reqs, window_sec)
    except Exception as e:
        print(f"[rate-limit] Upstash error: {e}", file=sys.stderr)
        if IS_PROD:
            return {"allowed": False, "remaining": 0, "retry_after": 30}
        return {"allowed": True, "remaining": max_reqs, "retry_after": 0}


def apply_rate_limit(handler, endpoint: str) -> bool:
    """
    Apply rate limit. Sets headers and sends 429 if limited.
    Returns True if request was rate-limited (caller should return immediately).
    """
    limit = LIMITS.get(endpoint)
    result = check_rate_limit(handler, endpoint)
    max_reqs = limit[0] if limit else 0

    handler.send_header("X-RateLimit-Limit", str(max_reqs))
    handler.send_header("X-RateLimit-Remaining", str(result["remaining"]))

    if not result["allowed"]:
        retry = result["retry_after"]
        handler.send_header("Retry-After", str(retry))
        msg = "Service temporarily unavailable" if result.get("config_missing") else "Too many requests"
        body = json.dumps({"error": msg, "retryAfter": retry}).encode()
        handler.send_response(429)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", len(body))
        handler.end_headers()
        handler.wfile.write(body)
        return True
    return False
