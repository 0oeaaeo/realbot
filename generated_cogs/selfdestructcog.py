import discord
from discord import app_commands
from discord.ext import commands

class SelfDestructCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{self.__class__.__name__} has been loaded.")

    @commands.command(name="hello")
    async def say_goodbye_and_unload(self, ctx: commands.Context):
        """Sends 'goodbye' and then unloads this cog."""
        try:
            await ctx.send("goodbye")
            # The name of the extension is the file name (module path)
            extension_name = self.__class__.__module__
            await self.bot.unload_extension(extension_name)
        except commands.ExtensionNotLoaded:
            await ctx.send(f"Error: The cog '{self.__class__.__name__}' was already unloaded or not found.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"An unexpected error occurred while trying to unload the cog: {e}", ephemeral=True)
            print(f"Error unloading {self.__class__.__name__}: {e}")

    @say_goodbye_and_unload.error
    async def say_goodbye_error(self, ctx: commands.Context, error: commands.CommandError):
        """Error handler for the hello command."""
        if isinstance(error, commands.CommandInvokeError):
            await ctx.send("An error occurred while executing the command.", ephemeral=True)
        else:
            await ctx.send(f"An error occurred: {error}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(SelfDestructCog(bot))