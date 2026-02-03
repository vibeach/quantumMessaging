#!/usr/bin/env python3
"""
Incept Request Processor
Polls for pending requests and processes them using either:
- Claude API with tool use (works on Render and locally) - ACTUALLY MAKES CHANGES
- Local Claude CLI (requires claude command installed)

AUTOMATIC RESTART & CONTINUATION:
- When the processor starts, it automatically detects interrupted work and continues it
- Interrupted requests (status='processing') are restarted with full context
- Interrupted improvements (status='implementing') are continued with full context
- All continuation requests include previous logs and progress to avoid repeating work

SEQUENTIAL PROCESSING (Race Condition Prevention):
- Requests are claimed atomically via claim_pending_request() to prevent conflicts
- Only one processor should handle a request at a time
- Improvements in auto-mode are processed one-by-one, not in parallel

Run this alongside your dashboard to auto-process requests.
"""

import subprocess
import time
import sys
import os
import json
import glob as glob_module

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import database
import dynamic_config

POLL_INTERVAL = 5  # seconds between checks
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Define tools for Claude to use
TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Use this to examine existing code before making changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file from project root (e.g., 'dashboard_v6.py' or 'templates/base_v6.html')"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to a file. This will overwrite the entire file. Use for creating new files or completely rewriting existing ones.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file from project root"
                },
                "content": {
                    "type": "string",
                    "description": "The complete content to write to the file"
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "Make a targeted edit to a file by replacing a specific string with new content. More precise than write_file for small changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file from project root"
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact string to find and replace (must be unique in the file)"
                },
                "new_string": {
                    "type": "string",
                    "description": "The string to replace it with"
                }
            },
            "required": ["path", "old_string", "new_string"]
        }
    },
    {
        "name": "list_files",
        "description": "List files in a directory or matching a glob pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., '*.py', 'templates/*.html', '**/*.js')"
                }
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "log_progress",
        "description": "Log progress message to the request log. Use this to communicate what you're doing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Progress message to log"
                },
                "level": {
                    "type": "string",
                    "enum": ["info", "success", "warning", "error"],
                    "description": "Log level"
                }
            },
            "required": ["message"]
        }
    }
]


def execute_tool(tool_name, tool_input, req_id):
    """Execute a tool and return the result."""
    try:
        if tool_name == "read_file":
            path = os.path.join(PROJECT_DIR, tool_input["path"])
            if not os.path.exists(path):
                return f"Error: File not found: {tool_input['path']}"
            with open(path, 'r') as f:
                content = f.read()
            return f"Contents of {tool_input['path']}:\n{content}"

        elif tool_name == "write_file":
            path = os.path.join(PROJECT_DIR, tool_input["path"])
            # Create directory if needed
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
            with open(path, 'w') as f:
                f.write(tool_input["content"])
            database.add_claude_log(req_id, f"Wrote file: {tool_input['path']}", 'info')
            return f"Successfully wrote {len(tool_input['content'])} characters to {tool_input['path']}"

        elif tool_name == "edit_file":
            path = os.path.join(PROJECT_DIR, tool_input["path"])
            if not os.path.exists(path):
                return f"Error: File not found: {tool_input['path']}"
            with open(path, 'r') as f:
                content = f.read()
            old_string = tool_input["old_string"]
            new_string = tool_input["new_string"]
            if old_string not in content:
                return f"Error: Could not find the specified string in {tool_input['path']}. The string to replace was not found."
            if content.count(old_string) > 1:
                return f"Error: The string appears {content.count(old_string)} times in the file. Please provide a more unique string to replace."
            new_content = content.replace(old_string, new_string, 1)
            with open(path, 'w') as f:
                f.write(new_content)
            database.add_claude_log(req_id, f"Edited file: {tool_input['path']}", 'info')
            return f"Successfully edited {tool_input['path']}"

        elif tool_name == "list_files":
            pattern = tool_input["pattern"]
            files = glob_module.glob(os.path.join(PROJECT_DIR, pattern), recursive=True)
            # Make paths relative
            files = [os.path.relpath(f, PROJECT_DIR) for f in files]
            return f"Files matching '{pattern}':\n" + "\n".join(files) if files else f"No files found matching '{pattern}'"

        elif tool_name == "log_progress":
            level = tool_input.get("level", "info")
            database.add_claude_log(req_id, tool_input["message"], level)
            return "Logged successfully"

        else:
            return f"Unknown tool: {tool_name}"

    except Exception as e:
        return f"Error executing {tool_name}: {str(e)}"


def get_settings():
    """Get current processor settings."""
    settings = database.get_incept_settings()
    return settings or {
        'mode': 'api',
        'model': 'claude-sonnet-4-20250514'
    }


def should_auto_push(req):
    """Check if auto_push is enabled for a request.

    Handles SQLite 0/1 values properly.
    """
    auto_push = req.get('auto_push')
    # SQLite returns 0/1, None means default to False (safe default)
    if auto_push is None:
        return False  # Changed: default to NOT pushing
    if isinstance(auto_push, bool):
        return auto_push
    # Handle SQLite integer (0/1) or string ('0'/'1')
    return str(auto_push) == '1' or auto_push == 1


