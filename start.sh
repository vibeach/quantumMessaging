#!/bin/bash
# Start script for Render deployment
# Runs monitor.py in background + gunicorn for dashboard

# Create data directory if needed
mkdir -p ${DATA_DIR:-/data}/media

# Start monitor in background
echo "Starting Telegram monitor..."
python monitor.py &
MONITOR_PID=$!

# Give monitor time to initialize
sleep 5

# Start dashboard with gunicorn
echo "Starting dashboard on port ${PORT:-5001}..."
exec gunicorn dashboard_v6:app \
    --bind 0.0.0.0:${PORT:-5001} \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
