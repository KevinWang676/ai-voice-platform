import json
import os
import shutil
import base64
import random
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from flask import request, session, jsonify
from flask_login import current_user
import threading

# Global variables
chat_histories = {}
user_last_request = {}
concurrent_request_semaphore = threading.Semaphore(10)

def get_request_identifier():
    """Get a unique identifier for the current request based on user ID or IP"""
    try:
        if current_user.is_authenticated:
            return f"user:{current_user.id}"
    except:
        pass
    return f"ip:{request.remote_addr}"

def backup_database():
    """Create a backup of the database file"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = 'db_backups'
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        backup_file = os.path.join(backup_dir, f'stories_backup_{timestamp}.db')

        # Only create backup when the database file exists and has data
        if os.path.exists('stories.db') and os.path.getsize('stories.db') > 0:
            shutil.copy2('stories.db', backup_file)

            # Keep only the last 7 backups
            backups = sorted([f for f in os.listdir(backup_dir) if f.startswith('stories_backup_')])
            for old_backup in backups[:-7]:
                os.remove(os.path.join(backup_dir, old_backup))

    except Exception as e:
        print(f"Backup error: {str(e)}")

def get_random_default_avatar(user_id):
    """Return a deterministic default avatar based on user ID."""
    avatar_files = [
        'static/default-avatars/cat1.svg',
        'static/default-avatars/cat2.svg',
        'static/default-avatars/dog1.svg',
        'static/default-avatars/dog2.svg',
        'static/default-avatars/panda.svg',
        'static/default-avatars/fox.svg',
        'static/default-avatars/penguin.svg',
        'static/default-avatars/koala.svg'
    ]
    # Use user_id to deterministically select an avatar
    avatar_index = (user_id - 1) % len(avatar_files) if user_id else 0
    avatar_file = avatar_files[avatar_index]

    with open(avatar_file, 'rb') as f:
        svg_data = f.read()
    base64_data = base64.b64encode(svg_data).decode('utf-8')
    return f'data:image/svg+xml;base64,{base64_data}'

def get_default_avatar():
    """Return a default avatar for anonymous users."""
    avatar_file = 'static/default-avatars/cat1.svg'
    with open(avatar_file, 'rb') as f:
        svg_data = f.read()
    base64_data = base64.b64encode(svg_data).decode('utf-8')
    return f'data:image/svg+xml;base64,{base64_data}'

def throttle_requests(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        REQUEST_COOLDOWN = 3
        user_id = current_user.id if current_user.is_authenticated else request.remote_addr

        # Check if user has made a recent request
        last_request_time = user_last_request.get(user_id)
        current_time = time.time()

        # Clean up old entries (older than REQUEST_COOLDOWN)
        cleanup_time = current_time - REQUEST_COOLDOWN
        user_last_request.update({
            uid: timestamp for uid, timestamp in user_last_request.items()
            if timestamp > cleanup_time
        })

        if last_request_time and current_time - last_request_time < REQUEST_COOLDOWN:
            wait_time = int(REQUEST_COOLDOWN - (current_time - last_request_time))
            return jsonify({
                'error': f'Requests are too frequent. Please wait {wait_time} seconds before trying again.'
            }), 429

        # Update last request time
        user_last_request[user_id] = current_time

        return f(*args, **kwargs)

    return decorated_function

def limit_concurrent_requests(f):
    """
    Decorator to limit the number of concurrent API requests to 10.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        acquired = concurrent_request_semaphore.acquire(blocking=False)
        if not acquired:
            return jsonify({
                'error': 'The server is currently busy. Please try again later.',
                'success': False
            }), 429

        try:
            return f(*args, **kwargs)
        finally:
            concurrent_request_semaphore.release()

    return decorated_function

def handle_api_error(error):
    """Handle common API errors and return user-friendly messages"""
    error_str = str(error)
    if "Arrearage" in error_str:
        return "API account balance insufficient, please contact administrator to recharge and try again"
    elif "Invalid authentication" in error_str or "Access denied" in error_str:
        return "API authentication failed, please verify that the API key is correct"
    elif "Rate limit" in error_str:
        return "Requests too frequent, please try again later"
    else:
        return f"An error occurred during request processing: {error_str}"

def format_response_text(text):
    """Format the response text by replacing markdown headers with bold text, correcting misplaced bold markers, and ensuring spacing."""
    if text:
        # Use regex to find all headers (#, ##, ###) with optional spaces and replace with **bold**.
        text = re.sub(r'^(#+)\s+(.*)', lambda m: f"**{m.group(2).strip()}**", text, flags=re.MULTILINE)

        # Fix misplaced '**' at the end of lines (e.g., **start:** -> **start**:)
        text = re.sub(r'\*\*(.+?)\*\*:', r'**\1**:', text)

        # Add a single blank space after **some_word** if immediately followed by text
        text = re.sub(r'(\*\*.+?\*\*)(\S)', r'\1 \2', text)

        return text
    return text

def get_chat_history_key(user_id=None):
    """Get a unique key for chat history based on user ID or IP"""
    if user_id and user_id != 'guest':
        return f"user:{user_id}"
    return f"ip:{request.remote_addr}"

def clear_user_chat_history(user_id=None):
    """Clear chat history for a specific user"""
    history_key = get_chat_history_key(user_id)
    if history_key in chat_histories:
        del chat_histories[history_key]
    character_chat_key = f"character_chat_{history_key}"
    if character_chat_key in chat_histories:
        del chat_histories[character_chat_key]

