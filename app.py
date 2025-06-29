from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session, Response, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user, AnonymousUserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from flask_limiter import Limiter
import json
import os
from datetime import datetime, timedelta, timezone
import random
from functools import wraps
import time
import shutil
from apscheduler.schedulers.background import BackgroundScheduler
import secrets
from flask_migrate import Migrate
from PIL import Image
import io
import base64
from werkzeug.utils import secure_filename
from datetime import timedelta
from sqlalchemy import func, inspect
from sqlalchemy.sql import text
import requests
import boto3
from zoneinfo import ZoneInfo
import traceback
from markupsafe import escape
import numpy as np
import torch
import torchaudio
import mimetypes
import re
from sqlalchemy import inspect
import string
import tempfile
import hashlib
import uuid
import requests
import csv
import azure.cognitiveservices.speech as speechsdk
import threading
from pydub import AudioSegment
import redis
import autogen
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager

# Import backend modules
from backend.config import Config
from backend.storage import upload_to_s3, delete_from_s3, upload_wav_to_s3, save_profile_image
from backend.utils import (
    get_request_identifier, backup_database, get_random_default_avatar, 
    get_default_avatar, throttle_requests, limit_concurrent_requests,
    handle_api_error, format_response_text, get_chat_history_key,
    clear_user_chat_history, clear_all_chat_histories, get_doubao_chat_key,
    get_china_time, to_china_timezone, replace_quotes_and_dashes,
    italicize_parentheses, get_character_chat_key, get_trending_posts,
    get_top_tags, create_notification, chat_histories
)
from backend.ai_services import (
    TextToImageAPI, generate_tts_audio, convert_voice, azure_tts_and_convert_voice,
    generate_music, tts_inference_instruct2_s3, generate_tts_audio_f5
)
from backend.ai_chat import (
    make_kimi_request, make_kimi_character_request, generate_new_ending,
    character_chat, character_chat_new, doubao_client
)
from backend.email import send_verification_email, send_password_reset_email
from backend.decorators import admin_required
from backend.auth import generate_secret_key, activate_secret_key

app = Flask(__name__)

# Load configuration from environment variables
app.config.from_object(Config)

# Validate required environment variables (warning mode for development)
try:
    Config.validate_required_env_vars()
    print("✅ All required environment variables are set!")
except ValueError as e:
    print(f"⚠️ Configuration Warning: {e}")
    print("⚠️ Some features may not work properly without proper environment variables.")
    print("📄 Please set environment variables according to env.example for full functionality.")

# Add max function to Jinja templates
app.jinja_env.globals.update(max=max)

# Create upload folder if it doesn't exist
if not os.path.exists(Config.UPLOAD_FOLDER):
    os.makedirs(Config.UPLOAD_FOLDER)

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_request_identifier,
    default_limits=["10000 per minute"],
    storage_uri=Config.RATELIMIT_STORAGE_URL
)

# Create backup directory if it doesn't exist
BACKUP_DIR = 'db_backups'
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

# Initialize scheduler for daily backups
scheduler = BackgroundScheduler()
scheduler.add_job(backup_database, 'interval', days=1)
scheduler.start()

# Initialize database and other Flask extensions
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize Flask-Mail
mail = Mail(app)

# Initialize serializer for email verification tokens
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# Initialize chat histories dictionary at the global level (imported from utils)
# chat_histories = {} - imported from backend.utils

# Add request throttling (imported from utils)
# user_last_request = {} - imported from backend.utils
# REQUEST_COOLDOWN = 3 - defined in throttle_requests function

# Add concurrent request limiting (imported from utils)
# concurrent_request_semaphore - imported from backend.utils

class Anonymous(AnonymousUserMixin):
    def get_avatar(self):
        return get_default_avatar()

login_manager.anonymous_user = Anonymous

# Import all the model definitions from the original app.py
# (Copy all the model classes exactly as they are - User, Story, ForumPost, etc.)

