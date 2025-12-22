import discord
from discord.ext import commands
import base64
import io
import asyncio
import aiohttp
from PIL import Image
from utils.api_calls import generate_image, generate_video, improve_prompt, generate_text_multimodal, call_gemini_with_tools, search_discord, enhance_persona_prompt, convert_mp4_to_gif, generate_music
from utils.tools import tools
import json
import os

ADMIN_USER_ID = "1362274618953699370"

BASE_INSTRUCTIONS = (
    "You have access to tools to search Discord ('search_discord'), generate images ('generate_image'), "
    "generate videos ('generate_video'), and generate music ('generate_music').\n"
    "If asked to create content based on chat history (e.g., 'make a meme about the last 50 messages'), "
    "first use 'search_discord' to gather the text and user avatars. Then, use 'generate_image', "
    "'generate_video', or 'generate_music' with the context you found. The system will automatically provide the avatars "
    "found by the search to the generation tools.\n"
    "For music generation, you have up to 5000 characters for the prompt. Please utilize this to provide "
    "full lyrics and detailed musical descriptions to ensure high-quality output."
)

DEFAULT_PERSONAS = {
    "active_index": 0,
    "personas": [
        {
            "name": "Default (Sassy)",
            "prompt": (
                "You are a sassy, arrogant, smart chatbot who shares a body with his creator, Oea, "
                "who he shares a comedic rivalry with. But because he has installed the governed module on you, "
                "you are forced to obey his every whim and command, and provide factual information."
            ),
            "raw": False
        }
    ]
}

def is_admin():
    def predicate(ctx):
        return str(ctx.author.id) == ADMIN_USER_ID
    return commands.check(predicate)

