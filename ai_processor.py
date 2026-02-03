#!/usr/bin/env python3
"""
AI Auto-Suggestion Processor
Runs in background to automatically generate reply suggestions for new messages.
"""

import time
import logging
import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database
import ai_assistant

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
POLL_INTERVAL = 10  # seconds between checks
MAX_PENDING = 5     # max messages to process per cycle


def process_new_messages():
    """Process messages that don't have suggestions yet."""
    # Get messages without suggestions
    pending = database.get_messages_without_suggestions(limit=MAX_PENDING)

    if not pending:
        return 0

    processed = 0
    for msg in pending:
        if not msg.get('text'):
            continue

        try:
            logger.info(f"Generating suggestions for message {msg['message_id']}: {msg['text'][:50]}...")

            result = ai_assistant.generate_suggestions(
                message_text=msg['text'],
                message_id=msg['message_id']
            )

            if result.get('error'):
                logger.warning(f"Error generating suggestions: {result['error']}")
            else:
                logger.info(f"Generated suggestions using {result.get('tokens_used', 0)} tokens")
                processed += 1

        except Exception as e:
            logger.error(f"Exception processing message {msg['message_id']}: {e}")

    return processed


def run_processor():
    """Main processor loop."""
    logger.info("=" * 50)
    logger.info("AI Auto-Suggestion Processor")
    logger.info("=" * 50)
    logger.info(f"Poll interval: {POLL_INTERVAL}s")
    logger.info("Waiting for new messages...")
    logger.info("=" * 50)

    # Initialize
    database.init_db()
    ai_assistant.ensure_default_prompts()

    if not ai_assistant.init_client():
        logger.error("Failed to initialize AI client. Check ANTHROPIC_API_KEY.")
        logger.info("Processor will continue but won't generate suggestions.")

    while True:
        try:
            processed = process_new_messages()
            if processed > 0:
                logger.info(f"Processed {processed} message(s)")

        except KeyboardInterrupt:
            logger.info("Stopping processor...")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    run_processor()
