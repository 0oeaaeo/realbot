"""
OpenCode Discord Client - Simple, Conversational Interface

A smooth, user-friendly Discord interface for OpenCode AI.
Just type `!code` to start, then chat naturally in the thread.

API Target: http://oea.wtf:4096
"""

import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
import aiohttp
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, AsyncGenerator
from datetime import datetime

logger = logging.getLogger('realbot.opencode')

# =============================================================================
# Configuration
# =============================================================================

OPENCODE_API_BASE = "http://oea.wtf:4096"
STREAM_UPDATE_INTERVAL = 0.3  # Fast updates for smooth feel
MAX_EMBED_LENGTH = 4000

# =============================================================================
# Simple API Client
# =============================================================================

class OpenCodeAPI:
    """Minimal async client for OpenCode API"""
    
    def __init__(self, base_url: str = OPENCODE_API_BASE):
        self.base_url = base_url.rstrip('/')
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=300)
            )
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"
        async with session.request(method, url, **kwargs) as resp:
            if resp.status >= 400:
                raise Exception(f"API error {resp.status}")
            if resp.status == 204:
                return True
            content_type = resp.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                return await resp.json()
            return await resp.text()
    
    async def health(self) -> dict:
        return await self._request('GET', '/global/health')
    
    async def create_session(self, title: str = None) -> dict:
        body = {'title': title} if title else {}
        return await self._request('POST', '/session', json=body)
    
    async def delete_session(self, session_id: str) -> bool:
        return await self._request('DELETE', f'/session/{session_id}')
    
    async def abort_session(self, session_id: str) -> bool:
        return await self._request('POST', f'/session/{session_id}/abort')
    
    async def share_session(self, session_id: str) -> dict:
        return await self._request('POST', f'/session/{session_id}/share')
    
    async def send_prompt(self, session_id: str, text: str) -> dict:
        body = {'parts': [{'type': 'text', 'text': text}]}
        return await self._request('POST', f'/session/{session_id}/message', json=body)
    
    async def send_prompt_async(self, session_id: str, text: str) -> bool:
        body = {'parts': [{'type': 'text', 'text': text}]}
        return await self._request('POST', f'/session/{session_id}/prompt_async', json=body)
    
    async def get_config(self) -> dict:
        return await self._request('GET', '/config')
    
    async def reply_permission(self, request_id: str, reply: str) -> bool:
        return await self._request('POST', f'/permission/{request_id}/reply', json={'reply': reply})
    
    async def subscribe_events(self) -> AsyncGenerator[dict, None]:
        """Subscribe to SSE events for streaming"""
        session = await self._get_session()
        url = f"{self.base_url}/event"
        async with session.get(url) as resp:
            async for line in resp.content:
                line = line.decode('utf-8').strip()
                if line.startswith('data:'):
                    try:
                        yield json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue

# =============================================================================
# Session State
# =============================================================================

@dataclass
class ActiveSession:
    """Tracks an active OpenCode session"""
    session_id: str
    thread_id: int
    channel_id: int
    user_id: int
    response_msg_id: Optional[int] = None
    is_streaming: bool = False
    stream_buffer: str = ""
    last_update: float = 0
    created_at: datetime = field(default_factory=datetime.now)

# =============================================================================
# UI Components
# =============================================================================

