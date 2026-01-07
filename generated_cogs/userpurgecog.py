import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio

logger = logging.getLogger('realbot')

class UserPurgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("UserPurgeCog cog initialized")

    @commands.command(name="purge", help="Deletes all messages from a specified user in the current channel.")
    @commands.is_owner()
    @commands.guild_only()
    async def purge(self, ctx: commands.Context, user: discord.Member):
        """Deletes all messages from a tagged user in the channel, no matter how old."""
        logger.info(f"!purge invoked by {ctx.author} to clear messages from {user.name} in channel {ctx.channel.name}")

        try:
            msg = await ctx.send(f"🔄 Purging all messages from {user.mention} in this channel. This might take a very long time...")
            
            deleted_count = 0
            
            # The purge command with bulk=False will delete messages one-by-one, bypassing the 14-day limit.
            # We set a practically infinite limit to scan the entire channel history.
            # discord.py returns the list of messages that were deleted.
            deleted_messages = await ctx.channel.purge(limit=None, check=lambda m: m.author.id == user.id, bulk=False)
            deleted_count = len(deleted_messages)

            await msg.edit(content=f"✅ Successfully purged **{deleted_count}** messages from {user.mention}.")
            logger.info(f"Successfully purged {deleted_count} messages from {user} ({user.id}) in channel {ctx.channel.id}")

        except discord.Forbidden:
            error_message = f"Error in !purge: I don't have the 'Manage Messages' permission in channel {ctx.channel.name}."
            logger.error(error_message)
            await ctx.send(f"❌ I lack the necessary permissions to delete messages in this channel. Please grant me the 'Manage Messages' permission.")
        except discord.HTTPException as e:
            error_message = f"An HTTP error occurred during purge: {e}"
            logger.exception(error_message)
            await ctx.send(f"❌ A Discord API error occurred. Please try again later. Details: `{e}`")
        except Exception as e:
            logger.exception(f"An unexpected exception occurred in !purge command")
            await ctx.send(f"❌ An unexpected error occurred. I have logged the details for my developer.")
            
async def setup(bot: commands.Bot):
    await bot.add_cog(UserPurgeCog(bot))