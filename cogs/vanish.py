"""
Vanish Cog

Bulk delete messages from a specific user in a channel.
Uses chunked approach: fetch 2000 messages, delete them, fetch next 2000, repeat.
Persists state so operations can survive restarts.
"""

import discord
from discord.ext import commands
import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Set
from datetime import datetime
from pathlib import Path

from utils.discord_search import get_search_client, SearchError

logger = logging.getLogger('realbot')

# Configuration
DELETE_DELAY = 1.0      # Seconds between deletes
SEARCH_DELAY = 0.4      # Seconds between search pages
CHUNK_SIZE = 2000       # Messages per chunk
BATCH_SIZE = 25         # Messages per search API call

# Persistence
DATA_DIR = Path(__file__).parent.parent / "data"
VANISH_STATE_FILE = DATA_DIR / "vanish_state.json"


@dataclass
class VanishJob:
    """Tracks an active vanish operation with persistence."""
    channel_id: int
    guild_id: int
    target_user_id: int
    target_user_name: str
    started_at: str  # ISO format for JSON serialization
    
    # Current chunk state
    current_chunk: List[str] = field(default_factory=list)
    chunk_index: int = 0  # Position within current chunk
    chunks_completed: int = 0
    
    # Stats
    deleted_count: int = 0
    failed_count: int = 0
    total_estimated: int = 0  # Initial estimate
    
    # Control
    is_running: bool = True
    is_cancelled: bool = False
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'VanishJob':
        return cls(**data)
    
    def get_progress_percent(self) -> float:
        if self.total_estimated == 0:
            return 0.0
        return min(100.0, (self.deleted_count / self.total_estimated) * 100)
    
    def get_eta(self) -> str:
        # Estimate based on remaining in current chunk + estimated remaining chunks
        remaining_in_chunk = len(self.current_chunk) - self.chunk_index
        # Rough estimate of remaining
        remaining = remaining_in_chunk + max(0, self.total_estimated - self.deleted_count - remaining_in_chunk)
        
        if remaining <= 0:
            return "Almost done"
        seconds_remaining = remaining * DELETE_DELAY
        if seconds_remaining < 60:
            return f"~{int(seconds_remaining)}s"
        elif seconds_remaining < 3600:
            return f"~{int(seconds_remaining / 60)}m"
        else:
            return f"~{int(seconds_remaining / 3600)}h {int((seconds_remaining % 3600) / 60)}m"