def git_commit_only(req_id, commit_message=None):
    """Commit changes WITHOUT pushing. Returns commit hash if successful."""
    try:
        # Check if there are any changes
        status_result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=10
        )

        if not status_result.stdout.strip():
            database.add_claude_log(req_id, 'No changes to commit', 'info')
            return None

        changes = status_result.stdout.strip().split('\n')
        database.add_claude_log(req_id, f'Found {len(changes)} changed file(s), committing (no push)...', 'info')

        # Configure git identity
        subprocess.run(['git', 'config', 'user.email', 'incept@telegram-dashboard.local'],
                      cwd=PROJECT_DIR, capture_output=True, timeout=5)
        subprocess.run(['git', 'config', 'user.name', 'Incept Processor'],
                      cwd=PROJECT_DIR, capture_output=True, timeout=5)

        # Stage all changes
        add_result = subprocess.run(
            ['git', 'add', '-A'],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=10
        )

        if add_result.returncode != 0:
            database.add_claude_log(req_id, f'Git add failed: {add_result.stderr}', 'error')
            return None

        # Commit
        msg = commit_message or f'Incept #{req_id}: Auto-commit changes'
        commit_result = subprocess.run(
            ['git', 'commit', '-m', msg],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=10
        )

        if commit_result.returncode != 0 and 'nothing to commit' not in commit_result.stdout:
            database.add_claude_log(req_id, f'Git commit failed: {commit_result.stderr}', 'error')
            return None

        # Get the commit hash
        hash_result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=5
        )
        commit_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else None

        database.add_claude_log(req_id, f'Committed locally (hash: {commit_hash[:8] if commit_hash else "unknown"}). Use Push button to push when ready.', 'success')
        return commit_hash

    except subprocess.TimeoutExpired:
        database.add_claude_log(req_id, 'Git commit timed out', 'error')
        return None
    except Exception as e:
        database.add_claude_log(req_id, f'Git commit error: {str(e)}', 'error')
        return None


