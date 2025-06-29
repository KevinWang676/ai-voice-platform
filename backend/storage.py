import boto3
import io
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from PIL import Image
import uuid
from flask_login import current_user
from backend.config import Config

# Initialize S3 client
s3 = boto3.client(
    "s3",
    aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
    region_name=Config.AWS_REGION,
)

def upload_to_s3(file, folder=""):
    """Upload a file to S3 and return the URL"""
    try:
        # Create a unique filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        original_filename = secure_filename(file.filename)
        file_extension = os.path.splitext(original_filename)[1]
        unique_filename = f"{folder}/{timestamp}{file_extension}"

        # Read file content
        file_content = file.read()

        # Upload to S3
        s3.upload_fileobj(io.BytesIO(file_content), Config.S3_BUCKET_NAME, unique_filename)

        # Generate the URL
        file_url = f"https://{Config.S3_BUCKET_NAME}.s3.{Config.AWS_REGION}.amazonaws.com/{unique_filename}"
        return file_url
    except Exception as e:
        print(f"S3 upload error: {str(e)}")
        return None

def delete_from_s3(file_url):
    """Delete a file from S3 using its URL"""
    try:
        if not file_url:
            return
        # Extract the key from the URL
        key = file_url.split(f"{Config.S3_BUCKET_NAME}.s3.{Config.AWS_REGION}.amazonaws.com/")[1]
        s3.delete_object(Bucket=Config.S3_BUCKET_NAME, Key=key)
    except Exception as e:
        print(f"S3 delete error: {str(e)}")

def upload_wav_to_s3(file, folder="", default_extension=".wav"):
    """
    Upload a WAV file (or other audio file) to S3.

    Args:
        file: The file object to upload (either a file path or file-like object)
        folder: Optional folder path within the S3 bucket
        default_extension: Default file extension if the original filename is not available

    Returns:
        str: URL of the uploaded file if successful, None otherwise
    """
    try:
        # Determine if the input is a file path or file object
        if isinstance(file, str):
            # If it's a file path, open it in binary read mode
            file_obj = open(file, 'rb')
        else:
            # Otherwise, assume it's a file object
            file_obj = file

        # Check if the file object has a 'read' method
        if not hasattr(file_obj, 'read') or not callable(file_obj.read):
            print("Error: The provided file object does not have a 'read' method.")
            if isinstance(file, str):
                file_obj.close()  # Clean up if we opened the file
            return None

        # Reset the file pointer to the beginning (if seekable)
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)

        # Generate a unique filename with microsecond precision and UUID
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        unique_id = str(uuid.uuid4())[:4]  # Use first 4 chars of UUID for brevity

        # Add user_id to filename if available in session
        user_identifier = ""
        try:
            if current_user and hasattr(current_user, 'id') and current_user.id:
                user_identifier = f"user{current_user.id}_"
        except:
            pass  # current_user might not be available in all contexts

        if hasattr(file_obj, 'filename') and file_obj.filename:
            # Use the filename attribute if available (e.g., from Flask file uploads)
            original_filename = secure_filename(file_obj.filename)
            file_extension = os.path.splitext(original_filename)[1]
        else:
            # Fallback to default extension
            file_extension = default_extension

        unique_filename = f"{folder}/{user_identifier}{timestamp}_{unique_id}{file_extension}".lstrip('/')

        # Upload the file to S3
        s3.upload_fileobj(file_obj, Config.S3_BUCKET_NAME, unique_filename)

        # Construct the file URL
        file_url = f"https://{Config.S3_BUCKET_NAME}.s3.{Config.AWS_REGION}.amazonaws.com/{unique_filename}"

        # Close the file if we opened it
        if isinstance(file, str):
            file_obj.close()

        return file_url
    except Exception as e:
        print(f"Error uploading file to S3: {str(e)}")
        # Close the file if we opened it and an error occurred
        if isinstance(file, str) and 'file_obj' in locals():
            file_obj.close()
        return None

def save_profile_image(file):
    """Process and save the uploaded profile image to S3"""
    try:
        # Check file size (8MB limit)
        file.seek(0, 2)  # Seek to end of file
        file_size = file.tell()
        file.seek(0)  # Reset file pointer

        if file_size > 8 * 1024 * 1024:  # 8MB in bytes
            return None

        # Read and process the image
        image = Image.open(file)

        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Create a square crop
        width, height = image.size
        size = min(width, height)
        left = (width - size) // 2
        top = (height - size) // 2
        right = left + size
        bottom = top + size
        image = image.crop((left, top, right, bottom))

        # Resize to standard size (300x300)
        image = image.resize((300, 300), Image.Resampling.LANCZOS)

        # Save the processed image to a bytes buffer
        buffer = io.BytesIO()
        image.save(buffer, 'JPEG', quality=85)
        buffer.seek(0)

        # Generate unique filename with user ID for better tracking
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        user_id = current_user.id if current_user and hasattr(current_user, 'id') else 'unknown'
        filename = f"profile_pictures/user_{user_id}_{timestamp}.jpg"

        # Upload to S3
        s3.upload_fileobj(buffer, Config.S3_BUCKET_NAME, filename)

        # Generate and return the S3 URL
        file_url = f"https://{Config.S3_BUCKET_NAME}.s3.{Config.AWS_REGION}.amazonaws.com/{filename}"
        return file_url

    except Exception as e:
        print(f"Error processing image: {str(e)}")
        return None 