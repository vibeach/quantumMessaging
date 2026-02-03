#!/usr/bin/env python3
"""
Media Transcription Module
Uses Telegram's built-in transcription for voice/video messages.
"""

import logging
import asyncio

logger = logging.getLogger(__name__)


async def transcribe_with_telegram(client, message, max_retries=5):
    """
    Transcribe a voice/video_note message using Telegram's built-in transcription.

    Note: Only works for voice messages and video_note (circles), not regular videos.

    Args:
        client: Telethon client
        message: The message object with voice/video_note
        max_retries: Maximum number of retries for pending transcription

    Returns:
        Transcript text or None if failed/not available
    """
    try:
        from telethon.tl.functions.messages import TranscribeAudioRequest

        # Get the peer
        peer = await client.get_input_entity(message.chat_id)

        # Request transcription
        result = await client(TranscribeAudioRequest(
            peer=peer,
            msg_id=message.id
        ))

        if result and hasattr(result, 'text') and result.text:
            logger.info(f"Telegram transcription: {result.text[:50]}...")
            return result.text

        # If pending, retry with exponential backoff
        if hasattr(result, 'pending') and result.pending:
            for attempt in range(max_retries):
                wait_time = 2 * (attempt + 1)  # 2, 4, 6, 8, 10 seconds
                logger.info(f"Transcription pending, retry {attempt + 1}/{max_retries} in {wait_time}s...")
                await asyncio.sleep(wait_time)

                result = await client(TranscribeAudioRequest(
                    peer=peer,
                    msg_id=message.id
                ))

                if result and hasattr(result, 'text') and result.text:
                    logger.info(f"Telegram transcription: {result.text[:50]}...")
                    return result.text

                # If no longer pending but still no text, stop retrying
                if not (hasattr(result, 'pending') and result.pending):
                    break

        return None

    except Exception as e:
        logger.error(f"Telegram transcription error: {e}")
        return None


async def get_existing_transcription(client, message):
    """
    Check if a message already has a transcription from Telegram.
    Some messages come with transcription already done.
    """
    try:
        # Check if the message has transcription attribute
        if hasattr(message, 'voice_transcription') and message.voice_transcription:
            return message.voice_transcription

        # For video notes and voice messages, try to get transcription
        if message.voice or message.video_note:
            return await transcribe_with_telegram(client, message)

        return None
    except Exception as e:
        logger.error(f"Error getting transcription: {e}")
        return None


def transcribe_media_sync(client, message):
    """
    Synchronous wrapper for transcription (for use in non-async contexts).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create a new task if loop is already running
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    get_existing_transcription(client, message)
                )
                return future.result(timeout=30)
        else:
            return loop.run_until_complete(get_existing_transcription(client, message))
    except Exception as e:
        logger.error(f"Sync transcription error: {e}")
        return None
