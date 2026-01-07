import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Union

# This import is specified by the user prompt's requirements
from utils.discord_search import search_messages

logger = logging.getLogger('realbot')

class ServerAnalyticsCog(commands.Cog):
    """
    A cog for analyzing server activity across all guilds the bot is a member of.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("ServerAnalyticsCog cog initialized")

    async def _get_activity_report(self) -> list:
        """
        Gathers data on the most active channel for each guild.
        """
        activity_report = []
        guilds = self.bot.guilds
        
        for guild in guilds:
            most_active_channel = None
            max_messages = -1
            
            logger.debug(f"Analyzing channels in guild: {guild.name} ({guild.id})")
            
            for channel in guild.text_channels:
                if not channel.permissions_for(guild.me).read_message_history:
                    continue

                try:
                    # Using search_messages to gauge activity as per the prompt's requirement
                    # A limit of 100 provides a reasonable sample size for recent activity
                    messages = await search_messages(
                        guild_id=str(guild.id),
                        channel_id=str(channel.id),
                        limit=100
                    )
                    
                    message_count = len(messages)
                    
                    if message_count > max_messages:
                        max_messages = message_count
                        most_active_channel = channel
                
                except Exception:
                    logger.exception(f"Exception while searching messages in {channel.name} ({channel.id})")
                    continue
            
            if most_active_channel:
                activity_report.append((guild.name, most_active_channel, max_messages))
            else:
                activity_report.append((guild.name, None, 0))
                
        return activity_report

    async def _run_server_activity_command(self, interaction_or_ctx: Union[discord.Interaction, commands.Context]):
        """
        Shared logic for running the command and sending the response.
        """
        user = interaction_or_ctx.author if isinstance(interaction_or_ctx, commands.Context) else interaction_or_ctx.user
        logger.info(f"serveractivity invoked by {user} ({user.id})")

        try:
            report = await self._get_activity_report()
            
            embed = discord.Embed(
                title="Server Activity Report",
                description="The most active channel in each server based on recent messages.",
                color=discord.Color.blue()
            )
            
            description_lines = []
            if not report:
                description_lines.append("The bot is not currently in any servers.")
            else:
                # Sort report by guild name for consistent output
                report.sort(key=lambda x: x[0])
                for guild_name, channel, count in report:
                    if channel:
                        description_lines.append(f"**{guild_name}**: {channel.mention} ({count} recent messages found)")
                    else:
                        description_lines.append(f"**{guild_name}**: No accessible channels or activity found.")

            embed.description = "\n".join(description_lines)

            if isinstance(interaction_or_ctx, discord.Interaction):
                await interaction_or_ctx.followup.send(embed=embed)
            else:
                await interaction_or_ctx.send(embed=embed)

            logger.info("Successfully generated and sent server activity report.")

        except Exception:
            logger.exception("An unhandled exception occurred in _run_server_activity_command")
            error_message = "An error occurred while generating the report. Please check the logs."
            if isinstance(interaction_or_ctx, discord.Interaction):
                await interaction_or_ctx.followup.send(error_message, ephemeral=True)
            else:
                await interaction_or_ctx.send(error_message)

    @commands.command(name="serveractivity", help="Lists the most active channel in each server. (Owner only)")
    @commands.is_owner()
    async def prefix_server_activity(self, ctx: commands.Context):
        """Prefix command to list server activity."""
        async with ctx.typing():
            await self._run_server_activity_command(ctx)

    @app_commands.command(name="serveractivity", description="Lists the most active channel in each server the bot is in.")
    @app_commands.checks.is_owner()
    async def slash_server_activity(self, interaction: discord.Interaction):
        """Slash command to list server activity."""
        await interaction.response.defer(thinking=True, ephemeral=False)
        await self._run_server_activity_command(interaction)

    @slash_server_activity.error
    async def on_slash_server_activity_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for the slash command."""
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("You must be the bot owner to use this command.", ephemeral=True)
            logger.warning(f"Non-owner {interaction.user} ({interaction.user.id}) tried to use slash command serveractivity.")
        else:
            logger.error(f"Unhandled error in slash_server_activity: {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)
            else:
                await interaction.followup.send("An unexpected error occurred.", ephemeral=True)
                
    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Error handler for prefix commands in this cog."""
        if isinstance(error, commands.NotOwner):
            await ctx.send("You must be the bot owner to use this command.")
            logger.warning(f"Non-owner {ctx.author} ({ctx.author.id}) tried to use prefix command serveractivity.")
        else:
            logger.error(f"Error in cog ServerAnalyticsCog for command {ctx.command}: {error}")
            await ctx.send("An unexpected error occurred while processing the command.")

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerAnalyticsCog(bot))