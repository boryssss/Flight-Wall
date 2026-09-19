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

if systemctl is-enabled --quiet flightwall.service 2>/dev/null; then
    echo "Restarting FlightWall..."
    sudo systemctl restart flightwall.service
fi
