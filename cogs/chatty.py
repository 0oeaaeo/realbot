"""
Chatty Mode Cog - Enhanced with Emotional Awareness

Enables passive channel listening with probability-based autonomous responses.
Features:
- Rolling 30-message context
- Probability-based and mention-triggered responses  
- Emotional state tracking via EmotionEngine
- User relationship tracking (trust/familiarity)
- Mood-aware response generation
"""

import discord
from discord.ext import commands
import asyncio
import os
import json
import random
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from pathlib import Path

from google import genai
from dotenv import load_dotenv

from utils.emotion_engine import get_emotion_engine

load_dotenv()

logger = logging.getLogger('realbot')

# Initialize GenAI Client
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
try:
    genai_client = genai.Client(api_key=API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize GenAI client for Chatty: {e}")
    genai_client = None

# Data file for persistence
DATA_DIR = Path(__file__).parent.parent / "data"
CHATTY_DATA_FILE = DATA_DIR / "chatty_state.json"


@dataclass
class ChannelState:
    """State for a single channel's chatty mode."""
    is_enabled: bool = False
    trigger_probability: int = 10  # 0-100, default 10%
    history: List[str] = field(default_factory=list)  # Last 25 messages
    
    def to_dict(self) -> dict:
        return {
            "is_enabled": self.is_enabled,
            "trigger_probability": self.trigger_probability,
            "history": self.history
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ChannelState':
        return cls(
            is_enabled=data.get("is_enabled", False),
            trigger_probability=data.get("trigger_probability", 10),
            history=data.get("history", [])
        )


class Chatty(commands.Cog):
    """Chatty Mode - passive listening with probability-based responses."""
    
    def __init__(self, bot):
        self.bot = bot
        # Per-channel state: channel_id -> ChannelState
        self.channel_states: Dict[int, ChannelState] = {}
        self._load_state()
    
    def _load_state(self):
        """Load state from JSON file."""
        if CHATTY_DATA_FILE.exists():
            try:
                with open(CHATTY_DATA_FILE, 'r') as f:
                    data = json.load(f)
                for channel_id_str, state_data in data.items():
                    self.channel_states[int(channel_id_str)] = ChannelState.from_dict(state_data)
                logger.info(f"Chatty: Loaded state for {len(self.channel_states)} channels")
            except Exception as e:
                logger.error(f"Chatty: Failed to load state: {e}")
    
    def _save_state(self):
        """Save state to JSON file."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                str(channel_id): state.to_dict() 
                for channel_id, state in self.channel_states.items()
            }
            with open(CHATTY_DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Chatty: Failed to save state: {e}")
    
    def _get_state(self, channel_id: int) -> ChannelState:
        """Get or create channel state."""
        if channel_id not in self.channel_states:
            self.channel_states[channel_id] = ChannelState()
        return self.channel_states[channel_id]
    
    def _get_persona(self) -> str:
        """Get current persona from PersonaCog, or default."""
        try:
            persona_cog = self.bot.get_cog("PersonaCog")
            if persona_cog and hasattr(persona_cog, 'get_system_prompt'):
                prompt = persona_cog.get_system_prompt()
                if prompt:
                    return prompt
        except Exception as e:
            logger.error(f"Chatty: Error getting persona: {e}")
        
        # Default persona
        return (
            "You are a friendly, casual Discord user participating in a group chat. "
            "Be natural, brief, and match the energy of the conversation. "
            "Don't be overly helpful or formal - you're just hanging out."
        )
    
    async def _fetch_recent_messages(self, channel: discord.TextChannel, limit: int = 30) -> List[str]:
        """Fetch the last N messages from a channel for fresh context."""
        messages = []
        try:
            async for msg in channel.history(limit=limit):
                if msg.content.strip() and not msg.content.startswith(('!', '?', '.')):
                    messages.append(f"{msg.author.display_name}: {msg.content}")
            # Reverse to get chronological order (oldest first)
            messages.reverse()
        except Exception as e:
            logger.error(f"Chatty: Error fetching messages: {e}")
        return messages
    
    async def _generate_response(self, channel: discord.TextChannel, persona: str, trigger_user_id: Optional[int] = None) -> Optional[str]:
        """Generate a response based on conversation history using REST API."""
        if not API_KEY:
            logger.error("GEMINI_API_KEY not set")
            return None
        
        try:
            import aiohttp
            
            # Fetch fresh context from channel (last 30 messages)
            recent_messages = await self._fetch_recent_messages(channel, limit=30)
            
            if not recent_messages:
                return None
            
            # Format history as context
            context = "\n".join(recent_messages)
            
            # Get emotional context
            emotion_engine = get_emotion_engine()
            emotional_state = emotion_engine.get_state("chatty", channel.id)
            mood = emotional_state.get_mood_description()
            
            # Get relationship with trigger user if available
            relationship_context = ""
            if trigger_user_id:
                rel = emotion_engine.get_user_relationship(channel.id, trigger_user_id)
                familiarity = rel.get("familiarity", 0.5)
                trust = rel.get("trust", 0.5)
                if familiarity > 0.7:
                    relationship_context = "You know this person well and can be more casual/friendly."
                elif familiarity < 0.3:
                    relationship_context = "This person is new to you, be slightly more reserved."
            
            # Build the full prompt with persona and emotional context
            full_prompt = f"""{persona}

=== YOUR CURRENT EMOTIONAL STATE ===
You are currently feeling: {mood}
Let this subtly influence your response tone.
{relationship_context}
=== END EMOTIONAL STATE ===

You are passively observing a Discord conversation and have decided to chime in.
Based on the recent chat history below, write a natural response that fits the conversation.
Keep it brief and casual - you're just a participant, not the main focus.

=== Recent Chat History ===
{context}
=== End History ===

Write a single, natural response to contribute to this conversation:"""

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={API_KEY}"
            
            payload = {
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {
                    "temperature": 0.9,
                    "maxOutputTokens": 2000
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Chatty API error ({response.status}): {error_text}")
                        return None
                    
                    data = await response.json()
                    
                    candidates = data.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
                    
                    return None
            
        except Exception as e:
            logger.error(f"Chatty: Error generating response: {e}")
            return None
    
    @commands.group(name="chatty", invoke_without_command=True)
    async def chatty(self, ctx: commands.Context):
        """Toggle chatty mode on/off for this channel."""
        state = self._get_state(ctx.channel.id)
        state.is_enabled = not state.is_enabled
        self._save_state()
        
        status = "**enabled** 💬" if state.is_enabled else "**disabled** 🔇"
        await ctx.send(f"Chatty mode {status} for this channel.\nTrigger probability: {state.trigger_probability}%")
    
    @chatty.command(name="trigger")
    async def chatty_trigger(self, ctx: commands.Context, probability: int):
        """Set the trigger probability (0-100%)."""
        if not 0 <= probability <= 100:
            await ctx.send("❌ Probability must be between 0 and 100.")
            return
        
        state = self._get_state(ctx.channel.id)
        state.trigger_probability = probability
        self._save_state()
        
        await ctx.send(f"✅ Trigger probability set to **{probability}%**")
    
    @chatty.command(name="status")
    async def chatty_status(self, ctx: commands.Context):
        """Show current chatty mode status."""
        state = self._get_state(ctx.channel.id)
        status = "Enabled ✅" if state.is_enabled else "Disabled ❌"
        persona_name = "Default"
        
        try:
            persona_cog = self.bot.get_cog("PersonaCog")
            if persona_cog and hasattr(persona_cog, 'get_active_persona'):
                active = persona_cog.get_active_persona()
                if active:
                    persona_name = active.get("name", "Custom")
        except:
            pass
        
        await ctx.send(
            f"**Chatty Mode Status**\n"
            f"• Status: {status}\n"
            f"• Trigger: {state.trigger_probability}%\n"
            f"• History: {len(state.history)}/25 messages\n"
            f"• Persona: {persona_name}"
        )
    
    @chatty.command(name="clear")
    async def chatty_clear(self, ctx: commands.Context):
        """Clear the conversation history for this channel."""
        state = self._get_state(ctx.channel.id)
        state.history = []
        self._save_state()
        await ctx.send("✅ Conversation history cleared.")
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen to messages and potentially respond."""
        # Ignore self
        if message.author == self.bot.user:
            return
        
        # Ignore DMs
        if not message.guild:
            return
        
        # Ignore commands
        if message.content.startswith(('!', '?', '.')):
            return
        
        # Get channel state
        state = self._get_state(message.channel.id)
        
        # If not enabled, don't process
        if not state.is_enabled:
            return
        
        # Process message through emotion engine (even if we don't respond)
        emotion_engine = get_emotion_engine()
        emotion_engine.process_message(
            mode="chatty",
            entity_id=message.channel.id,
            message=message.content,
            user_id=message.author.id,
            context=f"Message from {message.author.display_name}"
        )
        
        # Update user relationship (familiarity increases with interaction)
        emotion_engine.update_user_relationship(
            channel_id=message.channel.id,
            user_id=message.author.id,
            familiarity_delta=0.01  # Small increment per message
        )
        
        # Log message to history
        formatted_msg = f"{message.author.display_name}: {message.content}"
        state.history.append(formatted_msg)
        
        # Trim to last 30 messages
        if len(state.history) > 30:
            state.history = state.history[-30:]
        
        # Check if we should trigger
        trigger = False
        
        # Mandatory trigger: bot mentioned or replied to
        if self.bot.user in message.mentions:
            trigger = True
        elif message.reference:
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
                if ref_msg.author == self.bot.user:
                    trigger = True
            except:
                pass
        
        # Random trigger based on probability
        if not trigger and state.trigger_probability > 0:
            roll = random.randint(1, 100)
            if roll <= state.trigger_probability:
                trigger = True
                logger.info(f"Chatty: Random trigger (rolled {roll} <= {state.trigger_probability})")
        
        # Generate and send response
        if trigger:
            async with message.channel.typing():
                persona = self._get_persona()
                # Fetch fresh context and generate response with emotional awareness
                response = await self._generate_response(
                    message.channel, 
                    persona,
                    trigger_user_id=message.author.id
                )
                
                if response:
                    await message.channel.send(response)
                    
                    # Process our own response through emotion engine
                    emotion_engine.process_message(
                        mode="chatty",
                        entity_id=message.channel.id,
                        message=response,
                        user_id=self.bot.user.id,
                        context="Own response"
                    )
                    
                    # Increase trust with user we responded to
                    emotion_engine.update_user_relationship(
                        channel_id=message.channel.id,
                        user_id=message.author.id,
                        trust_delta=0.02  # Small trust boost
                    )
                    
                    # Add bot's response to history
                    bot_msg = f"{self.bot.user.display_name}: {response}"
                    state.history.append(bot_msg)
                    if len(state.history) > 30:
                        state.history = state.history[-30:]
                    
                    self._save_state()
    
    @chatty.command(name="mood")
    async def chatty_mood(self, ctx: commands.Context):
        """Display the bot's current emotional state for this channel."""
        emotion_engine = get_emotion_engine()
        emotional_state = emotion_engine.get_state("chatty", ctx.channel.id)
        
        # Build emotion bar display
        emotion_bars = []
        for emotion, intensity in sorted(emotional_state.emotions.items(), key=lambda x: -x[1]):
            bar_length = int(intensity * 10)
            bar = "█" * bar_length + "░" * (10 - bar_length)
            emotion_bars.append(f"`{emotion:12}` {bar} {int(intensity * 100)}%")
        
        # Get recent triggers
        recent = emotion_engine.get_recent_triggers("chatty", ctx.channel.id, limit=3)
        trigger_lines = []
        for t in recent:
            trigger_lines.append(f"• \"{t.get('trigger', '')[:40]}...\"")
        
        embed = discord.Embed(
            title=f"🤖 Chatty Mood in #{ctx.channel.name}",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Current Mood",
            value=emotional_state.get_mood_description().title(),
            inline=True
        )
        embed.add_field(
            name="Stability",
            value=f"{'Stable' if emotional_state.stability > 0.6 else 'Volatile' if emotional_state.stability < 0.4 else 'Moderate'}",
            inline=True
        )
        embed.add_field(
            name="Emotion Levels",
            value="\n".join(emotion_bars[:4]),  # Top 4 emotions
            inline=False
        )
        
        if trigger_lines:
            embed.add_field(
                name="Recent Triggers",
                value="\n".join(trigger_lines),
                inline=False
            )
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Chatty(bot))