# Followers association table
followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('created_at', db.DateTime, default=datetime.utcnow)
)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'follow', 'comment', 'like'
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('forum_post.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    # Add relationships
    user = db.relationship('User', foreign_keys=[user_id], backref='notifications_received')
    sender = db.relationship('User', foreign_keys=[sender_id], backref='notifications_sent')
    post = db.relationship('ForumPost', backref='notifications')
    comment = db.relationship('Comment', backref='notifications')

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    password_hash = db.Column(db.String(128))
    is_verified = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Profile fields
    avatar_url = db.Column(db.String(500))
    bio = db.Column(db.String(200))
    image_changes_count = db.Column(db.Integer, default=0)
    last_image_reset = db.Column(db.DateTime, default=datetime.utcnow)
    points = db.Column(db.Integer, default=30, nullable=False)
    last_points_reset = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    stories = db.relationship('Story', backref='user', lazy=True)
    forum_posts = db.relationship('ForumPost', backref='user', lazy=True)
    comments = db.relationship('Comment', backref='user', lazy=True)
    likes = db.relationship('PostLike', backref='user', lazy=True)

    # Add followers relationship
    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'),
        lazy='dynamic'
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_liked_post(self, post_id):
        return PostLike.query.filter_by(
            user_id=self.id,
            post_id=post_id
        ).first() is not None

    def has_liked_comment(self, comment_id):
        """Check if the user has liked a specific comment"""
        if not self.is_authenticated:
            return False
        return CommentLike.query.filter_by(
            user_id=self.id,
            comment_id=comment_id
        ).first() is not None

    def get_avatar(self):
        """Get user's avatar URL or data URL."""
        if not hasattr(self, 'is_authenticated') or not self.is_authenticated:
            return get_default_avatar()
        if self.avatar_url:
            return self.avatar_url
        if not hasattr(self, '_default_avatar'):
            self._default_avatar = get_random_default_avatar(self.id)
        return self._default_avatar

    def can_change_image(self):
        """Check if user can change their profile image"""
        now = datetime.utcnow()
        # Handle case where last_image_reset is None
        if self.last_image_reset is None:
            self.last_image_reset = now
            self.image_changes_count = 0
            db.session.commit()
            return True

        # Reset counter if it's a new month
        if self.last_image_reset.month != now.month or self.last_image_reset.year != now.year:
            self.image_changes_count = 0
            self.last_image_reset = now
            db.session.commit()
        return self.image_changes_count < 3

    def increment_image_changes(self):
        """Increment the image changes counter"""
        self.image_changes_count += 1
        db.session.commit()

    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)
            db.session.commit()
            return True
        return False

    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)
            db.session.commit()
            return True
        return False

    def is_following(self, user):
        return self.followed.filter(
            followers.c.followed_id == user.id
        ).count() > 0

    def get_followers_count(self):
        return self.followers.count()

    def get_following_count(self):
        return self.followed.count()

    def get_unread_notifications_count(self):
        return Notification.query.filter_by(user_id=self.id, is_read=False).count()

    def get_recent_notifications(self, limit=10):
        return Notification.query.filter_by(user_id=self.id)\
            .order_by(Notification.created_at.desc())\
            .limit(limit)\
            .all()

    def mark_notifications_as_read(self):
        notifications = Notification.query.filter_by(user_id=self.id, is_read=False).all()
        for notification in notifications:
            notification.is_read = True
        db.session.commit()

    def has_enough_points(self, required_points):
        """Check if user has enough points for an action"""
        # Skip point check for users with active membership
        if self.has_active_membership():
            return True

        # For regular users, check points normally
        self.reset_points_if_new_day()
        return self.points >= required_points

    def use_points(self, points_to_use):
        """Deduct points from user's balance"""
        if self.has_enough_points(points_to_use):
            self.points -= points_to_use
            db.session.commit()
            return True
        return False

    def reset_points_if_new_day(self):
        """Reset points to 30 if it's a new day in China time"""
        # Skip resetting points if user has an active membership
        if self.has_active_membership():
            return

        now = datetime.now(timezone(timedelta(hours=8)))  # China timezone
        last_reset = self.last_points_reset

        # Convert to China timezone if it's not aware
        if last_reset.tzinfo is None:
            last_reset = last_reset.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=8)))

        # If it's a new day in China time
        if now.date() > last_reset.date():
            self.points = 30
            self.last_points_reset = now
            db.session.commit()

    def has_active_membership(self):
        """Check if user has an active membership"""
        # Look for the most recent active membership
        membership = Membership.query.filter_by(
            user_id=self.id,
            is_active=True
        ).order_by(Membership.end_date.desc()).first()

        if not membership:
            return False

        # Check if it's still valid
        now = datetime.now(timezone.utc)
        end_date = membership.end_date

        # If end_date is naive, make it timezone-aware
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        # If membership has expired, reset points to 30
        if end_date <= now:
            # Deactivate the expired membership
            membership.is_active = False
            # Reset points to 30
            self.points = 30
            self.last_points_reset = now
            db.session.commit()
            return False

        return True

    def get_membership_expiry(self):
        """Get days remaining in membership"""
        membership = Membership.query.filter_by(
            user_id=self.id,
            is_active=True
        ).order_by(Membership.end_date.desc()).first()

        if not membership:
            return 0

        # Ensure both dates are timezone-aware for comparison
        now = datetime.now(timezone.utc)
        end_date = membership.end_date

        # If end_date is naive, make it timezone-aware
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        if end_date <= now:
            return 0

        delta = end_date - now
        # Return days remaining
        return max(1, int(delta.total_seconds() / 86400)+1)

    def extend_membership(self, days):
        """Add days to membership or create a new membership"""
        if days <= 0:
            return False

        now = datetime.now(timezone.utc)
        membership = Membership.query.filter_by(
            user_id=self.id,
            is_active=True
        ).order_by(Membership.end_date.desc()).first()

        if membership and membership.is_valid():
            # Get the end date and ensure it's timezone-aware
            end_date = membership.end_date
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)

            # Extend existing membership
            membership.end_date = end_date + timedelta(days=days)
        else:
            # Create new membership
            new_membership = Membership(
                user_id=self.id,
                start_date=now,
                end_date=now + timedelta(days=days),
                is_active=True
            )
            db.session.add(new_membership)

            # Deactivate old memberships
            for old_membership in Membership.query.filter_by(
                user_id=self.id,
                is_active=True
            ).all():
                if old_membership != new_membership:
                    old_membership.is_active = False

        db.session.commit()
        return True

