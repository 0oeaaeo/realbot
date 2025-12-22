import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
import logging

# Get the bot logger
logger = logging.getLogger('realbot')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = "gemini-3-pro-preview"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

class Roast(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info(f"Roast cog initialized")

    async def generate_roast_text(self, context_text: str) -> str | None:
        logger.debug(f"Generating roast with {len(context_text)} chars of context")
        
        if not GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY not set in environment")
            return None

        prompt = (
            "Based on the following message history from a user, write a dialed-in and succinct roast, "
            "exactly one paragraph in length. Use the message text as context to make it personal and biting.\n\n"
            f"User Messages:\n{context_text}"
        )
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
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
                    logger.debug(f"Gemini API response keys: {data.keys()}")
                    
                    candidates = data.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        if parts:
                            result = parts[0].get("text", "").strip()
                            logger.info(f"Generated roast: {len(result)} chars")
                            return result
                    
                    logger.warning(f"No candidates in Gemini response: {data}")
                    return None
        except Exception as e:
            logger.exception(f"Error generating roast: {e}")
            return None

    @commands.command()
    async def roast(self, ctx, user: discord.Member):
        """Scrapes the last 25 messages from a user and generates a roast using Gemini."""
        logger.info(f"Roast command invoked by {ctx.author} targeting {user}")
        
        user_messages = []
        
        # Scrape history to find the user's last 25 messages
        # We scan up to 500 messages to find 25 from the target user
        logger.debug(f"Scanning channel history for {user}'s messages...")
        async for message in ctx.channel.history(limit=500):
            if message.author.id == user.id and message.content.strip():
                user_messages.append(message.content)
                if len(user_messages) >= 25:
                    break
        
        logger.info(f"Found {len(user_messages)} messages from {user}")
        
        if not user_messages:
            logger.warning(f"No messages found for {user} in {ctx.channel}")
            await ctx.send(f"I couldn't find any recent text messages from {user.display_name} to roast!")
            return

        # Reverse to have chronological order (oldest to newest)
        user_messages.reverse()
        context_text = "\n".join(user_messages)

        async with ctx.typing():
            roast = await self.generate_roast_text(context_text)
            
            if roast:
                logger.info(f"Sending roast to {ctx.channel}")
                await ctx.send(f"{user.mention}\n{roast}")
            else:
                logger.error(f"Failed to generate roast for {user}")
                await ctx.send("I tried to think of a roast, but my circuits got crossed. Try again later.")

async def setup(bot):
    await bot.add_cog(Roast(bot))