import discord
import os
import logging
from logging.handlers import RotatingFileHandler
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# ===== LOGGING CONFIGURATION =====
def setup_logging():
    """Configure comprehensive logging to both file and console."""
    # Create logger
    logger = logging.getLogger('realbot')
    logger.setLevel(logging.DEBUG)
    
    # Create formatters
    file_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # File handler - rotating to manage size (5MB max, keep 3 backups)
    file_handler = RotatingFileHandler(
        'log.txt',
        maxBytes=5*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Also configure discord.py logging
    discord_logger = logging.getLogger('discord')
    discord_logger.setLevel(logging.INFO)
    discord_logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    logger.critical("DISCORD_TOKEN not found in .env file.")
    exit(1)

class RealBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix='!', intents=intents)
        logger.info("Bot instance created")

    async def setup_hook(self):
        logger.info("Running setup_hook...")
        # Load cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    logger.info(f'Loaded extension: {filename[:-3]}')
                except Exception as e:
                    logger.error(f'Failed to load extension {filename[:-3]}: {type(e).__name__}: {e}')
        
        # Sync commands
        await self.tree.sync()
        logger.info("Command tree synced")

    async def on_ready(self):
        logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        logger.info(f'Connected to {len(self.guilds)} guilds')
        for guild in self.guilds:
            logger.debug(f'  - {guild.name} (ID: {guild.id}, Members: {guild.member_count})')

    async def on_command(self, ctx):
        """Log all prefix commands."""
        logger.info(f'CMD | {ctx.author} ({ctx.author.id}) | #{ctx.channel} | !{ctx.command} {ctx.message.content[len(ctx.prefix)+len(ctx.command.name)+1:]}')

    async def on_command_error(self, ctx, error):
        """Log command errors."""
        logger.error(f'CMD_ERR | {ctx.author} | !{ctx.command} | {type(error).__name__}: {error}')

    async def on_app_command_completion(self, interaction, command):
        """Log slash command completions."""
        logger.info(f'SLASH | {interaction.user} ({interaction.user.id}) | #{interaction.channel} | /{command.name}')

    async def on_message(self, ctx):
        """Log all messages (debug level)."""
        if ctx.author.bot:
            return
        # Truncate long messages for logging
        content = ctx.content[:100] + '...' if len(ctx.content) > 100 else ctx.content
        logger.debug(f'MSG | {ctx.author} | #{ctx.channel} | {content}')
        await self.process_commands(ctx)

    async def on_member_join(self, member):
        """Log member joins."""
        logger.info(f'JOIN | {member} ({member.id}) joined {member.guild.name}')

    async def on_member_remove(self, member):
        """Log member leaves."""
        logger.info(f'LEAVE | {member} ({member.id}) left {member.guild.name}')

    async def on_voice_state_update(self, member, before, after):
        """Log voice state changes."""
        if before.channel != after.channel:
            if after.channel:
                logger.info(f'VOICE | {member} joined voice channel: {after.channel.name}')
            elif before.channel:
                logger.info(f'VOICE | {member} left voice channel: {before.channel.name}')

    async def on_guild_join(self, guild):
        """Log when bot joins a guild."""
        logger.info(f'GUILD_JOIN | Joined {guild.name} (ID: {guild.id}, Members: {guild.member_count})')

    async def on_guild_remove(self, guild):
        """Log when bot leaves a guild."""
        logger.info(f'GUILD_LEAVE | Left {guild.name} (ID: {guild.id})')

    async def on_error(self, event, *args, **kwargs):
        """Log all errors."""
        logger.exception(f'ERROR | Event: {event}')

bot = RealBot()

if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info(f"Bot starting at {datetime.now().isoformat()}")
    logger.info("=" * 50)
    bot.run(TOKEN, log_handler=None)  # Disable default handler since we configured our own