# Add all other model classes from the original app.py
class Story(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    original_content = db.Column(db.Text, nullable=False)
    edited_content = db.Column(db.Text)
    new_ending = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    forum_posts = db.relationship('ForumPost', backref='story', lazy=True)

class ForumPost(db.Model):
    __tablename__ = 'forum_post'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    chat_history = db.Column(db.Text)
    story_id = db.Column(db.Integer, db.ForeignKey('story.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    tags = db.Column(db.Text)
    cover_image = db.Column(db.String(500))
    views = db.Column(db.Integer, default=0)
    likes = db.relationship('PostLike', backref='post', lazy=True)
    comments = db.relationship('Comment', backref='post', lazy=True)
    is_private = db.Column(db.Boolean, default=False)

    @property
    def like_count(self):
        return len(self.likes)

    @property
    def comment_count(self):
        return len(self.comments)

    @property
    def tag_list(self):
        """Return tags as a list"""
        if not self.tags:
            return []
        return json.loads(self.tags)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('forum_post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id', name='fk_comment_parent'), nullable=True)
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy='dynamic')
    likes = db.relationship('CommentLike', backref='comment', lazy=True, cascade='all, delete-orphan')

    @property
    def like_count(self):
        return len(self.likes)

class CommentLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PostLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('forum_post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AnnouncementHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class GroupChatSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    agent_a_character = db.Column(db.String(100), nullable=False)
    agent_b_character = db.Column(db.String(100), nullable=False)
    agent_a_setting = db.Column(db.Text, nullable=False)
    agent_b_setting = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('group_chat_settings', lazy=True))

    def __repr__(self):
        return f'<GroupChatSetting {self.id} for user {self.user_id}>'

class SavedVoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    audio_url = db.Column(db.String(500), nullable=False)
    transcription = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('saved_voices', lazy=True))

    def __repr__(self):
        return f'<SavedVoice {self.id} for user {self.user_id}>'

class SecretKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(32), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_used = db.Column(db.Boolean, default=False)
    used_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    activated_at = db.Column(db.DateTime, nullable=True)
    days_valid = db.Column(db.Integer, default=30, nullable=False)
    user = db.relationship('User', backref=db.backref('secret_keys', lazy=True))

    def __repr__(self):
        return f'<SecretKey {self.key}>'

