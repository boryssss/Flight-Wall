#!/bin/bash
set -e

cd /home/borys/flightwall

echo "=== FlightWall update ==="

git pull --ff-only

source .venv/bin/activate

if [ -f requirements.txt ]; then
    pip install -r requirements.txt
fi

echo "=== Update complete ==="
