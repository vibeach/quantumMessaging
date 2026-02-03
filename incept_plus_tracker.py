"""
Incept+ Improvement Tracker
Tracks implemented improvements and manages feature flags and rollbacks.
"""

import subprocess
import json
import database
from datetime import datetime


def get_latest_commit_hash():
    """Get the hash of the latest git commit."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        print(f"Error getting commit hash: {e}")
    return None


def get_changed_files_in_commit(commit_hash):
    """Get list of files changed in a specific commit."""
    try:
        result = subprocess.run(
            ['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', commit_hash],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip().split('\n')
    except Exception as e:
        print(f"Error getting changed files: {e}")
    return []


def track_improvement_implementation(suggestion_id, request_id):
    """
    Track an improvement that was just implemented.
    Call this after an Incept request completes successfully.

    Args:
        suggestion_id: ID of the suggestion that was implemented
        request_id: ID of the Incept request that implemented it

    Returns:
        improvement_id if successful, None otherwise
    """
    # Get suggestion details
    suggestion = database.get_incept_suggestion(suggestion_id)
    if not suggestion:
        return None

    # Get the request details
    request = database.get_claude_request(request_id)
    if not request or request['status'] != 'completed':
        return None

    # Get the commit hash
    commit_hash = get_latest_commit_hash()
    files_changed = []

    if commit_hash:
        files_changed = get_changed_files_in_commit(commit_hash)

    # Create rollback info
    rollback_info = {
        'commit_hash': commit_hash,
        'previous_commit': None,  # Could be determined by git log
        'files_changed': files_changed,
        'request_id': request_id,
        'implementation_date': datetime.utcnow().isoformat()
    }

    # Add improvement record (returns tuple of (id, unique_id))
    improvement_id, unique_id = database.add_incept_improvement(
        suggestion_id=suggestion_id,
        title=suggestion['title'],
        description=suggestion['description'],
        implementation_summary=request.get('response', 'Implemented via Incept'),
        commit_hash=commit_hash,
        files_changed=json.dumps(files_changed),
        feature_flag=None,  # Could be auto-generated
        rollback_info=json.dumps(rollback_info)
    )

    # Update suggestion status
    database.update_incept_suggestion_status(suggestion_id, 'implemented')

    return improvement_id, unique_id


def rollback_improvement(improvement_id):
    """
    Rollback an improvement by reverting to the commit before it was implemented.

    Args:
        improvement_id: ID of the improvement to rollback

    Returns:
        (success: bool, message: str)
    """
    improvement = database.get_incept_improvement(improvement_id)
    if not improvement:
        return False, "Improvement not found"

    if not improvement['enabled']:
        return False, "Improvement is already disabled"

    # Parse rollback info
    try:
        rollback_info = json.loads(improvement['rollback_info']) if improvement['rollback_info'] else {}
    except:
        rollback_info = {}

    commit_hash = improvement.get('commit_hash') or rollback_info.get('commit_hash')

    if not commit_hash:
        # If no commit hash, just disable it logically
        database.toggle_incept_improvement(improvement_id, False)
        return True, "Improvement disabled (no commit hash available for revert)"

    try:
        # Create a revert commit
        result = subprocess.run(
            ['git', 'revert', '--no-commit', commit_hash],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return False, f"Git revert failed: {result.stderr}"

        # Commit the revert
        commit_msg = f"Revert improvement: {improvement['title']}\n\nReverting commit {commit_hash[:7]}"
        result = subprocess.run(
            ['git', 'commit', '-m', commit_msg],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            # Try to abort the revert
            subprocess.run(['git', 'revert', '--abort'], capture_output=True)
            return False, f"Git commit failed: {result.stderr}"

        # Disable the improvement
        database.toggle_incept_improvement(improvement_id, False)

        return True, f"Improvement reverted successfully. Revert commit created."

    except subprocess.TimeoutExpired:
        return False, "Git command timed out"
    except Exception as e:
        return False, f"Error during rollback: {str(e)}"


def generate_feature_flag_name(suggestion_id):
    """Generate a feature flag name for a suggestion."""
    suggestion = database.get_incept_suggestion(suggestion_id)
    if not suggestion:
        return None

    # Convert title to snake_case
    title = suggestion['title'].lower()
    title = ''.join(c if c.isalnum() or c == ' ' else ' ' for c in title)
    title = '_'.join(title.split())

    return f"incept_plus_{suggestion_id}_{title[:30]}"


def check_improvement_status(improvement_id):
    """
    Check if an improvement is currently active/enabled.

    Args:
        improvement_id: ID of the improvement

    Returns:
        dict with status information
    """
    improvement = database.get_incept_improvement(improvement_id)
    if not improvement:
        return {'exists': False}

    return {
        'exists': True,
        'enabled': bool(improvement['enabled']),
        'title': improvement['title'],
        'implemented_at': improvement['created_at'],
        'disabled_at': improvement.get('disabled_at'),
        'commit_hash': improvement.get('commit_hash'),
        'has_rollback_info': bool(improvement.get('rollback_info'))
    }


def list_improvements_summary():
    """Get a summary of all improvements."""
    improvements = database.get_incept_improvements(limit=1000)

    summary = {
        'total': len(improvements),
        'enabled': sum(1 for i in improvements if i['enabled']),
        'disabled': sum(1 for i in improvements if not i['enabled']),
        'with_commits': sum(1 for i in improvements if i.get('commit_hash')),
        'improvements': improvements
    }

    return summary
