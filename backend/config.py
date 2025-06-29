import os
from datetime import timedelta

class Config:
    # Flask Configuration
    SECRET_KEY = os.getenv('SECRET_KEY') or 'your-secret-key-here'
    
    # Database Configuration
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 20,
        'max_overflow': 5,
        'pool_timeout': 30,
        'pool_recycle': 1800,
    }
    
    # AWS S3 Configuration
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-2')
    S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'your-bucket-name')
    
    # Email Configuration
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.qq.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', '465'))
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'True').lower() == 'true'
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'False').lower() == 'true'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER')
    
    # API Keys
    DOUBAO_API_KEY = os.getenv('DOUBAO_API_KEY')
    KIMI_API_KEY = os.getenv('KIMI_API_KEY')
    AZURE_SPEECH_KEY = os.getenv('AZURE_SPEECH_KEY')
    AZURE_SPEECH_REGION = os.getenv('AZURE_SPEECH_REGION', 'eastus')
    
    # Image Generation API
    IMAGE_GEN_AK = os.getenv('IMAGE_GEN_AK')
    IMAGE_GEN_SK = os.getenv('IMAGE_GEN_SK')
    
    # Rate Limiting
    REQUEST_COOLDOWN = 3
    RATELIMIT_STORAGE_URL = os.getenv('RATELIMIT_STORAGE_URL', 'memory://')
    
    # File Upload
    UPLOAD_FOLDER = 'static/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    @classmethod
    def validate_required_env_vars(cls):
        """Validate that all required environment variables are set"""
        # Map validation names to actual config attribute names
        required_config_vars = {
            'SECRET_KEY': 'SECRET_KEY',
            'DATABASE_URL': 'SQLALCHEMY_DATABASE_URI',
            'AWS_ACCESS_KEY_ID': 'AWS_ACCESS_KEY_ID',
            'AWS_SECRET_ACCESS_KEY': 'AWS_SECRET_ACCESS_KEY',
            'S3_BUCKET_NAME': 'S3_BUCKET_NAME',
            'MAIL_USERNAME': 'MAIL_USERNAME',
            'MAIL_PASSWORD': 'MAIL_PASSWORD',
            'DOUBAO_API_KEY': 'DOUBAO_API_KEY',
            'KIMI_API_KEY': 'KIMI_API_KEY',
            'AZURE_SPEECH_KEY': 'AZURE_SPEECH_KEY',
            'IMAGE_GEN_AK': 'IMAGE_GEN_AK',
            'IMAGE_GEN_SK': 'IMAGE_GEN_SK'
        }
        
        missing_vars = []
        for env_var, config_attr in required_config_vars.items():
            if not getattr(cls, config_attr):
                missing_vars.append(env_var)
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        return True 