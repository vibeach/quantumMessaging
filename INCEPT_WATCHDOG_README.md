# Incept Processor Watchdog

## Overview

The Incept Watchdog automatically monitors and restarts the incept processor if it crashes, ensuring continuous operation of the self-improvement system.

## Features

### 1. Automatic Restart on Crash
- Monitors the incept processor and automatically restarts it if it crashes
- Configurable restart delay (default: 5 seconds)
- Protection against restart loops (max 10 restarts in 5 minutes)

### 2. Interruption Detection and Recovery
- On startup, detects requests that were being processed when the server stopped
- Automatically creates continuation requests with full context from the interrupted request
- Marks interrupted requests with a warning badge in the UI

### 3. Progress Tracking
- Each request shows a compact timeline of progress dots on the main incept page
- Dots are color-coded by log type: info (blue), success (green), warning (orange), error (red)
- Hover over any dot to see the timestamp and message
- Separators every 5 dots for easier reading

### 4. Status Badges
- **Interrupted**: Shows when a request was stopped mid-processing
- **Restart Count**: Displays how many times a request has been restarted
- **Continuation**: Links to the parent request that this one continues from

## Usage

### Running the Watchdog

Instead of running `incept_processor.py` directly, run the watchdog:

```bash
python3 incept_watchdog.py
```

The watchdog will:
1. Start the incept processor
2. Monitor its output in real-time
3. Restart it automatically if it crashes
4. Stop cleanly on Ctrl+C

### Running on Render

Update your render.yaml or start command to use the watchdog:

```yaml
services:
  - type: web
    name: telegram-dashboard
    env: python
    buildCommand: "pip install -r requirements.txt"
    startCommand: "python3 incept_watchdog.py &"
```

### Manual Restart

If you need to manually control the processor, you can still run it directly:

```bash
python3 incept_processor.py
```

## Configuration

Edit these constants in `incept_watchdog.py`:

- `RESTART_DELAY`: Seconds to wait before restarting (default: 5)
- `MAX_RESTART_ATTEMPTS`: Maximum restarts in time window (default: 10)
- `RESTART_WINDOW`: Time window in seconds (default: 300 = 5 minutes)

## How Interruption Recovery Works

1. **Detection**: On startup, the processor checks for requests with status='processing'
2. **Marking**: These are marked as interrupted with a timestamp
3. **Continuation**: New requests are created as continuations with:
   - Full context from the parent request
   - All logs from previous attempts
   - Incremented restart counter
4. **Processing**: The continuation request picks up where the original left off

## UI Indicators

### Main Incept Page
- **Progress Dots**: Compact timeline showing each log entry as a colored dot
- **Status Badges**: Show interrupted, restart count, and continuation info

### Detail Page
- **Full Status**: Interrupted badge with timestamp
- **Restart Counter**: Shows how many times restarted
- **Continuation Link**: Click to see the original request
- **Complete Log History**: All logs from previous attempts included

## Troubleshooting

### Watchdog keeps restarting
- Check the processor logs for the actual error
- May indicate a persistent issue that needs fixing
- Watchdog will stop after 10 restarts in 5 minutes to prevent infinite loops

### Request stuck in "processing"
- Likely interrupted by server restart
- Will be auto-continued on next processor startup
- Check the logs for interruption warning

### Missing progress dots
- Progress dots only appear if the request has logs
- Refresh the page if dots don't load immediately
- Check browser console for API errors