class Membership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    user = db.relationship('User', backref=db.backref('membership', lazy=True))

    def __repr__(self):
        return f'<Membership {self.id} for user {self.user_id}>'

    def is_valid(self):
        """Check if the membership is still valid"""
        if not self.is_active:
            return False

        now = datetime.now(timezone.utc)
        end_date = self.end_date

        # If end_date is naive, make it timezone-aware
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        return end_date > now

class ImageGeneration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class CharacterChat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    character_name = db.Column(db.String(200), nullable=False)
    chat_history = db.Column(db.Text, nullable=False)
    character_description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('character_chats', lazy=True))
    
    def __repr__(self):
        return f'<CharacterChat {self.character_name} - User {self.user_id}>'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# TTS functions are now imported from backend.ai_services

# Flask routes from the original app.py
@app.route('/')
def index():
    return render_template('home.html')

@app.route('/chat')
def chat():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
@throttle_requests
@limiter.limit("60 per hour")
def search():
    data = request.get_json()
    title = data.get('title', '').strip()

    if not title:
        return jsonify({'error': 'Please provide a title'}), 400

    # First check if story already exists in database
    existing_story = Story.query.filter_by(title=title).first()
    if existing_story:
        return jsonify([{
            'title': f"'{title}' Story Synopsis",
            'body': existing_story.original_content,
            'is_editable': True,
            'story_id': existing_story.id,
            'original_content': existing_story.original_content,
            'clear_character_chat': True
        }])

    # If story doesn't exist, use Kimi API for search
    content, error = make_kimi_request(title)
    if error:
        return jsonify([{
            'title': f"'{title}'",
            'body': f"{error}",
            'is_editable': False
        }])

    # Create a new story entry
    story = Story(
        title=title,
        original_content=content,
        user_id=current_user.id if current_user.is_authenticated else 1
    )
    db.session.add(story)
    db.session.commit()

    # Return the search results in the expected format
    return jsonify([{
        'title': f"'{title}' Story Synopsis",
        'body': content,
        'is_editable': True,
        'story_id': story.id,
        'original_content': content,
        'clear_character_chat': True
    }])

@app.route('/search_character', methods=['POST'])
@throttle_requests
@limiter.limit("60 per hour")
def search_character():
    data = request.get_json()
    title = data.get('title', '').strip()

    if not title:
        return jsonify({'error': 'Please provide character information'}), 400

    # First check if story already exists in database
    existing_story = Story.query.filter_by(title=title).first()
    if existing_story:
        return jsonify([{
            'title': f"'{title}' Character Introduction",
            'body': existing_story.original_content,
            'is_editable': True,
            'story_id': existing_story.id,
            'original_content': existing_story.original_content,
            'clear_character_chat': True
        }])

    # If story doesn't exist, use Kimi API for search
    content, error = make_kimi_character_request(title)
    if error:
        return jsonify([{
            'title': f"'{title}'",
            'body': f"{error}",
            'is_editable': False
        }])

    # Create a new story entry
    story = Story(
        title=title,
        original_content=content,
        user_id=current_user.id if current_user.is_authenticated else 1
    )
    db.session.add(story)
    db.session.commit()

    # Return the search results in the expected format
    return jsonify([{
        'title': f"'{title}' Character Introduction",
        'body': content,
        'is_editable': True,
        'story_id': story.id,
        'original_content': content,
        'clear_character_chat': True
    }])

@app.route('/generate', methods=['POST'])
@throttle_requests
@limiter.limit("100 per hour")
def generate():
    data = request.get_json()
    context = data.get('context')
    prompt = data.get('prompt')
    story_id = data.get('story_id')

    if not context or not prompt:
        return jsonify({'error': 'Please provide story content and ending direction'}), 400

    user_id = current_user.id if current_user.is_authenticated else 'guest'
    new_ending, error = generate_new_ending(user_id, context, prompt)
    if error:
        return jsonify({'error': error}), 500

    if story_id:
        story = Story.query.get(story_id)
        if story:
            story.edited_content = context
            story.new_ending = new_ending
            db.session.commit()

    return jsonify({'new_ending': new_ending})

