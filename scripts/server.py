"""
NRC Local Server — enables the Rerun button on the dashboard.

START THIS FIRST (run once, keep open):
    python scripts/server.py

Then open your dashboard and click Rerun.
Keep this terminal window open whenever you want Rerun to work.
"""

import subprocess, sys, os
from pathlib import Path
from flask import Flask, jsonify
from flask_cors import CORS

app   = Flask(__name__)
CORS(app)

SCRAPER = Path(__file__).parent / "scraper.py"
running = False

@app.route("/run", methods=["POST"])
def run():
    global running
    if running:
        return jsonify({"status": "already_running"}), 409

    api_key = os.environ.get("ANTHROPIC_API_KEY","").strip()
    if not api_key:
        return jsonify({"status":"error","message":"ANTHROPIC_API_KEY not set in this terminal"}), 500

    running = True
    print("\n>>> Rerun triggered from dashboard <<<\n")
    try:
        result = subprocess.run(
            [sys.executable, str(SCRAPER)],
            env={**os.environ},
            timeout=360,
        )
        running = False
        return jsonify({"status":"ok"}) if result.returncode == 0 else jsonify({"status":"error","code":result.returncode}), 500
    except subprocess.TimeoutExpired:
        running = False
        return jsonify({"status":"timeout"}), 500
    except Exception as e:
        running = False
        return jsonify({"status":"error","message":str(e)}), 500

@app.route("/ping")
def ping():
    return jsonify({"ok": True, "running": running})

if __name__ == "__main__":
    print("\n" + "="*50)
    print("NRC Local Server")
    print("="*50)
    print("Running at: http://localhost:5050")
    print("Keep this terminal open.")
    print("The Rerun button on your dashboard will")
    print("call this server to trigger the scraper.")
    print()
    print("To stop: Ctrl+C")
    print("="*50 + "\n")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠  WARNING: ANTHROPIC_API_KEY is not set.")
        print("   Set it before starting:")
        print("   Mac/Linux: export ANTHROPIC_API_KEY='sk-ant-...'")
        print("   Windows:   set ANTHROPIC_API_KEY=sk-ant-...")
        print()

    app.run(host="localhost", port=5050, debug=False)
