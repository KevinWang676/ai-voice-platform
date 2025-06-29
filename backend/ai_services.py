import json
import requests
import io
import tempfile
import os
import torch
import torchaudio
import numpy as np
import azure.cognitiveservices.speech as speechsdk
from openai import OpenAI
from volcenginesdkarkruntime import Ark
from datetime import datetime, timezone
import hmac
import hashlib
import urllib.parse
from dataclasses import dataclass
from typing import Optional, Dict
from pydub import AudioSegment
from backend.config import Config
from backend.storage import upload_wav_to_s3

@dataclass
class LogoInfo:
    add_logo: bool = False
    position: int = 0  # 0-bottom right 1-bottom left 2-top left 3-top right
    language: int = 0  # 0-Chinese 1-English
    opacity: float = 0.3
    logo_text_content: str = ""

class TextToImageAPI:
    def __init__(self, ak: str, sk: str):
        """
        Initialize the Text to Image API client

        Args:
            ak: Access Key
            sk: Secret Key
        """
        self.base_url = "https://visual.volcengineapi.com"
        self.ak = ak
        self.sk = sk
        self.service = "cv"
        self.region = "cn-north-1"

    def _get_canonical_headers(self, headers: Dict[str, str]) -> tuple:
        """Get canonical headers and signed headers"""
        canonical_headers = []
        signed_headers = []

        for k, v in sorted(headers.items()):
            lower_k = k.lower()
            strip_v = v.strip()
            canonical_headers.append(f"{lower_k}:{strip_v}")
            signed_headers.append(lower_k)

        return '\n'.join(canonical_headers) + '\n', ';'.join(signed_headers)

    def _get_canonical_request(self,
                             method: str,
                             url: str,
                             params: Dict[str, str],
                             headers: Dict[str, str],
                             payload: str) -> str:
        """Generate canonical request string"""
        canonical_uri = urllib.parse.urlparse(url).path or '/'

        # Sort query parameters
        query_params = []
        for k, v in sorted(params.items()):
            query_params.append(f"{k}={urllib.parse.quote(str(v))}")
        canonical_querystring = '&'.join(query_params)

        canonical_headers, signed_headers = self._get_canonical_headers(headers)

        payload_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()

        canonical_request = f"{method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        return canonical_request

    def _get_signature(self,
                      key: bytes,
                      date: str,
                      region: str,
                      service: str,
                      string_to_sign: str) -> str:
        """Calculate the signature"""
        k_date = hmac.new(key, date.encode('utf-8'), hashlib.sha256).digest()
        k_region = hmac.new(k_date, region.encode('utf-8'), hashlib.sha256).digest()
        k_service = hmac.new(k_region, service.encode('utf-8'), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b'request', hashlib.sha256).digest()

        return hmac.new(k_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    def _generate_auth_header(self, method: str, url: str, params: Dict, payload: Dict) -> Dict[str, str]:
        """Generate headers with authentication"""
        now = datetime.utcnow()
        date = now.strftime('%Y%m%d')
        iso_date = now.strftime('%Y%m%dT%H%M%SZ')

        headers = {
            'Content-Type': 'application/json',
            'Host': 'visual.volcengineapi.com',
            'X-Date': iso_date
        }

        # Convert payload to string
        payload_str = json.dumps(payload)

        # Get canonical request
        canonical_request = self._get_canonical_request(
            method,
            url,
            params,
            headers,
            payload_str
        )

        # Create string to sign
        algorithm = 'HMAC-SHA256'
        credential_scope = f"{date}/{self.region}/{self.service}/request"
        string_to_sign = f"{algorithm}\n{iso_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

        # Calculate signature
        signature = self._get_signature(
            self.sk.encode('utf-8'),
            date,
            self.region,
            self.service,
            string_to_sign
        )

        # Create authorization header
        signed_headers = 'content-type;host;x-date'
        credential = f"{self.ak}/{credential_scope}"
        auth_header = f"{algorithm} Credential={credential}, SignedHeaders={signed_headers}, Signature={signature}"

        headers['Authorization'] = auth_header
        headers['Region'] = self.region
        headers['Service'] = self.service

        return headers

    def generate_image(
        self,
        prompt: str,
        width: int = 512,
        height: int = 288,
        seed: int = -1,
        scale: float = 3.5,
        ddim_steps: int = 30,
        use_sr: bool = True,
        use_pre_llm: bool = False,
        return_url: bool = True,
        logo_info: Optional[LogoInfo] = None,
        req_schedule_conf: str = "general_v20_9B_pe"
    ) -> Dict:
        """
        Generate image from text prompt

        Args:
            prompt: Text prompt for image generation
            width: Image width (256-768)
            height: Image height (256-768)
            seed: Random seed (-1 for random)
            scale: Text influence degree (1-10)
            ddim_steps: Generation steps (1-100)
            use_sr: Whether to use super resolution
            use_pre_llm: Whether to use prompt enhancement
            return_url: Whether to return image URL
            logo_info: Logo watermark configuration
            req_schedule_conf: Schedule configuration

        Returns:
            API response dictionary
        """
        # Query parameters
        params = {
            'Action': 'CVProcess',
            'Version': '2022-08-31'
        }

        # Prepare request payload
        payload = {
            "req_key": "high_aes_general_v20_L",
            "prompt": prompt,
            "model_version": "general_v2.0_L",
            "req_schedule_conf": req_schedule_conf,
            "seed": seed,
            "scale": scale,
            "ddim_steps": ddim_steps,
            "width": width,
            "height": height,
            "use_sr": use_sr,
            "use_pre_llm": use_pre_llm,
            "return_url": return_url
        }

        # Add logo info if provided
        if logo_info:
            payload["logo_info"] = {
                "add_logo": logo_info.add_logo,
                "position": logo_info.position,
                "language": logo_info.language,
                "opacity": logo_info.opacity,
                "logo_text_content": logo_info.logo_text_content
            }

        # Generate headers with authentication
        headers = self._generate_auth_header('POST', self.base_url, params, payload)

        # Construct full URL
        url = f"{self.base_url}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=30  # Add timeout
            )

            # Print debug information
            print(f"Request URL: {url}")
            print(f"Request Headers: {json.dumps(headers, indent=2)}")
            print(f"Request Payload: {json.dumps(payload, indent=2)}")
            print(f"Response Status: {response.status_code}")
            print(f"Response Body: {response.text}")

            response.raise_for_status()

            result = response.json()

            if result.get("code") != 10000:
                raise Exception(f"API Error: {result.get('message', 'Unknown error')}")

            return result

        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {str(e)}")

