#!/usr/bin/env python3
"""
Claude Request Processor
Polls for pending requests and processes them using Claude Code CLI.
Run this alongside your dashboard to auto-process requests.
"""

import subprocess
import time
import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database

POLL_INTERVAL = 5  # seconds between checks
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def process_request(req):
    """Process a single request using Claude Code CLI."""
    req_id = req['id']
    request_text = req['text']

    print(f"\n{'='*60}")
    print(f"Processing request #{req_id}: {request_text[:50]}...")
    print(f"{'='*60}\n")

    # Mark as processing
    database.update_claude_request(req_id, 'processing')
    database.add_claude_log(req_id, 'Auto-processor picked up this request', 'info')

    # Build the prompt for Claude Code
    prompt = f"""You are processing a user request from the Claude Control dashboard.

REQUEST #{req_id}:
{request_text}

IMPORTANT INSTRUCTIONS:
1. This request is for the Telegram monitoring dashboard project in this directory
2. Make the requested changes to the codebase
3. After making changes, call the log_progress function to update status
4. When done, summarize what you did

To log progress, run this Python code:
```python
import database
database.add_claude_log({req_id}, 'Your message here', 'info')  # or 'success', 'error', 'warning'
```

To mark complete when done:
```python
import database
database.update_claude_request({req_id}, 'completed', 'Summary of what was done')
```

Now process the request."""

    try:
        # Run Claude Code with the prompt
        database.add_claude_log(req_id, 'Starting Claude Code CLI...', 'info')

        result = subprocess.run(
            [
                'claude',
                '-p', prompt,
                '--dangerously-skip-permissions'
            ],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        # Log output
        if result.stdout:
            # Log first part of output
            output_preview = result.stdout[:1000]
            database.add_claude_log(req_id, f'Output:\n{output_preview}', 'info')
            print(result.stdout)

        if result.returncode == 0:
            # Check if request was marked complete by Claude
            updated_req = database.get_claude_request(req_id)
            if updated_req and updated_req['status'] != 'completed':
                # Claude didn't mark it complete, do it now
                database.add_claude_log(req_id, 'Claude Code finished processing', 'success')
                summary = result.stdout[-500:] if result.stdout else 'Completed'
                database.update_claude_request(req_id, 'completed', summary)
            print(f"Request #{req_id} completed successfully")
        else:
            error_msg = result.stderr[:500] if result.stderr else result.stdout[:500] if result.stdout else 'Unknown error'
            database.add_claude_log(req_id, f'Error: {error_msg}', 'error')
            database.update_claude_request(req_id, 'error', error_msg)
            print(f"Request #{req_id} failed: {error_msg}")

    except subprocess.TimeoutExpired:
        database.add_claude_log(req_id, 'Request timed out after 5 minutes', 'error')
        database.update_claude_request(req_id, 'error', 'Timeout after 5 minutes')
        print(f"Request #{req_id} timed out")
    except FileNotFoundError:
        database.add_claude_log(req_id, 'Claude CLI not found - is it installed?', 'error')
        database.update_claude_request(req_id, 'error', 'Claude CLI not found')
        print("Error: 'claude' command not found. Make sure Claude Code CLI is installed.")
    except Exception as e:
        database.add_claude_log(req_id, f'Unexpected error: {str(e)}', 'error')
        database.update_claude_request(req_id, 'error', str(e))
        print(f"Request #{req_id} error: {e}")


def main():
    """Main polling loop."""
    print("Claude Request Processor")
    print("=" * 40)
    print(f"Project dir: {PROJECT_DIR}")
    print(f"Poll interval: {POLL_INTERVAL}s")
    print("Waiting for requests...")
    print("=" * 40)

    # Initialize database
    database.init_db()

    while True:
        try:
            # Check for pending requests
            pending = database.get_pending_claude_requests()

            if pending:
                print(f"\nFound {len(pending)} pending request(s)")
                # Process one at a time
                process_request(pending[0])

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\nStopping processor...")
            break
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
