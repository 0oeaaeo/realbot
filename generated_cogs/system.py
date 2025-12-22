import discord
from discord import app_commands
from discord.ext import commands
import psutil
import platform
import asyncio

class System(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="udead")
    async def udead(self, ctx):
        async with ctx.typing():
            uname = platform.uname()
            cpu_count = psutil.cpu_count(logical=True)
            # Run blocking cpu_percent in a separate thread
            cpu_percent = await asyncio.to_thread(psutil.cpu_percent, 1)
            memory = psutil.virtual_memory()

            embed = discord.Embed(title="System Status", color=discord.Color.green())
            embed.add_field(name="OS", value=f"{uname.system} {uname.release}", inline=False)
            embed.add_field(name="CPU Cores", value=str(cpu_count), inline=True)
            embed.add_field(name="CPU Usage", value=f"{cpu_percent}%", inline=True)
            embed.add_field(name="RAM Total", value=f"{memory.total / (1024**3):.2f} GB", inline=True)
            embed.add_field(name="RAM Used", value=f"{memory.used / (1024**3):.2f} GB ({memory.percent}%)", inline=True)

            await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(System(bot))