import discord
from discord.ext import commands
import logging
import datetime
from utils.discord_search import search_messages

logger = logging.getLogger('realbot')

class ReturnOfTheQueen(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.target_user_id = 1401225636969709701
        self.absence_period = datetime.timedelta(hours=2)
        self.gif_url = "https://cdn.discordapp.com/attachments/1415083961192939540/1449834449868034048/ezgif.com-crop.gif"
        self.last_posted_times = {}  # {channel_id: datetime}
        logger.info("ReturnOfTheQueen cog initialized")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id != self.target_user_id or message.author.bot or not message.guild:
            return

        try:
            now = discord.utils.utcnow()
            channel_id = message.channel.id

            last_posted = self.last_posted_times.get(channel_id)
            if last_posted and (now - last_posted) < self.absence_period:
                return

            logger.info(f"Target user {message.author} ({message.author.id}) sent a message in #{message.channel.name}. Checking for absence.")
            
            logger.debug(f"Calling search API for user {self.target_user_id} in channel {channel_id}")
            results = await search_messages(
                guild_id=str(message.guild.id),
                author_id=str(self.target_user_id),
                channel_id=str(channel_id),
                limit=2
            )

            post_gif = False
            if len(results) < 2:
                logger.info(f"Found less than 2 messages for {message.author} in search index. Assuming long absence.")
                post_gif = True
            else:
                # The first result is the message that just triggered this event.
                # The second result is their previous message.
                previous_message_id = results[1].id
                previous_message_time = discord.utils.snowflake_time(int(previous_message_id))
                time_since_last_message = now - previous_message_time
                logger.debug(f"Time since last message from {message.author}: {time_since_last_message}")

                if time_since_last_message >= self.absence_period:
                    logger.info(f"User {message.author} was absent for longer than {self.absence_period}. Posting GIF.")
                    post_gif = True

            if post_gif:
                await message.channel.send(self.gif_url)
                self.last_posted_times[channel_id] = now
                logger.info(f"Successfully posted return GIF for {message.author} in #{message.channel.name}")

        except Exception:
            logger.exception("Exception in ReturnOfTheQueen on_message listener")

async def setup(bot: commands.Bot):
    await bot.add_cog(ReturnOfTheQueen(bot))