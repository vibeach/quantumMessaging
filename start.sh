#!/bin/bash
# Start script for Render deployment
# Multi-user dashboard with built-in MonitorManager

# Create data directory if needed
mkdir -p ${DATA_DIR:-/data}/media

# Debug: Check environment variables
echo "=== Environment Check ==="
echo "QM_COORDINATOR_PASSWORD set: $([ -n "$QM_COORDINATOR_PASSWORD" ] && echo 'yes' || echo 'NO')"
echo "DATA_DIR: ${DATA_DIR:-/data}"
echo "========================="

# Start multi-user dashboard with gunicorn
# MonitorManager is built into dashboard_multi.py and starts automatically
echo "Starting multi-user dashboard on port ${PORT:-5001}..."
exec gunicorn dashboard_multi:app \
    --bind 0.0.0.0:${PORT:-5001} \
    --workers 1 \
    --threads 4 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
