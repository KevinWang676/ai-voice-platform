# DoingDream AI - Open Source Deployment Guide

## Project Overview

This is the simplified codebase of the all-in-one voice platform currently used by over **17,000** users. The official website, developed by Kevin Wang, is available at https://www.doingdream.com/

DoingDream AI is a comprehensive AI-powered platform featuring:
- **Story Generation**: AI-powered story creation and ending generation
- **Character Chat**: Interactive conversations with fictional characters
- **Text-to-Speech**: Advanced TTS with voice cloning capabilities
- **Voice Conversion**: Transform your voice to match reference audio
- **Music Generation**: Create music from lyrics and prompts
- **Image Generation**: AI-powered image creation
- **Forum System**: Community discussion platform
- **Group Chat**: Multi-character AI conversations

## Project Structure

```
ai-voice-platform/
├── backend/                     # Backend modules (NEW)
│   ├── __init__.py             # Package initialization
│   ├── config.py               # Environment configuration
│   ├── storage.py              # S3 and file storage functions
│   ├── ai_services.py          # AI service integrations (TTS, Image Gen, etc.)
│   ├── ai_chat.py              # AI chat functions (Kimi, Doubao, Character chat)
│   ├── utils.py                # General utility functions
│   ├── email.py                # Email services
│   ├── decorators.py           # Custom decorators
│   └── auth.py                 # Authentication and membership functions
├── app.py                      # Main Flask application (UPDATED)
├── env.example                 # Environment variables template (NEW)
├── requirements.txt            # Python dependencies
├── static/                     # Static files (CSS, JS, images)
├── templates/                  # HTML templates
└── README_DEPLOYMENT.md        # This deployment guide (NEW)
```


## Backend Modules

#### `backend/config.py`
- Environment variable management
- Configuration validation
- Default value handling

#### `backend/storage.py`
- AWS S3 integration
- File upload/download functions
- Image processing utilities

#### `backend/ai_services.py`
- Text-to-Speech APIs
- Voice conversion services
- Image generation (Volcengine)
- Music generation

#### `backend/ai_chat.py`
- Kimi API integration (web search)
- Doubao API integration (chat)
- Character chat functions
- Story ending generation

#### `backend/utils.py`
- Utility functions
- Rate limiting decorators
- Chat history management
- Time zone handling

## Environment Setup

### 1. Clone the Repository
```bash
git clone https://github.com/KevinWang676/ai-voice-platform.git
cd ai-voice-platform
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Environment Configuration

#### Copy the example environment file:
```bash
cp env.example .env
```

#### Configure your environment variables in `.env`:

```bash
# Flask Configuration
SECRET_KEY=your-unique-secret-key-here
DATABASE_URL=postgresql://username:password@localhost:5432/talktalkai

# AWS S3 Configuration (Required for file storage)
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
AWS_REGION=us-east-2
S3_BUCKET_NAME=your-bucket-name

# Email Configuration (Required for user registration)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_SSL=False
MAIL_USE_TLS=True
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
MAIL_DEFAULT_SENDER=your-email@gmail.com

# AI API Keys (Required for AI features)
DOUBAO_API_KEY=your-doubao-api-key
KIMI_API_KEY=your-kimi-api-key
AZURE_SPEECH_KEY=your-azure-speech-key
AZURE_SPEECH_REGION=eastus

# Image Generation API (Required for image generation)
IMAGE_GEN_AK=your-volcengine-access-key
IMAGE_GEN_SK=your-volcengine-secret-key

# Optional
RATELIMIT_STORAGE_URL=memory://
```

## Required Services Setup

### 1. Database (PostgreSQL)
```bash
# Local PostgreSQL
createdb talktalkai

# Or use a cloud service like:
# - Render PostgreSQL
# - AWS RDS
# - Google Cloud SQL
# - Heroku PostgreSQL
```

### 2. AWS S3 Bucket
1. Create an AWS account
2. Create an S3 bucket
3. Create an IAM user with S3 permissions
4. Get access key and secret key

### 3. Email Service
Choose one of:
- **Gmail**: Use app-specific password
- **QQ Mail**: Get authorization code
- **SendGrid**: Commercial email service
- **AWS SES**: Amazon's email service

### 4. AI API Keys

#### Doubao API (ByteDance)
- Sign up at Volcengine
- Create API key for Doubao model

#### Kimi API (Moonshot)
- Register at Moonshot AI
- Get API key for web search

#### Azure Speech Services
- Create Azure account
- Enable Speech Services
- Get subscription key

#### Volcengine Image Generation
- Register at Volcengine
- Enable image generation service
- Get access key and secret key

## Deployment Options

### Option 1: Local Development
```bash
# Set environment variables
export FLASK_APP=app.py
export FLASK_ENV=development

