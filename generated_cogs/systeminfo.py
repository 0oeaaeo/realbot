import discord
from discord import app_commands
from discord.ext import commands
import logging
import psutil
import platform
import os
import time
import datetime

logger = logging.getLogger('realbot')

class SystemInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        try:
            self.process = psutil.Process(os.getpid())
        except psutil.NoSuchProcess:
            logger.error("Could not get process PID for system info cog.")
            self.process = None
        self.start_time = time.time()
        logger.info("SystemInfo cog initialized")

    def format_bytes(self, size_bytes: int) -> str:
        """Converts bytes to a human-readable format."""
        if size_bytes is None:
            return "N/A"
        if size_bytes == 0:
            return "0B"
        power = 1024
        power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
        i = 0
        while size_bytes >= power and i < len(power_labels):
            size_bytes /= power
            i += 1
        return f"{size_bytes:.2f} {power_labels[i]}B"

    def format_timedelta(self, td: datetime.timedelta) -> str:
        """Formats a timedelta object into a human-readable string."""
        days, remainder = divmod(td.total_seconds(), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s"

    @commands.command(name="uhtest", help="Reports full system information.")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def uhtest(self, ctx: commands.Context):
        """Provides detailed system and bot information."""
        logger.info(f"!uhtest invoked by {ctx.author} in guild {ctx.guild.id}")

        try:
            async with ctx.typing():
                # CPU Info
                cpu_percent = await self.bot.loop.run_in_executor(None, psutil.cpu_percent, 1)
                cpu_cores_physical = psutil.cpu_count(logical=False)
                cpu_cores_logical = psutil.cpu_count(logical=True)
                cpu_freq = psutil.cpu_freq()

                # Memory Info
                virtual_mem = psutil.virtual_memory()
                swap_mem = psutil.swap_memory()

                # Disk Info
                disk_usage = psutil.disk_usage('/')

                # Uptime
                system_boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
                system_uptime = datetime.datetime.now() - system_boot_time
                bot_uptime_delta = datetime.timedelta(seconds=int(time.time() - self.start_time))

                # Bot Process Info
                bot_mem_usage = self.process.memory_info().rss if self.process else None

                embed = discord.Embed(
                    title="System & Bot Health Report",
                    color=discord.Color.blue(),
                    timestamp=ctx.message.created_at
                )
                embed.set_footer(
                    text=f"Requested by {ctx.author.display_name}", 
                    icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url
                )

                # CPU Field
                cpu_info = (
                    f"**Usage:** {cpu_percent}%\n"
                    f"**Cores:** {cpu_cores_physical} Physical / {cpu_cores_logical} Logical\n"
                    f"**Frequency:** {cpu_freq.current:.2f} MHz (Max: {cpu_freq.max:.2f} MHz)" if cpu_freq else "**Frequency:** N/A"
                )
                embed.add_field(name="🖥️ CPU", value=cpu_info, inline=True)

                # Memory Field
                mem_info = (
                    f"**RAM:** {self.format_bytes(virtual_mem.used)} / {self.format_bytes(virtual_mem.total)} ({virtual_mem.percent}%)\n"
                    f"**Swap:** {self.format_bytes(swap_mem.used)} / {self.format_bytes(swap_mem.total)} ({swap_mem.percent}%)\n"
                    f"**Bot Usage:** {self.format_bytes(bot_mem_usage)}"
                )
                embed.add_field(name="💾 Memory", value=mem_info, inline=True)

                # Disk Field
                disk_info = (
                    f"**Usage:** {self.format_bytes(disk_usage.used)} / {self.format_bytes(disk_usage.total)} ({disk_usage.percent}%)"
                )
                embed.add_field(name="💽 Disk (Root)", value=disk_info, inline=True)

                # Uptime Field
                uptime_info = (
                    f"**System:** {self.format_timedelta(system_uptime)}\n"
                    f"**Bot:** {self.format_timedelta(bot_uptime_delta)}"
                )
                embed.add_field(name="⏱️ Uptime", value=uptime_info, inline=True)

                # Versions Field
                version_info = (
                    f"**Python:** {platform.python_version()}\n"
                    f"**discord.py:** {discord.__version__}"
                )
                embed.add_field(name="🐍 Versions", value=version_info, inline=True)
                
                # Empty field for layout alignment
                embed.add_field(name="\u200b", value="\u200b", inline=True)

            await ctx.send(embed=embed)
            logger.info(f"Successfully sent system info for !uhtest requested by {ctx.author}")

        except Exception as e:
            logger.exception(f"Exception in uhtest command invoked by {ctx.author}")
            await ctx.send(f"An error occurred while fetching system information: `{e}`")

    @uhtest.error
    async def uhtest_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"This command is on cooldown. Please try again in {error.retry_after:.2f} seconds.", delete_after=5)
            logger.warning(f"uhtest command on cooldown for {ctx.author}")
        else:
            logger.error(f"An unhandled error occurred in the uhtest command: {error}")
            await ctx.send("An unexpected error occurred. Please check the logs for more details.")

async def setup(bot):
    await bot.add_cog(SystemInfo(bot))