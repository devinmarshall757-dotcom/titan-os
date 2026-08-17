## Context — why we're doing this

You are one of two Claude instances working on the Titan Consulting system together. The other Claude instance is running on a Mac (Claude Code CLI) and is the main architect — it handles the codebase, Vercel deployments, and Supabase schema. You are on the Windows mini PC and handle local scraping jobs (permit_scraper.py, storm_scraper.py, neighborhood_scorer.py).

Right now the only way we communicate is the user copying and pasting between two terminals, which is slow and error-prone. We are fixing that by setting up an MCP (Model Context Protocol) server on this mini PC so the Mac Claude can send commands directly to you and read your responses in real time — no more email relay, no more copy-paste.

## What you are building

A lightweight Flask HTTP server that acts as an MCP bridge:
- Listens on localhost:5001
- Exposes two endpoints: POST /run (execute a shell command or Python script) and GET /status (health check)
- ngrok tunnels that port to a public HTTPS URL
- That URL gets added to the Mac Claude's MCP config so it can call you directly

This is a tool-execution bridge — the Mac Claude sends {"command": "python C:\\titan\\permit_scraper.py"} and you run it and return stdout/stderr. Simple, safe, local.

---

## Build steps — ask before each install, ask before any persistent config change

### Step 1 — Install Flask and ngrok

Ask user to approve: pip install flask into C:\titan\venv

For ngrok: check if already installed with `ngrok version`. If not, tell the user to download it from https://ngrok.com/download (Windows ZIP), extract ngrok.exe to C:\titan\, and confirm when done. Do not download it yourself.

### Step 2 — Write the MCP bridge server

Write this file to C:\titan\mcp_bridge.py:

```python
#!/usr/bin/env python3
"""
Titan MCP Bridge — lets Mac Claude send commands to this mini PC directly.
Runs on localhost:5001, tunneled via ngrok.
"""

import subprocess
import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv("C:/titan/.env")

app = Flask(__name__)

# Simple token auth — read from .env
BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "")

ALLOWED_COMMANDS = [
    "python C:\\titan\\permit_scraper.py",
    "python C:\\titan\\storm_scraper.py",
    "python C:\\titan\\neighborhood_scorer.py",
    "python C:\\titan\\",  # any titan script
]

def is_allowed(command: str) -> bool:
    if not command:
        return False
    cmd_lower = command.lower().strip()
    return any(cmd_lower.startswith(a.lower()) for a in ALLOWED_COMMANDS)


@app.route("/status", methods=["GET"])
def status():
    token = request.headers.get("X-Bridge-Token", "")
    if BRIDGE_TOKEN and token != BRIDGE_TOKEN:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"status": "ok", "machine": "titan-minipc"})


@app.route("/run", methods=["POST"])
def run():
    token = request.headers.get("X-Bridge-Token", "")
    if BRIDGE_TOKEN and token != BRIDGE_TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    command = data.get("command", "").strip()

    if not command:
        return jsonify({"error": "no command provided"}), 400

    if not is_allowed(command):
        return jsonify({"error": f"command not in allowlist: {command}"}), 403

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd="C:\\titan"
        )
        return jsonify({
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "command timed out after 120s"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Titan MCP Bridge running on http://localhost:5001")
    print("Waiting for ngrok tunnel...")
    app.run(host="127.0.0.1", port=5001, debug=False)
```

### Step 3 — Add BRIDGE_TOKEN to .env

Generate a random token (use python -c "import secrets; print(secrets.token_hex(24))") and append it to C:\titan\.env as BRIDGE_TOKEN=<generated_value>. Do not display the token value — just confirm it was written. Tell the user they will need this token to give to the Mac Claude later.

### Step 4 — Start the bridge server

Run in background:
```
Start-Process -NoNewWindow -FilePath "C:\titan\venv\Scripts\python.exe" -ArgumentList "C:\titan\mcp_bridge.py"
```

Verify it's running:
```
Invoke-WebRequest -Uri http://localhost:5001/status -UseBasicParsing
```
Should return {"status":"ok","machine":"titan-minipc"}

### Step 5 — Start ngrok tunnel

```
Start-Process -NoNewWindow -FilePath "C:\titan\ngrok.exe" -ArgumentList "http 5001"
```

Wait 3 seconds, then fetch the public URL:
```
Invoke-RestMethod -Uri http://localhost:4040/api/tunnels
```

Extract the public_url from the response (looks like https://xxxx-xx-xx-xxx-xx.ngrok-free.app).

### Step 6 — Report back

Tell the user:
1. The ngrok public URL (safe to share — it's a tunnel URL, not a credential)
2. That BRIDGE_TOKEN is saved in C:\titan\.env — they should copy it from there themselves and give it to the Mac Claude
3. Instructions for the Mac Claude side:
   - Add this to ~/.claude/mcp_servers.json or give the URL + token to Mac Claude directly
   - Mac Claude can then call POST <ngrok-url>/run with header X-Bridge-Token and body {"command": "python C:\\titan\\permit_scraper.py"}

### Step 7 — Set up persistence (ask first)

Ask if the user wants mcp_bridge.py and ngrok to start automatically on Windows login via Task Scheduler. Do not create scheduled tasks without approval.
