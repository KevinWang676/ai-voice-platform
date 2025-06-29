import random
import string
from datetime import datetime, timezone

def generate_secret_key(db, SecretKey, days_valid=30):
    """Generate a new secret key for membership activation"""
    # Generate a random 32-character key
    key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=32))
    
    # Save the key to the database
    secret_key = SecretKey(
        key=key,
        created_at=datetime.now(),
        is_used=False,
        days_valid=days_valid
    )
    db.session.add(secret_key)
    db.session.commit()
    
    return secret_key

def activate_secret_key(db, SecretKey, User, key, user_id):
    """Activate a secret key for a user"""
    # Look up the key
    secret_key = SecretKey.query.filter_by(key=key).first()
    
    if not secret_key:
        return False, "Invalid activation code"
    
    if secret_key.is_used:
        return False, "This activation code has already been used"
    
    # Mark the key as used
    secret_key.is_used = True
    secret_key.used_by = user_id
    secret_key.activated_at = datetime.now(timezone.utc)
    
    # Update user's membership
    user = User.query.get(user_id)
    if user:
        user.extend_membership(secret_key.days_valid)
    
    db.session.commit()
    return True, f"Activation successful! Your membership has been extended by {secret_key.days_valid} days." 