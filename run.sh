#!/usr/bin/env bash
# Convenience launcher: creates a venv (first run only), installs
# dependencies, and starts the app on http://localhost:5000
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt
echo "Starting server on http://localhost:5000 ..."
python app.py
