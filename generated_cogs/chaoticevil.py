import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
import datetime

class ChaoticEvil(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="entropy", help="Unleashes random chaotic energy upon the channel.")
    async def entropy(self, ctx):
        """
        A chaotic command that performs a random annoying or confused action.
        """
        actions = [
            self._fake_error,
            self._gaslight_delete,
            self._mock_user,
            self._ghost_ping,
            self._react_spam
        ]
        
        action = random.choice(actions)
        try:
            await action(ctx)
        except Exception as e:
            # Even the error handler is chaotic
            await ctx.send(f"Task failed successfully: {e}")

    async def _fake_error(self, ctx):
        embed = discord.Embed(
            title="CRITICAL KERNEL PANIC",
            description=f"User {ctx.author.name} caused a stack overflow in sector 7G.\nInitiating server shutdown sequence...",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(text="Error Code: 0xDEADBEEF")
        msg = await ctx.send(embed=embed)
        await asyncio.sleep(4)
        await msg.edit(content="Just kidding. But seriously, don't do that again.", embed=None)

    async def _gaslight_delete(self, ctx):
        # Replies then deletes everything to confuse the user
        await ctx.message.add_reaction("👀")
        msg = await ctx.send(f"{ctx.author.mention} I can't believe you just said that. The admins have been notified.")
        await asyncio.sleep(3)
        await msg.delete()
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        # The user sees nothing but the memory of the bot scolding them.

    async def _mock_user(self, ctx):
        # SpongeBob case mocking
        content = ctx.message.content.replace("!entropy", "").strip()
        if not content:
            content = "I can't mock silence"
        
        mocked_text = "".join(
            c.upper() if i % 2 == 0 else c.lower() 
            for i, c in enumerate(content)
        )
        await ctx.send(f"{mocked_text} 🤪", reference=ctx.message)

    async def _ghost_ping(self, ctx):
        # Pings the user then immediately deletes the ping
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
            
        msg = await ctx.send(f"{ctx.author.mention} behind you!")
        await asyncio.sleep(0.5)
        await msg.delete()

    async def _react_spam(self, ctx):
        # Adds annoying reactions
        emojis = ["🤡", "💩", "💀", "👎", "🙄", "🚮", "🤨"]
        random.shuffle(emojis)
        for emoji in emojis[:4]:
            try:
                await ctx.message.add_reaction(emoji)
                await asyncio.sleep(0.2)
            except discord.Forbidden:
                break

    @app_commands.command(name="curse", description="Casts a minor inconvenience curse on a user.")
    @app_commands.describe(target="The user to curse")
    async def curse(self, interaction: discord.Interaction, target: discord.User):
        curses = [
            "may your socks always be slightly damp.",
            "may you never find the cool side of the pillow.",
            "may your wifi disconnect only during ranked matches.",
            "may you always step on a Lego in the dark.",
            "may your headphones catch on every door handle.",
            "may your phone charger only work at a specific angle.",
            "may you always feel like you have to sneeze but can't."
        ]
        chosen_curse = random.choice(curses)
        
        embed = discord.Embed(
            title="🧙‍♂️ Curse Cast!",
            description=f"{target.mention}, {chosen_curse}",
            color=discord.Color.purple()
        )
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(ChaoticEvil(bot))