class Vanish(commands.Cog):
    """Bulk delete messages from specific users with chunked processing."""
    
    def __init__(self, bot):
        self.bot = bot
        self.active_jobs: Dict[int, VanishJob] = {}
        self._load_state()
    
    def _load_state(self):
        """Load any saved vanish jobs from disk."""
        if VANISH_STATE_FILE.exists():
            try:
                with open(VANISH_STATE_FILE, 'r') as f:
                    data = json.load(f)
                for channel_id_str, job_data in data.items():
                    job = VanishJob.from_dict(job_data)
                    job.is_running = False  # Will need to be resumed
                    self.active_jobs[int(channel_id_str)] = job
                logger.info(f"Vanish: Loaded {len(self.active_jobs)} saved jobs")
            except Exception as e:
                logger.error(f"Vanish: Failed to load state: {e}")
    
    def _save_state(self):
        """Persist current jobs to disk."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                str(channel_id): job.to_dict()
                for channel_id, job in self.active_jobs.items()
            }
            with open(VANISH_STATE_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Vanish: Failed to save state: {e}")
    
    async def fetch_chunk(
        self,
        guild_id: str,
        channel_id: str,
        user_id: str,
        chunk_num: int,
        status_msg: discord.Message,
        chunk_size: int = CHUNK_SIZE
    ) -> List[str]:
        """Fetch a chunk of message IDs using pagination with progress updates."""
        client = get_search_client()
        chunk_ids: List[str] = []
        seen_ids: Set[str] = set()
        offset = 0
        last_update = datetime.now()
        
        while len(chunk_ids) < chunk_size:
            try:
                result = await client.search_with_retry(
                    guild_id,
                    author_id=[user_id],
                    channel_id=[channel_id],
                    sort_by="timestamp",
                    sort_order="desc",
                    limit=BATCH_SIZE,
                    offset=offset
                )
                
                messages = result.get_target_messages()
                
                if not messages:
                    break
                
                new_count = 0
                for msg in messages:
                    if msg.id not in seen_ids:
                        seen_ids.add(msg.id)
                        chunk_ids.append(msg.id)
                        new_count += 1
                
                if new_count == 0:
                    break
                
                offset += BATCH_SIZE
                
                # Update progress every 2 seconds or every 100 messages
                if (datetime.now() - last_update).seconds >= 2 or len(chunk_ids) % 100 == 0:
                    try:
                        await status_msg.edit(content=(
                            f"🔍 **Fetching chunk {chunk_num}**\n"
                            f"Found: {len(chunk_ids)}/{chunk_size} messages\n"
                            f"Scanning page {offset // BATCH_SIZE}..."
                        ))
                        last_update = datetime.now()
                    except:
                        pass
                
                await asyncio.sleep(SEARCH_DELAY)
                
            except SearchError as e:
                logger.error(f"Vanish chunk fetch error: {e}")
                break
        
        logger.info(f"Vanish: Fetched chunk of {len(chunk_ids)} messages")
        return chunk_ids
    
    async def get_initial_count(self, guild_id: str, channel_id: str, user_id: str) -> int:
        """Get total message count estimate."""
        client = get_search_client()
        try:
            result = await client.search_with_retry(
                guild_id,
                author_id=[user_id],
                channel_id=[channel_id],
                limit=1
            )
            return result.total_results
        except:
            return 0
    
    async def delete_message_safe(self, channel: discord.TextChannel, message_id: str) -> bool:
        """Delete a message with error handling."""
        try:
            message = await channel.fetch_message(int(message_id))
            await message.delete()
            return True
        except discord.NotFound:
            return True  # Already gone
        except discord.Forbidden:
            return False
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = getattr(e, 'retry_after', 5.0)
                logger.warning(f"Rate limited, waiting {retry_after}s")
                await asyncio.sleep(retry_after)
                return await self.delete_message_safe(channel, message_id)
            return False
        except:
            return False
    
    async def run_vanish_job(self, ctx: commands.Context, job: VanishJob, status_msg: discord.Message):
        """Execute the vanish job with chunked processing."""
        channel = ctx.channel
        guild_id = str(job.guild_id)
        channel_id = str(job.channel_id)
        user_id = str(job.target_user_id)
        
        last_update = datetime.now()
        last_save = datetime.now()
        
        while job.is_running and not job.is_cancelled:
            # If current chunk is exhausted, fetch a new one
            if job.chunk_index >= len(job.current_chunk):
                # Pause to let search index update after deletions
                if job.chunks_completed > 0:
                    try:
                        await status_msg.edit(content=f"⏳ Waiting for search index to refresh...")
                    except:
                        pass
                    await asyncio.sleep(5.0)
                
                new_chunk = await self.fetch_chunk(
                    guild_id, 
                    channel_id, 
                    user_id,
                    chunk_num=job.chunks_completed + 1,
                    status_msg=status_msg
                )
                
                if not new_chunk:
                    # No more messages
                    job.is_running = False
                    break
                
                job.current_chunk = new_chunk
                job.chunk_index = 0
                job.chunks_completed += 1
                self._save_state()
                
                logger.info(f"Vanish: Starting chunk {job.chunks_completed} with {len(new_chunk)} messages")
            
            # Delete current message
            msg_id = job.current_chunk[job.chunk_index]
            success = await self.delete_message_safe(channel, msg_id)
            
            if success:
                job.deleted_count += 1
            else:
                job.failed_count += 1
            
            job.chunk_index += 1
            
            # Update status every 5 seconds
            if (datetime.now() - last_update).seconds >= 5:
                try:
                    chunk_progress = f"[Chunk {job.chunks_completed}: {job.chunk_index}/{len(job.current_chunk)}]"
                    await status_msg.edit(content=(
                        f"🗑️ **Vanishing {job.target_user_name}**\n"
                        f"Deleted: {job.deleted_count} ({job.get_progress_percent():.1f}%)\n"
                        f"ETA: {job.get_eta()}\n"
                        f"{chunk_progress}"
                    ))
                    last_update = datetime.now()
                except:
                    pass
            
            # Save state every 30 seconds
            if (datetime.now() - last_save).seconds >= 30:
                self._save_state()
                last_save = datetime.now()
            
            await asyncio.sleep(DELETE_DELAY)
        
        # Cleanup
        if job.is_cancelled:
            final_msg = f"⚠️ **Vanish cancelled** - Deleted {job.deleted_count} messages from {job.target_user_name}."
        else:
            final_msg = f"✅ **Vanish complete** - Deleted {job.deleted_count} messages from {job.target_user_name}."
            if job.failed_count > 0:
                final_msg += f" ({job.failed_count} failed)"
        
        try:
            await status_msg.edit(content=final_msg)
        except:
            await ctx.send(final_msg)
        
        if ctx.channel.id in self.active_jobs:
            del self.active_jobs[ctx.channel.id]
        self._save_state()
    
    @commands.group(name="vanish", invoke_without_command=True)
    @commands.is_owner()
    async def vanish(self, ctx: commands.Context, user: discord.User):
        """Start deleting all messages from a user in this channel."""
        if ctx.channel.id in self.active_jobs:
            job = self.active_jobs[ctx.channel.id]
            if job.is_running:
                await ctx.send(
                    f"❌ Already vanishing **{job.target_user_name}**.\n"
                    f"Use `!vanish status` or `!vanish cancel`."
                )
                return
            else:
                # Stale job, remove it
                del self.active_jobs[ctx.channel.id]
        
        if not isinstance(ctx.channel, discord.TextChannel):
            await ctx.send("❌ This command only works in text channels.")
            return
        
        status_msg = await ctx.send(f"🔍 Counting messages from **{user.display_name}**...")
        
        try:
            total = await self.get_initial_count(
                str(ctx.guild.id),
                str(ctx.channel.id),
                str(user.id)
            )
            
            if total == 0:
                await status_msg.edit(content=f"❌ No messages found from **{user.display_name}**.")
                return
            
            # Time estimate
            est_seconds = total * DELETE_DELAY
            if est_seconds < 60:
                time_est = f"~{int(est_seconds)}s"
            elif est_seconds < 3600:
                time_est = f"~{int(est_seconds / 60)}m"
            else:
                time_est = f"~{int(est_seconds / 3600)}h {int((est_seconds % 3600) / 60)}m"
            
            job = VanishJob(
                channel_id=ctx.channel.id,
                guild_id=ctx.guild.id,
                target_user_id=user.id,
                target_user_name=user.display_name,
                started_at=datetime.now().isoformat(),
                total_estimated=total
            )
            self.active_jobs[ctx.channel.id] = job
            self._save_state()
            
            await status_msg.edit(content=(
                f"🗑️ **Starting vanish of {user.display_name}**\n"
                f"Found: ~{total} messages\n"
                f"Estimated time: {time_est}\n"
                f"Processing in chunks of {CHUNK_SIZE}\n\n"
                f"Use `!vanish status` or `!vanish cancel`"
            ))
            
            job.is_running = True
            self.bot.loop.create_task(self.run_vanish_job(ctx, job, status_msg))
            
        except Exception as e:
            logger.error(f"Vanish start error: {e}", exc_info=True)
            await status_msg.edit(content=f"❌ Error: {str(e)[:200]}")
    
    @vanish.command(name="status")
    async def vanish_status(self, ctx: commands.Context):
        """Check vanish progress."""
        if ctx.channel.id not in self.active_jobs:
            await ctx.send("❌ No active vanish in this channel.")
            return
        
        job = self.active_jobs[ctx.channel.id]
        
        embed = discord.Embed(
            title=f"🗑️ Vanish: {job.target_user_name}",
            color=discord.Color.orange() if job.is_running else discord.Color.green()
        )
        embed.add_field(name="Deleted", value=str(job.deleted_count), inline=True)
        embed.add_field(name="Estimated Total", value=str(job.total_estimated), inline=True)
        embed.add_field(name="Progress", value=f"{job.get_progress_percent():.1f}%", inline=True)
        embed.add_field(name="Chunks Done", value=str(job.chunks_completed), inline=True)
        embed.add_field(name="Current Chunk", value=f"{job.chunk_index}/{len(job.current_chunk)}", inline=True)
        embed.add_field(name="ETA", value=job.get_eta(), inline=True)
        embed.add_field(name="Status", value="Running ⏳" if job.is_running else "Paused ⏸️", inline=True)
        
        await ctx.send(embed=embed)
    
    @vanish.command(name="cancel")
    @commands.is_owner()
    async def vanish_cancel(self, ctx: commands.Context):
        """Cancel the current vanish."""
        if ctx.channel.id not in self.active_jobs:
            await ctx.send("❌ No active vanish in this channel.")
            return
        
        job = self.active_jobs[ctx.channel.id]
        job.is_cancelled = True
        await ctx.send(f"⚠️ Cancelling vanish of **{job.target_user_name}**...")
    
    @vanish.command(name="resume")
    @commands.is_owner()
    async def vanish_resume(self, ctx: commands.Context):
        """Resume a paused/interrupted vanish."""
        if ctx.channel.id not in self.active_jobs:
            await ctx.send("❌ No saved vanish to resume in this channel.")
            return
        
        job = self.active_jobs[ctx.channel.id]
        
        if job.is_running:
            await ctx.send("❌ Vanish is already running.")
            return
        
        job.is_running = True
        job.is_cancelled = False
        
        status_msg = await ctx.send(f"▶️ Resuming vanish of **{job.target_user_name}**...")
        self.bot.loop.create_task(self.run_vanish_job(ctx, job, status_msg))


async def setup(bot):
    await bot.add_cog(Vanish(bot))
