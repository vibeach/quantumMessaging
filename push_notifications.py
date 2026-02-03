"""
Push Notification Service for iOS PWA and Web Push.

Implements Web Push Protocol (RFC 8030) with VAPID authentication.
"""

import json
import logging
from pywebpush import webpush, WebPushException

import config
import database

logger = logging.getLogger(__name__)


def send_push_notification(title: str, body: str, icon: str = None, badge: str = None, tag: str = None, badge_count: int = None):
    """Send push notification to all active subscribers.

    Args:
        title: Notification title
        body: Notification body text
        icon: URL to notification icon
        badge: URL to badge icon (shown in status bar)
        tag: Tag to group/replace notifications
        badge_count: Number to show on app icon (None = auto from unread count)

    Returns:
        dict with success count and failures
    """
    subscriptions = database.get_active_push_subscriptions()

    if not subscriptions:
        logger.info("No active push subscriptions")
        return {"success": 0, "failed": 0, "total": 0}

    # Get badge count from unread messages if not specified
    if badge_count is None:
        try:
            badge_count = database.get_unread_count()
        except Exception:
            badge_count = 0

    # Check if badge is enabled in settings
    badge_enabled = database.get_setting('badge_enabled', 'true') == 'true'

    # Build notification payload
    payload = json.dumps({
        "title": title,
        "body": body,
        "icon": icon or "/static/ha-icon.svg",
        "badge": badge or "/static/ha-icon.svg",
        "tag": tag or "home-assistant",
        "requireInteraction": False,
        "silent": False,
        "badgeCount": badge_count if badge_enabled else 0
    })

    # VAPID claims
    vapid_claims = {
        "sub": config.VAPID_CLAIMS_EMAIL
    }

    success_count = 0
    failed_count = 0

    for sub in subscriptions:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {
                "p256dh": sub["p256dh"],
                "auth": sub["auth"]
            }
        }

        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=config.VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims
            )
            success_count += 1
            logger.debug(f"Push sent to {sub['endpoint'][:50]}...")
        except WebPushException as e:
            failed_count += 1
            logger.warning(f"Push failed for {sub['endpoint'][:50]}...: {e}")

            # If subscription is no longer valid, deactivate it
            if e.response and e.response.status_code in (404, 410):
                logger.info(f"Deactivating invalid subscription: {sub['endpoint'][:50]}...")
                database.deactivate_push_subscription(sub["endpoint"])
        except Exception as e:
            failed_count += 1
            logger.error(f"Push error: {type(e).__name__}: {e}")

    result = {
        "success": success_count,
        "failed": failed_count,
        "total": len(subscriptions)
    }
    logger.info(f"Push notifications sent: {result}")
    return result


def send_new_message_notification(sender_name: str, message_preview: str):
    """Send notification for a new message.

    Args:
        sender_name: Name of the message sender (unused for obfuscation)
        message_preview: Preview of the message text (obfuscated)
    """
    return send_push_notification(
        title="Home Assistant",
        body=message_preview,
        tag="new-message"
    )


def get_vapid_public_key():
    """Get the VAPID public key for client-side subscription."""
    return config.VAPID_PUBLIC_KEY
