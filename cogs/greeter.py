import asyncio
import discord
from discord.ext import commands
from discord.ui import View, Button
from shared import (
    VerificationModal, AUTHORIZED_ROLES, ROLE_NEW_USER, 
    VERIFY_CHANNEL_ID, OVERFLOW_CHANNEL_PREFIX, validate_verification, ALERT_ROLES
)

# Configuration
VERIFY_CATEGORY_ID = 1229471005114765423  # Category for overflow channels


class VerifyView(View):
    def __init__(self, target_user: discord.Member):
        super().__init__(timeout=None)  # Persistent view
        self.target_user = target_user

    @discord.ui.button(label="VERIFY", style=discord.ButtonStyle.green)
    async def verify_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check authorization
        if not any(role.id in AUTHORIZED_ROLES for role in interaction.user.roles):
            pings = " ".join([f"<@&{role_id}>" for role_id in ALERT_ROLES])
            await interaction.response.send_message(
                f"{pings} User {interaction.user.mention} attempted to verify without permission.",
                ephemeral=False
            )
            return

        is_valid, error_msg = validate_verification(interaction.user, self.target_user)
        if not is_valid:
            await interaction.response.send_message(f"Cannot verify: {error_msg}", ephemeral=True)
            return

        modal = VerificationModal(target_user=self.target_user, title="Verify User")
        await interaction.response.send_modal(modal)


