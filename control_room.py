#!/usr/bin/env python3
"""
Control Room Integration Service
Connects to Control Room API for health, mood, social, intimate, and extra data.
"""

import os
import logging
import requests
from functools import lru_cache
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Configuration
CONTROL_ROOM_API_KEY = os.environ.get('CONTROL_ROOM_API_KEY', '')
CONTROL_ROOM_BASE_URL = os.environ.get('CONTROL_ROOM_BASE_URL', 'https://control-room.onrender.com')
CONTROL_ROOM_WEBHOOK_SECRET = os.environ.get('CONTROL_ROOM_WEBHOOK_SECRET', '')

# Cache timeout (seconds)
CACHE_TIMEOUT = 300  # 5 minutes

# Last fetch timestamp for cache invalidation
_cache_timestamps = {}


def is_configured():
    """Check if Control Room integration is configured."""
    return bool(CONTROL_ROOM_API_KEY)


def get_headers():
    """Get authorization headers for API requests."""
    return {
        'Authorization': f'Bearer {CONTROL_ROOM_API_KEY}',
        'Content-Type': 'application/json'
    }


def fetch_dashboard_data(days=7):
    """
    Fetch comprehensive dashboard data from Control Room.

    Args:
        days: Number of days for trend data (default: 7)

    Returns:
        dict with stats, trends, and recent entries
    """
    if not is_configured():
        return {'error': 'Control Room not configured', 'configured': False}

    try:
        response = requests.get(
            f'{CONTROL_ROOM_BASE_URL}/api/external/dashboard',
            params={'days': days},
            headers=get_headers(),
            timeout=10
        )

        if response.status_code == 401:
            return {'error': 'Invalid API key', 'configured': True}

        response.raise_for_status()
        return response.json()

    except requests.exceptions.Timeout:
        logger.error("Control Room API timeout")
        return {'error': 'Connection timeout', 'configured': True}
    except requests.exceptions.ConnectionError:
        logger.error("Control Room API connection error")
        return {'error': 'Connection failed', 'configured': True}
    except Exception as e:
        logger.error(f"Control Room API error: {e}")
        return {'error': str(e), 'configured': True}


def fetch_entries(entry_type=None, limit=50, offset=0, since=None):
    """
    Fetch entries from Control Room.

    Args:
        entry_type: Filter by type (health, intimate, social, mood, extra) or None for all
        limit: Max entries to return
        offset: Pagination offset
        since: ISO timestamp to fetch only newer entries

    Returns:
        dict with entries for each type
    """
    if not is_configured():
        return {'error': 'Control Room not configured', 'configured': False}

    try:
        params = {'limit': limit, 'offset': offset}
        if entry_type:
            params['type'] = entry_type
        if since:
            params['since'] = since

        response = requests.get(
            f'{CONTROL_ROOM_BASE_URL}/api/external/entries',
            params=params,
            headers=get_headers(),
            timeout=10
        )

        if response.status_code == 401:
            return {'error': 'Invalid API key', 'configured': True}

        response.raise_for_status()
        return response.json()

    except requests.exceptions.Timeout:
        return {'error': 'Connection timeout', 'configured': True}
    except requests.exceptions.ConnectionError:
        return {'error': 'Connection failed', 'configured': True}
    except Exception as e:
        logger.error(f"Control Room entries error: {e}")
        return {'error': str(e), 'configured': True}


def fetch_schema():
    """
    Fetch the complete data schema from Control Room.

    Returns:
        dict with schema definitions for all entry types
    """
    if not is_configured():
        return {'error': 'Control Room not configured', 'configured': False}

    try:
        response = requests.get(
            f'{CONTROL_ROOM_BASE_URL}/api/external/schema',
            headers=get_headers(),
            timeout=10
        )

        if response.status_code == 401:
            return {'error': 'Invalid API key', 'configured': True}

        response.raise_for_status()
        return response.json()

    except Exception as e:
        logger.error(f"Control Room schema error: {e}")
        return {'error': str(e), 'configured': True}


def verify_webhook_secret(secret):
    """Verify webhook secret matches configured secret."""
    if not CONTROL_ROOM_WEBHOOK_SECRET:
        logger.warning("Webhook secret not configured, accepting all webhooks")
        return True
    return secret == CONTROL_ROOM_WEBHOOK_SECRET


