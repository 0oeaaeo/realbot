import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import re
import logging
import asyncio
from typing import Literal
from shared import ROLE_ADMIN

logger = logging.getLogger('realbot')

FORCED_NICKS_FILE = "forced_nicks.json"
NOSWIFTO_FILE = "noswifto.json"
GEMINI_CLI_PATH = "/root/.nvm/versions/node/v24.11.1/bin/gemini"

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.forced_nicks = self.load_forced_nicks()
        self.noswifto_enabled = self.load_noswifto_state()
        logger.info("Admin cog initialized")
    
    def is_admin(self, member: discord.Member) -> bool:
        """Check if user has admin role or is a bot admin."""
        has_role = any(role.id == ROLE_ADMIN for role in member.roles)
        is_bot_admin = hasattr(self.bot, 'bot_admins') and member.id in self.bot.bot_admins
        return has_role or is_bot_admin

    def load_forced_nicks(self):
        if not os.path.exists(FORCED_NICKS_FILE):
            return {}
        try:
            with open(FORCED_NICKS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading forced nicks: {e}")
            return {}

    def save_forced_nicks(self):
        try:
            with open(FORCED_NICKS_FILE, "w") as f:
                json.dump(self.forced_nicks, f, indent=4)
        except Exception as e:
            print(f"Error saving forced nicks: {e}")

    def load_noswifto_state(self):
        if not os.path.exists(NOSWIFTO_FILE):
            return False
        try:
            with open(NOSWIFTO_FILE, "r") as f:
                data = json.load(f)
                return data.get("enabled", False)
        except Exception as e:
            print(f"Error loading noswifto state: {e}")
            return False

    def save_noswifto_state(self):
        try:
            with open(NOSWIFTO_FILE, "w") as f:
                json.dump({"enabled": self.noswifto_enabled}, f, indent=4)
        except Exception as e:
            print(f"Error saving noswifto state: {e}")

    @commands.command(name="admin")
    @commands.guild_only()
    async def admin_modify(self, ctx: commands.Context, *, prompt: str):
        """
        Execute a complete bot modification using gemini-cli.
        
        This command will:
        1. Run gemini-cli with your prompt to modify the bot's code
        2. Show a summary of changes
        3. Restart the bot service
        
        Usage: !admin <your modification request>
        Example: !admin Add a new command that shows server stats
        """
        logger.info(f"!admin invoked by {ctx.author} with prompt: {prompt[:100]}...")
        
        if not self.is_admin(ctx.author):
            await ctx.send("❌ This command is admin-only.")
            return
        
        if not prompt.strip():
            await ctx.send("❌ Please provide a prompt describing what changes to make.")
            return
        
        # Initial status message
        status_msg = await ctx.send("🔧 **Modifying bot code...**\n```\nRunning gemini-cli...\n```")
        
        try:
            # Construct the gemini-cli command
            cmd = [
                GEMINI_CLI_PATH,
                '--yolo',
                '--model', 'gemini-3-pro-preview',
                prompt
            ]
            
            logger.info(f"Executing gemini-cli...")
            
            # Run gemini-cli
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd='/root/realbot'
            )
            
            # Wait for completion with timeout (5 minutes)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=300
                )
            except asyncio.TimeoutError:
                process.kill()
                await status_msg.edit(content="❌ **Timeout** - gemini-cli took too long (>5min)")
                return
            
            stdout_text = stdout.decode('utf-8', errors='replace')
            stderr_text = stderr.decode('utf-8', errors='replace')
            
            logger.debug(f"gemini-cli output: {stdout_text[:1000]}")
            
            if process.returncode != 0:
                error_preview = (stderr_text or stdout_text)[:500]
                await status_msg.edit(
                    content=f"❌ **gemini-cli failed** (exit code {process.returncode})\n```\n{error_preview}\n```"
                )
                return
            
            # Extract summary from output
            lines = stdout_text.split('\n')
            changes = []
            for line in lines:
                if any(x in line.lower() for x in ['modified', 'created', 'updated', 'added', 'deleted', 'wrote', 'writing', 'file:']):
                    changes.append(line.strip()[:100])
                if len(changes) >= 5:
                    break
            
            if not changes:
                changes = [l.strip()[:100] for l in lines if l.strip()][-5:]
            
            changes_text = '\n'.join(changes) if changes else "Changes applied"
            
            await status_msg.edit(
                content=f"✅ **Code modified successfully!**\n```\n{changes_text[:800]}\n```\n🔄 Restarting bot service..."
            )
            
            logger.info("gemini-cli completed, restarting service...")
            await asyncio.sleep(1)
            
            # Restart the bot service
            await asyncio.create_subprocess_exec(
                'systemctl', 'restart', 'oeabot.service',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
        except FileNotFoundError:
            await status_msg.edit(content=f"❌ **gemini-cli not found** at `{GEMINI_CLI_PATH}`")
            logger.error(f"gemini-cli not found at {GEMINI_CLI_PATH}")
        
        except Exception as e:
            logger.exception(f"Error in admin command: {e}")
            await status_msg.edit(content=f"❌ **Error:** `{type(e).__name__}: {e}`")
    
    @admin_modify.error
    async def admin_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Please provide a prompt. Usage: `!admin <modification request>`")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("❌ This command can only be used in a server.")
        else:
            logger.error(f"Admin command error: {error}")
            await ctx.send(f"❌ Error: {error}")

    @app_commands.command(name="forcenick", description="Force a user's nickname (Admin only)")
    async def forcenick(self, interaction: discord.Interaction, user: discord.Member, nickname: str):
        # Check for Admin Role OR Bot Admin
        if not self.is_admin(interaction.user):
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        user_id = str(user.id)

        if nickname.lower() == "off":
            if user_id in self.forced_nicks:
                del self.forced_nicks[user_id]
                self.save_forced_nicks()
                await interaction.response.send_message(f"Force nick disabled for {user.mention}.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Force nick was not enabled for {user.mention}.", ephemeral=True)
            return

        # Enable/Update force nick
        self.forced_nicks[user_id] = nickname
        self.save_forced_nicks()

        # Apply immediately
        try:
            if user.nick != nickname:
                await user.edit(nick=nickname)
            await interaction.response.send_message(f"Forced nickname for {user.mention} set to `{nickname}`.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"Failed to change nickname. I might not have permission (user role higher than mine?). Force nick is saved though.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)

    @app_commands.command(name="noswifto", description="Enable/Disable swifto filter (Admin only)")
    async def noswifto(self, interaction: discord.Interaction, mode: Literal['on', 'off'] = 'on'):
         # Check for Admin Role
        if not self.is_admin(interaction.user):
            await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
            return

        if mode == 'off':
            self.noswifto_enabled = False
            self.save_noswifto_state()
            await interaction.response.send_message("NoSwifto mode disabled.", ephemeral=True)
        else:
            self.noswifto_enabled = True
            self.save_noswifto_state()
            await interaction.response.send_message("NoSwifto mode ENABLED. Watch out Swifto.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        user_id = str(after.id)
        if user_id in self.forced_nicks:
            forced_nick = self.forced_nicks[user_id]
            
            # Check if nick is different (and not just None if forced is None, though forced shouldn't be None here)
            if after.nick != forced_nick:
                print(f"User {after} tried to change nick to {after.nick}, reverting to {forced_nick}")
                try:
                    await after.edit(nick=forced_nick)
                except discord.Forbidden:
                    print(f"Failed to revert nickname for {after}. Missing permissions.")
                except Exception as e:
                    print(f"Error reverting nickname for {after}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.noswifto_enabled:
            return
        
        # Swifto ID: 984986990506299414
        if message.author.id == 984986990506299414:
            if "swifto" in message.content.lower():
                try:
                    # 1. Capture and Modify Content
                    original_content = message.content
                    # Case insensitive replace of "Swifto" with "I"
                    # Using regex to match Swifto case-insensitively and replace with "I"
                    # However, prompt says "repeats exactly what he says, except replacing 'Swifto' with 'I'"
                    # It implies replacing the word Swifto with I.
                    
                    modified_content = re.sub(r'swifto', 'I', original_content, flags=re.IGNORECASE)
                    
                    final_content = f"{modified_content}\n**EDITED FOR YOUR SAFETY**"

                    # 2. Get/Create Webhook
                    webhook = None
                    if isinstance(message.channel, discord.TextChannel):
                        webhooks = await message.channel.webhooks()
                        for wh in webhooks:
                             # Try to find a webhook owned by the bot to reuse
                            if wh.token: # Ensure we have the token to send
                                webhook = wh
                                break
                        
                        if not webhook:
                            try:
                                webhook = await message.channel.create_webhook(name="SwiftoReplacer")
                            except Exception as e:
                                print(f"Failed to create webhook: {e}")
                                return 

                    if webhook:
                        # 3. Send Message via Webhook
                        await webhook.send(
                            content=final_content,
                            username="Swifto", # Force nickname Swifto
                            avatar_url=message.author.display_avatar.url # User's avatar
                        )
                        
                        # 4. Delete Original Message
                        await message.delete()

                except discord.Forbidden:
                    print("Could not delete message from Swifto or manage webhooks (missing perms).")
                except Exception as e:
                    print(f"Error in noswifto listener: {e}")

async def setup(bot):
    await bot.add_cog(Admin(bot))