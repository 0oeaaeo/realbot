import discord
from discord.ext import commands
import io
import base64
from utils.api_calls import generate_image

class NanoGen(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="nano2")
    async def nano(self, ctx, *, prompt: str = ""):
        """
        Generates an image using the raw Gemini API (Nano Banana 2 style).
        Supports image attachments as input for image-to-image.
        Usage: $nano <prompt> (with optional attached image or reply to image)
        """
        
        status_message = await ctx.send(f"🎨 **Nano Gen:** Request received...\n> Prompt: `{prompt}`")
        
        images_data = []
        attachments_to_process = []

        # 1. Check for attachments in replied-to message
        if ctx.message.reference and ctx.message.reference.message_id:
            try:
                replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if replied_message.attachments:
                    attachments_to_process.extend(replied_message.attachments)
            except discord.NotFound:
                pass # Message deleted or not found
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

        # If no prompt but image exists, ensure prompt is not empty string if API requires it
        if not prompt:
            prompt = " " 

        await status_message.edit(content="> 🖌️ Generating raw image...")
        
        try:
            # Call the API function directly
            image_io = await generate_image(prompt, images_data)
            
            if image_io:
                await status_message.delete()
                await ctx.send(
                    content=f"**Nano Raw:** {prompt}", 
                    file=discord.File(image_io, filename="nano_result.png")
                )
            else:
                await status_message.edit(content="❌ **Generation Failed:** The API returned no image.")
                
        except Exception as e:
            await status_message.edit(content=f"❌ **Error:** {e}")

async def setup(bot):
    await bot.add_cog(NanoGen(bot))
