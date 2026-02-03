#!/usr/bin/env python3
"""
Media Processing Utility for Telegram Monitor
Extracts metadata from media files (duration, dimensions, thumbnails)
"""

import os
import subprocess
import json
from PIL import Image
import config
import database


def get_media_info(file_path):
    """Extract media information using ffprobe."""
    if not os.path.exists(file_path):
        return None
        
    try:
        # Use ffprobe to get media info
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return None
            
        info = json.loads(result.stdout)
        
        # Extract relevant information
        format_info = info.get('format', {})
        streams = info.get('streams', [])
        
        metadata = {
            'duration': None,
            'width': None,
            'height': None,
            'size': int(format_info.get('size', 0)) if format_info.get('size') else None
        }
        
        # Get duration from format
        if 'duration' in format_info:
            try:
                metadata['duration'] = int(float(format_info['duration']))
            except (ValueError, TypeError):
                pass
        
        # Get video dimensions from first video stream
        for stream in streams:
            if stream.get('codec_type') == 'video':
                metadata['width'] = stream.get('width')
                metadata['height'] = stream.get('height')
                
                # Try to get duration from stream if not in format
                if not metadata['duration'] and 'duration' in stream:
                    try:
                        metadata['duration'] = int(float(stream['duration']))
                    except (ValueError, TypeError):
                        pass
                break
        
        return metadata
        
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, json.JSONDecodeError, Exception) as e:
        database.add_system_log('media', 'metadata_extraction', 'error', 
                              f'Failed to extract metadata from {file_path}', str(e))
        return None


def get_image_info(file_path):
    """Extract image information using PIL."""
    if not os.path.exists(file_path):
        return None
        
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            size = os.path.getsize(file_path)
            
            return {
                'duration': None,
                'width': width,
                'height': height,
                'size': size
            }
    except Exception as e:
        database.add_system_log('media', 'image_info', 'error',
                              f'Failed to get image info for {file_path}', str(e))
        return None


def generate_video_thumbnail(video_path, output_path, time_offset=1):
    """Generate a thumbnail for a video file using ffmpeg."""
    try:
        # Create thumbnails directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        cmd = [
            'ffmpeg', '-i', video_path, '-ss', str(time_offset),
            '-vframes', '1', '-vf', 'scale=320:240:force_original_aspect_ratio=decrease',
            '-y', output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        else:
            database.add_system_log('media', 'thumbnail_generation', 'error',
                                  f'Failed to generate thumbnail for {video_path}', result.stderr)
            return None

    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, Exception) as e:
        database.add_system_log('media', 'thumbnail_generation', 'error',
                              f'Failed to generate thumbnail for {video_path}', str(e))
        return None


def generate_video_snapshots(video_path, output_dir, duration, num_snapshots=10):
    """Generate equally spaced snapshots from a video file using ffmpeg."""
    if not duration or duration <= 0:
        return []

    try:
        # Create snapshots directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        snapshots = []

        # Calculate time intervals for snapshots
        # Avoid the very beginning and end (start at 5%, end at 95%)
        start_offset = duration * 0.05
        end_offset = duration * 0.95
        usable_duration = end_offset - start_offset

        if usable_duration <= 0:
            usable_duration = duration
            start_offset = 0

        interval = usable_duration / num_snapshots if num_snapshots > 1 else 0

        for i in range(num_snapshots):
            time_offset = start_offset + (i * interval) if num_snapshots > 1 else duration / 2

            # Generate unique filename for this snapshot
            filename = os.path.basename(video_path)
            name, ext = os.path.splitext(filename)
            snapshot_name = f"{name}_snap_{i:02d}.jpg"
            snapshot_path = os.path.join(output_dir, snapshot_name)

            cmd = [
                'ffmpeg', '-i', video_path, '-ss', str(time_offset),
                '-vframes', '1', '-vf', 'scale=160:120:force_original_aspect_ratio=decrease',
                '-y', snapshot_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and os.path.exists(snapshot_path):
                snapshots.append(snapshot_name)
            else:
                database.add_system_log('media', 'snapshot_generation', 'warning',
                                      f'Failed to generate snapshot {i} for {video_path}', result.stderr)

        if snapshots:
            database.add_system_log('media', 'snapshot_generation', 'success',
                                  f'Generated {len(snapshots)} snapshots for {video_path}')

        return snapshots

    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, Exception) as e:
        database.add_system_log('media', 'snapshot_generation', 'error',
                              f'Failed to generate snapshots for {video_path}', str(e))
        return []


def process_media_file(file_path, media_type):
    """Process a media file and extract all relevant metadata."""
    if not os.path.exists(file_path):
        return None

    metadata = None
    thumbnail_path = None
    snapshots = []

    # Extract metadata based on media type
    if media_type in ['photo', 'sticker']:
        metadata = get_image_info(file_path)
    elif media_type in ['video', 'video_note', 'circle', 'audio', 'voice']:
        metadata = get_media_info(file_path)

        # Generate thumbnail and snapshots for videos
        if media_type in ['video', 'video_note', 'circle'] and metadata:
            thumbnail_dir = os.path.join(config.MEDIA_PATH, 'thumbnails')
            os.makedirs(thumbnail_dir, exist_ok=True)

            filename = os.path.basename(file_path)
            name, ext = os.path.splitext(filename)
            thumbnail_name = f"{name}_thumb.jpg"
            thumbnail_full_path = os.path.join(thumbnail_dir, thumbnail_name)

            generated_thumb = generate_video_thumbnail(file_path, thumbnail_full_path)
            if generated_thumb:
                thumbnail_path = f"thumbnails/{thumbnail_name}"

            # Generate snapshots for videos/circles
            snapshots_dir = os.path.join(config.MEDIA_PATH, 'snapshots')
            duration = metadata.get('duration')
            if duration:
                snapshot_files = generate_video_snapshots(file_path, snapshots_dir, duration, num_snapshots=40)
                snapshots = [f"snapshots/{snap}" for snap in snapshot_files]
    else:
        # Try to get basic file info
        try:
            metadata = {
                'duration': None,
                'width': None,
                'height': None,
                'size': os.path.getsize(file_path)
            }
        except OSError:
            pass

    if metadata:
        metadata['thumbnail'] = thumbnail_path
        metadata['snapshots'] = snapshots

    return metadata


