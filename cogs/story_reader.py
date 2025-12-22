"""
Story Reader Cog

Discord bot cog for reading Literotica stories aloud in voice channels
using Google Gemini text-to-speech.
"""

import asyncio
import io
import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional

import discord
from discord.ext import commands

from utils.literotica import fetch_story, LiteroticaStory
from utils.tts import (
    generate_tts_audio,
    chunk_text_for_tts,
    AVAILABLE_VOICES,
    DEFAULT_VOICE,
    SAMPLE_RATE,
)


@dataclass
class ReadingSession:
    """Represents an active story reading session."""
    guild_id: int
    voice_client: discord.VoiceClient
    story: LiteroticaStory
    voice: str = DEFAULT_VOICE
    current_chapter: int = 0
    current_chunk: int = 0
    chunks: list[str] = field(default_factory=list)
    is_paused: bool = False
    is_stopped: bool = False
    text_channel: Optional[discord.TextChannel] = None


class StoryReaderCog(commands.Cog):
    """Cog for reading stories in voice channels."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions: dict[int, ReadingSession] = {}  # guild_id -> session
    
    def _get_session(self, guild_id: int) -> Optional[ReadingSession]:
        """Get the reading session for a guild."""
        return self.sessions.get(guild_id)
    
    async def _cleanup_session(self, guild_id: int):
        """Clean up a reading session."""
        session = self.sessions.pop(guild_id, None)
        if session and session.voice_client:
            try:
                if session.voice_client.is_connected():
                    await session.voice_client.disconnect()
            except Exception as e:
                print(f"Error disconnecting voice client: {e}")
    
    async def _send_status(self, session: ReadingSession, message: str):
        """Send a status message to the text channel."""
        if session.text_channel:
            try:
                await session.text_channel.send(message)
            except Exception:
                pass
    
    async def _play_audio_chunk(self, session: ReadingSession, audio_data: bytes) -> bool:
        """
        Play audio data through the voice client.
        
        Returns True if playback completed, False if interrupted.
        """
        if not session.voice_client or not session.voice_client.is_connected():
            return False
        
        # Write PCM data to a temporary file for FFmpeg
        with tempfile.NamedTemporaryFile(suffix='.pcm', delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name
        
        try:
            # Create audio source from PCM data
            # FFmpeg needs to know input format for raw PCM
            audio_source = discord.FFmpegPCMAudio(
                tmp_path,
                before_options=f'-f s16le -ar {SAMPLE_RATE} -ac 1'
            )
            
            # Play audio
            playback_complete = asyncio.Event()
            
            def after_playback(error):
                if error:
                    print(f"Playback error: {error}")
                playback_complete.set()
            
            session.voice_client.play(audio_source, after=after_playback)
            
            # Wait for playback to complete or session to be stopped
            while not playback_complete.is_set():
                if session.is_stopped:
                    session.voice_client.stop()
                    return False
                
                # Handle pause
                while session.is_paused and not session.is_stopped:
                    if session.voice_client.is_playing():
                        session.voice_client.pause()
                    await asyncio.sleep(0.5)
                
                if not session.is_paused and session.voice_client.is_paused():
                    session.voice_client.resume()
                
                await asyncio.sleep(0.1)
            
            return not session.is_stopped
            
        finally:
            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    
    async def _read_story(self, session: ReadingSession):
        """Main reading loop for a story."""
        try:
            story = session.story
            
            # Announce start
            await self._send_status(
                session,
                f"📖 **Now Reading:** {story.title}\n"
                f"✍️ **Author:** {story.author}\n"
                f"🔊 **Voice:** {session.voice}\n"
                f"📄 **Pages:** {len(story.chapters)}"
            )
            
            # Process each chapter
            for chapter_idx, chapter in enumerate(story.chapters):
                if session.is_stopped:
                    break
                
                session.current_chapter = chapter_idx
                
                if len(story.chapters) > 1:
                    await self._send_status(
                        session,
                        f"📄 Reading page {chapter_idx + 1} of {len(story.chapters)}..."
                    )
                
                # Split chapter into TTS-friendly chunks
                chunks = chunk_text_for_tts(chapter.content)
                session.chunks = chunks
                
                for chunk_idx, chunk_text in enumerate(chunks):
                    if session.is_stopped:
                        break
                    
                    session.current_chunk = chunk_idx
                    
                    # Generate TTS audio
                    audio_data = await generate_tts_audio(chunk_text, session.voice)
                    if not audio_data:
                        print(f"Failed to generate audio for chunk {chunk_idx + 1}")
                        continue
                    
                    # Play the audio
                    success = await self._play_audio_chunk(session, audio_data)
                    if not success:
                        break
                    
                    # Small delay between chunks for natural pacing
                    await asyncio.sleep(0.3)
            
            # Story complete
            if not session.is_stopped:
                await self._send_status(session, "✅ **Story complete!** Leaving voice channel.")
            
        except Exception as e:
            print(f"Error in reading loop: {e}")
            await self._send_status(session, f"❌ Error reading story: {e}")
        
        finally:
            await self._cleanup_session(session.guild_id)
    
    @commands.command(name='story')
    async def story_command(self, ctx: commands.Context, url: str, voice: str = DEFAULT_VOICE):
        """
        Join your voice channel and read a Literotica story.
        
        Usage: !story <url> [voice]
        Example: !story https://www.literotica.com/s/example-story Aoede
        
        Available voices: Aoede, Charon, Fenrir, Kore, Puck, Zephyr, Orbit, Sulafat
        """
        # Check if user is in a voice channel
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ You must be in a voice channel to use this command!")
            return
        
        voice_channel = ctx.author.voice.channel
        
        # Check for existing session
        if ctx.guild.id in self.sessions:
            await ctx.send("⚠️ Already reading a story! Use `!stop` to end the current session.")
            return
        
        # Validate voice
        if voice not in AVAILABLE_VOICES:
            await ctx.send(
                f"⚠️ Unknown voice '{voice}'. Using default: {DEFAULT_VOICE}\n"
                f"Available voices: {', '.join(AVAILABLE_VOICES)}"
            )
            voice = DEFAULT_VOICE
        
        # Fetch the story
        status_msg = await ctx.send(f"📚 Fetching story from Literotica...")
        
        try:
            story = await fetch_story(url)
        except Exception as e:
            await status_msg.edit(content=f"❌ Failed to fetch story: {e}")
            return
        
        if not story:
            await status_msg.edit(content="❌ Could not fetch story. Check the URL and try again.")
            return
        
        if not story.full_text.strip():
            await status_msg.edit(content="❌ Story appears to be empty or could not be parsed.")
            return
        
        await status_msg.edit(
            content=f"✅ Found: **{story.title}** by *{story.author}*\n"
                    f"📄 {len(story.chapters)} page(s), ~{len(story.full_text)} characters\n"
                    f"🔊 Joining voice channel..."
        )
        
        # Join voice channel
        try:
            voice_client = await voice_channel.connect()
        except Exception as e:
            await ctx.send(f"❌ Failed to join voice channel: {e}")
            return
        
        # Create session
        session = ReadingSession(
            guild_id=ctx.guild.id,
            voice_client=voice_client,
            story=story,
            voice=voice,
            text_channel=ctx.channel
        )
        self.sessions[ctx.guild.id] = session
        
        # Start reading in background
        self.bot.loop.create_task(self._read_story(session))
    
    @commands.command(name='stop')
    async def stop_command(self, ctx: commands.Context):
        """Stop reading and leave the voice channel."""
        session = self._get_session(ctx.guild.id)
        if not session:
            await ctx.send("❌ No story is currently being read.")
            return
        
        session.is_stopped = True
        await ctx.send("⏹️ Stopping story reading...")
    
    @commands.command(name='pause')
    async def pause_command(self, ctx: commands.Context):
        """Pause the current story reading."""
        session = self._get_session(ctx.guild.id)
        if not session:
            await ctx.send("❌ No story is currently being read.")
            return
        
        if session.is_paused:
            await ctx.send("⏸️ Already paused. Use `!resume` to continue.")
            return
        
        session.is_paused = True
        await ctx.send("⏸️ Paused. Use `!resume` to continue.")
    
    @commands.command(name='resume')
    async def resume_command(self, ctx: commands.Context):
        """Resume the paused story reading."""
        session = self._get_session(ctx.guild.id)
        if not session:
            await ctx.send("❌ No story is currently being read.")
            return
        
        if not session.is_paused:
            await ctx.send("▶️ Not paused!")
            return
        
        session.is_paused = False
        await ctx.send("▶️ Resuming...")
    
    @commands.command(name='skip')
    async def skip_command(self, ctx: commands.Context):
        """Skip to the next chapter/page."""
        session = self._get_session(ctx.guild.id)
        if not session:
            await ctx.send("❌ No story is currently being read.")
            return
        
        if session.current_chapter >= len(session.story.chapters) - 1:
            await ctx.send("⏭️ Already on the last page!")
            return
        
        # Stop current playback, the loop will move to next chapter
        if session.voice_client and session.voice_client.is_playing():
            session.voice_client.stop()
        
        # Skip remaining chunks in current chapter
        session.current_chunk = len(session.chunks)
        await ctx.send(f"⏭️ Skipping to page {session.current_chapter + 2}...")
    
    @commands.command(name='voice')
    async def voice_command(self, ctx: commands.Context, voice_name: str = None):
        """
        Change the TTS voice or list available voices.
        
        Usage: !voice [voice_name]
        """
        if not voice_name:
            voices_list = ", ".join(AVAILABLE_VOICES)
            await ctx.send(f"🔊 **Available voices:** {voices_list}\n\nDefault: {DEFAULT_VOICE}")
            return
        
        if voice_name not in AVAILABLE_VOICES:
            await ctx.send(
                f"❌ Unknown voice '{voice_name}'.\n"
                f"Available: {', '.join(AVAILABLE_VOICES)}"
            )
            return
        
        session = self._get_session(ctx.guild.id)
        if session:
            session.voice = voice_name
            await ctx.send(f"🔊 Voice changed to **{voice_name}** (takes effect on next chunk)")
        else:
            await ctx.send(f"🔊 Voice **{voice_name}** will be used for the next story.")
    
    @commands.command(name='nowplaying', aliases=['np'])
    async def nowplaying_command(self, ctx: commands.Context):
        """Show what story is currently being read."""
        session = self._get_session(ctx.guild.id)
        if not session:
            await ctx.send("❌ No story is currently being read.")
            return
        
        story = session.story
        status = "⏸️ Paused" if session.is_paused else "▶️ Playing"
        
        await ctx.send(
            f"📖 **{story.title}** by *{story.author}*\n"
            f"📄 Page {session.current_chapter + 1}/{len(story.chapters)}\n"
            f"🔊 Voice: {session.voice}\n"
            f"Status: {status}"
        )
    
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        """Handle voice state updates (e.g., bot being disconnected)."""
        # Check if it's our bot and we got disconnected
        if member.id == self.bot.user.id:
            if before.channel and not after.channel:
                # Bot was disconnected
                session = self._get_session(member.guild.id)
                if session:
                    session.is_stopped = True
                    await self._cleanup_session(member.guild.id)


async def setup(bot: commands.Bot):
    """Load the cog."""
    await bot.add_cog(StoryReaderCog(bot))