def git_commit_and_push(req_id, commit_message=None, max_retries=3):
    """Commit and push changes to git after CLI makes modifications.

    Includes retry logic to handle race conditions when multiple requests
    try to push simultaneously.
    """
    try:
        # Check if there are any changes
        status_result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=10
        )

        if not status_result.stdout.strip():
            database.add_claude_log(req_id, 'No changes to commit', 'info')
            return True

        changes = status_result.stdout.strip().split('\n')
        database.add_claude_log(req_id, f'Found {len(changes)} changed file(s), committing...', 'info')

        # Pull latest changes first to avoid conflicts (with rebase to keep our changes on top)
        database.add_claude_log(req_id, 'Pulling latest changes before commit...', 'info')
        pull_result = subprocess.run(
            ['git', 'pull', '--rebase', 'origin', 'master'],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=30
        )
        if pull_result.returncode != 0 and 'Already up to date' not in pull_result.stdout:
            # If rebase fails, try to abort and continue without rebase
            subprocess.run(['git', 'rebase', '--abort'], cwd=PROJECT_DIR, capture_output=True, timeout=5)
            database.add_claude_log(req_id, f'Git pull rebase had issues, continuing anyway: {pull_result.stderr[:200]}', 'warning')

        # Configure git identity
        subprocess.run(['git', 'config', 'user.email', 'incept@telegram-dashboard.local'],
                      cwd=PROJECT_DIR, capture_output=True, timeout=5)
        subprocess.run(['git', 'config', 'user.name', 'Incept Processor'],
                      cwd=PROJECT_DIR, capture_output=True, timeout=5)

        # Stage all changes
        add_result = subprocess.run(
            ['git', 'add', '-A'],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=10
        )

        if add_result.returncode != 0:
            database.add_claude_log(req_id, f'Git add failed: {add_result.stderr}', 'error')
            return False

        # Commit
        msg = commit_message or f'Incept #{req_id}: Auto-commit changes'
        commit_result = subprocess.run(
            ['git', 'commit', '-m', msg],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=10
        )

        if commit_result.returncode != 0 and 'nothing to commit' not in commit_result.stdout:
            database.add_claude_log(req_id, f'Git commit failed: {commit_result.stderr}', 'error')
            return False

        # Check if origin remote exists, configure if needed
        remote_check = subprocess.run(
            ['git', 'remote', 'get-url', 'origin'],
            cwd=PROJECT_DIR, capture_output=True, text=True, timeout=5
        )

        if remote_check.returncode != 0:
            github_repo = os.environ.get('GITHUB_REPO_URL')
            if not github_repo:
                database.add_claude_log(req_id, 'No git remote configured. Set GITHUB_REPO_URL env var.', 'error')
                return False
            subprocess.run(['git', 'remote', 'add', 'origin', github_repo],
                          cwd=PROJECT_DIR, capture_output=True, timeout=5)

        # Set up authentication if token available
        github_token = os.environ.get('GITHUB_TOKEN')
        if github_token:
            url_result = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                cwd=PROJECT_DIR, capture_output=True, text=True, timeout=5
            )
            remote_url = url_result.stdout.strip()
            if github_token not in remote_url and 'github.com' in remote_url:
                push_url = remote_url.replace('https://', f'https://{github_token}@')
                subprocess.run(['git', 'remote', 'set-url', 'origin', push_url],
                              cwd=PROJECT_DIR, capture_output=True, timeout=5)

        # Get current branch (empty if detached HEAD - common on Render)
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=PROJECT_DIR, capture_output=True, text=True, timeout=5
        )
        current_branch = branch_result.stdout.strip()
        target_branch = os.environ.get('GIT_BRANCH', 'master')

        # Push - handle detached HEAD state with retry logic for race conditions
        if current_branch:
            push_cmd = ['git', 'push', '-u', 'origin', current_branch]
        else:
            push_cmd = ['git', 'push', 'origin', f'HEAD:{target_branch}']

        # Retry loop for push (handles race conditions)
        for attempt in range(max_retries):
            database.add_claude_log(req_id, f'Pushing to remote (attempt {attempt + 1}/{max_retries})...', 'info')
            push_result = subprocess.run(
                push_cmd,
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True,
                timeout=30
            )

            if push_result.returncode == 0:
                database.add_claude_log(req_id, 'Changes pushed to git - Render will redeploy automatically', 'success')
                return True

            error_msg = push_result.stderr

            # Auth errors are not recoverable by retry
            if 'Authentication failed' in error_msg or 'could not read Username' in error_msg:
                database.add_claude_log(req_id, 'Git push auth failed. Set GITHUB_TOKEN env var.', 'error')
                return False

            # If push failed due to remote changes (race condition), pull and retry
            if 'rejected' in error_msg or 'fetch first' in error_msg or 'non-fast-forward' in error_msg:
                database.add_claude_log(req_id, f'Push rejected (another commit pushed). Pulling and retrying...', 'warning')
                # Pull with rebase to get remote changes
                pull_result = subprocess.run(
                    ['git', 'pull', '--rebase', 'origin', target_branch],
                    cwd=PROJECT_DIR,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if pull_result.returncode != 0:
                    # Rebase conflict - try to abort and merge instead
                    subprocess.run(['git', 'rebase', '--abort'], cwd=PROJECT_DIR, capture_output=True, timeout=5)
                    database.add_claude_log(req_id, 'Rebase failed, trying merge...', 'warning')
                    merge_result = subprocess.run(
                        ['git', 'pull', '--no-rebase', 'origin', target_branch],
                        cwd=PROJECT_DIR,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if merge_result.returncode != 0:
                        database.add_claude_log(req_id, f'Merge also failed: {merge_result.stderr[:200]}', 'error')
                        return False
                # Continue to next retry attempt
                continue

            # Other errors - log and fail
            database.add_claude_log(req_id, f'Git push failed: {error_msg}', 'error')
            return False

        database.add_claude_log(req_id, f'Git push failed after {max_retries} attempts', 'error')
        return False

    except subprocess.TimeoutExpired:
        database.add_claude_log(req_id, 'Git operation timed out', 'error')
        return False
    except Exception as e:
        database.add_claude_log(req_id, f'Git error: {str(e)}', 'error')
        return False


def build_context_summary(req):
    """Build a context summary from parent requests if this is a restart."""
    parent_id = req.get('parent_id')
    if not parent_id:
        return ""

    # Get full context including parent chain
    context = database.get_request_context(parent_id)
    if not context:
        return ""

    parts = []
    parts.append("\n=== PREVIOUS ATTEMPT CONTEXT ===")

    # Add parent request info
    parts.append(f"\nPrevious request #{parent_id}:")
    parts.append(f"Status: {context.get('status', 'unknown')}")

    # Add logs from parent
    if context.get('logs'):
        parts.append("\nProgress log from previous attempt:")
        for log in context['logs']:
            parts.append(f"  [{log.get('log_type', 'info')}] {log.get('message', '')}")

    # Add response/summary if available
    if context.get('response'):
        parts.append(f"\nPrevious result summary:\n{context['response'][:1000]}")

    # Add grandparent context if exists
    for i, parent in enumerate(context.get('parent_chain', [])[:2]):  # Limit to 2 levels
        parts.append(f"\n--- Earlier attempt #{parent.get('id')} ---")
        parts.append(f"Status: {parent.get('status', 'unknown')}")
        if parent.get('logs'):
            parts.append("Key logs:")
            for log in parent['logs'][-5:]:  # Last 5 logs
                parts.append(f"  [{log.get('log_type', 'info')}] {log.get('message', '')}")

    parts.append("\n=== END PREVIOUS CONTEXT ===\n")
    parts.append("Continue from where the previous attempt left off. Avoid repeating completed work.")

    return "\n".join(parts)


def process_with_api(req):
    """Process request using Claude API with tool use to actually make changes."""
    try:
        import anthropic
    except ImportError:
        database.add_claude_log(req['id'], 'anthropic package not installed. Run: pip install anthropic', 'error')
        database.update_claude_request(req['id'], 'error', 'anthropic package not installed')
        return False

    req_id = req['id']
    request_text = req['text']

    # Use mode/model from request, fallback to settings
    model = req.get('model') or get_settings().get('model', 'claude-sonnet-4-20250514')

    print(f"\n{'='*60}")
    print(f"Processing request #{req_id} via API ({model})")
    print(f"Request: {request_text[:50]}...")
    if req.get('parent_id'):
        print(f"Continuation of: #{req.get('parent_id')}")
    print(f"{'='*60}\n")

    database.update_claude_request(req_id, 'processing')
    database.add_claude_log(req_id, f'Processing via API with model: {model}', 'info')

    # System prompt for tool use - loaded from dynamic config (hot-reloadable!)
    system_prompt = dynamic_config.get_incept_system_prompt()

    # Build context from parent if this is a restart
    context_summary = build_context_summary(req)

    user_message = f"""Please implement the following request:

{request_text}
{context_summary}

Start by reading relevant files to understand the current code, then make the necessary changes."""

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        messages = [{"role": "user", "content": user_message}]

        database.add_claude_log(req_id, 'Starting agentic loop with tools...', 'info')

        total_input_tokens = 0
        total_output_tokens = 0
        iteration = 0
        max_iterations = 50  # Safety limit - increased for complex tasks
        changes_made = []

        while iteration < max_iterations:
            iteration += 1
            print(f"  Iteration {iteration}...")

            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                tools=TOOLS,
                messages=messages
            )

            # Track tokens
            total_input_tokens += response.usage.input_tokens if response.usage else 0
            total_output_tokens += response.usage.output_tokens if response.usage else 0

            # Check if we're done (no more tool use)
            if response.stop_reason == "end_turn":
                # Extract final text response
                final_text = ""
                for block in response.content:
                    if hasattr(block, 'text'):
                        final_text += block.text

                database.add_claude_log(req_id, f'Completed after {iteration} iterations', 'success')
                database.add_claude_log(req_id, f'Tokens: {total_input_tokens} in, {total_output_tokens} out', 'info')

                summary = f"Changes made:\n" + "\n".join(changes_made) if changes_made else "No file changes made"
                summary += f"\n\nFinal response:\n{final_text[:1000]}"

                database.update_claude_request(req_id, 'completed', summary)

                # Handle git commit based on auto_push setting
                if changes_made:
                    if should_auto_push(req):
                        git_commit_and_push(req_id, f'Incept #{req_id}: {request_text[:50]}')
                    else:
                        # Commit locally but don't push
                        git_commit_only(req_id, f'Incept #{req_id}: {request_text[:50]}')

                print(f"Request #{req_id} completed via API")
                return True

            # Process tool calls
            assistant_content = response.content
            tool_results = []

            for block in assistant_content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id

                    print(f"    Tool: {tool_name}")
                    result = execute_tool(tool_name, tool_input, req_id)

                    # Track file changes
                    if tool_name in ("write_file", "edit_file") and "Successfully" in result:
                        changes_made.append(f"- {tool_name}: {tool_input.get('path', 'unknown')}")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result
                    })

            # Add assistant response and tool results to messages
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})

        # Max iterations reached
        database.add_claude_log(req_id, f'Max iterations ({max_iterations}) reached', 'warning')
        database.update_claude_request(req_id, 'completed', f'Completed with {len(changes_made)} changes (max iterations reached)')

        # Handle git commit based on auto_push setting
        if changes_made:
            if should_auto_push(req):
                git_commit_and_push(req_id, f'Incept #{req_id}: {request_text[:50]}')
            else:
                # Commit locally but don't push
                git_commit_only(req_id, f'Incept #{req_id}: {request_text[:50]}')

        return True

    except Exception as e:
        error_msg = f'Error: {str(e)}'
        database.add_claude_log(req_id, error_msg, 'error')
        database.update_claude_request(req_id, 'error', error_msg)
        print(f"Request #{req_id} failed: {error_msg}")
        import traceback
        traceback.print_exc()
        return False