def generate_tts_audio(prompt_wav_file, prompt_text, tts_text, speed=1.0):
    """
    Generates speech from text using a TTS API and uploads the result to S3

    Args:
        tts_text (str): The text to convert to speech, including special tags
        prompt_text (str): The clean text prompt
        prompt_wav_file (str): Path to the WAV file to use as voice prompt or file-like object
        speed (float): Speaking speed multiplier (0.5 to 2.0, default: 1.0)

    Returns:
        str or dict: S3 file URL on success, or error dictionary on failure
    """
    # Validate speed parameter
    try:
        speed_value = float(speed)
        if speed_value < 0.5 or speed_value > 2.0:
            print(f"Warning: Speed value {speed_value} out of range (0.5-2.0). Using default 1.0 instead.")
            speed_value = 1.0
    except (ValueError, TypeError):
        print(f"Warning: Invalid speed format '{speed}'. Using default 1.0 instead.")
        speed_value = 1.0

    # Upload the prompt WAV file to S3 first
    reference_url = upload_wav_to_s3(prompt_wav_file, folder="reference_audio")
    if not reference_url:
        return {
            'success': False,
            'message': 'Failed to upload reference audio to S3',
            'time': int(datetime.now().timestamp())
        }

    # TTS API call
    url = "https://bfd4e958cca0.ngrok.app/inference_zero_shot"
    payload = {
        'tts_text': tts_text,
        'prompt_text': prompt_text,
        'prompt_wav_url': reference_url,
        'speed': str(speed_value)  # Add speed parameter to payload
    }

    # Make POST request with the URL in payload
    response = requests.post(url, data=payload, stream=False)

    # Check response status code
    if response.status_code != 200:
        return {
            'success': False,
            'message': f'API error: {response.status_code} - {response.text[:100]}',
            'time': int(datetime.now().timestamp())
        }

    # Get complete audio content at once
    tts_audio = response.content

    try:
        # Convert the audio data to the correct format
        tts_speech = torch.from_numpy(np.array(np.frombuffer(tts_audio, dtype=np.int16))).unsqueeze(dim=0)

        # Save directly to BytesIO with explicit format parameter
        audio_buffer = io.BytesIO()
        torchaudio.save(audio_buffer, tts_speech, 24000, format="wav")
        audio_buffer.seek(0)  # Reset file pointer to the beginning

        # Upload the audio buffer directly to S3
        file_url = upload_wav_to_s3(audio_buffer, folder="generated_audio_cosyvoice")

        if file_url:
            print(f"Successfully uploaded audio to S3, URL: {file_url}")
            return file_url  # Return just the URL string
        else:
            print("Failed to upload audio to S3")
            return {
                'success': False,
                'message': 'Failed to upload audio to S3',
                'time': int(datetime.now().timestamp())
            }

    except Exception as e:
        print(f"Error in text_to_speech: {str(e)}")
        return {
            'success': False,
            'message': str(e),
            'time': int(datetime.now().timestamp())
        }

