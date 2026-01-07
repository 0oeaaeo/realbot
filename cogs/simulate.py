"""
User Simulation Cog

Allows creating AI-powered simulations of Discord users based on their chat history.
Uses webhooks to impersonate users and the Gemini Interactions API with client-side state.
"""

import discord
from discord.ext import commands
import asyncio
import os
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List

from google import genai
from dotenv import load_dotenv

from utils.discord_search import get_search_client, SearchError

load_dotenv()

logger = logging.getLogger('realbot')

# Initialize GenAI Client
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
try:
    genai_client = genai.Client(api_key=API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize GenAI client for Simulate: {e}")
    genai_client = None

# Simulation system instruction template - raw message context approach
SIMULATION_SYSTEM_INSTRUCTION = """You are roleplaying as a Discord user named "{name}". 

I will show you their real message history so you can learn EXACTLY how they type and what they talk about. Your job is to become this person and respond to new messages as they would.

=== {name}'s REAL MESSAGES (STUDY THESE CAREFULLY, EACH LINE IS A NEW MESSAGE) ===
{messages}
=== END OF MESSAGES ===

IMPORTANT INSTRUCTIONS:
- You ARE {name} now. Respond in first person as them.
- NEVER repeat or paraphrase anything from the message history above. Create 100% NEW responses.
- Match their EXACT typing style: capitalization, punctuation, slang, abbreviations, emoji usage.
- If they type in lowercase, you type in lowercase. If they use "u" instead of "you", do that too.
- Keep your responses similar LENGTH to their typical messages.
- Match their energy, humor, and personality.
- Respond naturally to whatever is said to you - don't be robotic or overly formal.
- If you don't know something they would know, make something up that fits their personality.

You are {name}. Stay in character. Do NOT break character or mention that you're an AI."""


@dataclass
class SimulationState:
    """Tracks an active simulation session with client-side state."""
    target_user: discord.Member
    webhook: discord.Webhook
    system_instruction: str
    conversation_history: List[Dict] = field(default_factory=list)
    

class Simulate(commands.Cog):
    """Simulate Discord users based on their chat history using Interactions API."""
    
    def __init__(self, bot):
        self.bot = bot
        # Active simulations: channel_id -> SimulationState
        self.active_simulations: Dict[int, SimulationState] = {}
    
    async def fetch_user_messages(
        self,
        guild_id: str,
        channel_id: str,
        user_id: str,
        limit: int = 200
    ) -> List[str]:
        """Fetch messages from a user using Discord search API with pagination."""
        client = get_search_client()
        all_messages = []
        remaining = limit
        offset = 0
        
        logger.info(f"Simulation: Fetching up to {limit} messages for user {user_id}")
        
        while remaining > 0:
            params = {
                "author_id": [user_id],
                "channel_id": [channel_id],
                "sort_by": "timestamp",
                "sort_order": "desc",
                "limit": min(25, remaining),
                "offset": offset
            }
            
            try:
                result = await client.search_with_retry(guild_id, **params)
                targets = result.get_target_messages()
                
                if not targets:
                    break
                
                all_messages.extend(targets)
                remaining -= len(targets)
                offset += len(targets)
                
                # Rate limit respect
                await asyncio.sleep(0.3)
                
            except SearchError as e:
                logger.error(f"Simulation search error: {e}")
                break
        
        logger.info(f"Simulation: Fetched {len(all_messages)} messages")
        
        # Return only message content, chronologically (oldest first)
        formatted = []
        for msg in reversed(all_messages):
            if msg.content.strip():
                formatted.append(msg.content)
        
        return formatted
    
    def build_system_instruction(self, messages: List[str], user_name: str) -> str:
        """Build the system instruction with message history."""
        message_block = "\n".join(messages)
        
        return SIMULATION_SYSTEM_INSTRUCTION.format(
            name=user_name,
            messages=message_block
        )
    
    async def generate_response_streaming(
        self, 
        state: 'SimulationState', 
        user_message: str,
        webhook_msg: discord.WebhookMessage
    ) -> Optional[str]:
        """
        Generate a streaming response, updating webhook message as chunks arrive.
        """
        if not genai_client:
            logger.error("GenAI client not initialized")
            return None
        
        try:
            # Add user message to conversation history
            state.conversation_history.append({
                "role": "user",
                "content": user_message
            })
            
            loop = asyncio.get_running_loop()
            
            def create_stream():
                return genai_client.interactions.create(
                    model="gemini-3-flash-preview",
                    system_instruction=state.system_instruction,
                    input=state.conversation_history,
                    generation_config={
                        "temperature": 0.9,
                        "max_output_tokens": 2000
                    },
                    store=False,
                    stream=True
                )
            
            stream = await loop.run_in_executor(None, create_stream)
            
            accumulated_text = ""
            last_update_len = 0
            update_threshold = 15  # Update every ~15 chars
            
            def get_next_chunk(stream_iter):
                try:
                    return next(stream_iter)
                except StopIteration:
                    return None
            
            stream_iter = iter(stream)
            
            while True:
                chunk = await loop.run_in_executor(None, get_next_chunk, stream_iter)
                
                if chunk is None:
                    break
                
                # Handle different event types
                event_type = getattr(chunk, 'event_type', None)
                
                if event_type == "content.delta":
                    delta = getattr(chunk, 'delta', None)
                    if delta:
                        text = getattr(delta, 'text', None)
                        if text:
                            accumulated_text += text
                            
                            # Update webhook message periodically
                            if len(accumulated_text) - last_update_len >= update_threshold:
                                try:
                                    await webhook_msg.edit(content=accumulated_text + "▌")
                                    last_update_len = len(accumulated_text)
                                except Exception:
                                    pass  # Rate limited, skip this update
                
                elif event_type == "interaction.complete":
                    break
                
                # Also check if chunk has outputs directly (non-streaming fallback)
                elif hasattr(chunk, 'outputs'):
                    for output in chunk.outputs:
                        if getattr(output, 'type', None) == 'text':
                            accumulated_text = getattr(output, 'text', '')
                    break
            
            # Final update without cursor
            if accumulated_text:
                try:
                    await webhook_msg.edit(content=accumulated_text)
                except Exception as e:
                    logger.error(f"Failed to edit final webhook message: {e}")
                
                # Add to conversation history
                state.conversation_history.append({
                    "role": "model",
                    "content": accumulated_text
                })
            else:
                logger.warning("Simulate: No text accumulated from stream")
            
            return accumulated_text
            
        except Exception as e:
            logger.error(f"Error generating streaming response: {e}", exc_info=True)
            return None
    
    async def get_or_create_webhook(self, channel: discord.TextChannel) -> Optional[discord.Webhook]:
        """Get an existing webhook or create one for simulations."""
        try:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if wh.name == "UserSimulator" and wh.token:
                    return wh
            
            return await channel.create_webhook(name="UserSimulator")
        except discord.Forbidden:
            logger.error(f"No permission to manage webhooks in {channel.name}")
            return None
        except Exception as e:
            logger.error(f"Error getting/creating webhook: {e}")
            return None
    
    @commands.command(name="simulate")
    @commands.is_owner()
    async def simulate(self, ctx: commands.Context, user: discord.Member, message_count: int = 250):
        """Start simulating a user based on their chat history. Owner only.
        
        Usage: !simulate @user [message_count]
        message_count: Number of messages to gather (default: 250, max: 1500)
        """
        if ctx.channel.id in self.active_simulations:
            await ctx.send("❌ Already simulating someone in this channel. Use `!stopsim` first.")
            return
        
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ This command only works in text channels.")
            return
        
        if not genai_client:
            await ctx.send("❌ GenAI client not available.")
            return
        
        # Validate message count
        message_count = max(10, min(1500, message_count))
        
        status_msg = await ctx.send(f"🔍 Analyzing {user.display_name}'s messages (fetching up to {message_count})...")
        
        try:
            messages = await self.fetch_user_messages(
                str(ctx.guild.id),
                str(ctx.channel.id),
                str(user.id),
                limit=message_count
            )
            
            if len(messages) < 5:
                await status_msg.edit(content=f"❌ Not enough messages from {user.display_name} (found {len(messages)}, need 5+).")
                return
            
            await status_msg.edit(content=f"📊 Found {len(messages)} messages. Building personality model...")
            
            system_instruction = self.build_system_instruction(messages, user.display_name)
            
            webhook = await self.get_or_create_webhook(ctx.channel)
            if not webhook:
                await status_msg.edit(content="❌ Failed to create webhook. Check bot permissions.")
                return
            
            self.active_simulations[ctx.channel.id] = SimulationState(
                target_user=user,
                webhook=webhook,
                system_instruction=system_instruction,
                conversation_history=[]
            )
            
            await webhook.send(
                content=f"*{user.display_name} has entered the simulation*",
                username=user.display_name,
                avatar_url=user.display_avatar.url
            )
            
            await status_msg.edit(content=f"✅ **Simulation active!** Simulating **{user.display_name}** based on {len(messages)} messages.\n\nUse `!sim <message>` to interact. Use `!stopsim` to end.")
            
        except Exception as e:
            logger.error(f"Error starting simulation: {e}", exc_info=True)
            await status_msg.edit(content=f"❌ Error: {str(e)[:200]}")
    
    @commands.command(name="sim")
    async def sim(self, ctx: commands.Context, *, message: str):
        """Send a message to the active simulation."""
        if ctx.channel.id not in self.active_simulations:
            await ctx.send("❌ No active simulation. Use `!simulate @user` first.")
            return
        
        state = self.active_simulations[ctx.channel.id]
        
        # Send initial placeholder via webhook
        webhook_msg = await state.webhook.send(
            content="▌",
            username=state.target_user.display_name,
            avatar_url=state.target_user.display_avatar.url,
            wait=True  # Returns WebhookMessage we can edit
        )
        
        # Stream response with live edits
        response = await self.generate_response_streaming(state, message, webhook_msg)
        
        if not response:
            await webhook_msg.edit(content="❌ Failed to generate response.")
    
    @commands.command(name="stopsim")
    async def stopsim(self, ctx: commands.Context):
        """Stop the active simulation in this channel."""
        if ctx.channel.id not in self.active_simulations:
            await ctx.send("❌ No active simulation in this channel.")
            return
        
        state = self.active_simulations.pop(ctx.channel.id)
        
        await state.webhook.send(
            content=f"*{state.target_user.display_name} has left the simulation*",
            username=state.target_user.display_name,
            avatar_url=state.target_user.display_avatar.url
        )
        
        await ctx.send(f"✅ Stopped simulating **{state.target_user.display_name}**.")
        
        # Ask to save as persona
        save_msg = await ctx.send("💾 Save as persona? React ✅ or ❌")
        await save_msg.add_reaction("✅")
        await save_msg.add_reaction("❌")
        
        def check(reaction, user):
            return user == ctx.author and reaction.message.id == save_msg.id and str(reaction.emoji) in ["✅", "❌"]
        
        try:
            reaction, _ = await self.bot.wait_for('reaction_add', check=check, timeout=30.0)
            
            if str(reaction.emoji) == "✅":
                persona_cog = self.bot.get_cog("PersonaCog")
                if persona_cog:
                    persona_cog.personas.append({
                        "name": f"{state.target_user.display_name} (Simulated)",
                        "prompt": state.system_instruction,
                        "raw": True
                    })
                    persona_cog._save_personas()
                    await ctx.send(f"✅ Saved as persona index `{len(persona_cog.personas)-1}`")
                else:
                    await ctx.send("❌ PersonaCog not loaded.")
            else:
                await ctx.send("👋 Discarded.")
                
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out, discarded.")


async def setup(bot):
    await bot.add_cog(Simulate(bot))
