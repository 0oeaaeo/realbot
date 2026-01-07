import discord
from discord import app_commands
from discord.ext import commands
import logging
import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger('realbot')

class RateLimiterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Structure: {channel_id: {user_id: {"limit": timedelta, "last_message_time": datetime}}}
        self.rate_limits: Dict[int, Dict[int, Dict[str, Any]]] = {}
        logger.info("RateLimiterCog cog initialized")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        if isinstance(message.author, discord.Member) and message.author.guild_permissions.administrator:
            return

        channel_id = message.channel.id
        user_id = message.author.id

        if channel_id in self.rate_limits and user_id in self.rate_limits[channel_id]:
            user_limit = self.rate_limits[channel_id][user_id]
            limit_delta = user_limit["limit"]
            last_msg_time = user_limit["last_message_time"]
            now = datetime.datetime.now(datetime.timezone.utc)

            if last_msg_time is not None and (now - last_msg_time) < limit_delta:
                try:
                    await message.delete()
                    logger.info(f"Deleted rate-limited message from {message.author} ({user_id}) in #{message.channel.name}")
                except discord.Forbidden:
                    logger.error(f"Missing permissions to delete a rate-limited message in #{message.channel.name}")
                except discord.NotFound:
                    pass # Message was already deleted
                except Exception:
                    logger.exception(f"An unexpected error occurred while deleting a rate-limited message from {message.author}")
            else:
                self.rate_limits[channel_id][user_id]["last_message_time"] = now

    @commands.command(name="ratelimit", help="Sets a message rate limit for a user in the current channel.")
    @commands.has_permissions(manage_messages=True)
    async def ratelimit_prefix(self, ctx: commands.Context, user: discord.Member, limit_in_secs: int):
        logger.info(f"!ratelimit invoked by {ctx.author} for user {user.name} with limit {limit_in_secs}s")
        
        channel_id = ctx.channel.id
        user_id = user.id

        if limit_in_secs > 0:
            self.rate_limits.setdefault(channel_id, {})
            self.rate_limits[channel_id][user_id] = {
                "limit": datetime.timedelta(seconds=limit_in_secs),
                "last_message_time": None
            }
            await ctx.send(f"✅ Rate limit for {user.mention} set to 1 message every {limit_in_secs} seconds in this channel.")
            logger.info(f"Successfully set rate limit for {user.name} in #{ctx.channel.name}")
        else:
            if channel_id in self.rate_limits and user_id in self.rate_limits[channel_id]:
                del self.rate_limits[channel_id][user_id]
                if not self.rate_limits[channel_id]:
                    del self.rate_limits[channel_id] # Clean up empty channel entries
                await ctx.send(f"✅ Rate limit for {user.mention} has been removed from this channel.")
                logger.info(f"Successfully removed rate limit for {user.name} in #{ctx.channel.name}")
            else:
                await ctx.send(f"⚠️ No rate limit was set for {user.mention} in this channel.")
    
    @ratelimit_prefix.error
    async def ratelimit_prefix_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Invalid user or number provided. Usage: `!ratelimit @user <seconds>`")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument. Usage: `!ratelimit @user <seconds>`")
        else:
            logger.error(f"Error in !ratelimit command: {error}")
            logger.exception("Exception in !ratelimit command")
            await ctx.send("An unexpected error occurred.")


    ratelimit_group = app_commands.Group(name="ratelimit", description="Commands to manage user message rate limits.")

    @ratelimit_group.command(name="set", description="Set a message rate limit for a user in this channel.")
    @app_commands.describe(user="The user to rate limit.", seconds="The minimum number of seconds between messages.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def ratelimit_set_slash(self, interaction: discord.Interaction, user: discord.Member, seconds: app_commands.Range[int, 1, 86400]):
        logger.info(f"/ratelimit set invoked by {interaction.user} for user {user.name} with limit {seconds}s")
        
        channel_id = interaction.channel.id
        user_id = user.id

        self.rate_limits.setdefault(channel_id, {})
        self.rate_limits[channel_id][user_id] = {
            "limit": datetime.timedelta(seconds=seconds),
            "last_message_time": None
        }
        await interaction.response.send_message(f"✅ Rate limit for {user.mention} set to 1 message every {seconds} seconds in this channel.", ephemeral=True)
        logger.info(f"Successfully set rate limit for {user.name} in #{interaction.channel.name}")

    @ratelimit_group.command(name="remove", description="Remove a message rate limit for a user in this channel.")
    @app_commands.describe(user="The user to remove the rate limit from.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def ratelimit_remove_slash(self, interaction: discord.Interaction, user: discord.Member):
        logger.info(f"/ratelimit remove invoked by {interaction.user} for user {user.name}")
        
        channel_id = interaction.channel.id
        user_id = user.id

        if channel_id in self.rate_limits and user_id in self.rate_limits[channel_id]:
            del self.rate_limits[channel_id][user_id]
            if not self.rate_limits[channel_id]:
                del self.rate_limits[channel_id]
            await interaction.response.send_message(f"✅ Rate limit for {user.mention} has been removed from this channel.", ephemeral=True)
            logger.info(f"Successfully removed rate limit for {user.name} in #{interaction.channel.name}")
        else:
            await interaction.response.send_message(f"⚠️ No rate limit was set for {user.mention} in this channel.", ephemeral=True)

    @ratelimit_group.command(name="view", description="View all active rate limits in this channel.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def ratelimit_view_slash(self, interaction: discord.Interaction):
        logger.info(f"/ratelimit view invoked by {interaction.user} in #{interaction.channel.name}")
        
        channel_id = interaction.channel.id
        
        if channel_id in self.rate_limits and self.rate_limits[channel_id]:
            embed = discord.Embed(
                title=f"Active Rate Limits in #{interaction.channel.name}",
                color=discord.Color.blue()
            )
            description = ""
            for user_id, limit_info in self.rate_limits[channel_id].items():
                user = interaction.guild.get_member(user_id)
                user_mention = user.mention if user else f"`User ID: {user_id}`"
                seconds = limit_info['limit'].total_seconds()
                description += f"{user_mention}: 1 message per **{int(seconds)}** seconds\n"
            embed.description = description
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("There are no active rate limits in this channel.", ephemeral=True)

    @ratelimit_set_slash.error
    @ratelimit_remove_slash.error
    @ratelimit_view_slash.error
    async def on_ratelimit_slash_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("You don't have the `Manage Messages` permission to use this command.", ephemeral=True)
        else:
            logger.error(f"Error in /ratelimit slash command: {error}")
            logger.exception("Exception in /ratelimit slash command")
            if not interaction.response.is_done():
                await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RateLimiterCog(bot))