def convert_voice(source_file, target_file, song_or_not):
    """
    Convert a source voice to match a target voice using file inputs

    Args:
        source_file: Source audio file (file object from request.files)
        target_file: Target voice file (file object from request.files)
        song_or_not: if the uploaded source audio is singing voice

    Returns:
        str: URL of the converted audio file if successful, or error dict
    """
    api_url = "https://d72d600eb449.ngrok.app/convert/"

    try:
        # Prepare the files and form data
        files = {
            'source_audio': (source_file.filename, source_file.stream, 'audio/wav'),
            'target_audio': (target_file.filename, target_file.stream, 'audio/wav'),
        }

        # Set up parameters
        form_data = {
            'diffusion_steps': '50',
            'length_adjust': '1.0',
            'inference_cfg_rate': '0.7',
            'f0_condition': str(song_or_not).lower(),  # Convert to lowercase 'true'/'false'
            'auto_f0_adjust': 'true',
            'pitch_shift': '0',
        }

        # Make the POST request
        print(f"Sending request to {api_url} with parameters: {form_data}")
        response = requests.post(api_url, files=files, data=form_data)

        # Check if request was successful
        if response.status_code == 200:
            print("Voice conversion successful!")

            # Create a buffer to hold the audio content
            audio_buffer = io.BytesIO(response.content)

            # Upload the converted audio to S3
            file_url = upload_wav_to_s3(audio_buffer, folder="converted_audio")

            if file_url:
                print(f"Successfully uploaded converted audio to S3, URL: {file_url}")
                return file_url  # Return just the URL string
            else:
                print("Failed to upload converted audio to S3")
                return {
                    'success': False,
                    'message': 'Failed to upload converted audio to S3',
                    'time': int(datetime.now().timestamp())
                }
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
            return {
                'success': False,
                'message': f"API Error: {response.status_code} - {response.text}",
                'time': int(datetime.now().timestamp())
            }

    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        return {
            'success': False,
            'message': f'Voice conversion failed: {str(e)}',
            'time': int(datetime.now().timestamp())
        }

