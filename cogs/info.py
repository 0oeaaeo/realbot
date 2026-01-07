"""
Info Cog - Displays comprehensive bot and system information.

Shows servers, active users, and detailed system stats including
kernel, CPU, RAM, disk, OS, latency, and more.
"""

import discord
from discord.ext import commands
import os
import platform
import time
import asyncio
import logging
from datetime import datetime

import psutil

logger = logging.getLogger('realbot')


class InfoCog(commands.Cog):
    """Bot and system info command."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = datetime.now()
        logger.info("Info cog initialized")
    
    def _get_size(self, bytes_val: int, suffix: str = "B") -> str:
        """Convert bytes to human readable format."""
        for unit in ["", "K", "M", "G", "T", "P"]:
            if abs(bytes_val) < 1024.0:
                return f"{bytes_val:.1f}{unit}{suffix}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f}E{suffix}"
    
    def _get_uptime(self) -> str:
        """Get bot uptime as a formatted string."""
        delta = datetime.now() - self.start_time
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        
        return " ".join(parts)
    
    def _get_system_uptime(self) -> str:
        """Get system uptime as a formatted string."""
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        delta = datetime.now() - boot_time
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        
        return " ".join(parts)
    
    @commands.command(name="info")
    async def info(self, ctx: commands.Context):
        """
        Show comprehensive bot and system information.
        
        Displays:
        - All servers the bot is in
        - Active user counts
        - Full system info (kernel, CPU, RAM, disk, OS, latency)
        """
        # Measure latency
        start = time.perf_counter()
        msg = await ctx.send("📊 Gathering info...")
        api_latency = (time.perf_counter() - start) * 1000
        ws_latency = self.bot.latency * 1000
        
        # Gather all info in executor to avoid blocking
        loop = asyncio.get_running_loop()
        
        def gather_system_info():
            # CPU info
            cpu_percent = psutil.cpu_percent(interval=0.5)
            cpu_freq = psutil.cpu_freq()
            cpu_count_logical = psutil.cpu_count(logical=True)
            cpu_count_physical = psutil.cpu_count(logical=False)
            
            # Memory info
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # Disk info
            disk = psutil.disk_usage('/')
            
            # Load average (Unix)
            try:
                load_avg = os.getloadavg()
            except (OSError, AttributeError):
                load_avg = None
            
            # Try to get kernel info
            try:
                uname = platform.uname()
            except:
                uname = None
            
            return {
                'cpu_percent': cpu_percent,
                'cpu_freq': cpu_freq,
                'cpu_count_logical': cpu_count_logical,
                'cpu_count_physical': cpu_count_physical,
                'mem': mem,
                'swap': swap,
                'disk': disk,
                'load_avg': load_avg,
                'uname': uname,
            }
        
        sys_info = await loop.run_in_executor(None, gather_system_info)
        
        # Calculate bot stats
        total_guilds = len(self.bot.guilds)
        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        total_channels = sum(len(g.channels) for g in self.bot.guilds)
        
        # Get unique online/active users across all guilds
        online_members = 0
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.status != discord.Status.offline and not member.bot:
                    online_members += 1
        
        # Build the embed
        embed = discord.Embed(
            title="🤖 Bot & System Information",
            color=0x00BFFF,
            timestamp=datetime.now()
        )
        
        # === BOT INFO ===
        bot_info = (
            f"**Servers:** {total_guilds}\n"
            f"**Total Members:** {total_members:,}\n"
            f"**Online Users:** {online_members:,}\n"
            f"**Channels:** {total_channels:,}\n"
            f"**Bot Uptime:** {self._get_uptime()}"
        )
        embed.add_field(name="🤖 Bot Stats", value=bot_info, inline=True)
        
        # === LATENCY ===
        latency_info = (
            f"**WebSocket:** {ws_latency:.1f}ms\n"
            f"**API:** {api_latency:.1f}ms"
        )
        embed.add_field(name="📡 Latency", value=latency_info, inline=True)
        
        # === OS / KERNEL ===
        if sys_info['uname']:
            u = sys_info['uname']
            os_info = (
                f"**OS:** {u.system} {u.release}\n"
                f"**Kernel:** {u.version[:50]}{'...' if len(u.version) > 50 else ''}\n"
                f"**Arch:** {u.machine}\n"
                f"**Hostname:** {u.node}\n"
                f"**Python:** {platform.python_version()}"
            )
        else:
            os_info = f"**OS:** {platform.system()} {platform.release()}\n**Python:** {platform.python_version()}"
        embed.add_field(name="💻 System", value=os_info, inline=False)
        
        # === CPU ===
        cpu_freq_str = ""
        if sys_info['cpu_freq']:
            cpu_freq_str = f"\n**Frequency:** {sys_info['cpu_freq'].current:.0f}MHz"
        
        load_str = ""
        if sys_info['load_avg']:
            load_str = f"\n**Load Avg:** {sys_info['load_avg'][0]:.2f} / {sys_info['load_avg'][1]:.2f} / {sys_info['load_avg'][2]:.2f}"
        
        cpu_info = (
            f"**Usage:** {sys_info['cpu_percent']}%\n"
            f"**Cores:** {sys_info['cpu_count_physical']} physical, {sys_info['cpu_count_logical']} logical"
            f"{cpu_freq_str}"
            f"{load_str}"
        )
        embed.add_field(name="🔥 CPU", value=cpu_info, inline=True)
        
        # === MEMORY ===
        mem = sys_info['mem']
        swap = sys_info['swap']
        mem_info = (
            f"**RAM:** {self._get_size(mem.used)} / {self._get_size(mem.total)} ({mem.percent}%)\n"
            f"**Available:** {self._get_size(mem.available)}\n"
            f"**Swap:** {self._get_size(swap.used)} / {self._get_size(swap.total)} ({swap.percent}%)"
        )
        embed.add_field(name="🧠 Memory", value=mem_info, inline=True)
        
        # === DISK ===
        disk = sys_info['disk']
        disk_info = (
            f"**Used:** {self._get_size(disk.used)} / {self._get_size(disk.total)} ({disk.percent}%)\n"
            f"**Free:** {self._get_size(disk.free)}"
        )
        embed.add_field(name="💾 Disk (/)", value=disk_info, inline=True)
        
        # === UPTIME ===
        uptime_info = (
            f"**System:** {self._get_system_uptime()}\n"
            f"**Bot:** {self._get_uptime()}"
        )
        embed.add_field(name="⏱️ Uptime", value=uptime_info, inline=True)
        
        # === SERVER LIST ===
        if total_guilds <= 10:
            server_list = "\n".join([
                f"• **{g.name}** ({g.member_count:,} members)"
                for g in sorted(self.bot.guilds, key=lambda x: x.member_count or 0, reverse=True)
            ])
        else:
            top_servers = sorted(self.bot.guilds, key=lambda x: x.member_count or 0, reverse=True)[:10]
            server_list = "\n".join([
                f"• **{g.name}** ({g.member_count:,} members)"
                for g in top_servers
            ])
            server_list += f"\n*...and {total_guilds - 10} more*"
        
        embed.add_field(name="🌐 Servers", value=server_list or "No servers", inline=False)
        
        # Footer
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url if ctx.author.display_avatar else None)
        
        await msg.edit(content=None, embed=embed)
    
    @info.error
    async def info_error(self, ctx: commands.Context, error):
        """Handle errors for the info command."""
        logger.error(f"Info command error: {error}")
        await ctx.send(f"❌ An error occurred: {str(error)[:200]}")


async def setup(bot):
    await bot.add_cog(InfoCog(bot))