class SessionControlsView(View):
    """Simple control buttons that appear with responses"""
    
    def __init__(self, cog: 'OpenCodeCog', session: ActiveSession):
        super().__init__(timeout=None)
        self.cog = cog
        self.session = session
    
    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="oc_stop")
    async def stop_btn(self, interaction: discord.Interaction, button: Button):
        if not await self.cog.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        try:
            await self.cog.api.abort_session(self.session.session_id)
            self.session.is_streaming = False
            await interaction.response.send_message("⏹️ Stopped", ephemeral=True)
        except:
            await interaction.response.send_message("Already stopped", ephemeral=True)
    
    @discord.ui.button(label="🔗 Share", style=discord.ButtonStyle.secondary, custom_id="oc_share")
    async def share_btn(self, interaction: discord.Interaction, button: Button):
        if not await self.cog.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        try:
            result = await self.cog.api.share_session(self.session.session_id)
            url = result.get('share', {}).get('url', 'No URL')
            await interaction.response.send_message(f"🔗 {url}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Failed to share: {e}", ephemeral=True)
    
    @discord.ui.button(label="🗑️ End Session", style=discord.ButtonStyle.secondary, custom_id="oc_end")
    async def end_btn(self, interaction: discord.Interaction, button: Button):
        if not await self.cog.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        try:
            await self.cog.api.delete_session(self.session.session_id)
            if self.session.thread_id in self.cog.sessions:
                del self.cog.sessions[self.session.thread_id]
            await interaction.response.send_message("Session ended. Thread will remain for reference.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)


class PermissionView(View):
    """Quick permission approval buttons"""
    
    def __init__(self, cog: 'OpenCodeCog', request_id: str, permission: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.request_id = request_id
        self.permission = permission
    
    @discord.ui.button(label="✅ Allow", style=discord.ButtonStyle.success)
    async def allow(self, interaction: discord.Interaction, button: Button):
        if not await self.cog.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        await self.cog.api.reply_permission(self.request_id, "once")
        await interaction.response.edit_message(content=f"✅ Allowed: {self.permission}", view=None)
    
    @discord.ui.button(label="✅ Always", style=discord.ButtonStyle.primary)
    async def always(self, interaction: discord.Interaction, button: Button):
        if not await self.cog.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        await self.cog.api.reply_permission(self.request_id, "always")
        await interaction.response.edit_message(content=f"✅ Always allowed: {self.permission}", view=None)
    
    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: Button):
        if not await self.cog.bot.is_owner(interaction.user):
            return await interaction.response.send_message("❌ Owner only.", ephemeral=True)
        await self.cog.api.reply_permission(self.request_id, "reject")
        await interaction.response.edit_message(content=f"❌ Denied: {self.permission}", view=None)

# =============================================================================
# Main Cog
# =============================================================================

class OpenCodeCog(commands.Cog, name="OpenCode"):
    """
    Simple, conversational OpenCode interface.
    
    Just use `!code` to start a coding session, then chat naturally!
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = OpenCodeAPI()
        self.sessions: Dict[int, ActiveSession] = {}  # thread_id -> session
        self.event_task: Optional[asyncio.Task] = None
        logger.info("OpenCode cog initialized")
    
    async def cog_load(self):
        self.event_task = asyncio.create_task(self._event_listener())
        logger.info("OpenCode cog loaded")
    
    async def cog_unload(self):
        if self.event_task:
            self.event_task.cancel()
        await self.api.close()
    
    # -------------------------------------------------------------------------
    # The One Command You Need
    # -------------------------------------------------------------------------
    
    @commands.command(name="code", aliases=["opencode", "oc"])
    @commands.is_owner()
    async def start_session(self, ctx: commands.Context, *, initial_prompt: str = None):
        """
        Start an OpenCode coding session.
        
        Usage:
            !code                     - Start a new session
            !code help me with Python - Start with an initial question
        
        A thread will be created where you can chat naturally with OpenCode.
        Just type your messages - no commands needed!
        """
        # Check API health first
        try:
            await self.api.health()
        except:
            await ctx.send("❌ OpenCode API is not available. Try again later.")
            return
        
        # Create the session
        try:
            title = f"Code session for {ctx.author.display_name}"
            if initial_prompt:
                title = initial_prompt[:50] + "..." if len(initial_prompt) > 50 else initial_prompt
            
            session_data = await self.api.create_session(title=title)
            session_id = session_data['id']
        except Exception as e:
            await ctx.send(f"❌ Failed to create session: {e}")
            return
        
        # Create a thread for the session if supported
        thread_name = f"🤖 {title[:90]}"
        thread = None
        
        # Check if threads are supported in this channel
        can_thread = hasattr(ctx.channel, 'create_thread') and not isinstance(ctx.channel, discord.VoiceChannel)
        
        if can_thread:
            try:
                thread = await ctx.message.create_thread(name=thread_name, auto_archive_duration=60)
            except Exception as e:
                logger.debug(f"Message.create_thread failed: {e}")
                try:
                    thread = await ctx.channel.create_thread(
                        name=thread_name, 
                        type=discord.ChannelType.public_thread,
                        auto_archive_duration=60
                    )
                except Exception as e2:
                    logger.debug(f"Channel.create_thread failed: {e2}")
        
        # If no thread could be created, use the channel itself
        target = thread or ctx.channel
        
        # Store session
        session = ActiveSession(
            session_id=session_id,
            thread_id=target.id,
            channel_id=ctx.channel.id,
            user_id=ctx.author.id
        )
        self.sessions[target.id] = session
        logger.info(f"Session {session_id} started in {'thread' if target != ctx.channel else 'channel'} {target.id}")
        
        # Send welcome message
        welcome = discord.Embed(
            title="🤖 OpenCode Ready",
            description="Just type your coding questions and I'll help!\n\n"
                       "**Tips:**\n"
                       "• Be specific about what you need\n"
                       "• I can read and edit code files\n"
                       "• Ask me to explain, debug, or write code",
            color=discord.Color.green()
        )
        welcome.set_footer(text="Session active • Just type to chat")
        await target.send(embed=welcome)
        
        # If they provided an initial prompt, process it
        if initial_prompt:
            await self._process_message(target, ctx.author, initial_prompt, session)
        
        # Confirm in original channel
        if target != ctx.channel:
            await ctx.send(f"✅ Started! Continue in {target.mention}")
    
    # -------------------------------------------------------------------------
    # Natural Message Handling
    # -------------------------------------------------------------------------
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen to messages in session threads and respond naturally"""
        # Ignore bots
        if message.author.bot:
            return
        
        # Check if this is in an active session thread
        if message.channel.id not in self.sessions:
            return
        
        # OWNER ONLY SECURITY
        if not await self.bot.is_owner(message.author):
            return
        
        logger.info(f"Processing message in session thread {message.channel.id} from {message.author}")
        
        session = self.sessions[message.channel.id]
        
        # Check for exit keywords
        clean_content = message.content.strip().lower()
        if clean_content in ['exit', 'quit', 'stop', 'bye', 'end', 'end session']:
            try:
                await self.api.delete_session(session.session_id)
                del self.sessions[message.channel.id]
                await message.channel.send("👋 **Session ended.** I've stopped listening in this thread.")
                return
            except Exception as e:
                logger.error(f"Failed to end session via keyword: {e}")
        
        # Don't process commands
        if message.content.startswith('!'):
            return
        
        # Process the message as a prompt
        await self._process_message(message.channel, message.author, message.content, session)
    
    async def _process_message(self, channel, author: discord.Member, 
                               content: str, session: ActiveSession):
        """Process a user message and stream the response"""
        logger.info(f"Sending prompt to session {session.session_id}")
        
        # Create initial "thinking" message
        thinking_embed = discord.Embed(
            description="*Thinking...*",
            color=discord.Color.blue()
        )
        try:
            response_msg = await channel.send(embed=thinking_embed)
            logger.info(f"Created thinking message {response_msg.id}")
        except Exception as e:
            logger.error(f"Failed to send thinking message: {e}")
            return
        
        # Set up streaming state
        session.response_msg_id = response_msg.id
        session.is_streaming = True
        session.stream_buffer = ""
        session.last_update = asyncio.get_event_loop().time()
        
        try:
            # Send prompt (async mode for streaming)
            await self.api.send_prompt_async(session.session_id, content)
            
            # Wait for streaming to complete (SSE handler updates the message)
            timeout = 300  # 5 minutes
            start = asyncio.get_event_loop().time()
            
            while session.is_streaming:
                await asyncio.sleep(0.2)
                if asyncio.get_event_loop().time() - start > timeout:
                    session.is_streaming = False
                    break
            
            # Final update with controls
            await self._finalize_response(channel, response_msg, session)
            
        except Exception as e:
            logger.error(f"Message processing failed: {e}")
            error_embed = discord.Embed(
                description=f"❌ Error: {str(e)[:500]}",
                color=discord.Color.red()
            )
            await response_msg.edit(embed=error_embed)
            session.is_streaming = False
    
    async def _finalize_response(self, channel, response_msg, session: ActiveSession):
        """Finalize the response with proper formatting and controls"""
        text = session.stream_buffer or "*No response*"
        
        # Truncate if needed
        if len(text) > MAX_EMBED_LENGTH:
            text = text[:MAX_EMBED_LENGTH] + "\n\n*...truncated*"
        
        final_embed = discord.Embed(
            description=text,
            color=discord.Color.purple()
        )
        
        # Add subtle controls
        view = SessionControlsView(self, session)
        
        try:
            await response_msg.edit(embed=final_embed, view=view)
        except:
            pass
    
    # -------------------------------------------------------------------------
    # SSE Event Streaming
    # -------------------------------------------------------------------------
    
    async def _event_listener(self):
        """Background listener for real-time streaming updates"""
        while True:
            try:
                async for event in self.api.subscribe_events():
                    await self._handle_event(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SSE error: {e}")
                await asyncio.sleep(3)
    
    async def _handle_event(self, event: dict):
        """Handle SSE events for streaming"""
        event_type = event.get('type')
        props = event.get('properties', {})
        
        if event_type == 'message.part.updated':
            await self._on_message_update(props)
        elif event_type == 'session.idle':
            await self._on_session_idle(props)
        elif event_type == 'permission.asked':
            await self._on_permission_asked(props)
    
    async def _on_message_update(self, props: dict):
        """Handle streaming text updates"""
        part = props.get('part', {})
        delta = props.get('delta', '')
        session_id = part.get('sessionID')
        
        # Find the session
        session = None
        for s in self.sessions.values():
            if s.session_id == session_id and s.is_streaming:
                session = s
                break
        
        if not session or not session.response_msg_id:
            return
        
        # Accumulate text
        if part.get('type') == 'text':
            if delta:
                session.stream_buffer += delta
            else:
                session.stream_buffer = part.get('text', '')
        
        # Rate-limited UI update
        now = asyncio.get_event_loop().time()
        if now - session.last_update >= STREAM_UPDATE_INTERVAL:
            await self._update_streaming_display(session)
            session.last_update = now
    
    async def _update_streaming_display(self, session: ActiveSession):
        """Update the Discord message with current stream content"""
        try:
            channel = self.bot.get_channel(session.thread_id)
            if not channel:
                return
            
            message = await channel.fetch_message(session.response_msg_id)
            
            text = session.stream_buffer or "*Thinking...*"
            if len(text) > MAX_EMBED_LENGTH:
                text = text[:MAX_EMBED_LENGTH] + "\n\n*...continuing*"
            
            embed = discord.Embed(
                description=text,
                color=discord.Color.blue()
            )
            embed.set_footer(text="⏳ Generating...")
            
            await message.edit(embed=embed)
        except Exception as e:
            logger.debug(f"Stream update failed: {e}")
    
    async def _on_session_idle(self, props: dict):
        """Handle session becoming idle (response complete)"""
        session_id = props.get('sessionID')
        
        for session in self.sessions.values():
            if session.session_id == session_id:
                session.is_streaming = False
                break
    
    async def _on_permission_asked(self, props: dict):
        """Handle permission request from OpenCode"""
        request_id = props.get('id')
        session_id = props.get('sessionID')
        permission = props.get('permission', 'perform an action')
        patterns = props.get('patterns', [])
        
        # Find the session's thread
        for session in self.sessions.values():
            if session.session_id == session_id:
                try:
                    channel = self.bot.get_channel(session.thread_id)
                    if channel:
                        desc = f"**{permission}**"
                        if patterns:
                            desc += "\n" + "\n".join(f"• `{p}`" for p in patterns[:5])
                        
                        embed = discord.Embed(
                            title="🔐 Permission Needed",
                            description=desc,
                            color=discord.Color.orange()
                        )
                        
                        view = PermissionView(self, request_id, permission)
                        await channel.send(embed=embed, view=view)
                except Exception as e:
                    logger.error(f"Permission prompt failed: {e}")
                break

# =============================================================================
# Setup
# =============================================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(OpenCodeCog(bot))
    logger.info("OpenCode cog ready - use !code to start")
