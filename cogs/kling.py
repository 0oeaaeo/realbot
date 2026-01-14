import discord
from discord.ext import commands
import aiohttp
import asyncio
import json
import os
import re
import logging
import tempfile
import subprocess
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

logger = logging.getLogger(__name__)

# Owner ID - same as used elsewhere in the bot
OWNER_ID = "1362274618953699370"

# API configuration
KIE_API_KEY = os.getenv("SUNO_API_KEY") or os.getenv("KIE_API_KEY")
KIE_API_BASE = "https://api.kie.ai/api/v1"

# YouTube URL patterns
YOUTUBE_PATTERNS = [
    r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
    r'(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]{11})',
    r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
]


class KlingCog(commands.Cog):
    """Cog for Kling 2.6 Motion Control - image-to-video with motion transfer."""
    
    def __init__(self, bot):
        self.bot = bot

    def _is_owner(self, user_id: int) -> bool:
        """Check if user is the owner."""
        return str(user_id) == OWNER_ID

    def _is_youtube_url(self, url: str) -> bool:
        """Check if URL is a YouTube video URL."""
        for pattern in YOUTUBE_PATTERNS:
            if re.match(pattern, url):
                return True
        return False

    async def _download_youtube_video(self, url: str, status_message: discord.Message) -> tuple[str | None, str | None]:
        """
        Download a YouTube video using yt-dlp and upload to file host.
        Returns (hosted_url, error_message)
        """
        await status_message.edit(content="> 📥 Downloading YouTube video...")
        
        # Create temp file for video
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        
        try:
            # Download with yt-dlp and force H.264 re-encoding
            # Kling API requires actual H.264 codec, not VP9/WebM in MP4 container
            cmd = [
                "yt-dlp",
                "--legacy-server-connect",
                "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "--merge-output-format", "mp4",
                # Limit to first 25 seconds (Kling requires 3-30s)
                "--download-sections", "*0:00-0:25",
                # Force re-encode to H.264 video + AAC audio for Kling compatibility
                "--postprocessor-args", "ffmpeg:-c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k",
                "-o", tmp_path,
                "--no-playlist",
                "--max-filesize", "100M",  # API limit
                url
            ]
            
            loop = asyncio.get_event_loop()
            process = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            )
            
            if process.returncode != 0:
                logger.error(f"yt-dlp failed: {process.stderr}")
                return None, f"Failed to download YouTube video: {process.stderr[:200]}"
            
            # Check file exists and has content
            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                return None, "Downloaded video file is empty"
            
            file_size = os.path.getsize(tmp_path) / (1024 * 1024)
            logger.info(f"Downloaded YouTube video: {file_size:.1f}MB")
            
            await status_message.edit(content=f"> 📤 Uploading video to file host ({file_size:.1f}MB)...")
            
            # Upload to 0x0.st (anonymous file hosting, files expire after some time)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
                with open(tmp_path, "rb") as f:
                    data = aiohttp.FormData()
                    data.add_field("file", f, filename="video.mp4", content_type="video/mp4")
                    
                    async with session.post("https://0x0.st", data=data) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            return None, f"File upload failed: {error_text[:100]}"
                        
                        hosted_url = (await response.text()).strip()
                        logger.info(f"Uploaded video to: {hosted_url}")
                        return hosted_url, None
                        
        except subprocess.TimeoutExpired:
            return None, "YouTube download timed out (>2 minutes)"
        except Exception as e:
            logger.error(f"YouTube download error: {e}")
            return None, str(e)
        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    async def _create_kling_task(
        self,
        image_url: str,
        video_url: str,
        prompt: str = "",
        mode: str = "720p",
        character_orientation: str = "video"
    ) -> tuple[str | None, str | None]:
        """
        Create a Kling motion control task.
        Returns (task_id, error_message)
        """
        if not KIE_API_KEY:
            return None, "KIE_API_KEY/SUNO_API_KEY not configured"
        
        headers = {
            "Authorization": f"Bearer {KIE_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "kling-2.6/motion-control",
            "input": {
                "input_urls": [image_url],
                "video_urls": [video_url],
                "character_orientation": character_orientation,
                "mode": mode
            }
        }
        
        # Only add prompt if provided
        if prompt:
            payload["input"]["prompt"] = prompt[:2500]  # Max 2500 chars

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            try:
                async with session.post(
                    f"{KIE_API_BASE}/jobs/createTask",
                    json=payload,
                    headers=headers
                ) as response:
                    result = await response.json()
                    
                    if result.get("code") != 200:
                        error_msg = result.get("message") or result.get("msg") or "Unknown error"
                        logger.error(f"Kling task creation failed: {error_msg}")
                        return None, error_msg
                    
                    task_id = result["data"]["taskId"]
                    logger.info(f"Kling task created: {task_id}")
                    return task_id, None
                    
            except Exception as e:
                logger.error(f"Kling task creation error: {e}")
                return None, str(e)

    async def _poll_kling_task(self, task_id: str, status_message: discord.Message) -> tuple[str | None, str | None]:
        """
        Poll for Kling task completion.
        Returns (result_url, error_message)
        """
        headers = {
            "Authorization": f"Bearer {KIE_API_KEY}",
            "Content-Type": "application/json"
        }
        
        status_url = f"{KIE_API_BASE}/jobs/recordInfo?taskId={task_id}"
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            # Poll for up to 10 minutes (video generation can take a while)
            for attempt in range(120):
                await asyncio.sleep(5)
                
                try:
                    async with session.get(status_url, headers=headers) as response:
                        status_data = await response.json()
                        
                        if status_data.get("code") != 200:
                            error_msg = status_data.get("message") or status_data.get("msg")
                            logger.error(f"Kling status check failed: {error_msg}")
                            return None, error_msg
                        
                        state = status_data["data"].get("state")
                        
                        # Update status message periodically
                        if attempt % 6 == 0:  # Every 30 seconds
                            elapsed = (attempt + 1) * 5
                            await status_message.edit(
                                content=f"> 🎬 Processing video... ({elapsed}s elapsed)\n> Status: `{state}`"
                            )
                        
                        if state == "success":
                            # Parse result JSON
                            result_json_str = status_data["data"].get("resultJson", "{}")
                            try:
                                result_json = json.loads(result_json_str)
                                result_urls = result_json.get("resultUrls", [])
                                
                                if result_urls:
                                    logger.info(f"Kling task complete: {result_urls[0]}")
                                    return result_urls[0], None
                                else:
                                    return None, "Task succeeded but no result URL returned"
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse Kling result: {e}")
                                return None, f"Failed to parse result: {e}"
                        
                        elif state == "fail":
                            fail_msg = status_data["data"].get("failMsg") or "Unknown error"
                            fail_code = status_data["data"].get("failCode", "")
                            logger.error(f"Kling task failed: {fail_code} - {fail_msg}")
                            return None, fail_msg
                        
                        # Still processing, continue polling
                        logger.debug(f"Kling status: {state} (attempt {attempt + 1})")
                        
                except Exception as e:
                    logger.error(f"Kling polling error: {e}")
                    # Continue polling despite errors
                    continue
            
            return None, "Task timed out after 10 minutes"

    @commands.command(name="kling")
    async def kling(self, ctx: commands.Context, image_url: str = "", video_url: str = "", *, prompt: str = ""):
        """
        Generate a motion-controlled video using Kling 2.6.
        
        Transfers motion from a reference video to a character image.
        
        Usage:
            !kling <image_url> <video_url> [optional prompt]
        
        Arguments:
            image_url: URL of the character image (must show head, shoulders, torso)
            video_url: URL of the motion reference video (3-30 seconds, min 720p)
                       Also supports YouTube URLs! (will be auto-downloaded)
            prompt: Optional text description (max 2500 chars)
        
        Examples:
            !kling https://example.com/character.png https://example.com/dance.mp4
            !kling https://example.com/character.png https://youtu.be/dQw4w9WgXcQ Dancing
            !kling https://example.com/character.png https://youtube.com/shorts/xyz The character is dancing
        """
        # Owner-only check
        if not self._is_owner(ctx.author.id):
            await ctx.send("❌ This command is owner-only.")
            return
        
        if not image_url or not video_url:
            await ctx.send(
                "❌ **Usage:** `!kling <image_url> <video_url> [prompt]`\n\n"
                "**Arguments:**\n"
                "• `image_url`: Character image URL (shows head, shoulders, torso)\n"
                "• `video_url`: Motion reference video URL (3-30s, 720p+ resolution)\n"
                "• `prompt`: Optional description (max 2500 chars)\n\n"
                "**Example:**\n"
                "`!kling https://example.com/char.png https://example.com/dance.mp4 Dancing happily`"
            )
            return
        
        # Validate URLs look legit
        if not (image_url.startswith("http://") or image_url.startswith("https://")):
            await ctx.send("❌ Invalid image URL. Must start with http:// or https://")
            return
        
        if not (video_url.startswith("http://") or video_url.startswith("https://")):
            await ctx.send("❌ Invalid video URL. Must start with http:// or https://")
            return
        
        # Send initial status
        status_message = await ctx.send(
            f"> 🎬 **Kling Motion Control**\n"
            f"> Image: `{image_url[:50]}...`\n"
            f"> Video: `{video_url[:50]}...`\n"
            f"> Prompt: `{prompt[:50] if prompt else '(none)'}...`\n\n"
            f"> ⏳ Preparing..."
        )
        
        # Handle YouTube URLs - download and re-host
        actual_video_url = video_url
        if self._is_youtube_url(video_url):
            hosted_url, error = await self._download_youtube_video(video_url, status_message)
            if error:
                await status_message.edit(content=f"❌ **YouTube download failed:** {error}")
                return
            actual_video_url = hosted_url
            await status_message.edit(
                content=f"> 🎬 **Kling Motion Control**\n"
                f"> Image: `{image_url[:50]}...`\n"
                f"> Video: YouTube → `{actual_video_url[:40]}...`\n"
                f"> Prompt: `{prompt[:50] if prompt else '(none)'}...`\n\n"
                f"> ⏳ Creating task..."
            )
        
        # Create the task
        task_id, error = await self._create_kling_task(
            image_url=image_url,
            video_url=actual_video_url,
            prompt=prompt,
            mode="720p",  # Default to 720p (cheaper)
            character_orientation="video"  # Match video orientation
        )
        
        if error:
            await status_message.edit(content=f"❌ **Task creation failed:** {error}")
            return
        
        await status_message.edit(
            content=f"> 🎬 **Kling Motion Control**\n"
            f"> Task ID: `{task_id}`\n\n"
            f"> ⏳ Processing video... (this may take several minutes)"
        )
        
        # Poll for results
        result_url, error = await self._poll_kling_task(task_id, status_message)
        
        if error:
            await status_message.edit(content=f"❌ **Generation failed:** {error}")
            return
        
        # Download and send the video
        await status_message.edit(content="> 📥 Downloading generated video...")
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                async with session.get(result_url) as response:
                    if response.status != 200:
                        await status_message.edit(content=f"❌ Failed to download video: HTTP {response.status}")
                        return
                    
                    video_bytes = await response.read()
                    
                    # Check file size (Discord limit is 25MB for most servers)
                    size_mb = len(video_bytes) / (1024 * 1024)
                    if size_mb > 25:
                        # Too large, just send the URL
                        await status_message.edit(
                            content=f"✅ **Video generated!** (too large to upload: {size_mb:.1f}MB)\n\n"
                            f"🔗 **Download:** {result_url}"
                        )
                        return
                    
                    # Send as file
                    import io
                    video_file = discord.File(io.BytesIO(video_bytes), filename="kling_motion.mp4")
                    
                    await status_message.delete()
                    await ctx.send(
                        content=f"✅ **Kling Motion Control** - Generated from motion reference\n"
                        f"> Prompt: {prompt[:200] if prompt else '(none)'}",
                        file=video_file
                    )
                    
        except Exception as e:
            logger.error(f"Failed to download Kling result: {e}")
            await status_message.edit(
                content=f"⚠️ **Video generated but download failed.**\n\n"
                f"🔗 **Download manually:** {result_url}"
            )


async def setup(bot):
    await bot.add_cog(KlingCog(bot))