def azure_tts_and_convert_voice(user_text, reference_audio_file, song_or_not=False, emotion="default", rate="1.0"):
    """
    Generate speech using Azure TTS and then convert it to match a reference voice.

    Args:
        user_text: Text to be converted to speech
        reference_audio_file: Reference audio file (file object from request.files)
        song_or_not: Whether the conversion should use singing voice mode (default: False) [NOT USED]
        emotion: Emotion style to apply (default, affectionate, cheerful, empathetic, excited, sorry)
        rate: Speaking rate multiplier (0.5 to 2.0, default: 1.0)

    Returns:
        str: URL of the final converted audio file if successful, or error dict
    """
    try:
        # Azure TTS configuration
        speech_key = Config.AZURE_SPEECH_KEY
        service_region = Config.AZURE_SPEECH_REGION

        # Create a speech config with specified subscription key and service region
        speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
        speech_config.speech_synthesis_voice_name = "zh-CN-XiaoxiaoMultilingualNeural"

        # Valid emotions
        valid_emotions = ["affectionate", "cheerful", "empathetic", "excited", "sorry", "default"]

        # Validate and default emotion if invalid
        if emotion not in valid_emotions:
            print(f"Warning: Invalid emotion '{emotion}'. Using default instead.")
            emotion = "default"

        # Validate rate
        if rate is None:
            print("Warning: No rate provided. Using default 1.0 instead.")
            rate = "1.0"
        else:
            # Convert to float for validation
            try:
                rate_value = float(rate)
                if rate_value < 0.5 or rate_value > 2.0:
                    print(f"Warning: Rate value {rate_value} out of range (0.5-2.0). Using default 1.0 instead.")
                    rate = "1.0"
                else:
                    rate = str(rate_value) # Ensure it's a string for SSML
            except ValueError:
                print(f"Warning: Invalid rate format '{rate}'. Using default 1.0 instead.")
                rate = "1.0"

        # Create SSML string with user text, emotion and rate
        if emotion == "default":
            ssml_text = f"""
            <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
                <voice name="zh-CN-XiaoxiaoMultilingualNeural">
                  <prosody rate="{rate}">
                    {user_text}
                  </prosody>
                </voice>
            </speak>
            """
        else:
            ssml_text = f"""
            <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="zh-CN">
                <voice name="zh-CN-XiaoxiaoMultilingualNeural">
                    <mstts:express-as style="{emotion}" styledegree="2">
                        <prosody rate="{rate}">
                            {user_text}
                        </prosody>
                    </mstts:express-as>
                </voice>
            </speak>
            """

        # Create a temporary file to save the Azure TTS output
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            azure_tts_output_path = temp_file.name

        # Configure the audio output to the temporary file
        audio_config = speechsdk.audio.AudioOutputConfig(filename=azure_tts_output_path)

        # Create the speech synthesizer
        speech_synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_config
        )

        print(f"Starting Azure TTS synthesis for text: {user_text[:100]}...")

        # Synthesize the SSML text to the file
        result = speech_synthesizer.speak_ssml_async(ssml_text).get()

        # Check Azure TTS result
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f"Azure TTS synthesis completed successfully, saved to {azure_tts_output_path}")

            # Open the generated audio file for voice conversion
            azure_tts_file = open(azure_tts_output_path, 'rb')

            try:
                # Create a file-like object from the file
                source_file = type('obj', (object,), {
                    'filename': 'azure_tts_output.wav',
                    'stream': azure_tts_file
                })

                # Now convert the voice using the existing function
                conversion_result = convert_voice(
                    source_file=source_file,
                    target_file=reference_audio_file,
                    song_or_not=song_or_not
                )

                print(f"Voice conversion completed with result: {conversion_result}")
                return conversion_result

            except Exception as conversion_error:
                print(f"Error during voice conversion: {str(conversion_error)}")
                return {
                    'success': False,
                    'message': f'Voice conversion failed: {str(conversion_error)}',
                    'time': int(datetime.now().timestamp())
                }
            finally:
                # Close and delete the temporary file
                azure_tts_file.close()
                try:
                    os.unlink(azure_tts_output_path)
                except Exception as e:
                    print(f"Warning: Could not delete temporary file {azure_tts_output_path}: {str(e)}")

        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print(f"Azure TTS synthesis canceled: {cancellation_details.reason}")

            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                error_details = cancellation_details.error_details
                print(f"Azure TTS error details: {error_details}")

            return {
                'success': False,
                'message': f'Azure TTS synthesis failed: {cancellation_details.reason}',
                'time': int(datetime.now().timestamp())
            }

        # If we reach here, something unexpected happened
        return {
            'success': False,
            'message': 'Azure TTS synthesis failed with unknown reason',
            'time': int(datetime.now().timestamp())
        }

    except ImportError as e:
        print(f"Azure SDK Import Error: {str(e)}")
        return {
            'success': False,
            'message': f'Azure SDK Import Error: {str(e)}',
            'time': int(datetime.now().timestamp())
        }
    except Exception as e:
        print(f"Exception in azure_tts_and_convert_voice: {str(e)}")
        return {
            'success': False,
            'message': f'Azure TTS and voice conversion failed: {str(e)}',
            'time': int(datetime.now().timestamp())
        }