@app.route('/likes')
@login_required
def my_stories():
    page = request.args.get('page', 1, type=int)
    tab = request.args.get('tab', 'posts')  # Default to posts tab
    per_page = 12

    # Initialize all pagination objects to page 1
    if not request.args.get('page'):
        page = 1

    # Get user's own posts with pagination
    user_posts = ForumPost.query\
        .filter_by(user_id=current_user.id)\
        .order_by(ForumPost.created_at.desc())\
        .paginate(page=1 if tab != 'posts' else page, per_page=per_page, error_out=False)

    # Get posts that the user has liked with pagination
    liked_posts = ForumPost.query\
        .join(PostLike)\
        .filter(PostLike.user_id == current_user.id)\
        .order_by(ForumPost.created_at.desc())\
        .paginate(page=1 if tab != 'likes' else page, per_page=per_page, error_out=False)

    # Get user's stories with pagination
    stories = Story.query\
        .filter_by(user_id=current_user.id)\
        .order_by(Story.created_at.desc())\
        .paginate(page=1 if tab != 'stories' else page, per_page=per_page, error_out=False)

    # Get posts from followed users with pagination
    followed_posts = ForumPost.query\
        .join(User, ForumPost.user_id == User.id)\
        .join(followers, followers.c.followed_id == User.id)\
        .filter(followers.c.follower_id == current_user.id)\
        .order_by(ForumPost.created_at.desc())\
        .paginate(page=1 if tab != 'following' else page, per_page=per_page, error_out=False)

    return render_template('my_stories.html',
                         user_posts=user_posts,
                         liked_posts=liked_posts,
                         stories=stories,
                         followed_posts=followed_posts,
                         active_tab=tab)

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("100000 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username_or_email = request.form.get('username')  # This field can be username or email
        password = request.form.get('password')

        # Try to find user by username or email
        user = User.query.filter(
            db.or_(
                User.username == username_or_email,
                User.email == username_or_email
            )
        ).first()

        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            if next_page and '/forum/create' in next_page:
                pending_content = session.get('pendingSharedContent')
                if pending_content:
                    session.pop('pendingSharedContent', None)
                    session['sharedContent'] = pending_content
            return redirect(next_page or url_for('index'))
        else:
            flash('Invalid username/email or password', 'error')

    return render_template('login.html')

@app.route('/send-verification-code', methods=['POST'])
def send_verification_code():
    """Send verification code to user's email"""
    try:
        data = request.get_json()
        email = data.get('email')

        if not email:
            return jsonify({'success': False, 'message': 'Please provide an email address'}), 400

        # Check if email already exists
        if User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'message': 'Email already registered'}), 400

        # Generate a 4-digit verification code
        verification_code = str(random.randint(1000, 9999))
        
        # Store the code in session
        session[f'verification_code_{email}'] = verification_code
        
        # Set expiration time (1 hour)
        session[f'verification_code_expiry_{email}'] = int(time.time()) + 3600

        msg = Message(f'Your TalkTalkAI Verification Code: {verification_code}',
                     recipients=[email])
        msg.body = f'''Hello,

Thank you for registering with TalkTalkAI! To complete your account setup, please use the verification code below:

Verification Code: {verification_code}

This code will expire in 1 hour from the time this email was sent.

If you did not attempt to register for TalkTalkAI, you can safely ignore this message.

Best regards,
The TalkTalkAI Team
'''
        mail.send(msg)
        return jsonify({'success': True, 'message': 'Verification code sent. Please check your inbox.'})
    except Exception as e:
        app.logger.error(f'Error in send_verification_code: {str(e)}')
        return jsonify({'success': False, 'message': 'Failed to send verification code. Please try again later.'}), 500

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        verification_code = request.form.get('verification_code')

        if not all([username, password, email, verification_code]):
            flash('Please fill in all required fields')
            return redirect(url_for('register'))

        # Check if username already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))

        # Check if email already exists
        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('register'))
            
        # Verify the code
        session_key = f'verification_code_{email}'
        stored_code = session.get(session_key)
        stored_timestamp = session.get(f'verification_code_expiry_{email}')
        
        # Check if code exists and hasn't expired
        if not stored_code or not stored_timestamp or time.time() > stored_timestamp:
            flash('Verification code is invalid or has expired. Please request a new code.')
            return redirect(url_for('register'))
            
        # Check if the code matches
        if stored_code != verification_code:
            flash('Invalid verification code. Please try again.')
            return redirect(url_for('register'))

        try:
            # Create new user
            user = User(username=username, email=email)
            user.set_password(password)
            user.is_verified = True  # Mark as verified since code was confirmed

            db.session.add(user)
            db.session.commit()
            
            # Clear the verification code from session
            session.pop(session_key, None)
            session.pop(f'verification_code_expiry_{email}', None)

            flash('Registration successful! You can now log in.')
            return redirect(url_for('login'))

        except Exception as e:
            db.session.rollback()
            app.logger.error(f'Registration error: {str(e)}')
            flash('Registration failed, please try again')
            return redirect(url_for('register'))

    return render_template('register.html')