def get_connection_status():
    """
    Check connection to Control Room API.

    Returns:
        dict with status, configured, and optional error
    """
    if not is_configured():
        return {
            'status': 'not_configured',
            'configured': False,
            'message': 'Set CONTROL_ROOM_API_KEY environment variable'
        }

    try:
        response = requests.get(
            f'{CONTROL_ROOM_BASE_URL}/api/external/schema',
            headers=get_headers(),
            timeout=5
        )

        if response.status_code == 200:
            return {
                'status': 'connected',
                'configured': True,
                'base_url': CONTROL_ROOM_BASE_URL
            }
        elif response.status_code == 401:
            return {
                'status': 'auth_failed',
                'configured': True,
                'message': 'Invalid API key'
            }
        else:
            return {
                'status': 'error',
                'configured': True,
                'message': f'HTTP {response.status_code}'
            }

    except requests.exceptions.Timeout:
        return {
            'status': 'timeout',
            'configured': True,
            'message': 'Connection timeout'
        }
    except requests.exceptions.ConnectionError:
        return {
            'status': 'offline',
            'configured': True,
            'message': 'Cannot reach Control Room server'
        }
    except Exception as e:
        return {
            'status': 'error',
            'configured': True,
            'message': str(e)
        }


def format_entry_for_display(entry, entry_type):
    """
    Format a Control Room entry for display in the Lab page.

    Args:
        entry: The entry dict from Control Room
        entry_type: Type of entry (health, mood, social, intimate, extra)

    Returns:
        Formatted dict with display-friendly fields
    """
    formatted = {
        'id': entry.get('id'),
        'timestamp': entry.get('timestamp'),
        'type': entry_type
    }

    if entry_type == 'mood':
        formatted['icon'] = entry.get('overall_mood', '😐')
        formatted['primary'] = f"Energy: {entry.get('energy', '-')}/5"
        formatted['secondary'] = entry.get('highlight', '')
        formatted['details'] = {
            'anxiety': entry.get('anxiety'),
            'stress': entry.get('stress'),
            'gratitude': entry.get('gratitude')
        }

    elif entry_type == 'health':
        formatted['icon'] = '🏥'
        formatted['primary'] = entry.get('meal_type', 'Health entry')
        formatted['secondary'] = f"Water: {entry.get('water', '-')}L, Sleep: {entry.get('sleep_hours', '-')}h"
        formatted['details'] = {
            'portions': entry.get('portions'),
            'exercise_type': entry.get('exercise_type'),
            'exercise_duration': entry.get('exercise_duration')
        }

    elif entry_type == 'social':
        formatted['icon'] = '👥'
        formatted['primary'] = f"{entry.get('people_count', 0)} people"
        formatted['secondary'] = f"Quality hours: {entry.get('quality_hours', 0)}"
        formatted['details'] = {
            'events': entry.get('events'),
            'new_connections': entry.get('new_connections'),
            'loneliness_score': entry.get('loneliness_score')
        }

    elif entry_type == 'intimate':
        formatted['icon'] = '💕'
        formatted['primary'] = f"Intensity: {entry.get('intensity', '-')}/5"
        formatted['secondary'] = f"Duration: {entry.get('duration', '-')} min"
        formatted['details'] = {
            'mood_before': entry.get('mood_before'),
            'mood_after': entry.get('mood_after'),
            'notes': entry.get('notes')
        }

    elif entry_type == 'extra':
        formatted['icon'] = '🎉'
        formatted['primary'] = entry.get('location', 'Party/Event')
        formatted['secondary'] = f"Vibe: {entry.get('vibe_rating', '-')}/5"
        formatted['details'] = {
            'duration_hours': entry.get('duration_hours'),
            'people_count': entry.get('people_count'),
            'highlights': entry.get('highlights')
        }

    return formatted


