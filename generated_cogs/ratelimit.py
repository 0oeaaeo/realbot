import discord
from discord import app_commands
from discord.ext import commands
import logging
import datetime
import asyncio

logger = logging.getLogger('realbot')

class RateLimit(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rate_limited_users = {}
        logger.info("RateLimit cog initialized")

    def cog_unload(self):
        # Cancel all running countdown tasks when the cog is unloaded
        for user_data in self.rate_limited_users.values():
            task = user_data.get('countdown_task')
            if task and not task.done():
                task.cancel()
                logger.info(f"Cancelled active ratelimit task for user_id {user_data.get('user_id')}")

    async def _countdown_warning(self, channel: discord.TextChannel, user_id: int, duration: int):
        """Creates and manages a countdown message for a rate-limited user."""
        msg = None
        try:
            logger.info(f"Starting countdown warning for user {user_id} in channel {channel.id} for {duration}s.")
            msg = await channel.send(f"<@{user_id}>, you are on a cooldown. You can send a message in **{duration}** seconds.", delete_after=duration)
            
            # Store message ID to prevent new messages from being created
            if user_id in self.rate_limited_users:
                 self.rate_limited_users[user_id]['warning_message_id'] = msg.id

            for i in range(duration - 1, 0, -1):
                await asyncio.sleep(1)
                await msg.edit(content=f"<@{user_id}>, you are on a cooldown. You can send a message in **{i}** seconds.")
        
        except asyncio.CancelledError:
            logger.info(f"Countdown for user {user_id} cancelled.")
            if msg:
                try:
                    await msg.delete()
                except discord.NotFound:
                    pass # Message was already deleted
        except discord.NotFound:
            logger.warning(f"Countdown message for user {user_id} not found, it was likely deleted manually.")
        except discord.Forbidden:
            logger.error(f"Missing permissions to edit/delete message in channel {channel.id}.")
        except Exception as e:
            logger.exception(f"Exception in _countdown_warning for user {user_id}")
        finally:
            if user_id in self.rate_limited_users:
                self.rate_limited_users[user_id]['countdown_task'] = None
                self.rate_limited_users[user_id]['warning_message_id'] = None
                logger.debug(f"Cleaned up task and message_id for user {user_id}.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        user_id = message.author.id
        if user_id in self.rate_limited_users:
            user_data = self.rate_limited_users[user_id]
            
            # Ensure the ratelimit is for the correct guild
            if message.guild.id != user_data['guild_id']:
                return

            now = datetime.datetime.now(datetime.timezone.utc)
            time_since_last_message = now - user_data['last_message_time']
            
            if time_since_last_message.total_seconds() >= user_data['interval']:
                # Message is allowed
                user_data['last_message_time'] = now
                logger.debug(f"Allowed message from rate-limited user {message.author}.")
                
                # If there's an active countdown task, cancel it
                if user_data.get('countdown_task') and not user_data['countdown_task'].done():
                    user_data['countdown_task'].cancel()
            else:
                # Message is not allowed, delete it
                try:
                    await message.delete()
                    logger.info(f"Deleted message from rate-limited user {message.author} due to violation.")
                except discord.Forbidden:
                    logger.error(f"Failed to delete message from {message.author} in {message.channel.id}: Missing Permissions.")
                    return
                except discord.NotFound:
                    # Message already deleted, nothing to do
                    return

                # If no countdown is active, start one
                if not user_data.get('countdown_task') or user_data['countdown_task'].done():
                    time_left = round(user_data['interval'] - time_since_last_message.total_seconds())
                    if time_left > 0:
                        task = asyncio.create_task(self._countdown_warning(message.channel, user_id, time_left))
                        user_data['countdown_task'] = task

    @commands.command(name="ratelimit")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def ratelimit(self, ctx: commands.Context, member: discord.Member, interval: int):
        """Limits a user to one message per specified interval.

        Usage: !ratelimit @user 10
        This limits the user to 1 message every 10 seconds.
        """
        logger.info(f"Ratelimit command invoked by {ctx.author} on {member} for {interval}s.")
        
        if member.id == self.bot.user.id:
            await ctx.send("I cannot rate-limit myself.")
            return
        if member.guild_permissions.manage_messages:
            await ctx.send("I cannot rate-limit a moderator.")
            return
        if interval <= 0:
            await ctx.send("Interval must be a positive number of seconds.")
            return

        # If user is already limited, cancel their old countdown task
        if member.id in self.rate_limited_users:
            old_task = self.rate_limited_users[member.id].get('countdown_task')
            if old_task and not old_task.done():
                old_task.cancel()
                logger.info(f"Cancelled existing countdown for {member} due to new ratelimit.")

        self.rate_limited_users[member.id] = {
            'guild_id': ctx.guild.id,
            'interval': interval,
            'last_message_time': datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc),
            'countdown_task': None,
            'warning_message_id': None,
            'user_id': member.id
        }
        
        await ctx.send(f"✅ User {member.mention} is now limited to 1 message every {interval} seconds.")
        logger.info(f"Successfully rate-limited {member} in guild {ctx.guild.id}.")

    @commands.command(name="unratelimit")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def unratelimit(self, ctx: commands.Context, member: discord.Member):
        """Removes the rate limit from a user."""
        logger.info(f"Unratelimit command invoked by {ctx.author} on {member}.")
        
        if member.id in self.rate_limited_users:
            user_data = self.rate_limited_users[member.id]
            task = user_data.get('countdown_task')
            if task and not task.done():
                task.cancel()
                logger.info(f"Cancelled active countdown for {member} as they were un-rate-limited.")
            
            del self.rate_limited_users[member.id]
            await ctx.send(f"✅ Removed rate limit from {member.mention}.")
            logger.info(f"Successfully removed rate limit for {member} in guild {ctx.guild.id}.")
        else:
            await ctx.send(f"User {member.mention} is not currently rate-limited.")

    @ratelimit.error
    @unratelimit.error
    async def on_ratelimit_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You do not have the `Manage Messages` permission to use this command.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(f"Could not find a member named `{error.argument}`.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing required argument: `{error.param.name}`. Please check the command's usage.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Invalid argument provided. Please ensure you provide a valid user and a number for the interval.")
        else:
            logger.exception(f"An unhandled error occurred in the RateLimit cog: {error}")
            await ctx.send("An unexpected error occurred. Please check the logs.")

async def setup(bot: commands.Bot):
    await bot.add_cog(RateLimit(bot))