def process_pending_media():
    """Process all media files that don't have metadata yet."""
    messages = database.get_messages_needing_metadata()
    processed = 0

    for msg in messages:
        media_path = msg.get('media_path')
        if not media_path:
            continue

        full_path = os.path.join(config.MEDIA_PATH, media_path)
        metadata = process_media_file(full_path, msg.get('media_type'))

        if metadata:
            # Convert snapshots list to comma-separated string for database
            snapshots_str = ','.join(metadata.get('snapshots', [])) if metadata.get('snapshots') else None

            database.update_media_metadata(
                msg['message_id'],
                msg['chat_id'],
                duration=metadata.get('duration'),
                width=metadata.get('width'),
                height=metadata.get('height'),
                size=metadata.get('size'),
                thumbnail=metadata.get('thumbnail'),
                snapshots=snapshots_str
            )
            processed += 1
            database.add_system_log('media', 'metadata_processed', 'success',
                                  f'Processed metadata for {media_path}')
        else:
            database.add_system_log('media', 'metadata_failed', 'warning',
                                  f'Failed to process metadata for {media_path}')

    return processed


def process_pending_media_detailed():
    """Process all media files and return detailed results."""
    messages = database.get_messages_needing_metadata()
    results = {
        'processed': 0,
        'failed': 0,
        'details': [],
        'errors': []
    }

    for msg in messages:
        media_path = msg.get('media_path')
        media_type = msg.get('media_type')

        if not media_path:
            continue

        # Only process video types for snapshots
        if media_type not in ('video', 'video_note', 'circle'):
            continue

        full_path = os.path.join(config.MEDIA_PATH, media_path)

        # Check if file exists
        if not os.path.exists(full_path):
            results['failed'] += 1
            results['errors'].append({
                'file': media_path,
                'error': 'File not found'
            })
            continue

        try:
            metadata = process_media_file(full_path, media_type)

            if metadata and metadata.get('snapshots'):
                snapshots_str = ','.join(metadata.get('snapshots', []))
                database.update_media_metadata(
                    msg['message_id'],
                    msg['chat_id'],
                    duration=metadata.get('duration'),
                    width=metadata.get('width'),
                    height=metadata.get('height'),
                    size=metadata.get('size'),
                    thumbnail=metadata.get('thumbnail'),
                    snapshots=snapshots_str
                )
                results['processed'] += 1
                results['details'].append({
                    'file': media_path,
                    'snapshots': len(metadata.get('snapshots', [])),
                    'duration': metadata.get('duration')
                })
            else:
                results['failed'] += 1
                results['errors'].append({
                    'file': media_path,
                    'error': 'Failed to generate snapshots (no metadata returned)'
                })
        except Exception as e:
            results['failed'] += 1
            results['errors'].append({
                'file': media_path,
                'error': str(e)
            })

    return results


def check_media_files():
    """Check all media files for existence and mark missing ones."""
    media_messages = database.get_media_messages(limit=1000)
    missing = []
    
    for msg in media_messages:
        media_path = msg.get('media_path')
        if media_path:
            full_path = os.path.join(config.MEDIA_PATH, media_path)
            if not os.path.exists(full_path):
                missing.append({
                    'message_id': msg['message_id'],
                    'chat_id': msg['chat_id'],
                    'media_path': media_path,
                    'timestamp': msg['timestamp']
                })
    
    return missing


def cleanup_orphaned_thumbnails():
    """Remove thumbnail files that no longer have corresponding messages."""
    thumbnail_dir = os.path.join(config.MEDIA_PATH, 'thumbnails')
    if not os.path.exists(thumbnail_dir):
        return 0
        
    # Get all thumbnail paths from database
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT media_thumbnail FROM messages WHERE media_thumbnail IS NOT NULL")
        db_thumbnails = {row['media_thumbnail'] for row in cursor.fetchall()}
    
    # Find orphaned files
    removed = 0
    for filename in os.listdir(thumbnail_dir):
        if filename.endswith('_thumb.jpg'):
            rel_path = f"thumbnails/{filename}"
            if rel_path not in db_thumbnails:
                try:
                    os.remove(os.path.join(thumbnail_dir, filename))
                    removed += 1
                except OSError:
                    pass
    
    return removed


if __name__ == '__main__':
    print("Processing pending media metadata...")
    processed = process_pending_media()
    print(f"Processed {processed} media files")
    
    print("\nChecking for missing media files...")
    missing = check_media_files()
    if missing:
        print(f"Found {len(missing)} missing media files:")
        for m in missing[:10]:  # Show first 10
            print(f"  - {m['media_path']} (from {m['timestamp']})")
    else:
        print("All media files present")
    
    print("\nCleaning up orphaned thumbnails...")
    removed = cleanup_orphaned_thumbnails()
    print(f"Removed {removed} orphaned thumbnail files")