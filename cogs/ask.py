"""
Ask Cog - AI-powered command with Discord search and media generation.

Ported from general.py with enhanced search + analysis capabilities.
Uses gemini-3-pro-preview for tool calling and analysis.
"""

import discord
from discord.ext import commands
import base64
import json
import io
import asyncio
import aiohttp
import logging
import os
from typing import Optional, List, Dict, Any, Tuple

from google import genai
from google.genai import types
from dotenv import load_dotenv

from utils.discord_search import DiscordSearchClient, SearchResult, SearchError, get_search_client
from shared import ROLE_ADMIN

logger = logging.getLogger('realbot')

load_dotenv()
API_KEY = os.getenv("API_KEY")
SUNO_API_KEY = os.getenv("SUNO_API_KEY")

# Initialize GenAI Client
try:
    genai_client = genai.Client(api_key=API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize GenAI client: {e}")
    genai_client = None

# Tool definitions for Gemini
TOOLS = [
    {
        "name": "search_discord",
        "description": """Searches for Discord messages. Can search the current server or other servers the user has access to.

IMPORTANT:
- Default searches the CURRENT SERVER and CURRENT CHANNEL
- To search a DIFFERENT SERVER, specify guild_id or guild_name (server name)
- The available servers list is provided in context - use partial name matching
- Default limit is 20 messages (use smaller limits for focused queries)

Use the various filters to narrow down results effectively.""",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "content": {"type": "STRING", "description": "Text to search for in messages. Max 1024 chars."},
                "author_id": {"type": "STRING", "description": "Filter by user ID. Get this from the context provided."},
                "guild_id": {"type": "STRING", "description": "Server/guild ID to search. Defaults to CURRENT server. Specify to search OTHER servers."},
                "guild_name": {"type": "STRING", "description": "Server name to search (case-insensitive partial match). Use this instead of guild_id for convenience."},
                "channel_id": {"type": "STRING", "description": "Channel ID to search. Defaults to CURRENT channel. Only specify if searching OTHER channels. Comma-separated for multiple."},
                "limit": {"type": "NUMBER", "description": "Number of messages to return. Default 20, max 500. Use larger limits (100-500) when user asks for extensive history or context."},
                "author_type": {"type": "STRING", "description": "Filter by author type: 'user', 'bot', or 'webhook'."},
                "has": {"type": "STRING", "description": "Filter by content type: 'image', 'video', 'file', 'link', 'embed', 'sticker', 'sound', 'poll'. Comma-separated for multiple."},
                "mentions": {"type": "STRING", "description": "Filter messages that mention a specific user ID."},
                "pinned": {"type": "BOOLEAN", "description": "If true, only return pinned messages."},
                "link_hostname": {"type": "STRING", "description": "Filter by URL hostname (e.g., 'github.com', 'youtube.com')."},
                "attachment_extension": {"type": "STRING", "description": "Filter by file extension (e.g., 'png', 'pdf', 'mp4')."},
                "sort_by": {"type": "STRING", "description": "'timestamp' (default) or 'relevance'. Use 'relevance' when searching by content."},
                "sort_order": {"type": "STRING", "description": "'desc' (newest first, default) or 'asc' (oldest first)."}
            },
            "required": []
        }
    },
    {
        "name": "generate_image",
        "description": "Generates a new image based on a detailed textual prompt.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "prompt_text": {"type": "STRING", "description": "The detailed, final prompt for image generation."},
            },
            "required": ["prompt_text"]
        }
    },
    {
        "name": "edit_image",
        "description": """Edits an existing image based on instructions. Use this when the user wants to modify/edit an attached image.

IMPORTANT:
- Use when user provides an image and asks to edit, modify, change, add to, or transform it
- Requires an attached image (check attachment context for the image URL)
- Provide clear edit instructions describing what to change
- Examples: "remove the background", "add a hat to the person", "make it look like winter", "change the color to blue\"""",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "edit_prompt": {"type": "STRING", "description": "Detailed instructions for how to edit the image."},
                "image_url": {"type": "STRING", "description": "URL of the image to edit (from attachment context)."},
            },
            "required": ["edit_prompt", "image_url"]
        }
    },
    {
        "name": "generate_video",
        "description": "Generates a short video based on a detailed textual prompt.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "prompt_text": {"type": "STRING", "description": "The detailed, final prompt for video generation."},
            },
            "required": ["prompt_text"]
        }
    },
    {
        "name": "generate_music",
        "description": "Generates music using Suno AI. Requires a title, style, and a prompt with lyrics or description.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "prompt": {"type": "STRING", "description": "The detailed lyrics or musical description. MUST be under 5000 characters."},
                "title": {"type": "STRING", "description": "The title of the music track."},
                "style": {"type": "STRING", "description": "Specific music style tags (e.g., 'Upbeat Pop', 'Lo-fi Hip Hop')."},
                "instrumental": {"type": "BOOLEAN", "description": "If true, generates an instrumental track (no vocals). Defaults to false."},
            },
            "required": ["prompt", "title", "style"]
        }
    },
    {
        "name": "fetch_url",
        "description": """Fetches content from a URL and returns the text. Use this to read web pages, articles, documentation, or any URL the user provides.

IMPORTANT:
- Use this when the user includes a URL and wants you to read/summarize/analyze it
- Returns the text content of the page (HTML converted to readable text)
- Works with most public web pages, articles, blog posts, docs, etc.
- May not work with pages requiring login or dynamic JavaScript-heavy sites""",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "The full URL to fetch (including https://)"},
            },
            "required": ["url"]
        }
    },
    {
        "name": "remove_background",
        "description": """Removes the background from an image, leaving only the subject with transparency.

IMPORTANT:
- Use when user asks to remove background, make transparent, isolate subject, etc.
- Requires an image URL (must be a direct link to PNG, JPG, or WEBP)
- If user provides an attachment, you'll get the URL from the attachment context
- Returns a PNG with transparent background
- Max 5MB, max 4096px dimension""",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "image_url": {"type": "STRING", "description": "Direct URL to the image (PNG, JPG, or WEBP)"},
            },
            "required": ["image_url"]
        }
    },
    {
        "name": "upscale_image",
        "description": """Upscales an image to higher resolution using AI enhancement.

IMPORTANT:
- Use when user asks to upscale, enhance, increase resolution, make bigger/clearer, etc.
- Requires an image URL (must be a direct link to PNG, JPG, or WEBP)
- If user provides an attachment, you'll get the URL from the attachment context
- Returns a higher resolution version of the image
- Max 10MB input""",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "image_url": {"type": "STRING", "description": "Direct URL to the image (PNG, JPG, or WEBP)"},
            },
            "required": ["image_url"]
        }
    },
    {
        "name": "generate_sound_effect",
        "description": """Generates a sound effect based on a text description using ElevenLabs AI.

IMPORTANT:
- Use when user asks for sound effects, audio clips, foley sounds, ambient sounds, etc.
- Describe the sound in detail for best results (e.g., "heavy rain on a metal roof with distant thunder")
- Duration: 0.5-22 seconds (auto-determined if not specified)
- Can create looping sounds for ambient/background use
- Prompt influence controls how closely to follow the description (higher = more literal)""",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text": {"type": "STRING", "description": "Detailed description of the sound effect to generate"},
                "duration_seconds": {"type": "NUMBER", "description": "Duration in seconds (0.5-22). Leave empty for auto duration."},
                "loop": {"type": "BOOLEAN", "description": "If true, creates a seamlessly looping sound. Good for ambient/background sounds. Default false."},
                "prompt_influence": {"type": "NUMBER", "description": "How closely to follow the prompt (0.0-1.0). Higher = more literal interpretation. Default 0.3."},
            },
            "required": ["text"]
        }
    },
    {
        "name": "get_user_avatars",
        "description": """Gets avatar URLs for one or more Discord users. Use this when you need user profile pictures for image generation.

IMPORTANT:
- Use BEFORE generating images that should include or reference specific users
- Returns direct URLs to Discord avatars for each user that you can describe or use as reference
- User IDs are provided in context (mentioned users) or from search results
- Can fetch multiple users in one call for efficiency
- The returned avatar URLs can be fetched and included as reference images for generation""",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_ids": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Array of Discord user IDs to get avatars for."},
            },
            "required": ["user_ids"]
        }
    }
]

