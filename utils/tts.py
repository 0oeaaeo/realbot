"""
Google Gemini Text-to-Speech Utility

Generates speech audio from text using the Gemini 2.5 Flash TTS model.
"""

import os
import io
import wave
import asyncio
from typing import Optional, AsyncIterator
from dotenv import load_dotenv

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("google-genai library not installed. TTS features will not work.")
    genai = None
    types = None

load_dotenv()

# Available voice options for Gemini TTS
AVAILABLE_VOICES = [
    "Aoede",    # Warm, engaging female voice - great for storytelling
    "Charon",   # Deep male voice
    "Fenrir",   # Strong male voice
    "Kore",     # Clear female voice
    "Puck",     # Playful voice
    "Zephyr",   # Soft, gentle voice
    "Orbit",    # Neutral voice
    "Sulafat",  # Expressive voice
]

DEFAULT_VOICE = "Aoede"  # Best for story reading

# TTS model name
TTS_MODEL = "gemini-2.5-flash-preview-tts"

# Audio settings
SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit audio


def get_tts_client():
    """Get or create the GenAI client."""
    if not genai:
        return None
    
    api_key = os.getenv("API_KEY")
    if not api_key:
        print("API_KEY not found in environment")
        return None
    
    try:
        return genai.Client(api_key=api_key)
    except Exception as e:
        print(f"Failed to create GenAI client: {e}")
        return None


async def generate_tts_audio(
    text: str,
    voice: str = DEFAULT_VOICE
) -> Optional[bytes]:
    """
    Generate TTS audio from text using Gemini.
    
    Args:
        text: The text to convert to speech
        voice: Voice name to use (default: Aoede)
        
    Returns:
        Raw PCM audio bytes at 24kHz, or None if generation fails
    """
    if not genai or not types:
        print("google-genai not available")
        return None
    
    client = get_tts_client()
    if not client:
        return None
    
    # Validate voice
    if voice not in AVAILABLE_VOICES:
        print(f"Unknown voice '{voice}', using default: {DEFAULT_VOICE}")
        voice = DEFAULT_VOICE
    
    try:
        loop = asyncio.get_running_loop()
        
        def _generate():
            return client.models.generate_content(
                model=TTS_MODEL,
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice,
                            )
                        ),
                    ),
                )
            )
        
        response = await loop.run_in_executor(None, _generate)
        
        # Extract audio data from response
        if response.candidates and response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            if part.inline_data and part.inline_data.data:
                data = part.inline_data.data
                # Data might be bytes or base64 string
                if isinstance(data, str):
                    import base64
                    return base64.b64decode(data)
                return data
        
        print("No audio data in response")
        return None
        
    except Exception as e:
        print(f"TTS generation error: {e}")
        return None


async def generate_tts_wav(
    text: str,
    voice: str = DEFAULT_VOICE
) -> Optional[io.BytesIO]:
    """
    Generate TTS audio and return as WAV file.
    
    Args:
        text: The text to convert to speech
        voice: Voice name to use
        
    Returns:
        BytesIO containing WAV file data, or None if generation fails
    """
    pcm_data = await generate_tts_audio(text, voice)
    if not pcm_data:
        return None
    
    # Wrap PCM in WAV container
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)
    
    wav_buffer.seek(0)
    return wav_buffer


def chunk_text_for_tts(text: str, max_chars: int = 4000) -> list[str]:
    """
    Split text into chunks suitable for TTS generation.
    
    The Gemini TTS model has token limits, so we need to split long texts.
    This function tries to split at natural boundaries (paragraphs, sentences).
    
    Args:
        text: The full text to split
        max_chars: Maximum characters per chunk (conservative estimate for tokens)
        
    Returns:
        List of text chunks
    """
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    current_chunk = ""
    
    # Split by paragraphs first
    paragraphs = text.split('\n\n')
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # If paragraph itself is too long, split by sentences
        if len(para) > max_chars:
            sentences = _split_into_sentences(para)
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 2 <= max_chars:
                    current_chunk += sentence + " "
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence + " "
        else:
            # Try to add paragraph to current chunk
            if len(current_chunk) + len(para) + 2 <= max_chars:
                current_chunk += para + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para + "\n\n"
    
    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    import re
    # Simple sentence splitting - handles common cases
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


async def stream_tts_chunks(
    text: str,
    voice: str = DEFAULT_VOICE
) -> AsyncIterator[bytes]:
    """
    Stream TTS audio for long text by generating chunks.
    
    Args:
        text: Full text to convert
        voice: Voice name to use
        
    Yields:
        PCM audio bytes for each chunk
    """
    chunks = chunk_text_for_tts(text)
    
    for i, chunk in enumerate(chunks):
        print(f"Generating TTS chunk {i+1}/{len(chunks)}...")
        audio = await generate_tts_audio(chunk, voice)
        if audio:
            yield audio
        else:
            print(f"Failed to generate audio for chunk {i+1}")


# For testing
if __name__ == "__main__":
    async def test():
        print("Testing TTS generation...")
        print(f"Available voices: {', '.join(AVAILABLE_VOICES)}")
        
        test_text = "Hello! This is a test of the Gemini text to speech system. The voice should sound natural and expressive."
        
        wav_data = await generate_tts_wav(test_text, "Aoede")
        if wav_data:
            with open("test_output.wav", "wb") as f:
                f.write(wav_data.read())
            print("Success! Saved to test_output.wav")
        else:
            print("Failed to generate audio")
    
    asyncio.run(test())
