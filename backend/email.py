import random
import time
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from flask import url_for, current_app
from backend.config import Config

def send_verification_email(user_email):
    """Send verification email to user with verification link"""
    try:
        # Get Flask app context for mail and serializer
        mail = current_app.extensions['mail']
        serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        
        # Generate verification token
        token = serializer.dumps(user_email, salt='email-confirm')
        verify_url = url_for('verify_email', token=token, _external=True)
        
        msg = Message('Verify Your Email Address - TalkTalkAI',
                     recipients=[user_email])
        msg.body = f'''Hello,

Welcome to TalkTalkAI! To complete your registration, please click the following link to verify your email address:

{verify_url}

This link will expire in 1 hour. If you did not create an account with TalkTalkAI, you can safely ignore this email.

Best regards,
The TalkTalkAI Team
'''
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f'Error sending verification email: {str(e)}')
        return False

def send_password_reset_email(user_email):
    """Send password reset email to user"""
    try:
        # Get Flask app context for mail and serializer
        mail = current_app.extensions['mail']
        serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        
        token = serializer.dumps(user_email, salt='password-reset')
        reset_url = url_for('reset_password_form', token=token, _external=True)
        
        msg = Message('Reset Your Password - TalkTalkAI',
                     recipients=[user_email])
        msg.body = f'''Hello,

You requested to reset your password. Please click the following link to reset your password:
{reset_url}

This link will expire in 1 hour. If you did not request a password reset, please ignore this email.

Thank you,
TalkTalkAI Team
'''
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f'Error sending password reset email: {str(e)}')
        return False 