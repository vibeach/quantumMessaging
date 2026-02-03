#!/bin/bash
# Start script for Render deployment
# Runs monitor.py in background + gunicorn for dashboard

# Create data directory if needed
mkdir -p ${DATA_DIR:-/data}/media

# Debug: Check environment variables (length only, not values)
echo "=== Environment Check ==="
echo "SESSION_STRING length: ${#SESSION_STRING}"
echo "TELEGRAM_API_ID set: $([ -n \"$TELEGRAM_API_ID\" ] && echo 'yes' || echo 'NO')"
echo "TELEGRAM_API_HASH set: $([ -n \"$TELEGRAM_API_HASH\" ] && echo 'yes' || echo 'NO')"
echo "TARGET_USER set: $([ -n \"$TARGET_USER\" ] && echo 'yes' || echo 'NO')"
echo "========================="

# Start monitor in background with output visible
echo "Starting Telegram monitor..."
python -u monitor.py 2>&1 &
MONITOR_PID=$!

# Give monitor time to initialize and show any errors
sleep 10

# Check if monitor is still running
if kill -0 $MONITOR_PID 2>/dev/null; then
    echo "Monitor started successfully (PID: $MONITOR_PID)"
else
    echo "ERROR: Monitor failed to start! Check logs above."
fi

# Start dashboard with gunicorn
echo "Starting dashboard on port ${PORT:-5001}..."
exec gunicorn dashboard_v6:app \
    --bind 0.0.0.0:${PORT:-5001} \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