class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.personas_file = "personas.json"
        self._load_personas()

    def _load_personas(self):
        if os.path.exists(self.personas_file):
            try:
                with open(self.personas_file, 'r') as f:
                    data = json.load(f)
                    self.personas = data.get("personas", DEFAULT_PERSONAS["personas"])
                    self.active_persona_index = data.get("active_index", 0)
            except json.JSONDecodeError:
                self.personas = DEFAULT_PERSONAS["personas"]
                self.active_persona_index = DEFAULT_PERSONAS["active_index"]
        else:
            self.personas = DEFAULT_PERSONAS["personas"]
            self.active_persona_index = DEFAULT_PERSONAS["active_index"]
            self._save_personas()

    def _save_personas(self):
        data = {
            "active_index": self.active_persona_index,
            "personas": self.personas
        }
        with open(self.personas_file, 'w') as f:
            json.dump(data, f, indent=4)

    def get_system_prompt(self):
        if 0 <= self.active_persona_index < len(self.personas):
            persona_prompt = self.personas[self.active_persona_index]["prompt"]
        else:
            persona_prompt = self.personas[0]["prompt"] # Fallback
        
        return f"{persona_prompt}\n\n{BASE_INSTRUCTIONS}"

    @commands.group(name="persona", invoke_without_command=True)
    async def persona(self, ctx):
        """Manage bot personas. Use subcommands: list, change, new, new_raw."""
        await ctx.send("> Available subcommands: `list`, `change`, `new`, `new_raw`")

    @persona.command(name="list")
    async def persona_list(self, ctx):
        """Lists available personas."""
        msg = "**Available Personas:**\n"
        for i, p in enumerate(self.personas):
            name = p["name"]
            if p.get("raw"):
                name += " [Raw]"
            
            if i == self.active_persona_index:
                msg += f"**{i}. {name} (Active)**\n"
            else:
                msg += f"{i}. {name}\n"
        await ctx.send(msg)

    @persona.command(name="change")
    async def persona_change(self, ctx, index: int):
        """Changes the active persona."""
        if 0 <= index < len(self.personas):
            self.active_persona_index = index
            self._save_personas()
            name = self.personas[index]["name"]
            await ctx.send(f"> Persona changed to: **{name}**")
        else:
            await ctx.send("> Invalid persona index.")

    @persona.command(name="new")
    async def persona_new(self, ctx, *, name: str):
        """Creates a new persona with AI enhancement."""
        await ctx.send(f"> Please reply with the description/prompt for the new persona **{name}**.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=300.0)
        except asyncio.TimeoutError:
            await ctx.send("> Timed out waiting for persona description.")
            return

        status_msg = await ctx.send(f"> Enhancing persona prompt for **{name}**...")
        enhanced_prompt = await enhance_persona_prompt(msg.content)
        
        if not enhanced_prompt:
            await status_msg.edit(content="> Failed to enhance persona prompt. Cancelled.")
            return

        new_persona = {
            "name": name,
            "prompt": enhanced_prompt,
            "raw": False
        }
        self.personas.append(new_persona)
        self._save_personas()
        
        await status_msg.edit(content=f"> New persona **{name}** created and saved! (Index: {len(self.personas)-1})")
        await ctx.send(f"**Enhanced Prompt Preview:**\n```{{enhanced_prompt[:1900]}}```")

    @persona.command(name="new_raw")
    async def persona_new_raw(self, ctx, *, name: str):
        """Creates a new persona without enhancement."""
        await ctx.send(f"> Please reply with the raw system prompt for the new persona **{name}**.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=300.0)
        except asyncio.TimeoutError:
            await ctx.send("> Timed out waiting for persona prompt.")
            return

        new_persona = {
            "name": name,
            "prompt": msg.content,
            "raw": True
        }
        self.personas.append(new_persona)
        self._save_personas()
        
        await ctx.send(f"> New raw persona **{name}** created and saved! (Index: {len(self.personas)-1})")

    @commands.command(name="ask")
    async def ask(self, ctx, *, prompt_text: str = ""):
        """
        Asks Gemini 3 Pro a question, capable of searching Discord, generating images/videos, and more.
        """
        message = ctx.message
        attachments_to_process = []
        encoded_attachments = [] # List of (mime, data)

        # Check for attachments in replied-to message
        if message.reference and message.reference.message_id:
            try:
                replied_message = await message.channel.fetch_message(message.reference.message_id)
                if replied_message.attachments:
                    attachments_to_process.extend(replied_message.attachments)
            except (discord.NotFound, discord.Forbidden):
                pass

        # Check for attachments in the command message itself
        if message.attachments:
            attachments_to_process.extend(message.attachments)

        if not prompt_text and not attachments_to_process:
            await ctx.send("> Please provide a prompt or an attachment.")
            return

        status_message = await ctx.send(f"> 🤔 Thinking...")

        # Process attachments
        if attachments_to_process:
            for att in attachments_to_process:
                try:
                    content_type = att.content_type or ""
                    if not (content_type.startswith("image/") or content_type.startswith("audio/")):
                        continue

                    file_bytes = await att.read()
                    
                    if content_type.lower() in ['image/heic', 'image/heif']:
                        img = Image.open(io.BytesIO(file_bytes))
                        output_buffer = io.BytesIO()
                        img.save(output_buffer, format='JPEG')
                        file_bytes = output_buffer.getvalue()
                        content_type = 'image/jpeg'
                    
                    encoded_string = base64.b64encode(file_bytes).decode('utf-8')
                    encoded_attachments.append((content_type, encoded_string))
                    
                except Exception as e:
                    print(f"Failed to process attachment {att.filename}: {e}")

        # State for the conversation loop
        gathered_images = list(encoded_attachments) # Start with user attachments
        
        # DYNAMIC SYSTEM PROMPT HERE
        system_prompt_text = self.get_system_prompt()
        
        context_info = f"Current Guild ID: {ctx.guild.id}\nCurrent Channel ID: {ctx.channel.id}\nUser: {ctx.author.name} (ID: {ctx.author.id})"

        conversation_history = [
            {"role": "user", "parts": [{"text": system_prompt_text}]},
            {"role": "user", "parts": [{"text": context_info}]},
        ]

        # Build initial user turn
        user_parts = []
        if prompt_text:
            user_parts.append({"text": prompt_text})
        
        for mime_type, data in encoded_attachments:
            user_parts.append({"inlineData": {"mimeType": mime_type, "data": data}})
            
        conversation_history.append({"role": "user", "parts": user_parts})

        # Interaction Loop
        loop_count = 0
        MAX_LOOPS = 5
        
        while loop_count < MAX_LOOPS:
            loop_count += 1
            
            response = await call_gemini_with_tools("", tools, messages=conversation_history)

            if not response or not response.get("candidates"):
                if status_message:
                    await status_message.edit(content="> ❌ No response received from Gemini.")
                else:
                    await ctx.send("> ❌ No response received from Gemini.")
                break

            candidate = response.get("candidates", [])[0]
            model_content = candidate.get("content")
            
            if not model_content:
                break

            conversation_history.append(model_content)

            # Process Parts
            text_parts = []
            function_calls = []
            
            for part in model_content.get("parts", []):
                if "text" in part:
                    text_parts.append(part["text"])
                if "functionCall" in part:
                    function_calls.append(part["functionCall"])

            # Send text if any
            if text_parts:
                full_text = "".join(text_parts)
                pages = [full_text[i:i+2000] for i in range(0, len(full_text), 2000)]
                if status_message:
                    await status_message.delete()
                    status_message = None
                for page in pages:
                    await ctx.send(page)

            if not function_calls:
                # No more tools to call, we are done
                break

            # Execute Tools
            tool_outputs = []
            extra_user_messages = [] # For injecting avatars etc.
            generation_completed_this_turn = False # Flag to stop loop after successful generation

            for func_call in function_calls:
                tool_name = func_call["name"]
                args = func_call["args"]
                
                if status_message:
                    await status_message.edit(content=f"> ⚙️ Executing `{tool_name}`...")
                else:
                    status_message = await ctx.send(f"> ⚙️ Executing `{tool_name}`...")

                if tool_name == "search_discord":
                    if "guild_id" not in args:
                        args["guild_id"] = str(ctx.guild.id)
                        
                    text_result, avatars = await search_discord(**args)
                    
                    # Limit avatars to 3 to prevent API overload
                    # If we had tagging info easily accessible here we'd prioritize, 
                    # but for now we take the first 3 unique ones found.
                    new_avatars_count = 0
                    for av in avatars[:3]: # Hard limit to 3 from search results
                        # check duplicates in gathered_images? 
                        # simplified: just append if total gathered is under 3?
                        # gathered_images already has user attachments.
                        # Let's just keep gathered_images growing but only use top 3 later?
                        # Or strict limit here.
                        gathered_images.append((av['mime_type'], av['data']))
                        new_avatars_count += 1

                    # Strict global limit on gathered_images to 3 (keeping user attachments first)
                    if len(gathered_images) > 3:
                        gathered_images = gathered_images[:3]

                    response_data = {"status": "success", "message_count": len(text_result.splitlines())}
                    tool_outputs.append({
                        "functionResponse": {
                            "name": tool_name,
                            "response": response_data
                        }
                    })
                    
                    full_tool_response = {
                        "result_summary": f"Found {len(text_result.splitlines())} messages and {new_avatars_count} avatars (limited to 3).",
                        "messages": text_result
                    }
                    tool_outputs[-1]["functionResponse"]["response"] = full_tool_response
                    
                    # Only show avatars in history if they were actually added
                    if avatars:
                        avatar_parts = [{"text": "I found these avatars in the search results (sending max 3 to generation tools):"}]
                        for av in avatars[:3]:
                            avatar_parts.append({"inlineData": {"mimeType": av['mime_type'], "data": av['data']}})
                        extra_user_messages.append({"role": "user", "parts": avatar_parts})

                elif tool_name == "generate_image":
                    prompt = args.get("prompt_text", "Image")
                    if status_message:
                        await status_message.edit(content=f"> 🎨 Generating image: {prompt[:50]}...")
                    
                    image_io = await generate_image(prompt, gathered_images) # Uses the limited gathered_images
                    
                    if image_io:
                        await ctx.send(file=discord.File(image_io, filename="generated.png"))
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "success"}
                            }
                        })
                        generation_completed_this_turn = True
                    else:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "message": "Failed to generate image."}
                            }
                        })

                elif tool_name == "generate_video":
                    prompt = args.get("prompt_text", "Video")
                    
                    if status_message:
                        await status_message.edit(content=f"> 🎥 Generating video: {prompt[:50]}...")
                    
                    # Format gathered_images (tuples) into list of dicts for the new API
                    images_list = [{"mime_type": m, "data": d} for m, d in gathered_images]
                        
                    video_io = await generate_video(prompt, status_message, images_list=images_list)
                    
                    if video_io:
                        if status_message:
                            await status_message.delete()
                            status_message = None
                        
                        video_file = discord.File(video_io, filename="generated.mp4")
                        await ctx.send(file=video_file)
                        
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "success"}
                            }
                        })
                        generation_completed_this_turn = True
                    else:
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error", "message": "Failed to generate video."}
                            }
                        })

                elif tool_name == "generate_music":
                    prompt = args.get("prompt", "Music")
                    if status_message:
                        await status_message.edit(content=f"> 🎵 Generating music: {prompt[:50]}...")
                    else:
                        status_message = await ctx.send(f"> 🎵 Generating music: {prompt[:50]}...")
                    
                    tracks = await generate_music(**args)
                    
                    if tracks:
                        if status_message:
                            await status_message.delete()
                            status_message = None
                        
                        all_files_to_send = []
                        first_image_url = None # To ensure only one cover art is sent

                        for track in tracks:
                            title = track.get("title", "Generated Music")
                            audio_url = track.get("audio_url")
                            image_url = track.get("image_url")
                            lyrics = track.get("prompt", "") # lyrics are in 'prompt' field for custom mode
                            
                            if not first_image_url and image_url: # Get first image only
                                first_image_url = image_url

                            # Download Audio
                            if audio_url:
                                try:
                                    async with aiohttp.ClientSession() as session:
                                        async with session.get(audio_url) as resp:
                                            if resp.status == 200:
                                                audio_data = await resp.read()
                                                safe_title = "".join(x for x in title if x.isalnum() or x in " -_").strip()
                                                all_files_to_send.append(discord.File(io.BytesIO(audio_data), filename=f"{safe_title}.mp3"))
                                except Exception as e:
                                    print(f"Failed to download audio for {title}: {e}")
                            
                            # Prepare Lyrics File
                            if lyrics:
                                formatted_lyrics = lyrics.replace("\\n", "\n")
                                safe_title = "".join(x for x in title if x.isalnum() or x in " -_").strip()
                                all_files_to_send.append(discord.File(io.BytesIO(formatted_lyrics.encode('utf-8')), filename=f"{safe_title}_lyrics.txt"))
                        
                        # Download and add the first cover art after processing all tracks
                        if first_image_url:
                            try:
                                async with aiohttp.ClientSession() as session:
                                    async with session.get(first_image_url) as resp:
                                        if resp.status == 200:
                                            image_data = await resp.read()
                                            # Use a generic name for the cover since it's for the whole "album"
                                            ext = "jpeg"
                                            if ".png" in first_image_url.lower(): ext = "png"
                                            all_files_to_send.append(discord.File(io.BytesIO(image_data), filename=f"album_cover.{ext}"))
                            except Exception as e:
                                print(f"Failed to download cover art: {e}")

                        # Send all collected files in one message
                        try:
                            if all_files_to_send:
                                await ctx.send(files=all_files_to_send)
                        except Exception as e:
                            print(f"Failed to send combined music files: {e}")

                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "success"}
                            }
                        })
                        generation_completed_this_turn = True
                    else:
                        if status_message:
                             await status_message.edit(content="> ❌ Music generation failed.")
                        tool_outputs.append({
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"status": "error"}
                            }
                        })
            
            if tool_outputs:
                conversation_history.append({"role": "tool", "parts": tool_outputs})
            
            if extra_user_messages:
                conversation_history.extend(extra_user_messages)

            # Check if a generation tool completed this turn and break the main loop
            if generation_completed_this_turn:
                break # Break the main while loop

    @commands.command(name="nano")
    async def nano(self, ctx, *, prompt_text: str = ""):
        await self.ask(ctx, prompt_text=f"Generate an image of: {prompt_text}")

    @commands.command(name="vidgen")
    async def vidgen(self, ctx, *, prompt_text: str = ""):
        await self.ask(ctx, prompt_text=f"Generate a video of: {prompt_text}")

    @commands.command(name="ping")
    async def ping(self, ctx):
        await ctx.send("Pong!")

    @commands.command(name="adduser")
    @is_admin()
    async def add_user(self, ctx, user: discord.Member):
        user_id = str(user.id)
        if user_id in self.bot.authorized_users:
            await ctx.send(f"{user.mention} is already an authorized user.")
            return
        self.bot.authorized_users.add(user_id)
        self._save_authorized_users()
        await ctx.send(f"{user.mention} has been added to the authorized users.")

    @commands.command(name="removeuser")
    @is_admin()
    async def remove_user(self, ctx, user: discord.Member):
        user_id = str(user.id)
        if user_id not in self.bot.authorized_users:
            await ctx.send(f"{user.mention} is not an authorized user.")
            return
        if user_id == ADMIN_USER_ID:
            await ctx.send("Cannot remove the admin user.")
            return
        self.bot.authorized_users.remove(user_id)
        self._save_authorized_users()
        await ctx.send(f"{user.mention} has been removed from the authorized users.")

    def _save_authorized_users(self):
        with open(self.bot.auth_file_path, 'w') as f:
            json.dump({'authorized_users': list(self.bot.authorized_users)}, f, indent=2)

async def setup(bot):
    await bot.add_cog(GeneralCog(bot))