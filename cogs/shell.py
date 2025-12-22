import discord
from discord.ext import commands
import asyncio
import logging

logger = logging.getLogger('realbot')

class Shell(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("Shell cog initialized")

    @commands.command(name="shell")
    @commands.is_owner()
    async def shell(self, ctx: commands.Context, *, command: str):
        """Executes a shell command.

        Args:
            command: The command to execute.
        """
        logger.info(f"Shell command invoked by {ctx.author} with command: {command}")
        
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if stdout:
            output = stdout.decode()
            for i in range(0, len(output), 1990):
                 await ctx.send(f"```\n{output[i:i+1990]}\n```")

        if stderr:
            error_output = stderr.decode()
            for i in range(0, len(error_output), 1990):
                await ctx.send(f"```\n{error_output[i:i+1990]}\n```")

        if not stdout and not stderr:
            await ctx.send("Command executed with no output.")

async def setup(bot):
    await bot.add_cog(Shell(bot))
