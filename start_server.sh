#!/bin/bash
# NRC — Start the local server (enables Rerun button)
# Double-click this file or run: bash start_server.sh

echo ""
echo "================================================"
echo "  NRC Market Intelligence — Local Server"
echo "================================================"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "ERROR: Python 3 not found. Install from https://python.org"
  read -p "Press Enter to exit..."
  exit 1
fi

# Check API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "Enter your Anthropic API key (starts with sk-ant-):"
  read -s ANTHROPIC_API_KEY
  export ANTHROPIC_API_KEY
  echo ""
fi

# Install dependencies quietly
echo "Checking dependencies..."
pip install anthropic requests beautifulsoup4 flask flask-cors weasyprint -q

echo ""
echo "Starting server at http://localhost:5050"
echo "Keep this window open. Press Ctrl+C to stop."
echo ""

python3 "$(dirname "$0")/scripts/server.py"