def generate_music(lyrics_text, reference_prompt):
    """
    Generate music from lyrics text and a reference prompt, and upload to S3
    
    Args:
        lyrics_text (str): Direct lyrics text in LRC format
        reference_prompt (str): Text prompt to guide the musical style
        
    Returns:
        str or dict: S3 file URL on success, or error dictionary on failure
    """
    api_url = "https://e27615fd7ad8.ngrok.app/generate_music/"
    
    # Default parameters
    params = {
        "audio_length": 95,  # 95 seconds (supported values: 95, 285)
        "steps": 32,         # Diffusion steps
        "cfg_strength": 4.0, # Classifier-free guidance strength
        "chunked": True,    # Whether to use chunked decoding
        "lyrics_text": lyrics_text,
        "reference_prompt": reference_prompt
    }
    
    try:
        print(f"Sending request to {api_url}")
        print(f"Using lyrics text of {len(lyrics_text)} characters")
        print(f"Using reference prompt: {reference_prompt}")
        print(f"With parameters: {params}")
        
        # Send the request (this might take a while)
        print("Starting music generation process (this may take several minutes)...")
        response = requests.post(api_url, data=params)
        
        # Check the response
        if response.status_code == 200:
            print("Music generation successful!")
            
            # Create a buffer to hold the audio content
            audio_buffer = io.BytesIO(response.content)
            
            # Upload the generated audio to S3
            file_url = upload_wav_to_s3(audio_buffer, folder="generated_music")
            
            if file_url:
                print(f"Successfully uploaded generated music to S3, URL: {file_url}")
                return file_url  # Return just the URL string
            else:
                print("Failed to upload generated music to S3")
                return {
                    'success': False,
                    'message': 'Failed to upload generated music to S3',
                    'time': int(datetime.now().timestamp())
                }
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
            return {
                'success': False,
                'message': f"API Error: {response.status_code} - {response.text}",
                'time': int(datetime.now().timestamp())
            }
            
    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        return {
            'success': False,
            'message': f'Music generation failed: {str(e)}',
            'time': int(datetime.now().timestamp())
        }

def generate_tts_audio_f5(prompt_wav_file, prompt_text, tts_text, speed=1.0):
    """
    Generates speech from text using F5-TTS API and uploads the result to S3
    """
    from flask import current_app
    
    # Validate speed parameter
    try:
        speed_value = float(speed)
        if speed_value < 0.5 or speed_value > 2.0:
            print(f"Warning: Speed value {speed_value} out of range (0.5-2.0). Using default 1.0 instead.")
            speed_value = 1.0
    except (ValueError, TypeError):
        print(f"Warning: Invalid speed format '{speed}'. Using default 1.0 instead.")
        speed_value = 1.0
        
    reference_url = upload_wav_to_s3(prompt_wav_file, folder="reference_audio")
    if not reference_url:
        return {
            'success': False,
            'message': 'Failed to upload reference audio to S3',
            'time': int(datetime.now().timestamp())
        }
    
    url = "https://c61c4490bc1c.ngrok.app/generate_speech"
    payload = {
        'tts_text': tts_text,
        'ref_file': reference_url,
        'ref_text': prompt_text,
        'speed': str(speed_value)
    }

    response = requests.post(url, json=payload, stream=False)
    
    if response.status_code != 200:
        return {
            'success': False,
            'message': f'API error: {response.status_code} - {response.text[:100]}',
            'time': int(datetime.now().timestamp())
        }

    try:
        audio_buffer = io.BytesIO(response.content)
        audio_buffer.seek(0)
        
        file_url = upload_wav_to_s3(audio_buffer, folder="generated_audio_f5")
            
        if file_url:
            print(f"Successfully uploaded audio to S3, URL: {file_url}")
            return file_url
        else:
            print("Failed to upload audio to S3")
            return {
                'success': False,
                'message': 'Failed to upload audio to S3',
                'time': int(datetime.now().timestamp())
            }
            
    except Exception as e:
        print(f"Error in text_to_speech: {str(e)}")
        return {
            'success': False,
            'message': str(e),
            'time': int(datetime.now().timestamp())
        }

