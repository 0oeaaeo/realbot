import discord
from discord import app_commands
from discord.ext import commands
import logging
import os
import asyncio
import aiohttp

from utils.discord_search import get_user_messages

logger = logging.getLogger('realbot')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = "gemini-2.5-pro"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

class PersonaCombinerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("PersonaCombinerCog cog initialized")

    async def call_gemini_api(self, prompt: str, temperature: float = 0.8, max_tokens: int = 1024) -> str | None:
        """Call Gemini API using aiohttp."""
        if not GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY not set in environment")
            return None

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
        
        url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
        logger.debug(f"Calling Gemini API: {GEMINI_MODEL}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Gemini API error ({response.status}): {error_text[:500]}")
                        return None
                    
                    data = await response.json()
                    logger.debug(f"Gemini API response received")
                    
                    candidates = data.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        if parts:
                            result = parts[0].get("text", "").strip()
                            logger.info(f"Generated response: {len(result)} chars")
                            return result
                    
                    logger.warning(f"No candidates in Gemini response: {data}")
                    return None
        except Exception as e:
            logger.exception(f"Error calling Gemini API: {e}")
            return None

    @commands.command(name="combine", help="Combines two users' recent chat history to create a new persona.")
    @commands.cooldown(1, 60, commands.BucketType.user)
    @commands.guild_only()
    async def combine(self, ctx: commands.Context, user1: discord.Member, user2: discord.Member):
        """Creates a new persona by combining the personalities of two users."""
        logger.info(f"!combine invoked by {ctx.author} for users {user1.name} and {user2.name}")

        if not GEMINI_API_KEY:
            await ctx.send("Sorry, the AI generation service is not configured correctly. Please contact the bot administrator.")
            logger.error("Combine command failed: GEMINI_API_KEY not set.")
            return

        if user1 == user2:
            await ctx.send("You can't combine a user with themselves. Please provide two different users.")
            return

        if user1.bot or user2.bot:
            await ctx.send("You can't combine bots. Please provide two human users.")
            return

        async with ctx.typing():
            try:
                # Use the new Discord search API to get user messages
                logger.debug(f"Fetching messages for {user1.name} and {user2.name} using search API")
                
                user1_messages, user2_messages = await asyncio.gather(
                    get_user_messages(
                        guild_id=str(ctx.guild.id),
                        user_id=str(user1.id),
                        channel_id=str(ctx.channel.id),
                        limit=25
                    ),
                    get_user_messages(
                        guild_id=str(ctx.guild.id),
                        user_id=str(user2.id),
                        channel_id=str(ctx.channel.id),
                        limit=25
                    )
                )
                
                logger.info(f"Found {len(user1_messages)} messages for {user1.name}, {len(user2_messages)} for {user2.name}")

                if not user1_messages or not user2_messages:
                    await ctx.send("Could not find enough recent messages in this channel for one or both users to create a persona.")
                    logger.warning(f"Could not find enough messages for {user1.name} or {user2.name}")
                    return

                # Format messages with user display names
                user1_log_str = "\n".join(f"{user1.display_name}: {msg}" for msg in user1_messages)
                user2_log_str = "\n".join(f"{user2.display_name}: {msg}" for msg in user2_messages)

                prompt = (
                    "You are a persona synthesizer. Your task is to analyze the chat logs of two individuals and create a 'love child' persona "
                    "that represents a fusion of their personalities, speaking styles, and recurring themes.\n\n"
                    f"Here are the chat logs for User 1 ({user1.display_name}) and User 2 ({user2.display_name}):\n\n"
                    f"--- USER 1 ({user1.display_name}) CHAT LOGS ---\n{user1_log_str}\n--- END USER 1 CHAT LOGS ---\n\n"
                    f"--- USER 2 ({user2.display_name}) CHAT LOGS ---\n{user2_log_str}\n--- END USER 2 CHAT LOGS ---\n\n"
                    "Based on these logs, generate a detailed description of the resulting 'love child' persona. The description must include:\n"
                    "1. A creative name for this new persona.\n"
                    "2. A short behavioral and descriptive text block explaining their core personality traits, quirks, and how they combine the characteristics of the two original users.\n"
                    "3. A section with a few example quotes that this new persona would likely say, capturing their unique voice.\n\n"
                    "Present the output in a clear, readable format using Discord markdown."
                )

                result_text = await self.call_gemini_api(prompt, temperature=0.8, max_tokens=1024)

                if not result_text:
                    await ctx.send("Failed to generate persona. The AI service may be temporarily unavailable.")
                    return

                if len(result_text) > 2000:
                    for i in range(0, len(result_text), 2000):
                        await ctx.send(result_text[i:i+2000])
                else:
                    await ctx.send(result_text)

                logger.info(f"Successfully sent persona combination result")

            except Exception as e:
                logger.exception("Exception in !combine command")
                await ctx.send(f"An unexpected error occurred while generating the persona.\n`{e}`")

    @combine.error
    async def combine_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Please provide two users to combine. Usage: `!combine @user1 @user2`")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(f"I couldn't find a user named `{error.argument}`. Please make sure you've tagged them correctly.")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"This command is on cooldown. Please try again in {error.retry_after:.2f} seconds.")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("This command can only be used in a server channel.")
        else:
            logger.error(f"An unhandled error occurred in the combine command: {error}")
            await ctx.send("An unexpected error occurred. Please try again later.")

async def setup(bot: commands.Bot):
    await bot.add_cog(PersonaCombinerCog(bot))