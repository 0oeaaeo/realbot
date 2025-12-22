import discord
from discord import app_commands
from discord.ext import commands
import logging

logger = logging.getLogger('realbot')

class DebugHelper(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("DebugHelper cog initialized")

    # The following commands are a hypothetical implementation based on your request.
    # Review the comments within to diagnose potential issues with your own code.

    async def cog_check(self, ctx: commands.Context) -> bool:
        # A global check can be useful, but ensure it doesn't interfere with command-specific checks.
        # For this example, we'll assume it always passes.
        return True

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """A local error handler to provide specific feedback."""
        logger.error(f"Error in command '{ctx.command}' invoked by {ctx.author}: {error}")
        
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"You lack the required Discord permissions to use this command. You need: `{', '.join(error.missing_permissions)}`")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send(f"I don't have the required permissions to perform this action. I need: `{', '.join(error.missing_permissions)}`")
        elif isinstance(error, commands.CheckFailure):
            # This is often triggered by custom checks, like a custom admin system.
            await ctx.send("You do not meet the custom requirements to run this command (e.g., you are not a registered admin).")
        elif isinstance(error, commands.HierarchyError):
            await ctx.send("I cannot modify a member who has a role higher than or equal to my highest role.")
        else:
            logger.exception(f"An unhandled exception occurred in command {ctx.command}")
            await ctx.send("An unexpected error occurred. Please check the logs.")

    # This is a mock admin check. If your system uses something similar,
    # ensure it's being checked correctly in the commands that need it.
    async def is_custom_admin(self, user_id: int) -> bool:
        """
        Hypothetical check for a custom admin system.
        In a real scenario, this would check a database or a config file.
        For this example, we'll pretend there's a file `admins.txt`.
        """
        logger.debug(f"Performing custom admin check for user ID: {user_id}")
        # In a real bot, this could be a common point of failure.
        # Is the file being read correctly? Is the database connection alive?
        # Is the data format correct?
        try:
            # This is a simplified example.
            # with open('admins.txt', 'r') as f:
            #     admins = [int(line.strip()) for line in f]
            # return user_id in admins
            # Forcing a failure case to demonstrate the error handler.
            # return user_id in [123456789] # Replace with actual admin IDs in your system
            return True # Assuming check passes for demonstration.
        except Exception:
            logger.exception("Failed to read from the custom admin source.")
            return False

    def custom_admin_check():
        """A decorator for commands requiring custom admin privileges."""
        async def predicate(ctx: commands.Context):
            cog = ctx.cog
            if cog:
                return await cog.is_custom_admin(ctx.author.id)
            return False
        return commands.check(predicate)

    @commands.command(name="addadmin")
    @commands.is_owner() # Only the bot owner can add new admins.
    async def add_admin(self, ctx: commands.Context, member: discord.Member):
        """
        Adds a user to a custom admin list (hypothetical).
        CRITICAL: This command ONLY adds a user to a *custom* list. It does NOT grant
        them Discord permissions like 'Administrator' or 'Manage Nicknames'.
        """
        logger.info(f"addadmin invoked by {ctx.author} for target {member}")
        # In a real implementation, you would write member.id to a database or file here.
        # logger.debug(f"Writing {member.id} to admin storage.")
        await ctx.send(f"✅ {member.mention} has been added to the custom admin list. "
                       f"**Note:** This does not grant them Discord permissions.")
        logger.info(f"Successfully added {member} to custom admin list.")


    @commands.command(name="forcenick")
    # Multiple checks can be stacked. They are processed from the bottom up.
    # 1. First, it checks if the user is a custom admin.
    # 2. Then, it checks if the user has the 'Manage Nicknames' Discord permission.
    # BOTH must pass. An admin added via !addadmin might fail the second check.
    @commands.has_permissions(manage_nicknames=True)
    @custom_admin_check()
    async def force_nick(self, ctx: commands.Context, member: discord.Member, *, new_nickname: str):
        """
        Forces a nickname change on a member.
        
        POSSIBLE POINTS OF FAILURE FOR AN ADMIN:
        1.  `!addadmin` does not grant the `Manage Nicknames` Discord permission. The admin's ROLE needs it.
        2.  The Bot's role is not high enough in the role hierarchy to change the `member`'s nickname.
        3.  The `member` is the server owner, whose nickname cannot be changed by a bot.
        4.  The nickname is longer than 32 characters.
        """
        logger.info(f"forcenick invoked by {ctx.author} on {member} to set nickname '{new_nickname}'")

        if member.id == ctx.guild.owner_id:
            await ctx.send("I cannot change the nickname of the server owner.")
            logger.warning(f"Attempted to change owner's nickname by {ctx.author}")
            return
            
        if ctx.author.top_role <= member.top_role and ctx.guild.owner_id != ctx.author.id:
            await ctx.send("You can only change nicknames of members with roles below your own.")
            logger.warning(f"{ctx.author} tried to change nickname of {member} with equal or higher role.")
            return

        original_nick = member.display_name
        try:
            logger.debug(f"Attempting to call member.edit for {member.id}")
            await member.edit(nick=new_nickname, reason=f"Changed by {ctx.author.name}")
            await ctx.send(f"Successfully changed `{original_nick}`'s nickname to `{new_nickname}`.")
            logger.info(f"Successfully changed nickname for {member.id}")
        except discord.Forbidden as e:
            # This is the most common error. It means the BOT lacks permissions.
            logger.error(f"Forbidden to change nickname for {member.id}: {e}. Check bot role hierarchy and permissions.")
            await ctx.send("I failed to change the nickname. This is likely because:\n"
                         "1. My role is not high enough to manage this user.\n"
                         "2. I am missing the `Manage Nicknames` permission in this server.")
        except discord.HTTPException as e:
            logger.exception(f"HTTPException while trying to change nickname for {member.id}")
            await ctx.send(f"An API error occurred: {e.status} - {e.text}")


async def setup(bot: commands.Bot):
    await bot.add_cog(DebugHelper(bot))