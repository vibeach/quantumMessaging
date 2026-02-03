#!/usr/bin/env python3
"""
Incept Processor Watchdog
Monitors and automatically restarts the incept processor if it crashes.
"""

import subprocess
import time
import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database

RESTART_DELAY = 5  # seconds to wait before restarting
MAX_RESTART_ATTEMPTS = 10  # maximum restarts in a window
RESTART_WINDOW = 300  # time window in seconds (5 minutes)

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    """Main watchdog loop."""
    print("Incept Processor Watchdog")
    print("=" * 40)
    print(f"Project dir: {PROJECT_DIR}")
    print(f"Restart delay: {RESTART_DELAY}s")
    print("Monitoring processor...")
    print("=" * 40)

    restart_times = []
    process = None

    while True:
        try:
            # Clean up old restart times outside the window
            now = time.time()
            restart_times = [t for t in restart_times if now - t < RESTART_WINDOW]

            # Check if we've restarted too many times
            if len(restart_times) >= MAX_RESTART_ATTEMPTS:
                print(f"\n{'='*60}")
                print(f"ERROR: Too many restarts ({len(restart_times)}) in {RESTART_WINDOW}s")
                print("The processor may be crashing repeatedly. Stopping watchdog.")
                print(f"{'='*60}\n")
                break

            # Start the processor
            print(f"\n[{time.strftime('%H:%M:%S')}] Starting incept processor...")
            process = subprocess.Popen(
                [sys.executable, 'incept_processor.py'],
                cwd=PROJECT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Stream output
            for line in iter(process.stdout.readline, ''):
                if line:
                    print(line.rstrip())

            # Process exited
            exit_code = process.wait()
            print(f"\n[{time.strftime('%H:%M:%S')}] Processor exited with code {exit_code}")

            # If exit code is 0, it was a clean shutdown (Ctrl+C), don't restart
            if exit_code == 0:
                print("Clean shutdown detected. Stopping watchdog.")
                break

            # Record restart time
            restart_times.append(time.time())

            # Log the restart
            database.add_system_log('incept', 'processor_crash', 'warning',
                                   f'Processor crashed (exit code {exit_code}). Restarting...')

            # Wait before restarting
            print(f"Waiting {RESTART_DELAY}s before restart...")
            time.sleep(RESTART_DELAY)

        except KeyboardInterrupt:
            print("\n\nWatchdog interrupted. Stopping processor...")
            if process:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            break
        except Exception as e:
            print(f"Watchdog error: {e}")
            time.sleep(RESTART_DELAY)


if __name__ == '__main__':
    main()