SYSTEM_PROMPT = """You are a helpful AI assistant integrated into Discord with access to powerful search and generation tools.

## SEARCH GUIDELINES (CRITICAL):
1. **Default to current channel**: Unless the user explicitly asks about other channels, ALWAYS search only the current channel.
2. **Match user's requested scope**: If user asks for "last 100 messages" or "extensive history", use limit=100 or more. For quick queries, use limit=20-50.
3. **Use filters**: When searching for a specific user's messages, ALWAYS use author_id. The user IDs are provided in the context.
4. **Be specific**: Use content search, author filters, and other parameters to get relevant results.

## Available search_discord filters:
- content: Text to search for
- author_id: Filter by specific user (USE THIS when asked about what someone said)
- channel_id: Only specify if searching DIFFERENT channels (current channel is default)
- limit: Number of results (default 50, max 500). Use 100-300 for thorough analysis, 50-100 for normal queries.
- has: Filter by attachments (image, video, file, link, embed)
- author_type: Filter by user/bot/webhook
- pinned: Only pinned messages
- link_hostname: Filter by URL domain
- sort_by: 'timestamp' or 'relevance'

## WORKFLOW:
1. For "what did @user say" queries → use author_id filter with limit=50-100
2. For "last N messages" → use limit=N in current channel (up to 500)
3. For thorough analysis/roasts → use limit=100-300 for comprehensive context
4. For channel comparisons → search each channel separately with channel_id
5. Always analyze results and provide insightful summaries

Provide helpful, accurate, and insightful responses based on the data you gather."""