def get_lab_summary():
    """
    Get a summary of all Control Room data for the Lab dashboard.

    Returns:
        dict with formatted summaries for each category
    """
    if not is_configured():
        return {'configured': False}

    dashboard = fetch_dashboard_data(days=7)
    if 'error' in dashboard:
        return dashboard

    # Get recent entries for each type
    entries = fetch_entries(limit=20)
    if 'error' in entries:
        return entries

    summary = {
        'configured': True,
        'stats': dashboard.get('stats', {}),
        'trends': dashboard.get('trends', {}),
        'recent': {
            'mood': [],
            'health': [],
            'social': [],
            'intimate': [],
            'extra': []
        }
    }

    # Format recent entries
    for entry_type in ['mood', 'health', 'social', 'intimate', 'extra']:
        type_entries = entries.get(entry_type, {}).get('entries', [])
        for entry in type_entries[:5]:
            summary['recent'][entry_type].append(
                format_entry_for_display(entry, entry_type)
            )

    return summary


def get_full_lab_data(days=30):
    """
    Get comprehensive Lab data including full history and chart data.

    Args:
        days: Number of days of history to fetch

    Returns:
        dict with all data needed for the fancy Lab dashboard
    """
    if not is_configured():
        return {'configured': False}

    # Fetch dashboard data for trends
    dashboard = fetch_dashboard_data(days=days)
    if 'error' in dashboard:
        return dashboard

    # Fetch more entries for history
    entries = fetch_entries(limit=100)
    if 'error' in entries:
        return entries

    # Build comprehensive data structure
    data = {
        'configured': True,
        'stats': dashboard.get('stats', {}),
        'trends': dashboard.get('trends', {}),
        'chart_data': build_chart_data(entries, days),
        'timeline': build_timeline(entries),
        'entries': {
            'mood': [],
            'health': [],
            'social': [],
            'intimate': [],
            'extra': []
        },
        'totals': {
            'mood': 0,
            'health': 0,
            'social': 0,
            'intimate': 0,
            'extra': 0
        }
    }

    # Format all entries
    for entry_type in ['mood', 'health', 'social', 'intimate', 'extra']:
        type_data = entries.get(entry_type, {})
        type_entries = type_data.get('entries', [])
        data['totals'][entry_type] = type_data.get('total', len(type_entries))

        for entry in type_entries:
            data['entries'][entry_type].append(
                format_entry_for_display(entry, entry_type)
            )

    return data


def build_chart_data(entries, days=30):
    """
    Build chart-ready data from entries.

    Returns:
        dict with labels and datasets for various charts
    """
    from collections import defaultdict

    # Initialize date buckets for the past N days
    today = datetime.now().date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(days-1, -1, -1)]
    date_set = set(dates)

    # Initialize counters
    mood_by_date = defaultdict(list)
    energy_by_date = defaultdict(list)
    health_by_date = defaultdict(int)
    social_by_date = defaultdict(int)
    intimate_by_date = defaultdict(int)
    extra_by_date = defaultdict(int)

    # Process mood entries
    mood_entries = entries.get('mood', {}).get('entries', [])
    for entry in mood_entries:
        ts = entry.get('timestamp', '')[:10]
        if ts in date_set:
            energy = entry.get('energy')
            if energy is not None:
                energy_by_date[ts].append(energy)

    # Process health entries
    health_entries = entries.get('health', {}).get('entries', [])
    for entry in health_entries:
        ts = entry.get('timestamp', '')[:10]
        if ts in date_set:
            health_by_date[ts] += 1

    # Process social entries
    social_entries = entries.get('social', {}).get('entries', [])
    for entry in social_entries:
        ts = entry.get('timestamp', '')[:10]
        if ts in date_set:
            social_by_date[ts] += entry.get('people_count', 0)

    # Process intimate entries
    intimate_entries = entries.get('intimate', {}).get('entries', [])
    for entry in intimate_entries:
        ts = entry.get('timestamp', '')[:10]
        if ts in date_set:
            intimate_by_date[ts] += 1

    # Process extra entries
    extra_entries = entries.get('extra', {}).get('entries', [])
    for entry in extra_entries:
        ts = entry.get('timestamp', '')[:10]
        if ts in date_set:
            extra_by_date[ts] += 1

    # Build chart data
    return {
        'labels': dates,
        'energy': [
            sum(energy_by_date[d]) / len(energy_by_date[d]) if energy_by_date[d] else None
            for d in dates
        ],
        'health_count': [health_by_date[d] for d in dates],
        'social_people': [social_by_date[d] for d in dates],
        'intimate_count': [intimate_by_date[d] for d in dates],
        'extra_count': [extra_by_date[d] for d in dates],
    }


