import discord
from discord import app_commands
from discord.ext import commands
from shared import (
    VerificationModal, AUTHORIZED_ROLES, validate_verification, ALERT_ROLES, 
    ROLE_ADMIN, LOG_FILE, ROLE_NEW_USER, ROLE_LEVEL_2, ROLE_LEVEL_3, ROLE_LEVEL_4
)
import os
import time

def is_authorized(user: discord.Member):
    return any(role.id in AUTHORIZED_ROLES for role in user.roles)

class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="verifylog", description="Upload verification logs (Admin only)")
    async def verifylog(self, interaction: discord.Interaction):
        # Check for Admin Role
        if not any(role.id == ROLE_ADMIN for role in interaction.user.roles):
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        log_channel_id = 1048476915591286866
        channel = self.bot.get_channel(log_channel_id)

        if not channel:
            await interaction.response.send_message(f"Error: Target channel {log_channel_id} not found.", ephemeral=True)
            return

        if not os.path.exists(LOG_FILE):
            await interaction.response.send_message("Error: Log file not found.", ephemeral=True)
            return

        try:
            await interaction.response.defer(ephemeral=True)
            file = discord.File(LOG_FILE, filename="verification_logs.txt")
            await channel.send(f"Verification Logs requested by {interaction.user.mention}", file=file)
            await interaction.followup.send(f"Logs uploaded to {channel.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Failed to upload logs: {e}", ephemeral=True)

    @app_commands.command(name="checkverify", description="Check verification logs for a specific user (Admin only)")
    async def checkverify(self, interaction: discord.Interaction, user: discord.Member):
        # Check for Admin Role
        if not any(role.id == ROLE_ADMIN for role in interaction.user.roles):
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        if not os.path.exists(LOG_FILE):
            await interaction.response.send_message("Error: Log file not found.", ephemeral=True)
            return

        target_id = str(user.id)
        found_logs = []

        try:
            with open(LOG_FILE, "r") as f:
                for line in f:
                    if target_id in line:
                        found_logs.append(line.strip())
            
            if not found_logs:
                await interaction.response.send_message(f"No verification logs found for {user.mention}.", ephemeral=True)
            else:
                # Format output (handle potential length limits)
                log_output = "\n".join(found_logs)
                if len(log_output) > 1900:
                    # If too long, send as file
                    with open("temp_search_log.txt", "w") as temp_f:
                        temp_f.write(log_output)
                    file = discord.File("temp_search_log.txt", filename=f"verification_logs_{user.name}.txt")
                    await interaction.response.send_message(f"Verification logs for {user.mention}:", file=file, ephemeral=True)
                    os.remove("temp_search_log.txt")
                else:
                    await interaction.response.send_message(f"**Verification Logs for {user.mention}:**\n```\n{log_output}\n```", ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"An error occurred while reading logs: {e}", ephemeral=True)

    @app_commands.command(name="scrapeverify", description="Scrape historical verifications (Admin only)")
    async def scrapeverify(self, interaction: discord.Interaction):
        # Check for Admin Role
        if not any(role.id == ROLE_ADMIN for role in interaction.user.roles):
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        target_channel_id = 1254886501121130567
        target_bot_id = 1266643977730392084
        update_channel_id = 1048476915591286866
        
        channel = self.bot.get_channel(target_channel_id)
        update_channel = self.bot.get_channel(update_channel_id)

        if not channel:
            await interaction.response.send_message(f"Error: Target channel {target_channel_id} not found.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        count = 0
        logs_to_add = []
        last_update_time = time.time()
        
        try:
            async for message in channel.history(limit=None):
                # Periodic Update Logic
                current_time = time.time()
                if current_time - last_update_time >= 60:
                    if update_channel:
                        await update_channel.send(f"Scrape in progress... Processed {count} verification entries so far.")
                    last_update_time = current_time

                # DEBUG LOGGING
                if count < 5: # Print first 5 messages to see what they look like
                    print(f"MSG: {message.id} | Author: {message.author.id} | Content: {repr(message.content)} | Embeds: {len(message.embeds)}")
                    if message.embeds:
                        print(f"Embed Title: {message.embeds[0].title}")
                        print(f"Embed Desc: {repr(message.embeds[0].description)}")

                if message.author.id != target_bot_id:
                    continue
                
                content = message.content
                # Check embeds if content is empty
                if not content and message.embeds:
                    # Try to use embed description or title + description
                    embed = message.embeds[0]
                    content = (embed.title or "") + "\n" + (embed.description or "")
                    # Also check fields if needed, but let's start with this

                if "✅ User Verification Completed" not in content:
                    continue

                try:
                    # Combine content and embed fields for searching
                    full_text = content
                    if message.embeds:
                        embed = message.embeds[0]
                        full_text += "\n" + (embed.title or "") + "\n" + (embed.description or "")
                        for field in embed.fields:
                            full_text += "\n" + (field.name or "") + "\n" + (field.value or "")

                    # Regex Parsing
                    import re
                    
                    # User: Name (ID is usually separate or in parens, but format says "User: TAG (Name)")
                    # The example: "User: USER_TAG (Twisted91)"
                    user_match = re.search(r"User:\s*(.+)", full_text)
                    target_name = user_match.group(1).strip() if user_match else "Unknown"

                    # Verified by: @Tag (Name)
                    verifier_match = re.search(r"Verified by:\s*(.+)", full_text)
                    verifier_name = verifier_match.group(1).strip() if verifier_match else "Unknown"

                    # Verification Level: 4
                    level_match = re.search(r"Verification Level:\s*(\d+)", full_text)
                    level = level_match.group(1).strip() if level_match else "Unknown"

                    # User ID: 123456789
                    id_match = re.search(r"User ID:\s*(\d+)", full_text)
                    target_id = id_match.group(1).strip() if id_match else "Unknown"

                    # Method
                    # Look for text between "Verification Method" and "User Information"
                    # Handle potential emojis or newlines
                    method = "Unknown"
                    try:
                        # Regex for method section
                        # DOTALL to match newlines
                        method_match = re.search(r"Verification Method\s*\n(.+?)\n.*User Information", full_text, re.DOTALL | re.IGNORECASE)
                        if method_match:
                            method = method_match.group(1).strip()
                        else:
                            # Fallback: simple string slicing if regex fails
                            start_marker = "Verification Method"
                            end_marker = "User Information"
                            s_idx = full_text.find(start_marker)
                            e_idx = full_text.find(end_marker)
                            if s_idx != -1 and e_idx != -1:
                                method = full_text[s_idx + len(start_marker):e_idx].strip()
                    except:
                        pass

                    # Extract Verifier ID from mention if possible
                    verifier_id = "Unknown ID"
                    if "<@" in verifier_name:
                        try:
                            verifier_id = verifier_name.split('<@')[1].split('>')[0].replace('!', '')
                        except:
                            pass
                    
                    # Format timestamp
                    timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S.%f")

                    log_entry = (
                        f"{timestamp} | "
                        f"Verifier: {verifier_name} ({verifier_id}) | "
                        f"Target: {target_name} ({target_id}) | "
                        f"Level: {level} | "
                        f"Method: {method}\n"
                    )
                    logs_to_add.append(log_entry)
                    count += 1

                except Exception as e:
                    print(f"Failed to parse message {message.id}: {e}")
                    continue

            # Append to file
            if logs_to_add:
                # Reverse to keep chronological order (history is newest first)
                logs_to_add.reverse()
                with open(LOG_FILE, "a") as f:
                    f.writelines(logs_to_add)
            
            await interaction.followup.send(f"Scraping complete. Processed {count} verification entries.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"An error occurred during scraping: {e}", ephemeral=True)

    async def _perform_verification(self, interaction: discord.Interaction, user: discord.Member):
        if not is_authorized(interaction.user):
            pings = " ".join([f"<@&{role_id}>" for role_id in ALERT_ROLES])
            await interaction.response.send_message(
                f"{pings} User {interaction.user.mention} attempted to verify without permission.",
                ephemeral=False
            )
            return

        is_valid, error_msg = validate_verification(interaction.user, user)
        if not is_valid:
            await interaction.response.send_message(f"Cannot verify: {error_msg}", ephemeral=True)
            return

        modal = VerificationModal(target_user=user, title="Verify User")
        await interaction.response.send_modal(modal)

    @app_commands.command(name="verify", description="Verify a user")
    async def verify_slash(self, interaction: discord.Interaction, user: discord.Member):
        await self._perform_verification(interaction, user)

    @app_commands.command(name="verify-user", description="Verify a user (Alias for /verify)")
    async def verify_user_slash(self, interaction: discord.Interaction, user: discord.Member):
        await self._perform_verification(interaction, user)

    @commands.command(name="unverify")
    @commands.is_owner()
    async def unverify(self, ctx, user: discord.Member):
        """[Owner Only] Strip verification roles and give back Level 1 role for testing."""
        guild = ctx.guild
        
        # Roles to remove
        roles_to_remove = []
        for role_id in [ROLE_LEVEL_2, ROLE_LEVEL_3, ROLE_LEVEL_4]:
            role = guild.get_role(role_id)
            if role and role in user.roles:
                roles_to_remove.append(role)
        
        # Role to add
        new_user_role = guild.get_role(ROLE_NEW_USER)
        
        try:
            if roles_to_remove:
                await user.remove_roles(*roles_to_remove, reason=f"Unverify by {ctx.author}")
            if new_user_role and new_user_role not in user.roles:
                await user.add_roles(new_user_role, reason=f"Unverify by {ctx.author}")
            
            await ctx.send(f"✅ {user.mention} has been unverified and given Level 1 role.")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to manage roles for this user.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

@app_commands.context_menu(name="Verify User")
async def verify_context(interaction: discord.Interaction, user: discord.Member):
    if not is_authorized(interaction.user):
        pings = " ".join([f"<@&{role_id}>" for role_id in ALERT_ROLES])
        await interaction.response.send_message(
            f"{pings} User {interaction.user.mention} attempted to verify without permission.",
            ephemeral=False
        )
        return

    is_valid, error_msg = validate_verification(interaction.user, user)
    if not is_valid:
        await interaction.response.send_message(f"Cannot verify: {error_msg}", ephemeral=True)
        return

    modal = VerificationModal(target_user=user, title="Verify User")
    await interaction.response.send_modal(modal)

async def setup(bot):
    await bot.add_cog(Verification(bot))
    bot.tree.add_command(verify_context)