class Greeter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.overflow_channel_id = None  # Track the current overflow channel

    def _count_level1_in_channel(self, channel: discord.VoiceChannel) -> int:
        """Count users with Level 1 role in a voice channel."""
        count = 0
        for member in channel.members:
            if any(role.id == ROLE_NEW_USER for role in member.roles):
                count += 1
        return count

    def _get_level1_members_in_channel(self, channel: discord.VoiceChannel) -> list[discord.Member]:
        """Get all Level 1 users in a voice channel."""
        return [m for m in channel.members if any(role.id == ROLE_NEW_USER for role in m.roles)]

    async def _get_overflow_channel(self, guild: discord.Guild) -> discord.VoiceChannel | None:
        """Find existing overflow channel if any."""
        if self.overflow_channel_id:
            channel = guild.get_channel(self.overflow_channel_id)
            if channel:
                return channel
            else:
                self.overflow_channel_id = None  # Channel was deleted externally
        return None

    async def _create_overflow_channel(self, guild: discord.Guild) -> discord.VoiceChannel:
        """Create an overflow verification channel under the verify category."""
        category = guild.get_channel(VERIFY_CATEGORY_ID)
        main_channel = guild.get_channel(VERIFY_CHANNEL_ID)
        
        # Copy permissions from main channel if possible
        overwrites = main_channel.overwrites if main_channel else {}
        
        overflow = await guild.create_voice_channel(
            name=f"{OVERFLOW_CHANNEL_PREFIX}",
            category=category,
            overwrites=overwrites,
            reason="Created for overflow verification"
        )
        self.overflow_channel_id = overflow.id
        return overflow

    async def _delete_overflow_if_empty(self, channel: discord.VoiceChannel):
        """Delete overflow channel if it's empty."""
        if channel and channel.name.startswith(OVERFLOW_CHANNEL_PREFIX):
            if len(channel.members) == 0:
                try:
                    await channel.delete(reason="Overflow channel empty")
                    if self.overflow_channel_id == channel.id:
                        self.overflow_channel_id = None
                except discord.NotFound:
                    pass  # Already deleted

    async def _post_verification_prompt(self, channel: discord.abc.Messageable, user: discord.Member):
        """Send mod ping + verify button for a user."""
        pings = " ".join([f"<@&{role_id}>" for role_id in ALERT_ROLES])
        view = VerifyView(target_user=user)
        message_content = (
            f"{pings}\n"
            f"User {user.mention} has joined for verification."
        )
        await channel.send(message_content, view=view)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Welcome new members by tagging them in the verification channel."""
        channel = self.bot.get_channel(VERIFY_CHANNEL_ID)
        if channel:
            await channel.send(
                f"Welcome {member.mention}! Please join the voice channel above to begin verification."
            )
        else:
            print(f"Verify channel {VERIFY_CHANNEL_ID} not found.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Handle voice channel join/leave for verification flow."""
        print(f"Voice update for {member}: {before.channel} -> {after.channel}")
        
        # Check if user left a channel (for overflow cleanup)
        if before.channel and before.channel.name.startswith(OVERFLOW_CHANNEL_PREFIX):
            # Small delay to allow Discord to update member list
            await asyncio.sleep(1)
            await self._delete_overflow_if_empty(before.channel)

        # Only process if user JOINED a channel (after.channel is not None)
        if not after.channel:
            return

        # Only care about Level 1 users
        if not any(role.id == ROLE_NEW_USER for role in member.roles):
            return

        guild = member.guild
        main_channel = guild.get_channel(VERIFY_CHANNEL_ID)
        overflow_channel = await self._get_overflow_channel(guild)

        # Case 1: User joined the main verification channel
        if after.channel.id == VERIFY_CHANNEL_ID:
            # Count Level 1 users currently in main channel (excluding the one who just joined)
            level1_in_main = self._count_level1_in_channel(main_channel)
            
            if level1_in_main == 1:
                # This is the only Level 1 user - send verification prompt
                await asyncio.sleep(2)  # Brief delay before notification
                await self._post_verification_prompt(main_channel, member)
            else:
                # Another Level 1 user is already in main channel
                if overflow_channel is None:
                    # Create overflow channel and move user there
                    overflow_channel = await self._create_overflow_channel(guild)
                    try:
                        await member.move_to(overflow_channel, reason="Moving to overflow verification channel")
                        await asyncio.sleep(2)
                        await self._post_verification_prompt(overflow_channel, member)
                    except discord.HTTPException as e:
                        print(f"Failed to move user to overflow: {e}")
                else:
                    # Check if overflow is also occupied by a Level 1 user
                    level1_in_overflow = self._count_level1_in_channel(overflow_channel)
                    if level1_in_overflow == 0:
                        # Overflow exists but is empty of Level 1 - move user there
                        try:
                            await member.move_to(overflow_channel, reason="Moving to overflow verification channel")
                            await asyncio.sleep(2)
                            await self._post_verification_prompt(overflow_channel, member)
                        except discord.HTTPException as e:
                            print(f"Failed to move user to overflow: {e}")
                    else:
                        # Both channels are full - disconnect and show error
                        try:
                            await member.move_to(None, reason="Verification channels at capacity")
                            await main_channel.send(
                                f"⚠️ {member.mention} - Both verification channels are currently occupied. "
                                f"Please wait a moment and try joining again."
                            )
                        except discord.HTTPException as e:
                            print(f"Failed to disconnect user: {e}")

        # Case 2: User joined the overflow channel directly
        elif overflow_channel and after.channel.id == overflow_channel.id:
            # Count Level 1 users in overflow
            level1_in_overflow = self._count_level1_in_channel(overflow_channel)
            
            if level1_in_overflow == 1:
                # This is the only Level 1 user in overflow - send verification prompt
                await asyncio.sleep(2)
                await self._post_verification_prompt(overflow_channel, member)
            else:
                # Overflow already has a Level 1 user - check main channel
                level1_in_main = self._count_level1_in_channel(main_channel) if main_channel else 999
                if level1_in_main == 0:
                    # Main is empty, move user there
                    try:
                        await member.move_to(main_channel, reason="Moving to main verification channel")
                        await asyncio.sleep(2)
                        await self._post_verification_prompt(main_channel, member)
                    except discord.HTTPException as e:
                        print(f"Failed to move user to main: {e}")
                else:
                    # Both full - disconnect
                    try:
                        await member.move_to(None, reason="Verification channels at capacity")
                        await main_channel.send(
                            f"⚠️ {member.mention} - Both verification channels are currently occupied. "
                            f"Please wait a moment and try joining again."
                        )
                    except discord.HTTPException as e:
                        print(f"Failed to disconnect user: {e}")


async def setup(bot):
    await bot.add_cog(Greeter(bot))
