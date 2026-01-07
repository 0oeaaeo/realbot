import discord
from discord.ext import commands
import logging
import asyncio

logger = logging.getLogger('realbot')

class VoiceProtectCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.protected_users = set()
        logger.info("VoiceProtectCog cog initialized")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.id not in self.protected_users:
            return

        # Check if the change was a server mute being applied
        if not before.mute and after.mute:
            logger.info(f"Protected user {member} ({member.id}) was server muted in {member.guild.name}. Attempting to unmute.")
            try:
                # Add a small delay to avoid race conditions with other bots or moderation actions
                await asyncio.sleep(1)
                await member.edit(mute=False)
                logger.info(f"Successfully unmuted protected user {member} ({member.id}).")
            except discord.Forbidden:
                logger.error(f"Failed to unmute {member} ({member.id}). Missing 'Mute Members' permission in {member.guild.name}.")
            except discord.HTTPException as e:
                logger.error(f"An HTTP error occurred while trying to unmute {member} ({member.id}): {e}")
            except Exception:
                logger.exception(f"An unexpected exception occurred in on_voice_state_update for member {member.id}")


    @commands.command(name="protect", help="Protects a user from being server muted in voice channels.")
    @commands.has_permissions(administrator=True)
    async def protect(self, ctx: commands.Context, member: discord.Member, state: str = "on"):
        """
        Automatically unmutes a protected user if they are server muted.
        Usage: !protect @user [on|off]
        """
        logger.info(f"'protect' command invoked by {ctx.author} for target {member} with state '{state}'.")
        
        state = state.lower()

        if state == "on":
            if member.id in self.protected_users:
                await ctx.send(f"{member.mention} is already protected.")
                return
            
            self.protected_users.add(member.id)
            logger.info(f"Added {member} ({member.id}) to the protected list.")
            await ctx.send(f"{member.mention} is now under voice mute protection. I will automatically unmute them if a moderator mutes them.")

        elif state == "off":
            if member.id not in self.protected_users:
                await ctx.send(f"{member.mention} is not currently protected.")
                return
            
            self.protected_users.remove(member.id)
            logger.info(f"Removed {member} ({member.id}) from the protected list.")
            await ctx.send(f"{member.mention} is no longer under voice mute protection.")

        else:
            await ctx.send("Invalid state. Please use 'on' or 'off'. Example: `!protect @user off`")

    @protect.error
    async def protect_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You do not have the required permissions (Administrator) to use this command.")
            logger.warning(f"{ctx.author} tried to use 'protect' command without permissions.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(f"Could not find a member named '{error.argument}'. Please tag them or use their ID.")
            logger.warning(f"Member not found in 'protect' command invocation by {ctx.author}: {error.argument}")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("You must specify a user to protect. Usage: `!protect @user [on|off]`")
        else:
            logger.exception(f"An unhandled error occurred in the 'protect' command: {error}")
            await ctx.send("An unexpected error occurred. Please check the logs.")

async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceProtectCog(bot))