"""
Discord Search Cog

Admin-only search command with natural language query translation via Gemini.
Uses the experimental Discord guild message search API.
"""

import discord
from discord.ext import commands
import logging
import os
import json
import aiohttp
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from collections import Counter

from shared import ROLE_ADMIN
from utils.discord_search import DiscordSearchClient, SearchResult, SearchError

logger = logging.getLogger('realbot')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# System prompt for translating natural language to search parameters
SEARCH_TRANSLATION_PROMPT = '''You are a Discord message search query translator. Convert natural language queries into Discord search API parameters.

AVAILABLE PARAMETERS:
- content (String): Text to search for in message content
- author_id (Array[String]): Filter by user IDs (use snowflake IDs)
- channel_id (Array[String]): Filter by channel IDs (use snowflake IDs)
- has (Array[String]): Filter by content type. Values: link, embed, file, image, video, sound, sticker, poll
- min_id (String): Messages after this snowflake ID
- max_id (String): Messages before this snowflake ID
- pinned (Boolean): Filter pinned messages only
- mention_everyone (Boolean): Filter @everyone mentions
- author_type (Array[String]): Filter by author type: user, bot, webhook
- attachment_extension (Array[String]): Filter by file extension (e.g., "png", "mp4")
- link_hostname (Array[String]): Filter by URL hostname (e.g., "github.com")
- sort_by (String): "relevance" or "timestamp"
- sort_order (String): "asc" or "desc"
- limit (Integer): Results per page (1-25)

CONTEXT PROVIDED:
- User mentions in the query will include their Discord ID
- Channel mentions will include their Discord ID  
- Current timestamp for relative time calculations

OUTPUT FORMAT: Return ONLY a valid JSON object with the search parameters. No explanation, no markdown.

EXAMPLES:
Query: "images from user 123456789"
Output: {"author_id": ["123456789"], "has": ["image"]}

Query: "messages containing hello in channel 987654321"
Output: {"content": "hello", "channel_id": ["987654321"]}

Query: "links to github"
Output: {"has": ["link"], "link_hostname": ["github.com"]}

Query: "videos from bots"
Output: {"has": ["video"], "author_type": ["bot"]}

Query: "pinned messages"
Output: {"pinned": true}

USER QUERY:
'''


