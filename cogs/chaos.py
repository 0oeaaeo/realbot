import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
from typing import Literal
from shared import ROLE_ADMIN

# Gemini API configuration
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent"

# Prompt template for generating opposites
OPPOSITE_PROMPT = """take the following text, and modify it to make the person sound crazier, creeper, stalkier, unhinged.  but keep the general idea of the original message.  be sure to only output the transformed message, nothing else.

Message: {message}"""


class Chaos(commands.Cog):
    """Chaos mode: Replaces targeted users' messages with AI-generated opposites."""
    
    def __init__(self, bot):
        self.bot = bot
        # Track targeted users: set of user IDs
        self.chaos_targets: set[int] = set()
        # Track chaos channels: set of channel IDs (all messages get chaos'd)
        self.chaos_channels: set[int] = set()
    
    def is_admin(self, member: discord.Member) -> bool:
        """Check if user has admin role."""
        return any(role.id == ROLE_ADMIN for role in member.roles)
    
    async def generate_opposite(self, message: str) -> str | None:
        """Use Gemini REST API to generate the opposite of a message."""
        if not GEMINI_API_KEY:
            print("GEMINI_API_KEY not set in environment")
            return None
            
        try:
            prompt = OPPOSITE_PROMPT.format(message=message)
            
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }]
            }
            
            url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        print(f"Gemini API error ({response.status}): {error_text}")
                        return None
                    
                    data = await response.json()
                    
                    # Extract text from response
                    candidates = data.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
                    
                    return None
                    
        except Exception as e:
            print(f"Error generating opposite: {e}")
            return None
    
    async def get_or_create_webhook(self, channel: discord.TextChannel) -> discord.Webhook | None:
        """Get an existing webhook or create one for the channel."""
        try:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if wh.token:  # Ensure we have the token
                    return wh
            
            # Create new webhook
            return await channel.create_webhook(name="ChaosBot")
        except discord.Forbidden:
            print(f"No permission to manage webhooks in {channel.name}")
            return None
        except Exception as e:
            print(f"Error getting/creating webhook: {e}")
            return None
    
    @app_commands.command(name="chaos", description="Enable chaos mode for a user - replaces their messages with opposites (Admin only)")
    @app_commands.describe(
        user="The user to target",
        mode="Enable or disable chaos mode for this user"
    )
    async def chaos(
        self, 
        interaction: discord.Interaction, 
        user: discord.Member,
        mode: Literal['on', 'off'] = 'on'
    ):
        """Toggle chaos mode for a user."""
        if not self.is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ You are not authorized to use this command.", 
                ephemeral=True
            )
            return
        
        if mode == 'off':
            if user.id in self.chaos_targets:
                self.chaos_targets.discard(user.id)
                await interaction.response.send_message(
                    f"😇 Chaos mode **disabled** for {user.mention}. Their messages will no longer be turned into opposites.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"ℹ️ Chaos mode was not enabled for {user.mention}.",
                    ephemeral=True
                )
        else:
            self.chaos_targets.add(user.id)
            await interaction.response.send_message(
                f"😈 Chaos mode **enabled** for {user.mention}! Their messages will now be replaced with AI-generated opposites.",
                ephemeral=True
            )
    
    @app_commands.command(name="allchaos", description="Enable chaos mode for ALL messages in this channel (Admin only)")
    @app_commands.describe(
        mode="Enable or disable channel-wide chaos mode (omit to toggle)"
    )
    async def allchaos(
        self, 
        interaction: discord.Interaction, 
        mode: Literal['on', 'off'] = None
    ):
        """Toggle chaos mode for entire channel."""
        if not self.is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ You are not authorized to use this command.", 
                ephemeral=True
            )
            return
        
        channel_id = interaction.channel_id
        
        # Auto-toggle if no mode specified
        if mode is None:
            mode = 'off' if channel_id in self.chaos_channels else 'on'
        
        if mode == 'off':
            if channel_id in self.chaos_channels:
                self.chaos_channels.discard(channel_id)
                await interaction.response.send_message(
                    f"😇 Channel-wide chaos mode **disabled**. Messages will no longer be turned into opposites.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"ℹ️ Channel-wide chaos mode was not enabled.",
                    ephemeral=True
                )
        else:
            self.chaos_channels.add(channel_id)
            await interaction.response.send_message(
                f"😈 Channel-wide chaos mode **enabled**! ALL messages in this channel will now be replaced with AI-generated opposites.",
                ephemeral=True
            )
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Watch for messages from chaos targets and replace them."""
        # Ignore bots
        if message.author.bot:
            return
        
        # Check if this user is a chaos target OR if the channel has allchaos enabled
        is_user_target = message.author.id in self.chaos_targets
        is_channel_chaos = message.channel.id in self.chaos_channels
        
        if not is_user_target and not is_channel_chaos:
            return
        
        # Only works in text channels (need webhook support)
        if not isinstance(message.channel, discord.TextChannel):
            return
        
        # Skip empty messages or messages with only attachments
        if not message.content or not message.content.strip():
            return
        
        try:
            # Generate the opposite
            opposite = await self.generate_opposite(message.content)
            
            if not opposite:
                print(f"Failed to generate opposite for: {message.content[:50]}")
                return
            
            # Get webhook
            webhook = await self.get_or_create_webhook(message.channel)
            if not webhook:
                return
            
            # Send opposite message via webhook (spoofing user's identity)
            await webhook.send(
                content=opposite,
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url
            )
            
            # Delete the original message
            await message.delete()
            
        except discord.Forbidden:
            print(f"Missing permissions to delete message or use webhooks in {message.channel.name}")
        except Exception as e:
            print(f"Error in chaos on_message: {e}")


async def setup(bot):
    await bot.add_cog(Chaos(bot))

