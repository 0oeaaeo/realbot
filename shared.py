import discord
from discord.ui import Modal, TextInput
import datetime

# Configuration
LOG_CHANNEL_ID = 1254886501121130567
LOG_FILE = "verification_logs.txt"

# Roles
ROLE_NEW_USER = 1048476910377779320
ROLE_LEVEL_2 = 1058150917591011378
ROLE_LEVEL_3 = 1058152253032251422
ROLE_LEVEL_4 = 1048476910394544207

# Authorized Roles for Verifiers
AUTHORIZED_ROLES = [
    1316956925602173029,
    1213744152710217728,
    1417658266183270440,
    1220009739400904856
]

ALERT_ROLES = [
    1213744152710217728,
    1417658266183270440,
    1087288732559880212
]

ROLE_ADMIN = 1417658266183270440
VOICE_CHANNEL_ID = 1393004310228500580  # Legacy, kept for reference
VERIFY_CHANNEL_ID = 1451821790820302881  # Main verification voice channel
OVERFLOW_CHANNEL_PREFIX = "Overflow Verification"  # Prefix to identify overflow channels

def validate_verification(verifier: discord.Member, target: discord.Member) -> tuple[bool, str]:
    # Check if verifier is admin
    if any(role.id == ROLE_ADMIN for role in verifier.roles):
        return True, ""
    
    # Check if target is in a voice channel
    if not target.voice or not target.voice.channel:
        return False, "User is not in a voice channel."
    
    # Allow verification in the main verify channel or overflow channels
    channel = target.voice.channel
    if channel.id == VERIFY_CHANNEL_ID or channel.name.startswith(OVERFLOW_CHANNEL_PREFIX):
        return True, ""
    
    return False, "User must be in the verification voice channel."

class VerificationModal(Modal):
    def __init__(self, target_user: discord.Member, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_user = target_user

        self.add_item(TextInput(
            label="Verification Method",
            placeholder="How was the user verified?",
            style=discord.TextStyle.long
        ))

        self.add_item(TextInput(
            label="Verification Level (2, 3, or 4)",
            placeholder="Enter 2, 3, or 4",
            max_length=1
        ))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Validate again on submit (in case user left voice while typing)
            is_valid, error_msg = validate_verification(interaction.user, self.target_user)
            if not is_valid:
                await interaction.response.send_message(f"Verification Failed: {error_msg}", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            print("Modal callback started.")
            method = self.children[0].value
            level_str = self.children[1].value
            print(f"Method: {method}, Level: {level_str}")

            if level_str not in ['2', '3', '4']:
                await interaction.followup.send("Invalid level. Please enter 2, 3, or 4.", ephemeral=True)
                return

            level = int(level_str)
            
            # Role Management Logic
            guild = interaction.guild
            member = self.target_user
            print(f"Guild: {guild}, Member: {member}")
            
            roles_to_add = []
            roles_to_remove = []

            # Always remove new user role if present
            new_user_role = guild.get_role(ROLE_NEW_USER)
            if new_user_role and new_user_role in member.roles:
                roles_to_remove.append(new_user_role)

            # Determine roles to add based on level
            # Level 2 gets Level 2
            # Level 3 gets Level 2, Level 3
            # Level 4 gets Level 2, Level 3, Level 4
            
            role_l2 = guild.get_role(ROLE_LEVEL_2)
            role_l3 = guild.get_role(ROLE_LEVEL_3)
            role_l4 = guild.get_role(ROLE_LEVEL_4)

            if level >= 2:
                if role_l2: roles_to_add.append(role_l2)
            if level >= 3:
                if role_l3: roles_to_add.append(role_l3)
            if level >= 4:
                if role_l4: roles_to_add.append(role_l4)

            try:
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason=f"Verification Level {level} by {interaction.user}")
                if roles_to_add:
                    await member.add_roles(*roles_to_add, reason=f"Verification Level {level} by {interaction.user}")
                
                # Logging
                log_message = (
                    f"**Verification Log**\n"
                    f"**Verifier:** {interaction.user.mention} ({interaction.user.id})\n"
                    f"**Target User:** {member.mention} ({member.id})\n"
                    f"**Level:** {level}\n"
                    f"**Method:** {method}\n"
                    f"**Time:** {discord.utils.format_dt(datetime.datetime.now(), 'F')}"
                )

                # Log to channel
                log_channel = guild.get_channel(LOG_CHANNEL_ID)
                if log_channel:
                    await log_channel.send(log_message)
                else:
                    print(f"Log channel {LOG_CHANNEL_ID} not found.")

                # Log to file
                with open(LOG_FILE, "a") as f:
                    f.write(f"{datetime.datetime.now()} | Verifier: {interaction.user} ({interaction.user.id}) | Target: {member} ({member.id}) | Level: {level} | Method: {method}\n")

                await interaction.followup.send(f"Successfully verified {member.mention} to Level {level}.", ephemeral=True)

            except discord.Forbidden:
                await interaction.followup.send("I do not have permission to manage roles for this user.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)
        except Exception:
            import traceback
            traceback.print_exc()
