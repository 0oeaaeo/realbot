import discord
from discord.ext import commands

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def ping(self, ctx, host: str = None):
        await ctx.send("pong")

async def setup(bot):
    await bot.add_cog(Utility(bot))