def clear_all_chat_histories(user_id=None):
    """Clear all types of chat histories for a specific user"""
    history_key = get_chat_history_key(user_id)

    # Get all possible key patterns for this user
    key_patterns = [
        history_key,  # Base history key
        f"character_chat_{history_key}",  # Character chat key
        f"doubao_chat_{history_key}",  # Doubao chat key
        get_doubao_chat_key(user_id),  # Get specific doubao chat key
    ]

    # Clear all matching histories
    for pattern in key_patterns:
        # Clear exact matches
        if pattern in chat_histories:
            del chat_histories[pattern]
        # Clear any keys that start with the pattern (for character chats with different names)
        for key in list(chat_histories.keys()):
            if key.startswith(pattern):
                del chat_histories[key]

    # Ensure generate_new_ending and make_doubao_request start fresh
    if user_id in user_last_request:
        del user_last_request[user_id]

def get_doubao_chat_key(user_id=None):
    """Get a unique key for doubao chat based on user ID or IP"""
    history_key = get_chat_history_key(user_id)
    return f"doubao_chat_{history_key}"

def get_china_time():
    return datetime.now(ZoneInfo("Asia/Shanghai"))

def to_china_timezone(utc_dt):
    """Convert UTC datetime to China timezone (UTC+8)"""
    china_tz = timezone(timedelta(hours=8))
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(china_tz)

def replace_quotes_and_dashes(text: str) -> str:
    """
    Replace all occurrences of:
      - The English double quotes (") with paired Chinese quotes (" and ").
      - The Chinese dash sequence (——) with a tilde (~).

    The first encountered " is replaced with ", the next with ", and so on.
    The dash sequence replacement is performed first.

    Parameters:
        text (str): The input string.

    Returns:
        str: The modified string with the replacements applied.

    """
    # Replace all occurrences of the dash sequence first.
    text = text.replace("——", "～")

    # Delete all occurrences of the English double quotes.
    #text = text.replace('"', '')

    return text

def italicize_parentheses(text: str) -> str:
    """
    Finds any text enclosed in parentheses and wraps the entire match (including the parentheses)
    with a <span> tag to style it in grey and italic.

    For example, converts:
        (some description)
    into:
        <span style="color: grey; font-style: italic;">(some description)</span>

    Parameters:
        text (str): The input string.

    Returns:
        str: The modified string with the parentheses content styled.
    """
    # Using Chinese parentheses for matching as per the original code's likely intent
    return re.sub(r'\（.*?\）',
                  lambda m: f'<span style="color: silver; font-style: italic;">{m.group(0)}</span>',
                  text)

def get_character_chat_key(user_id=None, character_name=None):
    """Get a unique key for character chat that includes a hash of the character instruction"""
    history_key = get_chat_history_key(user_id)
    if character_name:
        # Create a short hash of the character instruction to use as identifier
        instruction_hash = str(hash(character_name))[:8]  # Take first 8 chars of hash
        return f"character_chat_{history_key}_{instruction_hash}"
    return f"character_chat_{history_key}"

def get_trending_posts(db, ForumPost, PostLike, func, limit=5):
    # Get today's date in China timezone by adding 8 hours to UTC time
    today = (datetime.utcnow() + timedelta(hours=8)).date()

    # First try to get posts with likes
    trending_posts = db.session.query(ForumPost)\
        .outerjoin(PostLike)\
        .filter(
            func.date(ForumPost.created_at + timedelta(hours=8)) == today,
            ForumPost.is_private == False  # Filter out private posts
        )\
        .group_by(ForumPost.id)\
        .order_by(func.count(PostLike.id).desc(), ForumPost.created_at.desc())\
        .limit(limit)\
        .all()

    # If we don't have enough posts with likes, get additional posts ordered by creation time
    if len(trending_posts) < limit:
        remaining_posts = db.session.query(ForumPost)\
            .filter(
                func.date(ForumPost.created_at + timedelta(hours=8)) == today,
                ForumPost.is_private == False,  # Filter out private posts
                ~ForumPost.id.in_([p.id for p in trending_posts])
            )\
            .order_by(ForumPost.created_at.desc())\
            .limit(limit - len(trending_posts))\
            .all()

        trending_posts.extend(remaining_posts)

    return trending_posts

def get_top_tags(ForumPost, limit=10):
    """Get the most used tags with their counts."""
    # Get all posts' tags
    posts = ForumPost.query.all()
    tag_counts = {}

    # Count occurrences of each tag
    for post in posts:
        if post.tags:  # Check if post has tags
            try:
                tags = json.loads(post.tags)  # Parse JSON string to list
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            except json.JSONDecodeError:
                continue  # Skip if JSON parsing fails

    # Sort tags by count and get top N
    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    return sorted_tags[:limit]

def create_notification(db, Notification, user_id, sender_id, type, post_id=None, comment_id=None):
    if user_id == sender_id:  # Don't create notifications for self-actions
        return

    # Check if a similar notification already exists
    if type == 'follow':
        # Check if a follow notification from this sender to this user already exists
        existing_notification = Notification.query.filter_by(
            user_id=user_id,
            sender_id=sender_id,
            type='follow'
        ).first()
    elif type == 'like':
        # Check if a like notification for this post or comment from this sender already exists
        if post_id:
            existing_notification = Notification.query.filter_by(
                user_id=user_id,
                sender_id=sender_id,
                type='like',
                post_id=post_id
            ).first()
        else:
            existing_notification = Notification.query.filter_by(
                user_id=user_id,
                sender_id=sender_id,
                type='like',
                comment_id=comment_id
            ).first()
    elif type == 'comment':
        # For comment notifications, we always create a new one
        existing_notification = None
    else:
        existing_notification = None

    # Only create notification if one doesn't already exist
    if not existing_notification:
        notification = Notification(
            user_id=user_id,
            sender_id=sender_id,
            type=type,
            post_id=post_id,
            comment_id=comment_id
        )
        db.session.add(notification)
        db.session.commit() 