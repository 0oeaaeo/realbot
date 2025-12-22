"""
Discord Search API Client

A reusable client for Discord's experimental guild message search API.
This endpoint is not yet supported in discord.py, so we interface directly via aiohttp.
"""

import aiohttp
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger('realbot')

# User token for search API (loaded from environment)
USER_TOKEN = os.getenv("USER_TOKEN")
if not USER_TOKEN:
    logger.warning("USER_TOKEN not set in environment - search may not work")

# Cache for available guilds
_guilds_cache: Optional[List[Dict[str, Any]]] = None


async def fetch_available_guilds() -> List[Dict[str, Any]]:
    """
    Fetch all guilds the user token has access to.
    Returns list of {id, name, icon, owner, permissions} dicts.
    """
    global _guilds_cache
    
    if _guilds_cache is not None:
        return _guilds_cache
    
    import httpx
    
    url = "https://canary.discord.com/api/v9/users/@me/guilds"
    headers = {
        'Authorization': USER_TOKEN,
        'accept': '*/*',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                _guilds_cache = response.json()
                logger.info(f"Fetched {len(_guilds_cache)} guilds for user token")
                return _guilds_cache
            else:
                logger.error(f"Failed to fetch guilds: {response.status_code}")
                return []
    except Exception as e:
        logger.error(f"Error fetching guilds: {e}")
        return []


def get_guilds_cache() -> Optional[List[Dict[str, Any]]]:
    """Get the current guilds cache (may be None if not fetched yet)."""
    return _guilds_cache


def _normalize_text(text: str) -> str:
    """Normalize text by converting fancy Unicode to ASCII and lowercasing."""
    import unicodedata
    # Normalize Unicode (NFKD decomposes fancy chars)
    normalized = unicodedata.normalize('NFKD', text)
    # Keep only ASCII letters and spaces
    ascii_text = ''.join(c for c in normalized if c.isascii() or c.isspace())
    return ascii_text.lower().strip()


async def lookup_guild_by_name(name: str) -> Optional[Dict[str, Any]]:
    """
    Find a guild by name with fuzzy matching.
    Handles fancy Unicode names (like 𝘔𝘐𝘙𝘈𝘎𝘌 -> mirage).
    Tries exact match, then substring, then word overlap scoring.
    Returns the guild dict or None if not found.
    """
    guilds = await fetch_available_guilds()
    if not guilds:
        return None
    
    name_normalized = _normalize_text(name)
    name_words = set(name_normalized.split())
    
    # First try exact match (with normalization)
    for guild in guilds:
        guild_normalized = _normalize_text(guild['name'])
        if guild_normalized == name_normalized:
            return guild
    
    # Then try substring match (either direction)
    for guild in guilds:
        guild_normalized = _normalize_text(guild['name'])
        if name_normalized in guild_normalized or guild_normalized in name_normalized:
            return guild
    
    # Fuzzy match: score by character overlap and word similarity
    def score_match(guild_name: str) -> float:
        guild_normalized = _normalize_text(guild_name)
        guild_words = set(guild_normalized.split())
        
        # Character-level: longest common substring ratio
        def lcs_ratio(s1, s2):
            if not s1 or not s2:
                return 0
            # Check if one starts with the other (handles typos like "mirag" -> "mirage")
            for g_word in guild_normalized.split():
                if g_word.startswith(name_normalized) or name_normalized.startswith(g_word):
                    return 0.8
            # Check character overlap
            common = sum(1 for c in name_normalized if c in guild_normalized)
            return common / max(len(name_normalized), len(guild_normalized))
        
        # Word-level matching
        word_overlap = len(name_words & guild_words)
        
        return lcs_ratio(name_normalized, guild_normalized) + (word_overlap * 0.3)
    
    # Score all guilds and pick best match if above threshold
    scored = [(guild, score_match(guild['name'])) for guild in guilds]
    scored.sort(key=lambda x: x[1], reverse=True)
    
    if scored and scored[0][1] >= 0.5:
        logger.info(f"Fuzzy matched '{name}' to '{scored[0][0]['name']}' (score: {scored[0][1]:.2f})")
        return scored[0][0]
    
    return None


def get_similar_guilds(name: str, limit: int = 5) -> List[str]:
    """Get a list of guild names that might match the given name."""
    if not _guilds_cache:
        return []
    
    name_lower = name.lower()
    suggestions = []
    
    for guild in _guilds_cache:
        guild_name = guild['name']
        guild_lower = guild_name.lower()
        # Basic similarity check
        if any(word in guild_lower for word in name_lower.split()):
            suggestions.append(guild_name)
        elif any(guild_lower.startswith(word[:3]) for word in name_lower.split() if len(word) >= 3):
            suggestions.append(guild_name)
    
    return suggestions[:limit]


def get_guild_names_for_context() -> str:
    """
    Get a formatted string of available guild names for AI context.
    Call fetch_available_guilds() first to populate the cache.
    """
    if not _guilds_cache:
        return "No guilds cached yet."
    
    lines = []
    for guild in _guilds_cache:
        lines.append(f"- {guild['name']} (ID: {guild['id']})")
    
    return "Available servers:\n" + "\n".join(lines)


@dataclass
class SearchMessage:
    """Represents a message from search results."""
    id: str
    channel_id: str
    author_id: str
    author_name: str
    author_avatar: Optional[str]  # Avatar hash from Discord API
    content: str
    timestamp: str
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    embeds: List[Dict[str, Any]] = field(default_factory=list)
    
    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> 'SearchMessage':
        """Parse a message from API response."""
        author = data.get('author', {})
        return cls(
            id=data.get('id', ''),
            channel_id=data.get('channel_id', ''),
            author_id=author.get('id', ''),
            author_name=author.get('username', 'Unknown'),
            author_avatar=author.get('avatar'),
            content=data.get('content', ''),
            timestamp=data.get('timestamp', ''),
            attachments=data.get('attachments', []),
            embeds=data.get('embeds', [])
        )
    
    def get_avatar_url(self, size: int = 256) -> str:
        """Get the Discord CDN URL for this author's avatar. Always returns PNG for compatibility."""
        if self.author_avatar:
            # Always use PNG (even for animated avatars) for AI model compatibility
            return f"https://cdn.discordapp.com/avatars/{self.author_id}/{self.author_avatar}.png?size={size}"
        # Default avatar based on user ID
        try:
            default_index = (int(self.author_id) >> 22) % 6
        except:
            default_index = 0
        return f"https://cdn.discordapp.com/embed/avatars/{default_index}.png"


@dataclass
class SearchResult:
    """Represents search results from the API."""
    messages: List[List[SearchMessage]]  # Nested structure: [[context, target, context], ...]
    total_results: int
    threads: List[Dict[str, Any]] = field(default_factory=list)
    members: List[Dict[str, Any]] = field(default_factory=list)
    analytics_id: str = ''
    
    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> 'SearchResult':
        """Parse search results from API response."""
        messages = []
        for hit_group in data.get('messages', []):
            group = [SearchMessage.from_api(msg) for msg in hit_group]
            messages.append(group)
        
        return cls(
            messages=messages,
            total_results=data.get('total_results', 0),
            threads=data.get('threads', []),
            members=data.get('members', []),
            analytics_id=data.get('analytics_id', '')
        )
    
    def get_target_messages(self) -> List[SearchMessage]:
        """Get the main target messages (middle message in each hit group)."""
        targets = []
        for group in self.messages:
            if group:
                # Target is typically the middle message, or first if only one
                mid_idx = len(group) // 2
                targets.append(group[mid_idx])
        return targets


class DiscordSearchClient:
    """
    Client for Discord's experimental guild message search API.
    
    Endpoint: GET /guilds/{guild_id}/messages/search
    """
    
    BASE_URL = "https://discord.com/api/v9"
    
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self._session: Optional[aiohttp.ClientSession] = None
    
    @property
    def headers(self) -> Dict[str, str]:
        # Use user token for search (no "Bot " prefix)
        return {
            "Authorization": USER_TOKEN,
            "Content-Type": "application/json"
        }
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _build_query_params(
        self,
        # Text query
        content: Optional[str] = None,
        slop: Optional[int] = None,
        # Authors & mentions
        author_id: Optional[List[str]] = None,
        author_type: Optional[List[str]] = None,
        mentions: Optional[List[str]] = None,
        mention_everyone: Optional[bool] = None,
        # Context & timing
        channel_id: Optional[List[str]] = None,
        min_id: Optional[str] = None,
        max_id: Optional[str] = None,
        pinned: Optional[bool] = None,
        # Content attributes
        has: Optional[List[str]] = None,
        include_nsfw: Optional[bool] = None,
        attachment_extension: Optional[List[str]] = None,
        attachment_filename: Optional[str] = None,
        embed_type: Optional[List[str]] = None,
        link_hostname: Optional[List[str]] = None,
        # Sorting & pagination
        sort_by: Optional[Literal['relevance', 'timestamp']] = None,
        sort_order: Optional[Literal['asc', 'desc']] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Build query parameters for the search request."""
        params = {}
        
        if content is not None:
            params['content'] = content[:1024]  # Max 1024 chars
        if slop is not None:
            params['slop'] = max(0, min(100, slop))  # 0-100
        
        # Array parameters need special handling
        if author_id:
            for aid in author_id[:1521]:  # Max 1521 items
                params.setdefault('author_id', []).append(aid)
        if author_type:
            for at in author_type:
                params.setdefault('author_type', []).append(at)
        if mentions:
            for m in mentions[:1521]:
                params.setdefault('mentions', []).append(m)
        if mention_everyone is not None:
            params['mention_everyone'] = str(mention_everyone).lower()
        
        if channel_id:
            for cid in channel_id[:500]:  # Max 500 items
                params.setdefault('channel_id', []).append(cid)
        if min_id:
            params['min_id'] = min_id
        if max_id:
            params['max_id'] = max_id
        if pinned is not None:
            params['pinned'] = str(pinned).lower()
        
        if has:
            for h in has:
                params.setdefault('has', []).append(h)
        if include_nsfw is not None:
            params['include_nsfw'] = str(include_nsfw).lower()
        if attachment_extension:
            for ext in attachment_extension:
                params.setdefault('attachment_extension', []).append(ext)
        if attachment_filename:
            params['attachment_filename'] = attachment_filename
        if embed_type:
            for et in embed_type:
                params.setdefault('embed_type', []).append(et)
        if link_hostname:
            for lh in link_hostname:
                params.setdefault('link_hostname', []).append(lh)
        
        if sort_by:
            params['sort_by'] = sort_by
        if sort_order:
            params['sort_order'] = sort_order
        if limit is not None:
            params['limit'] = max(1, min(25, limit))  # 1-25
        if offset is not None:
            params['offset'] = max(0, min(9975, offset))  # 0-9975
        
        return params
    
    async def search(
        self,
        guild_id: str,
        **kwargs
    ) -> SearchResult:
        """
        Execute a search query against the guild message search API.
        
        Args:
            guild_id: The guild ID to search in
            **kwargs: Search parameters (see _build_query_params)
        
        Returns:
            SearchResult object with messages, total_results, etc.
        
        Raises:
            Exception on API errors
        """
        import httpx
        import urllib.parse
        
        # Use canary.discord.com like the working curl request
        base_url = f"https://canary.discord.com/api/v9/guilds/{guild_id}/messages/search"
        params = self._build_query_params(**kwargs)
        params['include_nsfw'] = 'true'  # Add this like the working curl
        
        # Build URL
        query_string = urllib.parse.urlencode(params, doseq=True)
        url = f"{base_url}?{query_string}"
        
        # Browser-like headers matching the working curl request
        headers = {
            'Authorization': USER_TOKEN,
            'accept': '*/*',
            'accept-language': 'en-US',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.932 Chrome/138.0.7204.251 Electron/37.6.0 Safari/537.36',
            'x-discord-locale': 'en-US',
            'x-discord-timezone': 'America/Los_Angeles',
        }
        
        # DEBUG: Log full request details
        logger.info(f"=== DISCORD SEARCH DEBUG ===")
        logger.info(f"URL: {url}")
        logger.info(f"Auth token (first 30 chars): {headers.get('Authorization', 'NONE')[:30]}...")
        logger.info(f"============================")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Discord Search: Found {data.get('total_results', 0)} results")
                return SearchResult.from_api(data)
            
            elif response.status_code == 202:
                # Index not ready
                data = response.json()
                retry_after = data.get('retry_after', 5)
                logger.warning(f"Discord Search: Index not ready, retry after {retry_after}s")
                raise IndexNotReadyError(retry_after)
            
            elif response.status_code == 429:
                # Rate limited
                retry_after = float(response.headers.get('X-RateLimit-Reset-After', 5))
                logger.warning(f"Discord Search: Rate limited, retry after {retry_after}s")
                raise RateLimitError(retry_after)
            
            else:
                error_text = response.text
                logger.error(f"Discord Search failed ({response.status_code}): {error_text[:500]}")
                raise SearchError(f"API error {response.status_code}: {error_text[:200]}")
    
    async def search_with_retry(
        self,
        guild_id: str,
        max_retries: int = 3,
        **kwargs
    ) -> SearchResult:
        """
        Execute a search with automatic retry for rate limits and indexing delays.
        """
        for attempt in range(max_retries):
            try:
                return await self.search(guild_id, **kwargs)
            
            except IndexNotReadyError as e:
                if attempt < max_retries - 1:
                    logger.info(f"Search: Waiting {e.retry_after}s for index...")
                    await asyncio.sleep(e.retry_after)
                else:
                    raise
            
            except RateLimitError as e:
                if attempt < max_retries - 1:
                    logger.info(f"Search: Rate limited, waiting {e.retry_after}s...")
                    await asyncio.sleep(e.retry_after)
                else:
                    raise
        
        raise SearchError("Max retries exceeded")


class SearchError(Exception):
    """Base exception for search errors."""
    pass


class IndexNotReadyError(SearchError):
    """Raised when the guild search index is not ready (202 response)."""
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Index not ready, retry after {retry_after}s")


class RateLimitError(SearchError):
    """Raised when rate limited (429 response)."""
    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after}s")


# ============================================================================
# CONVENIENCE FUNCTIONS FOR EASY REUSE BY COGS
# ============================================================================

_search_client: Optional[DiscordSearchClient] = None


def get_search_client() -> DiscordSearchClient:
    """
    Get a singleton search client instance.
    Uses USER_TOKEN for search (configured at module level).
    """
    global _search_client
    if _search_client is None:
        # Token param is no longer used - headers use USER_TOKEN directly
        _search_client = DiscordSearchClient("")
    return _search_client


async def get_user_messages(
    guild_id: str,
    user_id: str,
    channel_id: Optional[str] = None,
    limit: int = 25,
    content_only: bool = True
) -> List[str]:
    """
    Convenience function to get recent messages from a user.
    
    Args:
        guild_id: The guild ID to search in
        user_id: The user ID to get messages from
        channel_id: Optional channel ID to restrict search
        limit: Maximum number of messages to return (max 25 per request)
        content_only: If True, return only message content strings
    
    Returns:
        List of message content strings (if content_only=True)
        or List of SearchMessage objects
    """
    client = get_search_client()
    
    params = {
        "author_id": [user_id],
        "sort_by": "timestamp",
        "sort_order": "desc",
        "limit": min(25, limit)
    }
    
    if channel_id:
        params["channel_id"] = [channel_id]
    
    try:
        result = await client.search_with_retry(guild_id, **params)
        targets = result.get_target_messages()
        
        if content_only:
            return [msg.content for msg in targets if msg.content.strip()]
        return targets
    
    except SearchError as e:
        logger.error(f"get_user_messages failed: {e}")
        return []


async def search_messages(
    guild_id: str,
    content: Optional[str] = None,
    author_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    has: Optional[List[str]] = None,
    limit: int = 25
) -> List[SearchMessage]:
    """
    General-purpose message search.
    
    Args:
        guild_id: The guild ID to search in
        content: Text content to search for
        author_id: Filter by author
        channel_id: Filter by channel
        has: Content filters (image, video, link, file, etc.)
        limit: Max results (1-25)
    
    Returns:
        List of SearchMessage objects
    """
    client = get_search_client()
    
    params = {
        "sort_by": "timestamp",
        "sort_order": "desc",
        "limit": min(25, limit)
    }
    
    if content:
        params["content"] = content
    if author_id:
        params["author_id"] = [author_id]
    if channel_id:
        params["channel_id"] = [channel_id]
    if has:
        params["has"] = has
    
    try:
        result = await client.search_with_retry(guild_id, **params)
        return result.get_target_messages()
    
    except SearchError as e:
        logger.error(f"search_messages failed: {e}")
        return []