# Run the application
python app.py
```

### Option 2: Production Deployment

#### Using Gunicorn
```bash
# Install gunicorn
pip install gunicorn

# Run with gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

#### Using Docker
```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

#### Cloud Deployment Platforms
- **Render**: Easy deployment with PostgreSQL
- **Heroku**: Traditional PaaS platform
- **AWS Elastic Beanstalk**: AWS managed platform
- **Google Cloud Run**: Serverless containers
- **DigitalOcean App Platform**: Simple deployment

### Option 3: Render Deployment (Recommended)

1. **Connect your GitHub repository to Render**
2. **Create a new Web Service**
3. **Set environment variables in Render dashboard**
4. **Create PostgreSQL database in Render**
5. **Deploy automatically on git push**

Example Render configuration:
```yaml
# render.yaml
services:
  - type: web
    name: talktalkai
    env: python
    buildCommand: "pip install -r requirements.txt"
    startCommand: "gunicorn -w 4 -b 0.0.0.0:$PORT app:app"
    envVars:
      - key: SECRET_KEY
        generateValue: true
      - key: DATABASE_URL
        fromDatabase:
          name: talktalkai-db
          property: connectionString
```

## Database Migration
```bash
# Initialize migration repository (first time only)
flask db init

# Create migration
flask db migrate -m "Initial migration"

# Apply migration
flask db upgrade
```

## Security Considerations

### 1. Environment Variables
- Never commit `.env` file to git
- Use strong, unique secret keys
- Rotate API keys regularly

### 2. Production Settings
```python
# In production, set these environment variables:
FLASK_ENV=production
SECRET_KEY=very-long-random-string
DATABASE_URL=your-production-database-url
```

### 3. Rate Limiting
- The app includes built-in rate limiting
- Adjust limits in `backend/utils.py` as needed
- Consider using Redis for distributed rate limiting

### 4. HTTPS
- Always use HTTPS in production
- Most cloud platforms provide SSL certificates
- Configure your reverse proxy (nginx) for HTTPS

## Monitoring and Logging

### Application Logs
```python
import logging
logging.basicConfig(level=logging.INFO)
```

### Error Tracking
Consider integrating:
- **Sentry**: Error tracking and performance monitoring
- **LogRocket**: Frontend error tracking
- **Datadog**: Comprehensive monitoring

## Performance Optimization

### 1. Database
- Add database indexes for frequently queried fields
- Use connection pooling
- Consider read replicas for heavy read workloads

### 2. Caching
- Implement Redis for session storage
- Cache frequently accessed data
- Use CDN for static files

### 3. Background Tasks
```python
# Consider using Celery for background tasks
from celery import Celery

celery = Celery('talktalkai')
celery.config_from_object('celeryconfig')

@celery.task
def process_audio_file(file_path):
    # Long-running audio processing
    pass
```

## API Rate Limits

The application implements several rate limiting strategies:
- **Global**: 10,000 requests per minute per user
- **Search**: 60 requests per hour
- **TTS Generation**: 60 requests per hour
- **Voice Conversion**: 60 requests per hour
- **Image Generation**: 30 requests per hour

## Troubleshooting

### Common Issues

#### 1. "Missing required environment variables"
- Check that all required variables are set in your `.env` file
- Verify environment variable names match exactly

#### 2. Database connection errors
- Verify DATABASE_URL is correct
- Check database server is running
- Ensure database exists

#### 3. S3 upload failures
- Verify AWS credentials are correct
- Check S3 bucket permissions
- Ensure bucket exists in specified region

#### 4. AI API errors
- Verify API keys are valid
- Check API quotas and billing
- Monitor API rate limits

### Debug Mode
```bash
export FLASK_DEBUG=1
export FLASK_ENV=development
python app.py
```

## Contributing

### Development Setup
1. Fork the repository
2. Create a feature branch
3. Set up development environment with `.env`
4. Make your changes
5. Test thoroughly
6. Submit a pull request

### Code Style
- Follow PEP 8 for Python code
- Use meaningful variable names
- Add docstrings to functions
- Include error handling

## License

[Add your license information here]

## Support

For issues and questions:
1. Check this README first
2. Search existing GitHub issues
3. Create a new issue with detailed information
4. Include logs and error messages

## Credits

- **Flask**: Web framework
- **SQLAlchemy**: Database ORM
- **Doubao API**: AI chat capabilities
- **Kimi API**: Web search functionality
- **Azure Speech**: Text-to-speech services
- **AWS S3**: File storage
- **Volcengine**: Image generation

---

**Important**: This application requires several paid APIs and services. Make sure you understand the costs involved before deploying to production. 
