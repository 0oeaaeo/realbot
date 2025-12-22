import discord
from discord.ext import commands
import io
import base64
import json
import os
import time
from utils.api_calls import generate_image

# Owner ID - same as used elsewhere in the bot
OWNER_ID = "1362274618953699370"

# File to store nano-enabled users
NANO_USERS_FILE = "nano_users.json"


class NanoCog(commands.Cog):
    """Cog for generating images using Gemini's image generation capabilities."""
    
    def __init__(self, bot):
        self.bot = bot
        self.nano_users = {}  # {user_id: {"cooldown": seconds, "last_used": timestamp}}
        self._load_nano_users()

    def _load_nano_users(self):
        """Load nano-enabled users from file."""
        if os.path.exists(NANO_USERS_FILE):
            try:
                with open(NANO_USERS_FILE, 'r') as f:
                    self.nano_users = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.nano_users = {}
        else:
            self.nano_users = {}

    def _save_nano_users(self):
        """Save nano-enabled users to file."""
        with open(NANO_USERS_FILE, 'w') as f:
            json.dump(self.nano_users, f, indent=2)

    def _is_owner(self, user_id: str) -> bool:
        """Check if user is the owner."""
        return str(user_id) == OWNER_ID

    def _can_use_nano(self, user_id: str) -> tuple[bool, str]:
        """
        Check if user can use nano command.
        Returns (can_use, reason_if_not)
        """
        user_id_str = str(user_id)
        
        # Owner always can use
        if self._is_owner(user_id_str):
            return True, ""
        
        # Check if user is nano-enabled
        if user_id_str not in self.nano_users:
            return False, "You are not authorized to use the nano2 command."
        
        user_data = self.nano_users[user_id_str]
        cooldown = user_data.get("cooldown", 0)
        last_used = user_data.get("last_used", 0)
        
        # Check cooldown
        time_since_last = time.time() - last_used
        if time_since_last < cooldown:
            remaining = int(cooldown - time_since_last)
            return False, f"Cooldown active. Please wait **{remaining}** seconds."
        
        return True, ""

    def _update_last_used(self, user_id: str):
        """Update the last used timestamp for a user."""
        user_id_str = str(user_id)
        if user_id_str in self.nano_users:
            self.nano_users[user_id_str]["last_used"] = time.time()
            self._save_nano_users()

    @commands.command(name="addnano")
    async def add_nano_user(self, ctx, user: discord.User, cooldown: int = 60):
        """
        Add a user to the nano-enabled list with a cooldown.
        Owner only.
        
        Usage: !addnano @user cooldown_in_seconds
        """
        if not self._is_owner(ctx.author.id):
            await ctx.send("❌ Only the owner can use this command.")
            return
        
        if cooldown < 0:
            await ctx.send("❌ Cooldown must be a positive number.")
            return
        
        user_id_str = str(user.id)
        self.nano_users[user_id_str] = {
            "cooldown": cooldown,
            "last_used": 0
        }
        self._save_nano_users()
        
        await ctx.send(f"✅ Added **{user.display_name}** to nano-enabled users with a **{cooldown}s** cooldown.")

    @commands.command(name="remnano")
    async def remove_nano_user(self, ctx, user: discord.User):
        """
        Remove a user from the nano-enabled list.
        Owner only.
        
        Usage: !remnano @user
        """
        if not self._is_owner(ctx.author.id):
            await ctx.send("❌ Only the owner can use this command.")
            return
        
        user_id_str = str(user.id)
        if user_id_str in self.nano_users:
            del self.nano_users[user_id_str]
            self._save_nano_users()
            await ctx.send(f"✅ Removed **{user.display_name}** from nano-enabled users.")
        else:
            await ctx.send(f"⚠️ **{user.display_name}** was not in the nano-enabled list.")

    @commands.command(name="listnano")
    async def list_nano_users(self, ctx):
        """
        List all nano-enabled users.
        Owner only.
        """
        if not self._is_owner(ctx.author.id):
            await ctx.send("❌ Only the owner can use this command.")
            return
        
        if not self.nano_users:
            await ctx.send("📋 No nano-enabled users.")
            return
        
        lines = ["📋 **Nano-Enabled Users:**"]
        for user_id, data in self.nano_users.items():
            try:
                user = await self.bot.fetch_user(int(user_id))
                name = user.display_name
            except:
                name = f"Unknown ({user_id})"
            
            cooldown = data.get("cooldown", 0)
            lines.append(f"• **{name}** - {cooldown}s cooldown")
        
        await ctx.send("\n".join(lines))

    @commands.command(name="nano2")
    async def nano2(self, ctx, *, prompt: str = ""):
        """
        Generates an image using the Gemini API (Nano Banana 2 style).
        Supports image attachments as input for image-to-image generation.
        
        Usage: 
            !nano2 <prompt> - Generate an image from text
            !nano2 <prompt> (with attached image) - Generate based on image + prompt
            Reply to an image with !nano2 <prompt> - Iterate on the replied image
        """
        # Check if user can use the command
        can_use, reason = self._can_use_nano(ctx.author.id)
        if not can_use:
            await ctx.send(f"❌ {reason}")
            return
        
        status_message = await ctx.send(f"🎨 **Nano Gen:** Request received...\n> Prompt: `{prompt[:100]}{'...' if len(prompt) > 100 else ''}`")
        
        images_data = []
        attachments_to_process = []

        # 1. Check for attachments in replied-to message (enables image iteration via replies)
        if ctx.message.reference and ctx.message.reference.message_id:
            try:
                replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if replied_message.attachments:
                    attachments_to_process.extend(replied_message.attachments)
            except discord.NotFound:
                pass  # Message deleted or not found
            except discord.Forbidden:
                pass  # No permission to read message
            except Exception as e:
                print(f"Error fetching replied message: {e}")

        # 2. Check for attachments in the current message
        if ctx.message.attachments:
            attachments_to_process.extend(ctx.message.attachments)
        
        # 3. Process all found attachments
        if attachments_to_process:
            await status_message.edit(content="> 📥 Downloading attachments...")
            for attachment in attachments_to_process:
                # Filter for images
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    try:
                        # Read attachment data
                        data = await attachment.read()
                        # Encode to base64 string as required by api_calls.generate_image
                        encoded_data = base64.b64encode(data).decode('utf-8')
                        images_data.append((attachment.content_type, encoded_data))
                    except Exception as e:
                        print(f"Error downloading/encoding attachment: {e}")
        
        if not prompt and not images_data:
            await status_message.edit(content="❌ **Error:** Please provide a text prompt or an attached image.")
            return

        # If no prompt but image exists, use a space so the API doesn't reject it
        if not prompt:
            prompt = " " 

        await status_message.edit(content="> 🖌️ Generating image...")
        
        try:
            # Call the API function directly
            image_io = await generate_image(prompt, images_data)
            
            if image_io:
                # Update last used time for non-owner users
                if not self._is_owner(ctx.author.id):
                    self._update_last_used(ctx.author.id)
                
                await status_message.delete()
                await ctx.send(
                    content=f"**Nano Raw:** {prompt[:200]}{'...' if len(prompt) > 200 else ''}", 
                    file=discord.File(image_io, filename="nano_result.png")
                )
            else:
                await status_message.edit(content="❌ **Generation Failed:** The API returned no image.")
                
        except Exception as e:
            await status_message.edit(content=f"❌ **Error:** {e}")


async def setup(bot):
    await bot.add_cog(NanoCog(bot))