def build_timeline(entries):
    """
    Build a unified timeline of all entries.

    Returns:
        list of timeline items sorted by timestamp (newest first)
    """
    timeline = []

    for entry_type in ['mood', 'health', 'social', 'intimate', 'extra']:
        type_entries = entries.get(entry_type, {}).get('entries', [])
        for entry in type_entries:
            formatted = format_entry_for_display(entry, entry_type)
            timeline.append(formatted)

    # Sort by timestamp (newest first)
    timeline.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

    return timeline[:50]  # Return last 50 items


def get_entry_details(entry_type, entry_id):
    """
    Get detailed information about a specific entry.

    Args:
        entry_type: Type of entry (health, mood, social, intimate, extra)
        entry_id: ID of the entry

    Returns:
        dict with full entry details
    """
    if not is_configured():
        return {'error': 'Control Room not configured'}

    # Fetch all entries of this type and find the one we need
    entries = fetch_entries(entry_type=entry_type, limit=100)
    if 'error' in entries:
        return entries

    type_entries = entries.get(entry_type, {}).get('entries', [])
    for entry in type_entries:
        if entry.get('id') == entry_id:
            return {
                'success': True,
                'entry': entry,
                'formatted': format_entry_for_display(entry, entry_type)
            }

    return {'error': 'Entry not found'}


def get_category_stats(entry_type, days=30):
    """
    Get detailed statistics for a specific category.

    Args:
        entry_type: Type of entry (health, mood, social, intimate, extra)
        days: Number of days to analyze

    Returns:
        dict with category-specific statistics
    """
    if not is_configured():
        return {'error': 'Control Room not configured'}

    entries = fetch_entries(entry_type=entry_type, limit=200)
    if 'error' in entries:
        return entries

    type_entries = entries.get(entry_type, {}).get('entries', [])

    # Filter to requested date range
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    recent_entries = [e for e in type_entries if e.get('timestamp', '') >= cutoff]

    stats = {
        'total_entries': len(recent_entries),
        'days_analyzed': days
    }

    if entry_type == 'mood':
        energies = [e.get('energy') for e in recent_entries if e.get('energy') is not None]
        anxieties = [e.get('anxiety') for e in recent_entries if e.get('anxiety') is not None]
        stresses = [e.get('stress') for e in recent_entries if e.get('stress') is not None]

        stats['avg_energy'] = round(sum(energies) / len(energies), 1) if energies else 0
        stats['avg_anxiety'] = round(sum(anxieties) / len(anxieties), 1) if anxieties else 0
        stats['avg_stress'] = round(sum(stresses) / len(stresses), 1) if stresses else 0

    elif entry_type == 'health':
        waters = [e.get('water') for e in recent_entries if e.get('water') is not None]
        sleeps = [e.get('sleep_hours') for e in recent_entries if e.get('sleep_hours') is not None]

        stats['avg_water'] = round(sum(waters) / len(waters), 1) if waters else 0
        stats['avg_sleep'] = round(sum(sleeps) / len(sleeps), 1) if sleeps else 0

    elif entry_type == 'social':
        people = [e.get('people_count', 0) for e in recent_entries]
        hours = [e.get('quality_hours', 0) for e in recent_entries]

        stats['total_people'] = sum(people)
        stats['total_quality_hours'] = sum(hours)
        stats['avg_people_per_entry'] = round(sum(people) / len(people), 1) if people else 0

    elif entry_type == 'intimate':
        intensities = [e.get('intensity') for e in recent_entries if e.get('intensity') is not None]
        durations = [e.get('duration') for e in recent_entries if e.get('duration') is not None]

        stats['avg_intensity'] = round(sum(intensities) / len(intensities), 1) if intensities else 0
        stats['avg_duration'] = round(sum(durations) / len(durations), 0) if durations else 0

    elif entry_type == 'extra':
        vibes = [e.get('vibe_rating') for e in recent_entries if e.get('vibe_rating') is not None]
        durations = [e.get('duration_hours') for e in recent_entries if e.get('duration_hours') is not None]

        stats['avg_vibe'] = round(sum(vibes) / len(vibes), 1) if vibes else 0
        stats['total_party_hours'] = round(sum(durations), 1) if durations else 0

    return stats