class Search(commands.Cog):
    """Discord message search with natural language queries."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.search_client: Optional[DiscordSearchClient] = None
        logger.info("Search cog initialized")
    
    def is_admin(self, member: discord.Member) -> bool:
        """Check if user has admin role."""
        return any(role.id == ROLE_ADMIN for role in member.roles)
    
    def _get_search_client(self) -> DiscordSearchClient:
        """Get the search client (uses USER_TOKEN from utils/discord_search.py)."""
        if self.search_client is None:
            # Use the singleton from discord_search which has USER_TOKEN configured
            from utils.discord_search import get_search_client
            self.search_client = get_search_client()
        return self.search_client
    
    async def translate_query_to_params(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Use Gemini to translate natural language to search parameters."""
        if not GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY not set")
            return {"content": query}  # Fallback to simple content search
        
        # Build context-aware prompt
        full_prompt = SEARCH_TRANSLATION_PROMPT + query
        
        # Add context about mentioned users/channels
        if context.get('mentioned_users'):
            full_prompt += f"\n\nMentioned users (name -> ID): {context['mentioned_users']}"
        if context.get('mentioned_channels'):
            full_prompt += f"\n\nMentioned channels (name -> ID): {context['mentioned_channels']}"
        full_prompt += f"\n\nCurrent timestamp: {datetime.utcnow().isoformat()}"
        
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {
                "temperature": 0.1,  # Low temperature for consistent output
                "maxOutputTokens": 500
            }
        }
        
        url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
        logger.debug(f"Translating search query: {query}")
        
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
                        return {"content": query}
                    
                    data = await response.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        # Clean up and parse JSON
                        text = text.strip()
                        if text.startswith("```"):
                            # Remove markdown code blocks if present
                            text = text.split("```")[1]
                            if text.startswith("json"):
                                text = text[4:]
                        
                        params = json.loads(text)
                        logger.info(f"Translated query to params: {params}")
                        return params
                    
                    return {"content": query}
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}")
            return {"content": query}
        except Exception as e:
            logger.exception(f"Error translating query: {e}")
            return {"content": query}
    
    def format_search_results(self, result: SearchResult, guild: discord.Guild) -> str:
        """Format search results for display."""
        if result.total_results == 0:
            return "No messages found matching your search."
        
        lines = [f"**Found {result.total_results} messages**\n"]
        
        # Get target messages (main results)
        targets = result.get_target_messages()
        
        for i, msg in enumerate(targets[:10], 1):  # Limit to 10 displayed
            # Truncate content for display
            content = msg.content[:150] + "..." if len(msg.content) > 150 else msg.content
            content = content.replace("\n", " ")  # Single line
            
            # Format timestamp
            try:
                ts = datetime.fromisoformat(msg.timestamp.replace('Z', '+00:00'))
                time_str = ts.strftime("%Y-%m-%d %H:%M")
            except:
                time_str = "Unknown"
            
            # Build message line
            lines.append(f"`{i}.` **{msg.author_name}** ({time_str})")
            if content:
                lines.append(f"   {content}")
            
            # Show attachments/embeds
            if msg.attachments:
                lines.append(f"   📎 {len(msg.attachments)} attachment(s)")
            if msg.embeds:
                lines.append(f"   🔗 {len(msg.embeds)} embed(s)")
            
            # Add jump link
            lines.append(f"   [Jump to message](https://discord.com/channels/{guild.id}/{msg.channel_id}/{msg.id})")
            lines.append("")
        
        if result.total_results > 10:
            lines.append(f"*...and {result.total_results - 10} more results*")
        
        return "\n".join(lines)
    
    @commands.command(name="search")
    @commands.guild_only()
    async def search(self, ctx: commands.Context, *, query: str):
        """
        Search messages using natural language.
        
        Examples:
          !search images from @user
          !search messages containing hello
          !search links to github
          !search pinned messages in #general
        """
        logger.info(f"!search invoked by {ctx.author} with query: {query}")
        
        if not self.is_admin(ctx.author):
            await ctx.send("❌ This command is admin-only.")
            return
        
        if not GEMINI_API_KEY:
            await ctx.send("❌ Search is not configured (missing API key).")
            return
        
        async with ctx.typing():
            try:
                # Extract mentioned users/channels for context
                context = {
                    "mentioned_users": {u.name: str(u.id) for u in ctx.message.mentions},
                    "mentioned_channels": {c.name: str(c.id) for c in ctx.message.channel_mentions}
                }
                
                # Translate natural language to search params
                params = await self.translate_query_to_params(query, context)
                
                if not params:
                    await ctx.send("❌ Could not understand the search query.")
                    return
                
                # Show what we're searching for
                await ctx.send(f"🔍 Searching with parameters: `{json.dumps(params, indent=None)[:500]}`")
                
                # Execute search
                client = self._get_search_client()
                result = await client.search_with_retry(
                    guild_id=str(ctx.guild.id),
                    limit=25,
                    **params
                )
                
                # Format and send results
                formatted = self.format_search_results(result, ctx.guild)
                
                # Split if too long
                if len(formatted) > 2000:
                    for i in range(0, len(formatted), 1900):
                        await ctx.send(formatted[i:i+1900])
                else:
                    await ctx.send(formatted)
                
                logger.info(f"Search completed: {result.total_results} results")
            
            except SearchError as e:
                logger.error(f"Search error: {e}")
                await ctx.send(f"❌ Search failed: {e}")
            
            except Exception as e:
                logger.exception(f"Unexpected error in search: {e}")
                await ctx.send(f"❌ An error occurred: {type(e).__name__}: {e}")
    
    @commands.command(name="topword")
    @commands.guild_only()
    async def topword(self, ctx: commands.Context, *, word: str):
        """
        Find the top 10 users who have said a specific word.
        
        Usage: $topword <word>
        """
        if not word:
             await ctx.send("Please provide a word to search for.")
             return

        status_msg = await ctx.send(f"🔍 Searching for top users saying `{word}`... This may take a moment.")
        
        client = self._get_search_client()
        counts = Counter()
        author_names = {}
        
        # We will fetch up to 1000 messages or 40 pages to be safe/fast enough
        MAX_MESSAGES = 1000
        PAGE_SIZE = 25
        total_found = 0
        analyzed = 0
        
        try:
            # First request to get total results and first page
            result = await client.search_with_retry(
                guild_id=str(ctx.guild.id),
                content=word,
                limit=PAGE_SIZE,
                offset=0
            )
            
            total_found = result.total_results
            if total_found == 0:
                await status_msg.edit(content=f"No one has said `{word}` yet (or no results found).")
                return

            # Process first page
            for msg in result.get_target_messages():
                counts[msg.author_id] += 1
                if msg.author_id not in author_names:
                    author_names[msg.author_id] = msg.author_name
            analyzed += len(result.get_target_messages())
            
            # Determine how many more pages to fetch
            # We want to fetch up to MAX_MESSAGES
            to_fetch = min(total_found, MAX_MESSAGES)
            
            # If there are more pages
            if to_fetch > analyzed:
                # Calculate number of pages needed
                current_offset = PAGE_SIZE
                while current_offset < to_fetch:
                    # Update status every 4 pages (100 messages)
                    if current_offset % 100 == 0:
                         await status_msg.edit(content=f"🔍 Analyzing messages... ({analyzed}/{to_fetch})")

                    page_result = await client.search_with_retry(
                        guild_id=str(ctx.guild.id),
                        content=word,
                        limit=PAGE_SIZE,
                        offset=current_offset
                    )
                    
                    messages = page_result.get_target_messages()
                    if not messages:
                        break
                        
                    for msg in messages:
                        counts[msg.author_id] += 1
                        if msg.author_id not in author_names:
                            author_names[msg.author_id] = msg.author_name
                    
                    analyzed += len(messages)
                    current_offset += PAGE_SIZE
                    
                    # Small delay to be respectful to the API
                    await asyncio.sleep(0.2)
            
            # Build Leaderboard
            top_users = counts.most_common(10)
            
            embed = discord.Embed(
                title=f"🏆 Top Users saying '{word}'",
                description=f"Total messages found: {total_found}\nAnalyzed: {analyzed} messages",
                color=discord.Color.gold()
            )
            
            for i, (auth_id, count) in enumerate(top_users, 1):
                name = author_names.get(auth_id, f"User {auth_id}")
                # Try to get member from guild for better name/display name
                member = ctx.guild.get_member(int(auth_id))
                if member:
                    name = member.display_name
                
                embed.add_field(
                    name=f"#{i} {name}",
                    value=f"{count} times",
                    inline=False
                )
            
            if analyzed < total_found:
                 embed.set_footer(text=f"Note: Only the most recent {analyzed} occurrences were analyzed.")

            await status_msg.edit(content=None, embed=embed)
            
        except SearchError as e:
            logger.error(f"Topword search error: {e}")
            await status_msg.edit(content=f"❌ Search failed: {e}")
        except Exception as e:
            logger.exception(f"Topword unexpected error: {e}")
            await status_msg.edit(content=f"❌ An error occurred: {e}")

    @search.error
    async def search_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Please provide a search query. Example: `!search images from @user`")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("❌ This command can only be used in a server.")
        else:
            logger.error(f"Search command error: {error}")
            await ctx.send(f"❌ An error occurred: {error}")
    
    def cog_unload(self):
        """Clean up when cog is unloaded."""
        if self.search_client:
            # Schedule cleanup
            asyncio.create_task(self.search_client.close())


async def setup(bot: commands.Bot):
    await bot.add_cog(Search(bot))