class AskCog(commands.Cog):
    """AI-powered ask command with Discord search and media generation."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.search_client: Optional[DiscordSearchClient] = None
        self._load_ask_users()
        logger.info("Ask cog initialized")
    
    def is_admin(self, member: discord.Member) -> bool:
        """Check if user has admin role, is a bot admin, or has ask permission."""
        has_role = any(role.id == ROLE_ADMIN for role in member.roles)
        is_bot_admin = hasattr(self.bot, 'bot_admins') and member.id in self.bot.bot_admins
        has_ask_perm = hasattr(self.bot, 'ask_users') and member.id in self.bot.ask_users
        return has_role or is_bot_admin or has_ask_perm
    
    def _load_ask_users(self):
        """Load ask_users from file."""
        if not hasattr(self.bot, 'ask_users'):
            self.bot.ask_users = set()
        try:
            with open('ask_users.json', 'r') as f:
                users = json.load(f)
                self.bot.ask_users.update(int(x) for x in users)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Failed to load ask_users: {e}")
    
    def _save_ask_users(self):
        """Save ask_users to file."""
        try:
            with open('ask_users.json', 'w') as f:
                json.dump(list(self.bot.ask_users), f)
        except Exception as e:
            logger.error(f"Failed to save ask_users: {e}")
    
    @commands.command(name="addask")
    @commands.is_owner()
    async def addask(self, ctx, user: discord.Member):
        """[Owner Only] Give a user permission to use !ask."""
        if not hasattr(self.bot, 'ask_users'):
            self.bot.ask_users = set()
        
        if user.id in self.bot.ask_users:
            await ctx.send(f"{user.mention} already has !ask permission.")
            return
        
        self.bot.ask_users.add(user.id)
        self._save_ask_users()
        await ctx.send(f"✅ {user.mention} can now use !ask.")
    
    @commands.command(name="removeask")
    @commands.is_owner()
    async def removeask(self, ctx, user: discord.Member):
        """[Owner Only] Remove a user's permission to use !ask."""
        if not hasattr(self.bot, 'ask_users'):
            self.bot.ask_users = set()
        
        if user.id not in self.bot.ask_users:
            await ctx.send(f"{user.mention} doesn't have !ask permission.")
            return
        
        self.bot.ask_users.discard(user.id)
        self._save_ask_users()
        await ctx.send(f"✅ Removed !ask permission from {user.mention}.")
    
    @commands.command(name="listask")
    @commands.is_owner()
    async def listask(self, ctx):
        """[Owner Only] List users with !ask permission."""
        if not hasattr(self.bot, 'ask_users') or not self.bot.ask_users:
            await ctx.send("No users have !ask permission.")
            return
        
        mentions = []
        for uid in self.bot.ask_users:
            user = self.bot.get_user(uid)
            if user:
                mentions.append(f"- {user.mention} (`{uid}`)")
            else:
                mentions.append(f"- *Unknown* (`{uid}`)")
        
        await ctx.send(f"**Users with !ask permission:**\n" + "\n".join(mentions))
    
    def _get_search_client(self) -> DiscordSearchClient:
        """Get the search client (uses USER_TOKEN from utils/discord_search.py)."""
        if self.search_client is None:
            # Use the singleton from discord_search which has USER_TOKEN configured
            self.search_client = get_search_client()
        return self.search_client
    
    async def _retry_api_call(self, func, *args, timeout: int = 60, **kwargs):
        """Execute an API call with retry logic for 503 and 429 errors."""
        max_retries = 3
        base_delay = 2
        
        for attempt in range(max_retries):
            try:
                loop = asyncio.get_running_loop()
                return await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: func(*args, **kwargs)),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"API call timed out after {timeout}s")
                if attempt < max_retries - 1:
                    continue
                raise
            except Exception as e:
                error_msg = str(e)
                is_retryable = False
                
                if "503" in error_msg or "UNAVAILABLE" in error_msg:
                    is_retryable = True
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.info(f"API unavailable (503), retrying in {delay}s...")
                        await asyncio.sleep(delay)
                elif "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    is_retryable = True
                    if attempt < max_retries - 1:
                        delay = base_delay * (4 ** attempt)
                        logger.info(f"Rate limited (429), retrying in {delay}s...")
                        await asyncio.sleep(delay)
                
                if not is_retryable or attempt == max_retries - 1:
                    raise e
    
    async def _call_gemini_with_tools(self, messages: List[Dict]) -> Optional[Dict]:
        """Call Gemini API with tools and return response in dict format."""
        if not genai_client:
            return None
        
        try:
            tools_obj = [types.Tool(function_declarations=TOOLS)]
            
            response = await self._retry_api_call(
                genai_client.models.generate_content,
                model="gemini-3-pro-preview",
                contents=messages,
                config=types.GenerateContentConfig(
                    tools=tools_obj,
                    temperature=0.7
                )
            )
            
            # Convert to legacy dict format for compatibility
            candidates_list = []
            for cand in response.candidates:
                parts_list = []
                for part in cand.content.parts:
                    part_dict = {}
                    if part.text:
                        part_dict["text"] = part.text
                    if part.function_call:
                        part_dict["functionCall"] = {
                            "name": part.function_call.name,
                            "args": dict(part.function_call.args)
                        }
                    # Include thoughtSignature - critical for Gemini 3 Pro function calling
                    if hasattr(part, 'thought_signature') and part.thought_signature:
                        part_dict["thoughtSignature"] = part.thought_signature
                    parts_list.append(part_dict)
                    
                candidates_list.append({
                    "content": {
                        "role": cand.content.role,
                        "parts": parts_list
                    }
                })
            
            return {"candidates": candidates_list}
        
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None
    
    async def _call_gemini_streaming(
        self,
        messages: List[Dict],
        output_message: discord.Message,
        ctx: commands.Context
    ) -> Optional[Dict]:
        """
        Call Gemini API with streaming, updating Discord message in real-time.
        Returns the final response in dict format for tool handling.
        Properly handles thought_signature for Gemini 3 Pro function calling.
        """
        if not genai_client:
            return None
        
        try:
            tools_obj = [types.Tool(function_declarations=TOOLS)]
            loop = asyncio.get_running_loop()
            
            # Run streaming in executor since SDK is sync
            def run_stream():
                return genai_client.models.generate_content_stream(
                    model="gemini-3-pro-preview",
                    contents=messages,
                    config=types.GenerateContentConfig(
                        tools=tools_obj,
                        temperature=0.7
                    )
                )
            
            stream = await loop.run_in_executor(None, run_stream)
            
            accumulated_text = ""
            function_calls_with_signatures = []  # Store function calls with their signatures
            last_update = 0
            update_interval = 0.5  # Update every 0.5 seconds
            role = "model"
            last_thought_signature = None  # Track thought signature for text parts
            
            # Track time for rate-limited updates
            import time
            
            for chunk in stream:
                if chunk.candidates:
                    for cand in chunk.candidates:
                        if cand.content:
                            role = cand.content.role
                            for part in cand.content.parts:
                                if part.text:
                                    accumulated_text += part.text
                                    
                                    # Capture thought_signature from text parts too
                                    if hasattr(part, 'thought_signature') and part.thought_signature:
                                        last_thought_signature = part.thought_signature
                                    
                                    # Update message periodically to avoid rate limits
                                    current_time = time.time()
                                    if current_time - last_update > update_interval:
                                        display_text = accumulated_text[:1990] + "..." if len(accumulated_text) > 1990 else accumulated_text
                                        if display_text.strip():
                                            try:
                                                await output_message.edit(content=display_text)
                                            except discord.HTTPException:
                                                pass  # Rate limited, skip this update
                                        last_update = current_time
                                
                                if part.function_call:
                                    fc_entry = {
                                        "name": part.function_call.name,
                                        "args": dict(part.function_call.args)
                                    }
                                    # Capture thought_signature - critical for Gemini 3 Pro
                                    if hasattr(part, 'thought_signature') and part.thought_signature:
                                        fc_entry["thought_signature"] = part.thought_signature
                                    function_calls_with_signatures.append(fc_entry)
            
            # Final update with complete text
            if accumulated_text.strip():
                # Handle pagination for long responses
                if len(accumulated_text) > 2000:
                    pages = [accumulated_text[i:i+2000] for i in range(0, len(accumulated_text), 2000)]
                    await output_message.edit(content=pages[0])
                    for page in pages[1:]:
                        await ctx.send(page)
                else:
                    await output_message.edit(content=accumulated_text)
            
            # Build response parts with proper thought_signature preservation
            full_parts = []
            if accumulated_text:
                text_part = {"text": accumulated_text}
                if last_thought_signature:
                    text_part["thoughtSignature"] = last_thought_signature
                full_parts.append(text_part)
            
            for fc in function_calls_with_signatures:
                fc_part = {
                    "functionCall": {
                        "name": fc["name"],
                        "args": fc["args"]
                    }
                }
                # Include thought_signature if present (critical for Gemini 3 Pro)
                if "thought_signature" in fc:
                    fc_part["thoughtSignature"] = fc["thought_signature"]
                full_parts.append(fc_part)
            
            if not full_parts:
                return None
            
            return {
                "candidates": [{
                    "content": {
                        "role": role,
                        "parts": full_parts
                    }
                }]
            }
        
        except Exception as e:
            logger.error(f"Gemini streaming error: {e}")
            return None
    
    async def _execute_search(
        self,
        guild_id: str,
        channel_id: Optional[str] = None,
        author_id: Optional[str] = None,
        content: Optional[str] = None,
        limit: int = 20,
        author_type: Optional[str] = None,
        has: Optional[str] = None,
        mentions: Optional[str] = None,
        pinned: Optional[bool] = None,
        link_hostname: Optional[str] = None,
        attachment_extension: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None
    ) -> Tuple[str, List[Dict]]:
        """Execute Discord search and return formatted results."""
        print(f"\n=== ASK.PY _execute_search CALLED ===")
        print(f"guild_id={guild_id}, channel_id={channel_id}, author_id={author_id}")
        try:
            client = self._get_search_client()
            print(f"Search client: {client}")
            print(f"Client headers: {client.headers}")
            
            params = {
                "sort_by": sort_by or "timestamp",
                "sort_order": sort_order or "desc",
                "limit": min(25, limit)  # API max is 25 per request
            }
            
            # Handle multi-channel search
            if channel_id:
                channel_ids = [c.strip() for c in channel_id.split(",")]
                params["channel_id"] = channel_ids
            
            if author_id:
                params["author_id"] = [author_id]
            
            if content:
                params["content"] = content
            
            # Handle new parameters
            if author_type:
                params["author_type"] = [author_type]
            
            if has:
                # Handle comma-separated values
                has_values = [h.strip() for h in has.split(",")]
                params["has"] = has_values
            
            if mentions:
                params["mentions"] = [mentions]
            
            if pinned is not None:
                params["pinned"] = pinned
            
            if link_hostname:
                hostnames = [h.strip() for h in link_hostname.split(",")]
                params["link_hostname"] = hostnames
            
            if attachment_extension:
                extensions = [e.strip() for e in attachment_extension.split(",")]
                params["attachment_extension"] = extensions
            
            # Paginate if limit > 25
            all_messages = []
            remaining = min(limit, 500)  # Cap at 500
            offset = 0
            page = 0
            total_available = None
            
            logger.info(f"Discord search: requesting up to {remaining} messages")
            
            while remaining > 0:
                params["limit"] = min(25, remaining)
                params["offset"] = offset
                page += 1
                
                result = await client.search_with_retry(guild_id, **params)
                targets = result.get_target_messages()
                
                # Track total available results
                if total_available is None:
                    total_available = result.total_results
                    logger.info(f"Discord search: {total_available} total results available")
                
                if not targets:
                    logger.info(f"Discord search: no more results at page {page} (offset {offset})")
                    break
                
                all_messages.extend(targets)
                remaining -= len(targets)
                offset += len(targets)  # Use actual returned count for offset
                
                logger.info(f"Discord search: page {page} returned {len(targets)} messages (total: {len(all_messages)}, remaining: {remaining})")
                
                # Only stop if we've fetched everything available
                if len(all_messages) >= total_available:
                    logger.info(f"Discord search: fetched all {total_available} available results")
                    break
                
                await asyncio.sleep(0.3)  # Rate limit respect
            
            # Format messages for context
            message_lines = []
            avatars = {}  # Dict mapping user_id -> {username, avatar_url}
            
            for msg in reversed(all_messages):  # Chronological order
                message_lines.append(f"{msg.author_name}: {msg.content}")
                
                # Track unique authors and their avatars
                if msg.author_id not in avatars:
                    avatars[msg.author_id] = {
                        "username": msg.author_name,
                        "avatar_url": msg.get_avatar_url()
                    }
            
            return "\n".join(message_lines), avatars
        
        except SearchError as e:
            logger.error(f"Search error: {e}")
            return f"Search failed: {e}", []
        except Exception as e:
            logger.error(f"Unexpected search error: {e}")
            return f"Search error: {e}", []
    
    async def _generate_image(self, prompt: str, reference_images: List[Tuple[str, str]] = None) -> Optional[io.BytesIO]:
        """Generate an image using Gemini."""
        if not genai_client:
            return None
        
        try:
            contents = []
            
            # Add reference images if provided
            if reference_images:
                for mime_type, data in reference_images[:3]:  # Max 3 reference images
                    contents.append(types.Part.from_bytes(
                        data=base64.b64decode(data),
                        mime_type=mime_type
                    ))
            
            # Add the prompt
            contents.append(prompt)
            
            loop = asyncio.get_running_loop()
            
            def run_generation():
                return genai_client.models.generate_content(
                    model="gemini-3-pro-image-preview",
                    contents=contents
                )
            
            response = await loop.run_in_executor(None, run_generation)
            
            if response.candidates:
                for cand in response.candidates:
                    for part in cand.content.parts:
                        if part.inline_data and part.inline_data.data:
                            data = part.inline_data.data
                            if isinstance(data, bytes):
                                return io.BytesIO(data)
                            elif isinstance(data, str):
                                return io.BytesIO(base64.b64decode(data))
            
            return None
        
        except Exception as e:
            logger.error(f"Image generation error: {e}")
            return None
    
    async def _edit_image(self, image_data: Tuple[str, str], edit_prompt: str) -> Optional[io.BytesIO]:
        """Edit an image using Gemini. Takes (mime_type, base64_data) tuple and edit instructions."""
        if not genai_client:
            return None
        
        try:
            mime_type, data = image_data
            
            contents = [
                types.Part.from_bytes(
                    data=base64.b64decode(data),
                    mime_type=mime_type
                ),
                edit_prompt
            ]
            
            loop = asyncio.get_running_loop()
            
            def run_edit():
                return genai_client.models.generate_content(
                    model="gemini-3-pro-image-preview",
                    contents=contents
                )
            
            response = await loop.run_in_executor(None, run_edit)
            
            if response.candidates:
                for cand in response.candidates:
                    for part in cand.content.parts:
                        if part.inline_data and part.inline_data.data:
                            result_data = part.inline_data.data
                            if isinstance(result_data, bytes):
                                return io.BytesIO(result_data)
                            elif isinstance(result_data, str):
                                return io.BytesIO(base64.b64decode(result_data))
            
            return None
        
        except Exception as e:
            logger.error(f"Image edit error: {e}")
            return None
    
    async def _generate_video(self, prompt: str, status_message: discord.Message) -> Optional[io.BytesIO]:
        """Generate a video using Veo."""
        if not genai_client:
            return None
        
        try:
            await status_message.edit(content=f"**Prompt:** {prompt}\n\n> Sending video generation request...")
            
            def run_generation():
                return genai_client.models.generate_videos(
                    model="veo-3.1-generate-preview",
                    prompt=prompt
                )
            
            operation = await self._retry_api_call(run_generation)
            
            await status_message.edit(content=f"**Prompt:** {prompt}\n\n> Video generation started. Polling for results...")
            
            while not operation.done:
                await asyncio.sleep(10)
                operation = await self._retry_api_call(genai_client.operations.get, operation)
            
            if operation.error:
                await status_message.edit(content=f"> Video generation failed: {operation.error}")
                return None
            
            video_result = operation.response.generated_videos[0]
            
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
                tmp_vid_path = tmp_vid.name
            
            loop = asyncio.get_running_loop()
            
            def save_video():
                video_bytes = genai_client.files.download(file=video_result.video)
                with open(tmp_vid_path, "wb") as f:
                    f.write(video_bytes)
            
            await loop.run_in_executor(None, save_video)
            
            with open(tmp_vid_path, "rb") as f:
                video_bytes = f.read()
            
            os.remove(tmp_vid_path)
            return io.BytesIO(video_bytes)
        
        except Exception as e:
            logger.error(f"Video generation error: {e}")
            await status_message.edit(content=f"> Video generation error: {e}")
            return None
    
    async def _generate_music(self, prompt: str, title: str, style: str, instrumental: bool = False) -> Optional[List[Dict]]:
        """Generate music using Suno AI via kie.ai."""
        suno_key = SUNO_API_KEY
        if not suno_key:
            logger.error("SUNO_API_KEY not set")
            return None
        
        url = "https://api.kie.ai/api/v1/generate"
        headers = {
            "Authorization": f"Bearer {suno_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "title": title,
            "prompt": prompt[:5000],
            "tags": style,
            "customMode": True,
            "instrumental": instrumental,
            "model": "V5",
            "callBackUrl": "https://example.com/callback"
        }
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                result = await response.json()
                
                if result.get('code') != 200:
                    logger.error(f"Suno API Error: {result.get('msg')}")
                    return None
                
                task_id = result['data']['taskId']
                status_url = f"https://api.kie.ai/api/v1/generate/record-info?taskId={task_id}"
                
                for _ in range(60):  # 5 minutes timeout
                    await asyncio.sleep(5)
                    status_resp = await client.get(status_url, headers=headers)
                    status_resp.raise_for_status()
                    status_data = await status_resp.json()
                    
                    if status_data.get('code') != 200:
                        return None
                    
                    task_state = status_data['data']['status']
                    
                    if task_state in ['SUCCESS', 'FIRST_SUCCESS']:
                        suno_data = status_data['data']['response']['sunoData']
                        tracks = []
                        for track in suno_data:
                            if track.get('audioUrl'):
                                tracks.append({
                                    "audio_url": track['audioUrl'],
                                    "image_url": track.get('imageUrl'),
                                    "title": track.get('title', 'Untitled'),
                                    "prompt": track.get('prompt')
                                })
                        return tracks if tracks else None
                    
                    elif task_state in ['CREATE_TASK_FAILED', 'GENERATE_AUDIO_FAILED', 'SENSITIVE_WORD_ERROR']:
                        return None
                
                return None
            
            except Exception as e:
                logger.error(f"Music generation error: {e}")
                return None
    
    async def _fetch_url(self, url: str) -> str:
        """Fetch content from a URL and convert HTML to readable text."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(url, headers=headers, allow_redirects=True) as response:
                    if response.status != 200:
                        return f"Error: HTTP {response.status} - Could not fetch URL"
                    
                    content_type = response.headers.get('Content-Type', '')
                    
                    # Handle non-HTML content
                    if 'application/json' in content_type:
                        import json
                        text = await response.text()
                        try:
                            data = json.loads(text)
                            return json.dumps(data, indent=2)[:50000]  # Limit JSON size
                        except:
                            return text[:50000]
                    
                    if 'text/plain' in content_type:
                        text = await response.text()
                        return text[:50000]
                    
                    # Parse HTML
                    html = await response.text()
                    
                    # Try to use BeautifulSoup if available
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Remove script and style elements
                        for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                            element.decompose()
                        
                        # Get text
                        text = soup.get_text(separator='\n', strip=True)
                        
                        # Clean up whitespace
                        lines = [line.strip() for line in text.splitlines() if line.strip()]
                        text = '\n'.join(lines)
                        
                        return text[:50000]  # Limit to ~50k chars
                    except ImportError:
                        # Fallback: basic HTML stripping
                        import re
                        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                        text = re.sub(r'<[^>]+>', ' ', text)
                        text = re.sub(r'\s+', ' ', text).strip()
                        return text[:50000]
        
        except asyncio.TimeoutError:
            return "Error: Request timed out after 30 seconds"
        except aiohttp.ClientError as e:
            return f"Error: Failed to fetch URL - {str(e)}"
        except Exception as e:
            logger.error(f"URL fetch error: {e}")
            return f"Error: {str(e)}"
    
    async def _remove_background(self, image_url: str) -> Optional[str]:
        """Remove background from an image using kie.ai API. Returns URL of result image."""
        api_key = SUNO_API_KEY  # Same API key as Suno (kie.ai)
        if not api_key:
            logger.error("SUNO_API_KEY not set (needed for kie.ai API)")
            return None
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Create task
        create_url = "https://api.kie.ai/api/v1/jobs/createTask"
        payload = {
            "model": "recraft/remove-background",
            "input": {
                "image": image_url
            }
        }
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as client:
            try:
                # Create the task
                response = await client.post(create_url, json=payload, headers=headers)
                response.raise_for_status()
                result = await response.json()
                
                if result.get('code') != 200:
                    logger.error(f"Background removal task creation failed: {result.get('msg')}")
                    return None
                
                task_id = result['data']['taskId']
                logger.info(f"Background removal task created: {task_id}")
                
                # Poll for results
                status_url = f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}"
                
                for attempt in range(60):  # 5 minute timeout (60 * 5 seconds)
                    await asyncio.sleep(5)
                    
                    status_resp = await client.get(status_url, headers=headers)
                    status_resp.raise_for_status()
                    status_data = await status_resp.json()
                    
                    if status_data.get('code') != 200:
                        logger.error(f"Background removal status check failed: {status_data.get('msg')}")
                        return None
                    
                    state = status_data['data'].get('state')
                    
                    if state == 'success':
                        # Parse the result JSON
                        import json
                        result_json = status_data['data'].get('resultJson', '{}')
                        result_data = json.loads(result_json)
                        result_urls = result_data.get('resultUrls', [])
                        
                        if result_urls:
                            logger.info(f"Background removal complete: {result_urls[0]}")
                            return result_urls[0]
                        else:
                            logger.error("Background removal succeeded but no result URL")
                            return None
                    
                    elif state == 'fail':
                        fail_msg = status_data['data'].get('failMsg', 'Unknown error')
                        logger.error(f"Background removal failed: {fail_msg}")
                        return None
                    
                    # Still waiting, continue polling
                    logger.debug(f"Background removal status: {state} (attempt {attempt + 1})")
                
                logger.error("Background removal timed out after 5 minutes")
                return None
                
            except Exception as e:
                logger.error(f"Background removal error: {e}")
                return None
    
    async def _upscale_image(self, image_url: str) -> Optional[str]:
        """Upscale an image using kie.ai API. Returns URL of result image."""
        api_key = SUNO_API_KEY  # Same API key as Suno (kie.ai)
        if not api_key:
            logger.error("SUNO_API_KEY not set (needed for kie.ai API)")
            return None
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Create task
        create_url = "https://api.kie.ai/api/v1/jobs/createTask"
        payload = {
            "model": "recraft/crisp-upscale",
            "input": {
                "image": image_url
            }
        }
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as client:
            try:
                # Create the task
                response = await client.post(create_url, json=payload, headers=headers)
                response.raise_for_status()
                result = await response.json()
                
                if result.get('code') != 200:
                    logger.error(f"Upscale task creation failed: {result.get('msg')}")
                    return None
                
                task_id = result['data']['taskId']
                logger.info(f"Upscale task created: {task_id}")
                
                # Poll for results
                status_url = f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}"
                
                for attempt in range(60):  # 5 minute timeout
                    await asyncio.sleep(5)
                    
                    status_resp = await client.get(status_url, headers=headers)
                    status_resp.raise_for_status()
                    status_data = await status_resp.json()
                    
                    if status_data.get('code') != 200:
                        logger.error(f"Upscale status check failed: {status_data.get('msg')}")
                        return None
                    
                    state = status_data['data'].get('state')
                    
                    if state == 'success':
                        import json
                        result_json = status_data['data'].get('resultJson', '{}')
                        result_data = json.loads(result_json)
                        result_urls = result_data.get('resultUrls', [])
                        
                        if result_urls:
                            logger.info(f"Upscale complete: {result_urls[0]}")
                            return result_urls[0]
                        else:
                            logger.error("Upscale succeeded but no result URL")
                            return None
                    
                    elif state == 'fail':
                        fail_msg = status_data['data'].get('failMsg', 'Unknown error')
                        logger.error(f"Upscale failed: {fail_msg}")
                        return None
                    
                    logger.debug(f"Upscale status: {state} (attempt {attempt + 1})")
                
                logger.error("Upscale timed out after 5 minutes")
                return None
                
            except Exception as e:
                logger.error(f"Upscale error: {e}")
                return None
    
    async def _generate_sound_effect(self, text: str, duration_seconds: Optional[float] = None, loop: bool = False, prompt_influence: float = 0.3) -> Optional[str]:
        """Generate a sound effect using ElevenLabs via kie.ai API. Returns URL of result audio."""
        api_key = SUNO_API_KEY  # Same API key (kie.ai)
        if not api_key:
            logger.error("SUNO_API_KEY not set (needed for kie.ai API)")
            return None
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Create task
        create_url = "https://api.kie.ai/api/v1/jobs/createTask"
        
        input_params = {
            "text": text[:5000],  # Max 5000 chars
            "loop": loop,
            "prompt_influence": max(0.0, min(1.0, prompt_influence)),  # Clamp 0-1
            "output_format": "mp3_44100_128"
        }
        
        if duration_seconds is not None:
            # Clamp to valid range
            input_params["duration_seconds"] = max(0.5, min(22, duration_seconds))
        
        payload = {
            "model": "elevenlabs/sound-effect-v2",
            "input": input_params
        }
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as client:
            try:
                # Create the task
                response = await client.post(create_url, json=payload, headers=headers)
                response.raise_for_status()
                result = await response.json()
                
                if result.get('code') != 200:
                    logger.error(f"Sound effect task creation failed: {result.get('msg')}")
                    return None
                
                task_id = result['data']['taskId']
                logger.info(f"Sound effect task created: {task_id}")
                
                # Poll for results
                status_url = f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}"
                
                for attempt in range(60):  # 5 minute timeout
                    await asyncio.sleep(5)
                    
                    status_resp = await client.get(status_url, headers=headers)
                    status_resp.raise_for_status()
                    status_data = await status_resp.json()
                    
                    if status_data.get('code') != 200:
                        logger.error(f"Sound effect status check failed: {status_data.get('msg')}")
                        return None
                    
                    state = status_data['data'].get('state')
                    
                    if state == 'success':
                        import json
                        result_json = status_data['data'].get('resultJson', '{}')
                        result_data = json.loads(result_json)
                        result_urls = result_data.get('resultUrls', [])
                        
                        if result_urls:
                            logger.info(f"Sound effect complete: {result_urls[0]}")
                            return result_urls[0]
                        else:
                            logger.error("Sound effect succeeded but no result URL")
                            return None
                    
                    elif state == 'fail':
                        fail_msg = status_data['data'].get('failMsg', 'Unknown error')
                        logger.error(f"Sound effect failed: {fail_msg}")
                        return None
                    
                    logger.debug(f"Sound effect status: {state} (attempt {attempt + 1})")
                
                logger.error("Sound effect timed out after 5 minutes")
                return None
                
            except Exception as e:
                logger.error(f"Sound effect error: {e}")
                return None
    
    @commands.command(name="ask")
    @commands.guild_only()
    async def ask(self, ctx: commands.Context, *, prompt_text: str = ""):
        """
        Ask Gemini a question with access to Discord search and media generation.
        
        Examples:
          !ask what has @user been talking about?
          !ask summarize the last 20 messages
          !ask compare the tone in #general vs #random
          !ask generate an image of a sunset
        """
        # Admin-only check
        if not self.is_admin(ctx.author):
            await ctx.send("❌ This command is admin-only.")
            return
        
        message = ctx.message
        attachments_to_process = []
        encoded_attachments = []
        
        # Check for attachments in replied-to message
        if message.reference and message.reference.message_id:
            try:
                replied_message = await message.channel.fetch_message(message.reference.message_id)
                if replied_message.attachments:
                    attachments_to_process.extend(replied_message.attachments)
            except (discord.NotFound, discord.Forbidden):
                pass
        
        # Check for attachments in command message
        if message.attachments:
            attachments_to_process.extend(message.attachments)
        
        if not prompt_text and not attachments_to_process:
            await ctx.send("> Please provide a prompt or an attachment.")
            return
        
        status_message = await ctx.send("> 🤔 Thinking...")
        
        # Process attachments
        for att in attachments_to_process:
            try:
                content_type = att.content_type or ""
                if not (content_type.startswith("image/") or content_type.startswith("audio/")):
                    continue
                
                file_bytes = await att.read()
                
                if content_type.lower() in ['image/heic', 'image/heif']:
                    from PIL import Image
                    img = Image.open(io.BytesIO(file_bytes))
                    output_buffer = io.BytesIO()
                    img.save(output_buffer, format='JPEG')
                    file_bytes = output_buffer.getvalue()
                    content_type = 'image/jpeg'
                
                encoded_string = base64.b64encode(file_bytes).decode('utf-8')
                encoded_attachments.append((content_type, encoded_string))
            
            except Exception as e:
                logger.warning(f"Failed to process attachment {att.filename}: {e}")
        
        # State for conversation loop
        gathered_images = list(encoded_attachments)
        
        # Fetch available guilds for cross-server search
        from utils.discord_search import fetch_available_guilds, get_guild_names_for_context
        await fetch_available_guilds()  # Pre-fetch and cache guilds
        guilds_context = get_guild_names_for_context()
        
        context_info = f"Current Server: {ctx.guild.name} (ID: {ctx.guild.id})\nCurrent Channel: #{ctx.channel.name} (ID: {ctx.channel.id})\nUser: {ctx.author.name} (ID: {ctx.author.id})\n\n{guilds_context}"
        
        # Build initial conversation
        conversation_history = [
            {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
            {"role": "user", "parts": [{"text": context_info}]},
        ]
        
        # Add user mentions context with avatar URLs
        if ctx.message.mentions:
            mentions_info = "Mentioned users (with avatar URLs for image generation):\n" + "\n".join(
                f"- {u.name}: ID {u.id}, Avatar: {u.display_avatar.url}" for u in ctx.message.mentions
            )
            conversation_history.append({"role": "user", "parts": [{"text": mentions_info}]})
        
        if ctx.message.channel_mentions:
            channel_info = "Mentioned channels:\n" + "\n".join(
                f"- #{c.name}: ID {c.id}" for c in ctx.message.channel_mentions
            )
            conversation_history.append({"role": "user", "parts": [{"text": channel_info}]})
        
        # Add attachment URLs for tools like remove_background
        if attachments_to_process:
            attachment_info = "Attached images (use these URLs with remove_background or other image tools):\n" + "\n".join(
                f"- {att.filename}: {att.url}" for att in attachments_to_process 
                if att.content_type and att.content_type.startswith("image/")
            )
            if "- " in attachment_info:  # Only add if there are actual image attachments
                conversation_history.append({"role": "user", "parts": [{"text": attachment_info}]})
        
        # Build user turn
        user_parts = []
        if prompt_text:
            user_parts.append({"text": prompt_text})
        
        for mime_type, data in encoded_attachments:
            user_parts.append({"inlineData": {"mimeType": mime_type, "data": data}})
        
        conversation_history.append({"role": "user", "parts": user_parts})
        
        # Interaction loop
        MAX_LOOPS = 5
        
        for loop_count in range(MAX_LOOPS):
            # Use streaming for text responses (updates message in real-time)
            response = await self._call_gemini_streaming(conversation_history, status_message, ctx)
            
            if not response or not response.get("candidates"):
                await status_message.edit(content="> ❌ No response received from Gemini.")
                return
            
            candidate = response.get("candidates", [])[0]
            model_content = candidate.get("content")
            
            if not model_content:
                break
            
            conversation_history.append(model_content)
            
            # Process parts - text already sent via streaming
            text_parts = []
            function_calls = []
            
            for part in model_content.get("parts", []):
                if "text" in part:
                    text_parts.append(part["text"])
                if "functionCall" in part:
                    function_calls.append(part["functionCall"])
            
            # Text was already sent via streaming, just track if we had text
            has_text = bool(text_parts)
            
            if not function_calls:
                # No tools to call, we're done
                if has_text:
                    status_message = None  # Already used for text output
                break
            
            # Execute tools
            tool_outputs = []
            extra_user_messages = []
            generation_completed = False
            
            # If we had text output via streaming, the status_message was used for it
            # Create a new status message for tool execution
            if has_text:
                status_message = await ctx.send(f"> ⚙️ Executing tools...")
            
            for func_call in function_calls:
                tool_name = func_call["name"]
                args = func_call["args"]
                
                if status_message:
                    await status_message.edit(content=f"> ⚙️ Executing `{tool_name}`...")
                else:
                    status_message = await ctx.send(f"> ⚙️ Executing `{tool_name}`...")
                
                if tool_name == "search_discord":
                    # Handle guild_id - can be specified directly or via guild_name
                    search_guild_id = args.get("guild_id")
                    guild_name = args.get("guild_name")
                    
                    if guild_name and not search_guild_id:
                        # Look up guild by name
                        from utils.discord_search import lookup_guild_by_name
                        guild = await lookup_guild_by_name(guild_name)
                        if guild:
                            search_guild_id = guild['id']
                            logger.info(f"Resolved guild_name '{guild_name}' to {guild['name']} (ID: {search_guild_id})")
                        else:
                            # Guild not found, report error
                            tool_outputs.append({
                                "functionResponse": {
                                    "name": tool_name,
                                    "response": {
                                        "status": "error",
                                        "error": f"Could not find server matching '{guild_name}'"
                                    }
                                }
                            })
                            continue
                    
                    if not search_guild_id:
                        # Default to current guild
                        search_guild_id = str(ctx.guild.id)
                    
                    logger.info(f"=== SEARCH GUILD DEBUG: ID {search_guild_id} ===")
                    
                    # Default to current channel only if searching current guild
                    search_channel_id = args.get("channel_id")
                    if not search_channel_id and search_guild_id == str(ctx.guild.id):
                        search_channel_id = str(ctx.channel.id)
                    # If searching a different guild, don't filter by channel (search all)
                    
                    # Parse limit with lower default
                    limit = int(args.get("limit", 20))
                    
                    text_result, avatars = await self._execute_search(
                        guild_id=search_guild_id,
                        channel_id=search_channel_id,
                        author_id=args.get("author_id"),
                        content=args.get("content"),
                        limit=limit,
                        author_type=args.get("author_type"),
                        has=args.get("has"),
                        mentions=args.get("mentions"),
                        pinned=args.get("pinned"),
                        link_hostname=args.get("link_hostname"),
                        attachment_extension=args.get("attachment_extension"),
                        sort_by=args.get("sort_by"),
                        sort_order=args.get("sort_order")
                    )
                    
                    # Fetch avatar images and add to gathered_images for generation
                    # Also add them to the conversation so the AI can see them
                    avatar_parts = []
                    for user_id, user_info in avatars.items():
                        avatar_url = user_info.get("avatar_url")
                        if avatar_url:
                            try:
                                # Convert animated GIF avatars to PNG (Gemini works better with static images)
                                if '.gif' in avatar_url:
                                    avatar_url = avatar_url.replace('.gif', '.png')
                                    logger.info(f"Converted animated avatar to PNG for {user_info.get('username', user_id)}")
                                
                                async with aiohttp.ClientSession() as session:
                                    async with session.get(avatar_url) as resp:
                                        if resp.status == 200:
                                            avatar_bytes = await resp.read()
                                            content_type = resp.headers.get('Content-Type', 'image/png')
                                            encoded = base64.b64encode(avatar_bytes).decode('utf-8')
                                            gathered_images.append((content_type, encoded))
                                            # Add to avatar_parts for conversation context
                                            avatar_parts.append({
                                                "text": f"Avatar of {user_info.get('username', 'Unknown')} (ID: {user_id}):"
                                            })
                                            avatar_parts.append({
                                                "inlineData": {"mimeType": content_type, "data": encoded}
                                            })
                                            logger.info(f"Added avatar for {user_info.get('username', user_id)} to conversation context")
                            except Exception as e:
                                logger.warning(f"Failed to fetch avatar for {user_id}: {e}")
                    
                    # Add avatars to conversation so AI can see them
                    if avatar_parts:
                        extra_user_messages.append({
                            "role": "user",
                            "parts": [{"text": "Here are the profile pictures of users from the search results:"}] + avatar_parts
                        })
                    
                    tool_outputs.append({
                        "functionResponse": {
                            "name": tool_name,
                            "response": {
                                "status": "success",
                                "message_count": len(text_result.splitlines()),
                                "messages": text_result,
                                "users": avatars,  # Include user avatars for image generation
                                "note": f"Loaded {len(avatars)} user avatar(s) - their profile pictures are now visible to you"
                            }
                        }
                    })
                
                elif tool_name == "generate_image":
                    prompt = args.get("prompt_text", "Image")
                    if status_message:
                        await status_message.edit(content=f"> 🎨 Generating image: {prompt[:50]}...")
                    
                    image_io = await self._generate_image(prompt, gathered_images)
                    
                    if image_io:
                        await ctx.send(file=discord.File(image_io, filename="generated.png"))
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "success"}
                            }
                        })
                        generation_completed = True
                    else:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "message": "Failed to generate image."}
                            }
                        })
                
                elif tool_name == "edit_image":
                    edit_prompt = args.get("edit_prompt", "")
                    image_url = args.get("image_url", "")
                    
                    if not edit_prompt:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "error": "No edit instructions provided"}
                            }
                        })
                        continue
                    
                    # Find the image from gathered_images or fetch from URL
                    image_data = None
                    if gathered_images:
                        # Use the first gathered image
                        image_data = gathered_images[0]
                    elif image_url:
                        # Fetch from URL
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(image_url) as resp:
                                    if resp.status == 200:
                                        content_type = resp.headers.get('Content-Type', 'image/png')
                                        img_bytes = await resp.read()
                                        image_data = (content_type, base64.b64encode(img_bytes).decode('utf-8'))
                        except Exception as e:
                            logger.error(f"Failed to fetch image for edit: {e}")
                    
                    if not image_data:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "error": "No image provided to edit"}
                            }
                        })
                        continue
                    
                    if status_message:
                        await status_message.edit(content=f"> ✏️ Editing image: {edit_prompt[:50]}...")
                    
                    edited_io = await self._edit_image(image_data, edit_prompt)
                    
                    if edited_io:
                        await ctx.send(file=discord.File(edited_io, filename="edited.png"))
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "success"}
                            }
                        })
                        generation_completed = True
                    else:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "message": "Failed to edit image."}
                            }
                        })
                
                elif tool_name == "generate_video":
                    prompt = args.get("prompt_text", "Video")
                    
                    if status_message:
                        await status_message.edit(content=f"> 🎥 Generating video: {prompt[:50]}...")
                    
                    video_io = await self._generate_video(prompt, status_message)
                    
                    if video_io:
                        if status_message:
                            await status_message.delete()
                            status_message = None
                        
                        await ctx.send(file=discord.File(video_io, filename="generated.mp4"))
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "success"}
                            }
                        })
                        generation_completed = True
                    else:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "message": "Failed to generate video."}
                            }
                        })
                
                elif tool_name == "generate_music":
                    prompt = args.get("prompt", "Music")
                    title = args.get("title", "Generated Track")
                    style = args.get("style", "Pop")
                    instrumental = args.get("instrumental", False)
                    
                    if status_message:
                        await status_message.edit(content=f"> 🎵 Generating music: {title}...")
                    
                    tracks = await self._generate_music(prompt, title, style, instrumental)
                    
                    if tracks:
                        if status_message:
                            await status_message.delete()
                            status_message = None
                        
                        files_to_send = []
                        
                        async with aiohttp.ClientSession() as session:
                            for track in tracks:
                                audio_url = track.get("audio_url")
                                if audio_url:
                                    try:
                                        async with session.get(audio_url) as resp:
                                            if resp.status == 200:
                                                audio_data = await resp.read()
                                                safe_title = "".join(x for x in track["title"] if x.isalnum() or x in " -_").strip()
                                                files_to_send.append(discord.File(io.BytesIO(audio_data), filename=f"{safe_title}.mp3"))
                                    except Exception as e:
                                        logger.warning(f"Failed to download audio: {e}")
                        
                        if files_to_send:
                            await ctx.send(files=files_to_send)
                        
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "success"}
                            }
                        })
                        generation_completed = True
                    else:
                        if status_message:
                            await status_message.edit(content="> ❌ Music generation failed.")
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error"}
                            }
                        })
                
                elif tool_name == "fetch_url":
                    url = args.get("url", "")
                    if not url:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "error": "No URL provided"}
                            }
                        })
                        continue
                    
                    if status_message:
                        await status_message.edit(content=f"> 🌐 Fetching URL: {url[:50]}...")
                    
                    content = await self._fetch_url(url)
                    
                    tool_outputs.append({
                        "functionResponse": {
                            "name": tool_name,
                            "response": {
                                "status": "success" if not content.startswith("Error:") else "error",
                                "url": url,
                                "content": content
                            }
                        }
                    })
                
                elif tool_name == "remove_background":
                    image_url = args.get("image_url", "")
                    if not image_url:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "error": "No image URL provided"}
                            }
                        })
                        continue
                    
                    if status_message:
                        await status_message.edit(content=f"> 🖼️ Removing background...")
                    
                    result_url = await self._remove_background(image_url)
                    
                    if result_url:
                        # Download and send the result image
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(result_url) as resp:
                                    if resp.status == 200:
                                        image_data = await resp.read()
                                        await ctx.send(
                                            file=discord.File(io.BytesIO(image_data), filename="background_removed.png")
                                        )
                                        tool_outputs.append({
                                            "functionResponse": {
                                                "name": tool_name,
                                                "response": {"status": "success", "message": "Background removed and image sent"}
                                            }
                                        })
                                        generation_completed = True
                                    else:
                                        tool_outputs.append({
                                            "functionResponse": {
                                                "name": tool_name,
                                                "response": {"status": "error", "error": f"Failed to download result: HTTP {resp.status}"}
                                            }
                                        })
                        except Exception as e:
                            tool_outputs.append({
                                "functionResponse": {
                                    "name": tool_name,
                                    "response": {"status": "error", "error": str(e)}
                                }
                            })
                    else:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "error": "Background removal failed"}
                            }
                        })
                
                elif tool_name == "upscale_image":
                    image_url = args.get("image_url", "")
                    if not image_url:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "error": "No image URL provided"}
                            }
                        })
                        continue
                    
                    if status_message:
                        await status_message.edit(content=f"> 🔍 Upscaling image...")
                    
                    result_url = await self._upscale_image(image_url)
                    
                    if result_url:
                        # Download and send the result image
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(result_url) as resp:
                                    if resp.status == 200:
                                        image_data = await resp.read()
                                        await ctx.send(
                                            file=discord.File(io.BytesIO(image_data), filename="upscaled.png")
                                        )
                                        tool_outputs.append({
                                            "functionResponse": {
                                                "name": tool_name,
                                                "response": {"status": "success", "message": "Image upscaled and sent"}
                                            }
                                        })
                                        generation_completed = True
                                    else:
                                        tool_outputs.append({
                                            "functionResponse": {
                                                "name": tool_name,
                                                "response": {"status": "error", "error": f"Failed to download result: HTTP {resp.status}"}
                                            }
                                        })
                        except Exception as e:
                            tool_outputs.append({
                                "functionResponse": {
                                    "name": tool_name,
                                    "response": {"status": "error", "error": str(e)}
                                }
                            })
                    else:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "error": "Upscale failed"}
                            }
                        })
                
                elif tool_name == "generate_sound_effect":
                    text = args.get("text", "")
                    if not text:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "error": "No text description provided"}
                            }
                        })
                        continue
                    
                    duration = args.get("duration_seconds")
                    loop = args.get("loop", False)
                    influence = args.get("prompt_influence", 0.3)
                    
                    if status_message:
                        await status_message.edit(content=f"> 🔊 Generating sound effect...")
                    
                    result_url = await self._generate_sound_effect(text, duration, loop, influence)
                    
                    if result_url:
                        # Download and send the audio
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(result_url) as resp:
                                    if resp.status == 200:
                                        audio_data = await resp.read()
                                        # Create a safe filename
                                        safe_name = "".join(c for c in text[:30] if c.isalnum() or c in " -_").strip() or "sound_effect"
                                        await ctx.send(
                                            file=discord.File(io.BytesIO(audio_data), filename=f"{safe_name}.mp3")
                                        )
                                        tool_outputs.append({
                                            "functionResponse": {
                                                "name": tool_name,
                                                "response": {"status": "success", "message": "Sound effect generated and sent"}
                                            }
                                        })
                                        generation_completed = True
                                    else:
                                        tool_outputs.append({
                                            "functionResponse": {
                                                "name": tool_name,
                                                "response": {"status": "error", "error": f"Failed to download audio: HTTP {resp.status}"}
                                            }
                                        })
                        except Exception as e:
                            tool_outputs.append({
                                "functionResponse": {
                                    "name": tool_name,
                                    "response": {"status": "error", "error": str(e)}
                                }
                            })
                    else:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "error": "Sound effect generation failed"}
                            }
                        })
                
                elif tool_name == "get_user_avatars":
                    user_ids = args.get("user_ids", [])
                    if not user_ids:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "error": "No user IDs provided"}
                            }
                        })
                        continue
                    
                    results = {}
                    for user_id in user_ids:
                        try:
                            uid = int(user_id)
                            user = self.bot.get_user(uid)
                            if not user:
                                user = await self.bot.fetch_user(uid)
                            if user:
                                avatar_url = str(user.display_avatar.url)
                                # Convert animated GIF avatars to PNG for AI model compatibility
                                if '.gif' in avatar_url:
                                    avatar_url = avatar_url.replace('.gif', '.png')
                                    logger.info(f"Converted animated avatar to PNG for {user.name}")
                                
                                results[user_id] = {
                                    "username": user.name,
                                    "avatar_url": avatar_url
                                }
                                # Fetch the avatar and add to gathered_images for generation
                                try:
                                    async with aiohttp.ClientSession() as session:
                                        async with session.get(avatar_url) as resp:
                                            if resp.status == 200:
                                                avatar_bytes = await resp.read()
                                                content_type = resp.headers.get('Content-Type', 'image/png')
                                                encoded = base64.b64encode(avatar_bytes).decode('utf-8')
                                                gathered_images.append((content_type, encoded))
                                                logger.info(f"Added avatar for {user.name} to gathered_images")
                                except Exception as e:
                                    logger.warning(f"Failed to fetch avatar image for {user_id}: {e}")
                            else:
                                results[user_id] = {"error": "User not found"}
                        except ValueError:
                            results[user_id] = {"error": "Invalid user ID format"}
                        except Exception as e:
                            results[user_id] = {"error": str(e)}
                    
                    tool_outputs.append({
                        "functionResponse": {
                            "name": tool_name,
                            "response": {
                                "status": "success",
                                "users": results,
                                "note": "Avatar images have been loaded as reference images for generation"
                            }
                        }
                    })
            
            if tool_outputs:
                conversation_history.append({"role": "tool", "parts": tool_outputs})
            
            if extra_user_messages:
                conversation_history.extend(extra_user_messages)
            
            if generation_completed:
                break
        
        # Clean up status message if still present
        if status_message:
            try:
                await status_message.delete()
            except:
                pass
    
    @ask.error
    async def ask_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send("❌ This command can only be used in a server.")
        else:
            logger.error(f"Ask command error: {error}")
            await ctx.send(f"❌ An error occurred: {error}")
    
    def cog_unload(self):
        """Clean up when cog is unloaded."""
        if self.search_client:
            asyncio.create_task(self.search_client.close())


async def setup(bot: commands.Bot):
    await bot.add_cog(AskCog(bot))
