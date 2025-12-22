import discord
from discord import app_commands
from discord.ext import commands

class PingPong(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ping", help="Responds with pong")
    async def ping(self, ctx):
        try:
            await ctx.send("pong")
        except discord.HTTPException as e:
            await ctx.send(f"Failed to send message: {str(e)}")
        except Exception as e:
            await ctx.send(f"An unexpected error occurred: {str(e)}")

async def setup(bot):
    await bot.add_cog(PingPong(bot))