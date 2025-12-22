import discord
from discord.ext import commands
import logging
import os
import json

logger = logging.getLogger('realbot')

class BotAdminManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.admins_file = "bot_admins.json"
        
        # Initialize bot_admins set if not present
        if not hasattr(bot, 'bot_admins'):
            bot.bot_admins = set()

        # Load owners first
        if bot.owner_ids:
            bot.bot_admins.update(bot.owner_ids)
            logger.info(f"Initialized bot_admins with owner IDs: {bot.owner_ids}")
        elif bot.owner_id:
            bot.bot_admins.add(bot.owner_id)
            logger.info(f"Initialized bot_admins with owner ID: {bot.owner_id}")

        # Load persisted admins
        self.load_admins()
        logger.info("BotAdminManager cog initialized")

    def load_admins(self):
        if os.path.exists(self.admins_file):
            try:
                with open(self.admins_file, 'r') as f:
                    admins = json.load(f)
                    # Ensure they are ints
                    admins = {int(x) for x in admins}
                    self.bot.bot_admins.update(admins)
                logger.info(f"Loaded {len(admins)} admins from {self.admins_file}")
            except Exception as e:
                logger.error(f"Failed to load bot admins from file: {e}")

    def save_admins(self):
        try:
            # We save the current state of bot_admins
            # (including owners, which is fine, they are admins)
            with open(self.admins_file, 'w') as f:
                json.dump(list(self.bot.bot_admins), f)
            logger.info("Saved bot admins to file")
        except Exception as e:
            logger.error(f"Failed to save bot admins to file: {e}")

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Checks if the user is the bot owner."""
        return await self.bot.is_owner(ctx.author)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Cog-specific error handler."""
        if isinstance(error, commands.CheckFailure):
            logger.warning(f"User {ctx.author} (ID: {ctx.author.id}) tried to use an owner-only command: {ctx.command.name}")
            await ctx.reply("Sorry, this command can only be used by the bot owner.", ephemeral=True)
        elif isinstance(error, commands.MemberNotFound):
            logger.error(f"MemberNotFound error in '{ctx.command.name}': {error}")
            await ctx.reply(f"Could not find a member named `{error.argument}`. Please check the name or ID.", ephemeral=True)
        elif isinstance(error, commands.MissingRequiredArgument):
            logger.error(f"MissingRequiredArgument error in '{ctx.command.name}': {error}")
            await ctx.reply(f"You are missing a required argument: `{error.param.name}`. Please provide a user.", ephemeral=True)
        else:
            logger.exception("An unhandled exception occurred in the BotAdminManager cog")
            await ctx.reply("An unexpected error occurred. Please check the logs.", ephemeral=True)

    @commands.command(name="addadmin")
    async def add_admin(self, ctx: commands.Context, user: discord.Member):
        """Adds a user as a bot admin. Owner only."""
        logger.info(f"addadmin invoked by {ctx.author} for target {user.name}")
        try:
            if user.bot:
                logger.warning(f"Attempted to add a bot ({user.name}) as an admin.")
                await ctx.reply("Bots cannot be added as admins.", ephemeral=True)
                return

            if user.id in self.bot.bot_admins:
                logger.info(f"User {user.name} is already a bot admin.")
                await ctx.reply(f"{user.mention} is already a bot admin.", ephemeral=True)
                return

            self.bot.bot_admins.add(user.id)
            self.save_admins()
            logger.info(f"Successfully added {user.name} (ID: {user.id}) as a bot admin.")
            await ctx.reply(f"✅ Successfully added {user.mention} as a bot admin.")

        except Exception as e:
            logger.exception(f"Exception in add_admin command for user {user.name}")
            await ctx.reply("An unexpected error occurred while trying to add the admin.", ephemeral=True)

    @commands.command(name="removeadmin")
    async def remove_admin(self, ctx: commands.Context, user: discord.User):
        """Removes a user from bot admins. Owner only."""
        logger.info(f"removeadmin invoked by {ctx.author} for target {user.name}")
        try:
            # Prevent owner from removing themselves
            if user.id == self.bot.owner_id or (self.bot.owner_ids and user.id in self.bot.owner_ids):
                logger.warning(f"Owner {ctx.author} attempted to remove themselves from admins.")
                await ctx.reply("The bot owner cannot be removed from the admin list.", ephemeral=True)
                return

            if user.id not in self.bot.bot_admins:
                logger.info(f"User {user.name} is not a bot admin.")
                await ctx.reply(f"{user.mention} is not currently a bot admin.", ephemeral=True)
                return

            self.bot.bot_admins.remove(user.id)
            self.save_admins()
            logger.info(f"Successfully removed {user.name} (ID: {user.id}) from bot admins.")
            await ctx.reply(f"✅ Successfully removed {user.mention} from bot admins.")

        except Exception as e:
            logger.exception(f"Exception in remove_admin command for user {user.name}")
            await ctx.reply("An unexpected error occurred while trying to remove the admin.", ephemeral=True)

    @commands.command(name="listadmins")
    async def list_admins(self, ctx: commands.Context):
        """Lists all current bot admins. Owner only."""
        logger.info(f"listadmins invoked by {ctx.author}")
        try:
            if not self.bot.bot_admins:
                await ctx.send("There are currently no bot admins.")
                return

            embed = discord.Embed(
                title="Current Bot Admins",
                color=discord.Color.blue()
            )
            
            admin_mentions = []
            for admin_id in self.bot.bot_admins:
                user = self.bot.get_user(admin_id)
                if user:
                    admin_mentions.append(f"- {user.mention} (`{admin_id}`)")
                else:
                    admin_mentions.append(f"- *Unknown User* (`{admin_id}`)")

            embed.description = "\n".join(admin_mentions)
            await ctx.send(embed=embed)
            logger.info(f"Successfully listed bot admins for {ctx.author}.")

        except Exception as e:
            logger.exception("Exception in list_admins command")
            await ctx.send("An error occurred while fetching the admin list.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(BotAdminManager(bot))