def process_with_cli(req):
    """Process request using local Claude CLI with selected model."""
    req_id = req['id']
    request_text = req['text']

    # Use mode/model from request, fallback to settings
    model = req.get('model') or get_settings().get('model', 'claude-sonnet-4-20250514')

    # Map API model names to CLI model names
    model_map = {
        'claude-sonnet-4-20250514': 'sonnet',
        'claude-opus-4-20250514': 'opus',
        'claude-3-5-sonnet-20241022': 'sonnet',
        'claude-3-5-haiku-20241022': 'haiku',
    }
    cli_model = model_map.get(model, 'sonnet')

    print(f"\n{'='*60}")
    print(f"Processing request #{req_id} via Local CLI ({cli_model})")
    print(f"Request: {request_text[:50]}...")
    if req.get('parent_id'):
        print(f"Continuation of: #{req.get('parent_id')}")
    print(f"{'='*60}\n")

    # Mark as processing
    database.update_claude_request(req_id, 'processing')
    database.add_claude_log(req_id, f'Processing via Local Claude CLI with model: {cli_model}', 'info')

    # Build context from parent if this is a restart
    context_summary = build_context_summary(req)

    # Build the prompt for Claude Code
    prompt = f"""You are processing a user request from the Incept dashboard.

REQUEST #{req_id}:
{request_text}
{context_summary}

IMPORTANT INSTRUCTIONS:
1. This request is for the Telegram monitoring dashboard project in this directory
2. Make the requested changes to the codebase
3. After making changes, call the log_progress function to update status
4. When done, summarize what you did
5. DO NOT commit or push to git - the system will handle git operations automatically after you finish

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

Now process the request. Remember: DO NOT run any git commands."""

    try:
        # Run Claude Code with the prompt and selected model
        database.add_claude_log(req_id, f'Starting Claude Code CLI with --model {cli_model}...', 'info')

        result = subprocess.run(
            [
                'claude',
                '-p', prompt,
                '--model', cli_model,
                '--dangerously-skip-permissions'
            ],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=1200  # 20 minute timeout
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

            # Handle git commit based on auto_push setting
            if should_auto_push(req):
                git_commit_and_push(req_id, f'Incept #{req_id}: {request_text[:50]}')
            else:
                # Commit locally but don't push
                git_commit_only(req_id, f'Incept #{req_id}: {request_text[:50]}')

            print(f"Request #{req_id} completed successfully")
            return True
        else:
            error_msg = result.stderr[:500] if result.stderr else result.stdout[:500] if result.stdout else 'Unknown error'
            database.add_claude_log(req_id, f'Error: {error_msg}', 'error')
            database.update_claude_request(req_id, 'error', error_msg)
            print(f"Request #{req_id} failed: {error_msg}")
            return False

    except subprocess.TimeoutExpired:
        database.add_claude_log(req_id, 'Request timed out after 20 minutes', 'error')
        database.update_claude_request(req_id, 'error', 'Timeout after 20 minutes')
        print(f"Request #{req_id} timed out")
        return False
    except FileNotFoundError:
        database.add_claude_log(req_id, 'Claude CLI not found - is it installed?', 'error')
        database.update_claude_request(req_id, 'error', 'Claude CLI not found')
        print("Error: 'claude' command not found. Make sure Claude Code CLI is installed.")
        return False
    except Exception as e:
        database.add_claude_log(req_id, f'Unexpected error: {str(e)}', 'error')
        database.update_claude_request(req_id, 'error', str(e))
        print(f"Request #{req_id} error: {e}")
        return False


def process_with_cli_token(req):
    """Process request using Claude CLI with OAuth token (for Render/headless).

    This uses your Max membership (unlimited usage) instead of API credits.
    The OAuth token is obtained by running 'claude setup-token' locally.

    IMPORTANT: We must ensure NO API key is accessible to the CLI, otherwise
    it will prefer API mode over OAuth. This includes:
    - Environment variables (ANTHROPIC_API_KEY, CLAUDE_API_KEY)
    - Config file settings
    """
    req_id = req['id']

    # Check for OAuth token (env var takes priority, then config.py)
    oauth_token = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN') or getattr(config, 'CLAUDE_CODE_OAUTH_TOKEN', '')
    if not oauth_token:
        database.add_claude_log(req_id, 'CLAUDE_CODE_OAUTH_TOKEN not set. Run: claude setup-token', 'error')
        database.update_claude_request(req_id, 'error', 'CLAUDE_CODE_OAUTH_TOKEN not configured')
        return False

    # Save any API keys so we can restore them after
    saved_env_vars = {}
    api_key_vars = [
        'ANTHROPIC_API_KEY',
        'CLAUDE_API_KEY',
        'ANTHROPIC_AUTH_TOKEN',
    ]

    for var in api_key_vars:
        if var in os.environ:
            saved_env_vars[var] = os.environ.pop(var)

    # Ensure the OAuth token is set in environment
    os.environ['CLAUDE_CODE_OAUTH_TOKEN'] = oauth_token

    database.add_claude_log(req_id, 'Using CLI with OAuth token (Max membership - no API credits)', 'info')
    database.add_claude_log(req_id, f'Cleared {len(saved_env_vars)} API key env vars to force OAuth mode', 'info')

    try:
        # Run CLI with explicit print mode
        return process_with_cli_oauth(req)
    finally:
        # Restore saved environment variables for other modes
        for var, value in saved_env_vars.items():
            os.environ[var] = value


def process_with_cli_oauth(req):
    """Process request using Claude CLI specifically for OAuth mode.

    This is a specialized version that ensures OAuth authentication is used.
    """
    req_id = req['id']
    request_text = req['text']

    # Use mode/model from request, fallback to settings
    model = req.get('model') or get_settings().get('model', 'claude-sonnet-4-20250514')

    # Map API model names to CLI model names
    model_map = {
        'claude-sonnet-4-20250514': 'sonnet',
        'claude-opus-4-20250514': 'opus',
        'claude-3-5-sonnet-20241022': 'sonnet',
        'claude-3-5-haiku-20241022': 'haiku',
    }
    cli_model = model_map.get(model, 'sonnet')

    print(f"\n{'='*60}")
    print(f"Processing request #{req_id} via CLI OAuth ({cli_model})")
    print(f"Request: {request_text[:50]}...")
    print(f"{'='*60}\n")

    # Mark as processing
    database.update_claude_request(req_id, 'processing')
    database.add_claude_log(req_id, f'Processing via CLI OAuth with model: {cli_model}', 'info')

    # Build context from parent if this is a restart
    context_summary = build_context_summary(req)

    # Build the prompt for Claude Code
    prompt = f"""You are processing a user request from the Incept dashboard.

REQUEST #{req_id}:
{request_text}
{context_summary}

IMPORTANT INSTRUCTIONS:
1. This request is for the Telegram monitoring dashboard project in this directory
2. Make the requested changes to the codebase
3. After making changes, call the log_progress function to update status
4. When done, summarize what you did
5. DO NOT commit or push to git - the system will handle git operations automatically after you finish

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

Now process the request. Remember: DO NOT run any git commands."""

    try:
        # Run Claude Code with the prompt and selected model
        # Using explicit environment to ensure OAuth token is used
        database.add_claude_log(req_id, f'Starting Claude Code CLI (OAuth mode) with --model {cli_model}...', 'info')

        # Build a clean environment with only OAuth token, no API keys
        clean_env = os.environ.copy()
        # Double-check no API keys are present
        for key in ['ANTHROPIC_API_KEY', 'CLAUDE_API_KEY', 'ANTHROPIC_AUTH_TOKEN']:
            clean_env.pop(key, None)

        result = subprocess.run(
            [
                'claude',
                '-p', prompt,
                '--model', cli_model,
                '--dangerously-skip-permissions'
            ],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=1200,  # 20 minute timeout
            env=clean_env  # Use clean environment
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

            # Handle git commit based on auto_push setting
            if should_auto_push(req):
                git_commit_and_push(req_id, f'Incept #{req_id}: {request_text[:50]}')
            else:
                # Commit locally but don't push
                git_commit_only(req_id, f'Incept #{req_id}: {request_text[:50]}')

            print(f"Request #{req_id} completed successfully via OAuth")
            return True
        else:
            error_msg = result.stderr[:500] if result.stderr else result.stdout[:500] if result.stdout else 'Unknown error'

            # Check for API credit errors - this means OAuth isn't being used properly
            if 'credit balance' in error_msg.lower() or 'api key' in error_msg.lower():
                database.add_claude_log(req_id, 'ERROR: CLI is still using API mode instead of OAuth. Check Claude CLI configuration.', 'error')
                database.add_claude_log(req_id, 'Try running "claude /logout" then "claude /login" on the server to reset auth.', 'warning')

            database.add_claude_log(req_id, f'Error: {error_msg}', 'error')
            database.update_claude_request(req_id, 'error', error_msg)
            print(f"Request #{req_id} failed: {error_msg}")
            return False

    except subprocess.TimeoutExpired:
        database.add_claude_log(req_id, 'Request timed out after 20 minutes', 'error')
        database.update_claude_request(req_id, 'error', 'Timeout after 20 minutes')
        print(f"Request #{req_id} timed out")
        return False
    except FileNotFoundError:
        database.add_claude_log(req_id, 'Claude CLI not found - is it installed?', 'error')
        database.update_claude_request(req_id, 'error', 'Claude CLI not found')
        print("Error: 'claude' command not found. Make sure Claude Code CLI is installed.")
        return False
    except Exception as e:
        database.add_claude_log(req_id, f'Unexpected error: {str(e)}', 'error')
        database.update_claude_request(req_id, 'error', str(e))
        print(f"Request #{req_id} error: {e}")
        return False


def check_queue_empty_and_push():
    """Check if queue is empty and push_queue_at_end is enabled - if so, push all commits."""
    if not database.is_push_queue_at_end():
        return False

    # Check if queue is truly empty (no queued, no implementing)
    queue_status = database.get_improvements_queue_status()
    if queue_status['queued'] > 0 or queue_status['implementing'] > 0:
        return False  # Still work in queue

    # Queue is empty - push all accumulated commits
    print(f"\n{'='*60}")
    print("  [Push Queue at End] Queue complete - pushing all commits...")
    print(f"{'='*60}\n")

    import subprocess
    import os
    repo_path = os.path.dirname(__file__)

    try:
        # Check for unpushed commits
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        current_branch = branch_result.stdout.strip()

        unpushed_result = subprocess.run(
            ['git', 'rev-list', '--count', f'origin/{current_branch}..HEAD'],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        unpushed_count = int(unpushed_result.stdout.strip()) if unpushed_result.returncode == 0 else 0

        if unpushed_count == 0:
            print("  No commits to push")
            return True

        # Push all commits
        push_result = subprocess.run(
            ['git', 'push'],
            cwd=repo_path, capture_output=True, text=True, timeout=60
        )

        if push_result.returncode == 0:
            print(f"  Successfully pushed {unpushed_count} commit(s)")
            database.add_system_log('incept_plus', 'push_queue_complete', 'success',
                                   f'Queue complete - pushed {unpushed_count} commit(s)')
            return True
        else:
            print(f"  Push failed: {push_result.stderr}")
            database.add_system_log('incept_plus', 'push_queue_complete', 'error',
                                   f'Push failed: {push_result.stderr[:200]}')
            return False

    except Exception as e:
        print(f"  Error pushing: {e}")
        return False


def process_request(req):
    """Process a single request based on request's mode or current settings."""
    # Use mode from request, fallback to settings
    mode = req.get('mode') or get_settings().get('mode', 'api')

    if mode == 'api':
        result = process_with_api(req)
    elif mode == 'cli_token':
        result = process_with_cli_token(req)
    else:  # 'local' or any other
        result = process_with_cli(req)

    # After processing completes, check if queue is empty and should push
    if result:
        check_queue_empty_and_push()

    return result


def check_and_restart_interrupted():
    """Check for interrupted requests and automatically restart them."""
    interrupted = database.get_interrupted_requests()
    if interrupted:
        print(f"\n{'='*60}")
        print(f"Found {len(interrupted)} interrupted request(s) from previous run")
        print(f"{'='*60}\n")

        for req in interrupted:
            req_id = req['id']
            print(f"  Request #{req_id} was interrupted - creating continuation...")

            # Log the restart
            database.add_claude_log(req_id, 'Request was interrupted (server restart detected). Auto-restarting...', 'warning')

            # Mark original as error status to prevent re-processing
            database.update_claude_request(req_id, 'error', 'Interrupted by server restart. Continued in new request.')

            # Create continuation request with full context
            new_id = database.restart_claude_request(
                req_id,
                mode=req.get('mode'),
                model=req.get('model'),
                auto_push=req.get('auto_push')
            )

            if new_id:
                database.add_claude_log(new_id, f'Auto-restarted from interrupted request #{req_id}', 'info')
                print(f"  Created continuation request #{new_id}")


def build_improvement_context(suggestion):
    """Build full context for an improvement including previous work.

    Returns a detailed prompt with all relevant history for continuation.
    """
    suggestion_id = suggestion['id']

    # Get full context including related requests and logs
    full_context = database.get_improvement_full_context(suggestion_id)

    context_parts = [
        f"IMPROVEMENT #{suggestion_id}: {suggestion['title']}",
        "=" * 60,
        "",
        f"Description: {suggestion['description']}",
        "",
        "Implementation Details:",
        suggestion.get('implementation_details', 'No specific details provided'),
        "",
        f"Category: {suggestion.get('category', 'general')}",
        f"Priority: {suggestion.get('priority', 3)}",
        f"Estimated Effort: {suggestion.get('estimated_effort', 'unknown')}",
    ]

    # Add previous work context if any
    if full_context and full_context.get('related_requests'):
        context_parts.extend([
            "",
            "=" * 60,
            "PREVIOUS WORK ON THIS IMPROVEMENT:",
            "=" * 60,
        ])

        for req in full_context['related_requests']:
            context_parts.extend([
                "",
                f"--- Request #{req['id']} ({req['status']}) ---",
                f"Created: {req.get('created_at', 'unknown')}",
            ])

            # Add logs from this request
            if req.get('logs'):
                context_parts.append("Logs:")
                for log in req['logs'][-20:]:  # Last 20 logs
                    level = log.get('level', 'info').upper()
                    msg = log.get('message', '')[:200]
                    context_parts.append(f"  [{level}] {msg}")

            # Add response summary if completed
            if req.get('response'):
                response_preview = req['response'][:500]
                context_parts.extend([
                    "Response summary:",
                    f"  {response_preview}..."
                ])

    # Add dependencies if any
    if suggestion.get('dependencies'):
        context_parts.extend([
            "",
            f"Dependencies: {suggestion['dependencies']}",
        ])

    return "\n".join(context_parts)


def check_and_continue_implementing_improvements():
    """Check for improvements that were being implemented when the process stopped.

    Creates continuation requests with FULL CONTEXT to complete any
    improvements that were interrupted (status='implementing').
    """
    implementing = database.get_incept_suggestions(status='implementing')
    if implementing:
        print(f"\n{'='*60}")
        print(f"Found {len(implementing)} uncompleted improvement(s) from previous run")
        print(f"{'='*60}\n")

        # Get current settings for new requests
        incept_settings = database.get_incept_settings()
        mode = incept_settings.get('mode', 'api')
        model = incept_settings.get('model', 'claude-sonnet-4-20250514')

        for suggestion in implementing:
            suggestion_id = suggestion['id']
            print(f"  Improvement #{suggestion_id}: {suggestion['title'][:50]}...")

            # Build FULL context from previous work
            full_context = build_improvement_context(suggestion)

            # Build continuation request
            request_text = f"""CONTINUATION: Complete the following improvement that was interrupted.

{full_context}

================================================================================
INSTRUCTIONS:
================================================================================

This improvement was being implemented when the server was restarted/interrupted.

IMPORTANT STEPS:
1. Review the previous work context above to understand what has been done
2. Check the current state of files using Read tool
3. Check recent git commits to see what was already committed
4. CONTINUE from where the previous work left off - do NOT repeat completed work
5. Complete any remaining implementation
6. Test that the changes work correctly
7. Ensure all code is properly formatted and follows project conventions

When complete, summarize what was already done vs what you completed."""

            # Check push settings
            batch_mode = database.is_incept_batch_mode()
            push_queue_at_end = database.is_push_queue_at_end()
            auto_push = not (batch_mode or push_queue_at_end)

            # Create continuation request
            req_id = database.add_claude_request(
                request_text,
                mode=mode,
                model=model,
                auto_push=auto_push
            )

            database.add_claude_log(
                req_id,
                f'Auto-continuing interrupted improvement #{suggestion_id}: {suggestion["title"]}',
                'info'
            )

            print(f"  Created continuation request #{req_id} for improvement #{suggestion_id}")


def process_next_queued_improvement():
    """Process the next improvement from the queue.

    This function:
    1. Checks if queue is paused
    2. Atomically claims the next improvement
    3. Creates an incept request with full context
    4. The request will auto-push when complete

    Returns True if an improvement was queued for processing, False otherwise.
    """
    # Check if queue is paused
    if database.is_improvements_queue_paused():
        return False

    # Check if there are any pending incept requests (don't start new improvement
    # if there's other work in progress)
    pending = database.get_pending_claude_requests()
    if pending:
        return False

    # Also check if any improvement is currently being processed
    implementing = database.get_incept_suggestions(status='implementing')
    if implementing:
        return False

    # Atomically claim the next improvement
    suggestion = database.claim_next_improvement()
    if not suggestion:
        return False

    suggestion_id = suggestion['id']
    print(f"\n{'='*60}")
    print(f"Processing queued improvement #{suggestion_id}: {suggestion['title'][:50]}...")
    print(f"{'='*60}\n")

    # Get current settings
    incept_settings = database.get_incept_settings()
    mode = incept_settings.get('mode', 'api')
    model = incept_settings.get('model', 'claude-sonnet-4-20250514')

    # Build full context
    full_context = build_improvement_context(suggestion)

    # Create the implementation request
    request_text = f"""IMPLEMENT IMPROVEMENT: Please implement the following improvement.

{full_context}

================================================================================
INSTRUCTIONS:
================================================================================

Implement this improvement completely. Follow these steps:

1. Read and understand the existing codebase structure
2. Plan the implementation approach
3. Make the necessary code changes
4. Test that your changes work correctly
5. Ensure code follows project conventions
6. Update any related documentation if needed

After completing the implementation:
- Summarize what you implemented
- List all files that were changed
- Note any follow-up improvements that might be needed

The changes will be automatically committed when complete."""

    # Check push settings
    batch_mode = database.is_incept_batch_mode()
    push_queue_at_end = database.is_push_queue_at_end()

    # Don't auto-push if batch_mode OR push_queue_at_end is enabled
    auto_push = not (batch_mode or push_queue_at_end)

    if batch_mode:
        print(f"  [Batch Mode] Will commit but NOT push - use 'Push All' when ready")
    elif push_queue_at_end:
        print(f"  [Push Queue at End] Will commit but defer push until queue is empty")

    # Create request with appropriate auto_push setting
    req_id = database.add_claude_request(
        request_text,
        mode=mode,
        model=model,
        auto_push=auto_push
    )

    database.add_claude_log(
        req_id,
        f'Processing improvement #{suggestion_id} from queue: {suggestion["title"]}',
        'info'
    )

    print(f"  Created request #{req_id} for improvement #{suggestion_id}")
    return True


def get_queue_status_summary():
    """Get a summary of the improvements queue status."""
    status = database.get_improvements_queue_status()
    paused = database.is_improvements_queue_paused()

    return {
        **status,
        'paused': paused,
        'total_in_queue': status['queued'] + status['implementing']
    }


def main():
    """Main polling loop.

    PROCESSING ORDER:
    1. On startup: Continue interrupted requests and improvements
    2. During loop:
       a. Process pending incept requests first (user-submitted)
       b. When no pending requests, process improvements queue
       c. Improvements are processed one-at-a-time with auto-push
    """
    print("Incept Request Processor")
    print("=" * 40)
    print(f"Project dir: {PROJECT_DIR}")
    print(f"Poll interval: {POLL_INTERVAL}s")

    settings = get_settings()
    print(f"Mode: {settings.get('mode', 'api')}")
    print(f"Model: {settings.get('model', 'claude-sonnet-4-20250514')}")

    # Check auth status
    oauth_token = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN') or getattr(config, 'CLAUDE_CODE_OAUTH_TOKEN', '')
    if oauth_token:
        print("OAuth Token: Set (CLI Token mode available)")
    else:
        print("OAuth Token: Not set (run 'claude setup-token' to enable)")

    if os.environ.get('ANTHROPIC_API_KEY'):
        print("API Key: Set (API mode available)")
    else:
        print("API Key: Not set")

    print("Waiting for requests...")
    print("=" * 40)

    # Initialize database
    database.init_db()

    # Check for interrupted requests on startup and auto-restart them
    check_and_restart_interrupted()

    # Check for uncompleted improvements and create continuation requests
    check_and_continue_implementing_improvements()

    # Print initial queue status
    queue_status = get_queue_status_summary()
    if queue_status['total_in_queue'] > 0:
        print(f"\nImprovements Queue: {queue_status['queued']} queued, {queue_status['implementing']} implementing")
        if queue_status['paused']:
            print("  Queue is PAUSED - improvements will not be processed")
        if queue_status['current']:
            print(f"  Currently implementing: #{queue_status['current']['id']} - {queue_status['current']['title'][:40]}")
        if queue_status['next']:
            print(f"  Next in queue: #{queue_status['next']['id']} - {queue_status['next']['title'][:40]}")

    last_queue_check = 0
    QUEUE_CHECK_INTERVAL = 30  # Check queue every 30 seconds when idle

    while True:
        try:
            # STEP 1: Process pending incept requests first (user-submitted work)
            claimed = database.claim_pending_request()

            if claimed:
                print(f"\nClaimed request #{claimed['id']}")
                # Refresh settings before processing
                settings = get_settings()
                print(f"Current mode: {settings.get('mode', 'api')}")
                # Process the claimed request
                process_request(claimed)

                # After completing a request, immediately check for more
                continue

            # STEP 2: No pending requests - check improvements queue
            current_time = time.time()
            if current_time - last_queue_check >= QUEUE_CHECK_INTERVAL:
                last_queue_check = current_time

                # Try to process next improvement from queue
                if process_next_queued_improvement():
                    # Improvement was queued - it will create an incept request
                    # Continue loop to process it
                    continue

                # Print queue status periodically when idle
                queue_status = get_queue_status_summary()
                if queue_status['total_in_queue'] > 0 and not queue_status['paused']:
                    print(f"\nQueue: {queue_status['queued']} waiting, {queue_status['implementing']} implementing")

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\nStopping processor...")
            # Mark any processing requests as interrupted
            processing = database.get_claude_requests(limit=100)
            for req in processing:
                if req['status'] == 'processing':
                    database.mark_request_interrupted(req['id'])
                    print(f"Marked request #{req['id']} as interrupted")
            break
        except Exception as e:
            print(f"Error in main loop: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