def tts_inference_instruct2_s3(
    tts_text: str,
    instruct_text: str,
    prompt_wav_path: str,
    speed: float = 1.0,
    folder: str = "tts_instruct_audio",
):
    """
    Client function to call the inference_instruct2 endpoint and upload result to S3.
    """
    from flask import current_app
    import traceback
    import torch
    import torchaudio
    import numpy as np
    
    try:
        endpoint = "https://bfd4e958cca0.ngrok.app/inference_instruct2"
        
        current_app.logger.info(f"Using TTS instruct endpoint: {endpoint}")
        
        payload = {
            "tts_text": tts_text,
            "instruct_text": instruct_text,
            "speed": str(speed)
        }
        
        current_app.logger.info(f"TTS instruct parameters: tts_text length={len(tts_text)}, speed={speed}")
        
        if isinstance(prompt_wav_path, str):
            files = {
                "prompt_wav": (os.path.basename(prompt_wav_path), open(prompt_wav_path, "rb"), "audio/wav")
            }
        else:
            if hasattr(prompt_wav_path, 'seek'):
                prompt_wav_path.seek(0)
            files = {
                "prompt_wav": ("prompt.wav", prompt_wav_path, "audio/wav")
            }
        
        try:
            current_app.logger.info("Sending request to TTS server...")
            try:
                response = requests.request(
                    "POST",
                    endpoint,
                    data=payload,
                    files=files,
                    stream=False,
                    timeout=120
                )
                response.raise_for_status()
            except requests.exceptions.Timeout:
                current_app.logger.error("TTS server request timed out after 120 seconds")
                return None
            except requests.exceptions.ConnectionError:
                current_app.logger.error(f"Connection error to TTS server endpoint: {endpoint}")
                return None
            except requests.exceptions.HTTPError as http_err:
                current_app.logger.error(f"HTTP error from TTS server: {http_err}")
                return None
                
            current_app.logger.info(f"TTS server response status: {response.status_code}")
            
            tts_audio = response.content
            current_app.logger.info(f"Received audio content, size: {len(tts_audio)} bytes")
            
            if len(tts_audio) < 100:
                current_app.logger.error(f"Received suspiciously small audio response: {len(tts_audio)} bytes")
                current_app.logger.error(f"Response content: {tts_audio}")
                return None
            
            current_app.logger.info("Processing audio with PyTorch...")
            try:
                if tts_audio[:4] != b'RIFF' or b'WAVE' not in tts_audio[:12]:
                    current_app.logger.warning("Response does not appear to be a valid WAV file, attempting to process anyway")
                
                tts_speech = torch.from_numpy(np.array(np.frombuffer(tts_audio, dtype=np.int16))).unsqueeze(dim=0)
                
                if tts_speech.numel() == 0 or tts_speech.shape[1] < 100:
                    current_app.logger.error(f"Invalid audio data shape: {tts_speech.shape}")
                    return None
                
                temp_file = io.BytesIO()
                torchaudio.save(temp_file, tts_speech, 24000, format="wav")
                temp_file.seek(0)
                
                current_app.logger.info(f"Uploading audio to S3 folder: {folder}")
                file_url = upload_wav_to_s3(temp_file, folder=folder)
                
                if not file_url:
                    current_app.logger.error("Failed to upload to S3")
                else:
                    current_app.logger.info(f"Audio saved to S3: {file_url}")
                
                return file_url
            except Exception as e:
                current_app.logger.error(f"Error processing audio data: {str(e)}")
                traceback.print_exc()
                return None
            
        except requests.exceptions.RequestException as e:
            print(f"API request error: {str(e)}")
            return None
            
    except Exception as e:
        print(f"TTS inference error: {str(e)}")
        traceback.print_exc()
        return None
    
    finally:
        if isinstance(prompt_wav_path, str) and 'files' in locals():
            files["prompt_wav"][1].close() 