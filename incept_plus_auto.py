"""
Incept+ Auto-Mode Worker
Continuously generates and implements improvements when auto-mode is active.
"""

import time
import logging
import database
import incept_plus_suggester
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def process_auto_mode_session(session):
    """Process a single auto-mode session iteration.

    NOTE: Processes improvements ONE AT A TIME to avoid race conditions.
    Only creates one new request per iteration to ensure sequential processing.
    """
    session_id = session['id']
    direction = session['direction']
    max_suggestions = session['max_suggestions']
    current_count = session['suggestions_generated']

    logger.info(f"Processing auto-mode session {session_id}: {current_count}/{max_suggestions}")

    # Check if we've reached the limit
    if current_count >= max_suggestions:
        logger.info(f"Session {session_id} reached max suggestions, completing")
        database.update_incept_auto_session(session_id, status='completed')
        return False

    # RACE CONDITION PREVENTION: Check if there are any pending or processing requests
    # Only create new improvement requests when the queue is empty
    pending_requests = database.get_claude_requests(limit=10)
    active_requests = [r for r in pending_requests if r['status'] in ('pending', 'claimed', 'processing')]

    if active_requests:
        logger.info(f"Session {session_id}: Waiting for {len(active_requests)} active request(s) to complete before creating new improvements")
        # Don't create new requests until current ones are done
        return True

    try:
        # Generate suggestions - but only create ONE request at a time for sequential processing
        logger.info(f"Generating suggestions for direction: {direction}")
        suggestions = incept_plus_suggester.generate_and_save_suggestions(
            direction=direction,
            context=f"Auto-mode session {session_id}, iteration {current_count + 1}",
            max_suggestions=min(1, max_suggestions - current_count)  # Generate ONE at a time for sequential processing
        )

        # Auto-accept all suggestions in auto-mode
        for suggestion in suggestions:
            suggestion_id = suggestion['id']
            database.update_incept_suggestion_status(suggestion_id, 'accepted')

            # Create Incept request to implement it
            request_text = f"""Implement the following improvement (Auto-Mode):

Title: {suggestion['title']}

Description: {suggestion['description']}

Implementation Details:
{suggestion['implementation_details']}

Category: {suggestion['category']}
Estimated Effort: {suggestion.get('estimated_effort', 'unknown')}
"""

            # Get settings for Incept
            incept_settings = database.get_incept_settings()
            mode = incept_settings.get('mode', 'api')
            model = incept_settings.get('model', 'claude-sonnet-4-20250514')

            # Add the request
            req_id = database.add_claude_request(request_text, mode=mode, model=model, auto_push=True)
            logger.info(f"Created Incept request {req_id} for suggestion {suggestion_id}")

            # Update suggestion status
            database.update_incept_suggestion_status(suggestion_id, 'implementing')

        # Update session progress
        new_count = current_count + len(suggestions)
        database.update_incept_auto_session(
            session_id,
            suggestions_generated=new_count,
            suggestions_implemented=new_count  # Since we auto-accept in auto-mode
        )

        logger.info(f"Session {session_id} progress: {new_count}/{max_suggestions}")
        return True

    except Exception as e:
        logger.error(f"Error in auto-mode session {session_id}: {e}")
        database.update_incept_auto_session(session_id, status='error')
        return False


def run_auto_mode_worker(interval=60):
    """
    Run the auto-mode worker loop.

    Args:
        interval: Seconds between checks (default 60)
    """
    logger.info("Starting Incept+ auto-mode worker")

    while True:
        try:
            # Check for active auto-mode session
            session = database.get_active_incept_auto_session()

            if session:
                logger.info(f"Found active session: {session['id']}")
                process_auto_mode_session(session)
            else:
                logger.debug("No active auto-mode session")

            # Wait before next check
            time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Auto-mode worker stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in auto-mode worker: {e}")
            time.sleep(interval)


if __name__ == '__main__':
    # Get settings
    settings = database.get_incept_plus_settings()
    interval = settings.get('auto_mode_interval', 300)  # Default 5 minutes

    run_auto_mode_worker(interval=interval)