@app.route('/verify-email/<token>')
def verify_email(token):
    try:
        email = serializer.loads(token, salt='email-confirm', max_age=3600)  # 1 hour expiration
        user = User.query.filter_by(email=email).first()

        if user:
            user.is_verified = True
            db.session.commit()
            flash('Email verified successfully! Please log in to your TalkTalkAI account.', 'success')
        else:
            flash('Invalid verification link.', 'error')

        return redirect(url_for('login'))
    except:
        flash('The verification link is invalid or has expired.', 'error')
        return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/clear_session')
def clear_session():
    session.clear()
    return "Session cleared!", 200

@app.route('/clear-chat', methods=['POST'])
def clear_chat():
    """Clear all chat histories for the current session"""
    try:
        # Clear both character chat and new ending histories
        session['chat_history'] = []
        session['new_ending_history'] = []
        session.modified = True
        return jsonify({"success": True, "message": "Chat history cleared! What other novels or movies do you like? Tell me!"})
    except Exception as e:
        print("Error clearing chat history:", str(e))
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/character-chat', methods=['POST'])
@throttle_requests
@limiter.limit("1000 per hour")
def handle_character_chat():
    """Handle character chat requests"""
    try:
        data = request.get_json()
        story_content = data.get('story_content')
        character_name = data.get('character_name')
        message = data.get('message')
        model_type = data.get('model_type', 'doubao')  # Default to doubao if not specified

        if not all([story_content, character_name, message]):
            return jsonify({'error': 'Please ensure the "Original Plot Edit Area" is filled correctly. Search for the work name first.'}), 400

        user_id = current_user.id if current_user.is_authenticated else None
        history_key = get_chat_history_key(user_id)

        # Initialize session chat history if not exists
        if 'chat_history' not in session:
            session['chat_history'] = []

        response, error, actual_ai_response = character_chat(history_key, model_type, story_content, character_name, message)
        if error:
            return jsonify({'error': error}), 400

        # Add the new message and response to session history
        session['chat_history'].extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": actual_ai_response}
        ])
        session.modified = True

        return jsonify({'response': response})
    except Exception as e:
        print("Error in handle_character_chat:", str(e))
        return jsonify({'error': str(e)}), 500

# Basic TTS routes
@app.route('/tts')
def text_to_speech_page():
    return render_template('text_to_speech.html')

@app.route('/vc')
def voice_conversion_page():
    return render_template('voice_conversion.html')

@app.route('/music')
def music_generation_page():
    return render_template('music_generation.html')

@app.route('/voice')
@login_required
def character_chat_page():
    return render_template('character_chat.html')

@app.route('/party')
def group_chat_page():
    return render_template('group_chat.html')

# Password reset functionality
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        
        if not email:
            flash('Please enter your email address', 'error')
            return redirect(url_for('forgot_password'))
            
        user = User.query.filter_by(email=email).first()
        if not user:
            flash('Email not found. Please check your email address.', 'error')
            return redirect(url_for('forgot_password'))
            
        if send_password_reset_email(email):
            flash('Password reset email has been sent. Please check your inbox.', 'success')
        else:
            flash('Failed to send reset email. Please try again later.', 'error')
        
        return redirect(url_for('login'))
        
    return render_template('forgot_password.html')
    
@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_form(token):
    try:
        email = serializer.loads(token, salt='password-reset', max_age=3600)
    except:
        flash('The password reset link is invalid or has expired.', 'error')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not password or not confirm_password:
            flash('Please enter both password fields', 'error')
            return render_template('reset_password.html', token=token)
            
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('reset_password.html', token=token)
            
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(password)
            db.session.commit()
            flash('Your password has been reset successfully. Please login with your new password.', 'success')
            return redirect(url_for('login'))
        else:
            flash('User not found', 'error')
            return redirect(url_for('login'))
            
    return render_template('reset_password.html', token=token)

@app.route('/reset_password', methods=['POST'])
def reset_password_with_email():
    """API endpoint for password reset with email (for AJAX requests)"""
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'message': 'Please provide your email address'}), 400
        
        # Find user by email
        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({'success': False, 'message': 'Email not found. Please check your email address.'}), 404
        
        # Send password reset email
        if send_password_reset_email(email):
            return jsonify({'success': True, 'message': 'Password reset email has been sent. Please check your inbox.'})
        else:
            return jsonify({'success': False, 'message': 'Failed to send reset email. Please try again later.'}), 500
            
    except Exception as e:
        app.logger.error(f'Password reset error: {str(e)}')
        return jsonify({'success': False, 'message': 'Password reset failed. Please try again later.'}), 500

# NOTE: Due to the complexity of migrating 76+ routes, this shows the critical functionality.
# Additional routes for forum, admin, TTS processing, membership, etc. would need to be added
# to complete the full migration. The core authentication and basic functionality is now present.

# Add error handler for rate limit exceeded
@app.errorhandler(429)
def ratelimit_handler(e):
    identifier = get_request_identifier()
    endpoint = request.endpoint

    # For hourly limits, we need to calculate the remaining time in the current hour
    current_time = datetime.now()
    next_hour = (current_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    wait_seconds = (next_hour - current_time).total_seconds()

    minutes = int(wait_seconds // 60)
    seconds = int(wait_seconds % 60)
    wait_time_str = f"{minutes} min {seconds} sec" if minutes > 0 else f"{seconds} sec"

    # Return a user-friendly message for the web interface
    if request.is_json:
        return jsonify({
            "error": f"Rate limit exceeded. Please wait {wait_time_str} before trying again.",
            "identifier": identifier,
            "retry_after": e.description
        }), 429

    # Return a more technical message for non-JSON requests
    return jsonify({
        "error": f"Rate limit exceeded. Please wait {wait_time_str} before trying again.",
        "identifier": identifier,
        "retry_after": e.description
    }), 429

# Add template filters and context processors
@app.template_filter('json_loads')
def json_loads_filter(s):
    try:
        return json.loads(s) if s else []
    except:
        return []

@app.template_filter('add_hours')
def add_hours(dt, hours=8):
    """Return a datetime shifted by `hours`."""
    if dt is None:
        return None
    return dt + timedelta(hours=hours)

@app.template_filter('china_time')
def china_time_filter(dt):
    """Convert UTC time to China time and format it"""
    if not dt:
        return ''
    china_tz = timezone(timedelta(hours=8))
    if dt.tzinfo is None:
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        dt = dt.replace(tzinfo=local_tz).astimezone(timezone.utc)
    china_time = dt.astimezone(china_tz)
    return china_time.strftime('%Y-%m-%d %H:%M')

@app.template_filter('truncate_text')
def truncate_text(text, length=100):
    """Truncate text to the specified length and add ellipsis if needed."""
    from markupsafe import escape
    if not text:
        return ""

    safe_text = escape(text)
    safe_text = safe_text.replace('\n', ' ').replace('\r', '')

    if len(safe_text) <= length:
        return safe_text

    return safe_text[:length] + '...'

@app.context_processor
def utility_processor():
    return {
        'get_default_avatar': get_default_avatar
    }

# NOTE: All other routes from the original app.py need to be added here following the same pattern
# This includes all the login, register, forum, admin, TTS, etc. routes

if __name__ == '__main__':
    with app.app_context():
        # Only create tables if they don't exist
        db.create_all()
        
        # Check if points column exists and add it if it doesn't
        try:
            inspector = inspect(db.engine)
            columns = [column['name'] for column in inspector.get_columns('user')]
            
            # Add points columns if they don't exist
            if 'points' not in columns:
                print("Adding 'points' column to User table...")
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE "user" ADD COLUMN points INTEGER DEFAULT 30 NOT NULL'))
                    conn.commit()
            
            if 'last_points_reset' not in columns:
                print("Adding 'last_points_reset' column to User table...")
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE "user" ADD COLUMN last_points_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL'))
                    conn.commit()
                    
            print("Points system columns added successfully!")
                
            # Create backup of existing data
            backup_database()
            print("Database checked and ready - all existing data preserved!")
        except Exception as e:
            print(f"Error checking/updating database: {str(e)}")
    app.run(debug=True, port=5002, host='0.0.0.0') 