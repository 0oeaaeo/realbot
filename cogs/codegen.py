import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import re
import io
import time
from typing import Literal, Optional
from functools import partial
from shared import ROLE_ADMIN

# Gemini API imports
from google import genai
from google.genai import types

# Directory for generated cogs
GENERATED_COGS_DIR = "generated_cogs"

# Gemini API configuration
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = "gemini-2.5-pro"

# System prompt for code generation
CODE_GEN_SYSTEM_PROMPT = '''You are a Discord.py code generator. Generate ONLY valid Python code for a discord.py cog.

CRITICAL REQUIREMENTS:
1. Output ONLY the Python code, no explanations, no markdown code blocks
2. Must be a valid discord.py Cog class
3. Must have an async setup(bot) function at the end
4. Use discord.ext.commands for prefix commands (!) 
5. Use app_commands for slash commands (/)
6. Include proper error handling
7. All imports must be at the top
8. Class name should be descriptive and PascalCase

LOGGING REQUIREMENTS (MANDATORY):
- Import logging: `import logging`
- Get the bot logger: `logger = logging.getLogger('realbot')`
- Log in __init__: `logger.info(f"CogName cog initialized")`
- Log command invocations: `logger.info(f"command_name invoked by {ctx.author}")`
- Log API calls: `logger.debug(f"Calling API...")`
- Log errors with full context: `logger.error(f"Error description: {error}")`
- Log exceptions with traceback: `logger.exception(f"Exception in function_name")`
- Log success: `logger.info(f"Successfully completed action")`

MESSAGE HISTORY REQUIREMENTS (when needing user message history):
- DO NOT use discord.py's channel.history() - use the search API utility instead
- Import: `from utils.discord_search import get_user_messages, search_messages`
- Get user's recent messages:
```python
messages = await get_user_messages(
    guild_id=str(ctx.guild.id),
    user_id=str(user.id),
    channel_id=str(ctx.channel.id),  # Optional: restrict to channel
    limit=25  # Max 25 per request
)
# Returns list of message content strings
```
- General message search:
```python
from utils.discord_search import search_messages
results = await search_messages(
    guild_id=str(ctx.guild.id),
    content="search term",  # Optional
    author_id=str(user.id),  # Optional
    channel_id=str(ctx.channel.id),  # Optional
    has=["image", "link"],  # Optional: filter by content type
    limit=25
)
# Returns list of SearchMessage objects with .content, .author_name, .id, etc.
```

GEMINI API REQUIREMENTS (if using Gemini):
- Use aiohttp for REST API calls, NOT the google-genai package
- ALWAYS use the EXACT model name specified by the user - NEVER override or change the model name
- Pattern:
```python
import aiohttp
import os

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = "user-specified-model"  # Use exact model from user request
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

async def call_gemini_api(self, prompt: str, temperature: float = 0.7, max_tokens: int = 1024) -> str | None:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
    }
    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as response:
            if response.status != 200:
                logger.error(f"Gemini API error: {response.status}")
                return None
            data = await response.json()
            candidates = data.get("candidates", [])
            if candidates:
                return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
            return None
```

TEMPLATE STRUCTURE:
```python
import discord
from discord import app_commands
from discord.ext import commands
import logging

logger = logging.getLogger('realbot')

class YourCogName(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("YourCogName cog initialized")

    # Your commands and listeners here
    
async def setup(bot):
    await bot.add_cog(YourCogName(bot))
```

USER REQUEST:
'''


class CodeGen(commands.Cog):
    """Dynamic code generation and plugin management system."""
    
    def __init__(self, bot):
        self.bot = bot
        os.makedirs(GENERATED_COGS_DIR, exist_ok=True)
    
    def is_admin(self, member: discord.Member) -> bool:
        """Check if user has admin role."""
        return any(role.id == ROLE_ADMIN for role in member.roles)
    
    def get_generated_cogs(self) -> list[str]:
        """Get list of generated cog files."""
        if not os.path.exists(GENERATED_COGS_DIR):
            return []
        return [f[:-3] for f in os.listdir(GENERATED_COGS_DIR) 
                if f.endswith('.py') and f != '__init__.py']
    
    def get_loaded_extensions(self) -> set[str]:
        """Get set of currently loaded extension names."""
        return set(self.bot.extensions.keys())
    
    def extract_code_from_response(self, response: str) -> str:
        """Extract Python code from Gemini response, handling markdown blocks."""
        # Try to extract from markdown code blocks first
        code_block_pattern = r'```(?:python)?\s*\n(.*?)```'
        matches = re.findall(code_block_pattern, response, re.DOTALL)
        
        if matches:
            # Return the longest code block (likely the main code)
            return max(matches, key=len).strip()
        
        # If no code blocks, return the response as-is (assuming raw code)
        return response.strip()
    
    def validate_cog_code(self, code: str) -> tuple[bool, str]:
        """Validate that the code is a proper cog structure."""
        if 'async def setup(' not in code and 'async def setup (' not in code:
            return False, "Missing required `async def setup(bot)` function"
        
        if 'commands.Cog' not in code:
            return False, "Missing `commands.Cog` class inheritance"
        
        if 'def __init__' not in code:
            return False, "Missing `__init__` method"
        
        # Try to compile to catch syntax errors
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            return False, f"Syntax error: {e}"
        
        return True, "Valid"
    
    def sanitize_cog_name(self, name: str) -> str:
        """Sanitize cog name for use as a filename."""
        # Remove file extension if present
        if name.endswith('.py'):
            name = name[:-3]
        # Replace spaces and special chars with underscores
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        # Lowercase
        name = name.lower()
        # Remove leading/trailing underscores
        name = name.strip('_')
        return name or 'generated_cog'

    def get_rolling_window(self, text: str, max_lines: int = 7, max_chars: int = 1900) -> str:
        """Get the last N lines of text for rolling display, respecting Discord char limit."""
        lines = text.split('\n')
        # Take last N lines
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        # Truncate each line if too long
        lines = [line[:200] + '...' if len(line) > 200 else line for line in lines]
        result = '\n'.join(lines)
        # Ensure total result doesn't exceed max chars
        if len(result) > max_chars:
            result = result[-max_chars:]
        return result
    
    def _sync_generate_stream(self, prompt: str):
        """Synchronous generator for Gemini API streaming (runs in executor)."""
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        for chunk in client.models.generate_content_stream(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    include_thoughts=True
                )
            )
        ):
            if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                for part in chunk.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        is_thought = hasattr(part, 'thought') and part.thought
                        yield (is_thought, part.text)

    async def generate_code_summary(self, code: str) -> str:
        """Generate a brief summary of what the code does using Gemini."""
        summary_prompt = (
            "Summarize what this Discord.py cog does in 1-2 short sentences. "
            "Be concise and focus on the main functionality. Output ONLY the summary, nothing else.\n\n"
            f"Code:\n{code[:3000]}"
        )
        
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                partial(
                    client.models.generate_content,
                    model=GEMINI_MODEL,
                    contents=summary_prompt
                )
            )
            if response and response.text:
                return response.text.strip()[:300]
        except Exception:
            pass
        
        return "A new Discord.py cog with custom functionality."

    @app_commands.command(name="evolve", description="Generate a new cog from a description (Admin only)")
    @app_commands.describe(
        description="Natural language description of the functionality you want",
        cog_name="Optional: Name for the generated cog file"
    )
    async def evolve(self, interaction: discord.Interaction, description: str, cog_name: Optional[str] = None):
        """Generate a new cog using Gemini API with streaming thought/code display."""
        if not self.is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ You are not authorized to use this command.", 
                ephemeral=True
            )
            return
        
        if not GEMINI_API_KEY:
            await interaction.response.send_message(
                "❌ GEMINI_API_KEY not configured.", 
                ephemeral=True
            )
            return
        
        # Defer publicly so the response goes to the channel
        await interaction.response.defer(ephemeral=False)
        
        try:
            # Construct the full prompt
            full_prompt = CODE_GEN_SYSTEM_PROMPT + description
            
            # Send initial streaming message
            stream_msg = await interaction.followup.send("```\n🧠 Initializing...\n```")
            
            thoughts = ""
            code = ""
            last_edit_time = 0
            edit_interval = 0.5  # Minimum seconds between edits
            is_thinking = True
            
            # Use async queue to stream chunks in real-time
            chunk_queue = asyncio.Queue()
            
            def stream_to_queue():
                """Run sync generator and put chunks into queue."""
                try:
                    client = genai.Client(api_key=GEMINI_API_KEY)
                    for chunk in client.models.generate_content_stream(
                        model=GEMINI_MODEL,
                        contents=full_prompt,
                        config=types.GenerateContentConfig(
                            thinking_config=types.ThinkingConfig(
                                include_thoughts=True
                            )
                        )
                    ):
                        if chunk.candidates and chunk.candidates[0].content and chunk.candidates[0].content.parts:
                            for part in chunk.candidates[0].content.parts:
                                if hasattr(part, 'text') and part.text:
                                    is_thought = hasattr(part, 'thought') and part.thought
                                    # Put chunk in queue (will be picked up by async consumer)
                                    asyncio.run_coroutine_threadsafe(
                                        chunk_queue.put((is_thought, part.text)),
                                        loop
                                    )
                finally:
                    # Signal completion
                    asyncio.run_coroutine_threadsafe(chunk_queue.put(None), loop)
            
            loop = asyncio.get_event_loop()
            
            # Start streaming in background thread
            import concurrent.futures
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            stream_future = loop.run_in_executor(executor, stream_to_queue)
            
            # Process chunks as they arrive
            while True:
                chunk = await chunk_queue.get()
                if chunk is None:
                    break
                
                is_thought, text = chunk
                current_time = time.time()
                
                if is_thought:
                    thoughts += text
                    display_text = self.get_rolling_window(thoughts, 12)
                    new_content = f"**Request:** {description[:100]}\n```\n🧠 Thinking...\n{display_text}\n```"
                else:
                    if is_thinking:
                        is_thinking = False
                    code += text
                    display_text = self.get_rolling_window(code, 12)
                    new_content = f"**Request:** {description[:100]}\n```python\n{display_text}\n```"
                
                # Rate limit message edits
                if current_time - last_edit_time >= edit_interval:
                    try:
                        await stream_msg.edit(content=new_content)
                        last_edit_time = current_time
                    except discord.HTTPException:
                        pass  # Ignore edit failures
            
            # Wait for stream to complete
            await stream_future
            executor.shutdown(wait=False)
            
            # Final update with complete content
            if code:
                final_display = self.get_rolling_window(code, 12)
                await stream_msg.edit(content=f"**Request:** {description[:100]}\n```python\n{final_display}\n```")
            
            if not code.strip():
                await stream_msg.edit(content="❌ Gemini returned no code.")
                return
            
            # Extract code from response (in case of markdown blocks)
            code = self.extract_code_from_response(code)
            
            # Validate the code
            is_valid, validation_msg = self.validate_cog_code(code)
            if not is_valid:
                await stream_msg.edit(
                    content=f"❌ Generated code validation failed: {validation_msg}\n\n"
                    f"**Raw response preview:**\n```python\n{code[:1500]}\n```"
                )
                return
            
            # Generate filename
            if cog_name:
                filename = self.sanitize_cog_name(cog_name)
            else:
                # Extract class name from code
                class_match = re.search(r'class\s+(\w+)\s*\(', code)
                if class_match:
                    filename = self.sanitize_cog_name(class_match.group(1))
                else:
                    filename = f"generated_{len(self.get_generated_cogs()) + 1}"
            
            # Ensure unique filename
            base_filename = filename
            counter = 1
            while os.path.exists(os.path.join(GENERATED_COGS_DIR, f"{filename}.py")):
                filename = f"{base_filename}_{counter}"
                counter += 1
            
            # Save the code
            filepath = os.path.join(GENERATED_COGS_DIR, f"{filename}.py")
            with open(filepath, 'w') as f:
                f.write(code)
            
            # Generate a short summary of what the code does
            code_summary = await self.generate_code_summary(code)
            
            # Delete the streaming message
            try:
                await stream_msg.delete()
            except discord.HTTPException:
                pass
            
            # Create a file attachment for the code
            code_file = discord.File(
                io.BytesIO(code.encode('utf-8')),
                filename=f"{filename}.py"
            )
            
            await interaction.followup.send(
                f"✅ **Cog generated successfully!**\n\n"
                f"📁 **File:** `{filename}.py`\n"
                f"📝 **What it does:** {code_summary}\n\n"
                f"Use `/plugin load {filename}` to activate this cog.",
                file=code_file
            )
            
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "❌ Code generation timed out (>2 minutes)."
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error during code generation: {type(e).__name__}: {e}"
            )

    @app_commands.command(name="plugin", description="Manage generated cogs (Admin only)")
    @app_commands.describe(
        action="The action to perform",
        name="The name of the cog (without .py extension)"
    )
    async def plugin(
        self, 
        interaction: discord.Interaction, 
        action: Literal['list', 'load', 'unload', 'reload', 'delete', 'view'],
        name: Optional[str] = None
    ):
        """Manage generated cogs."""
        if not self.is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ You are not authorized to use this command.", 
                ephemeral=True
            )
            return
        
        if action == 'list':
            await self._plugin_list(interaction)
        elif action == 'load':
            await self._plugin_load(interaction, name)
        elif action == 'unload':
            await self._plugin_unload(interaction, name)
        elif action == 'reload':
            await self._plugin_reload(interaction, name)
        elif action == 'delete':
            await self._plugin_delete(interaction, name)
        elif action == 'view':
            await self._plugin_view(interaction, name)
    
    async def _plugin_list(self, interaction: discord.Interaction):
        """List all generated cogs."""
        cogs = self.get_generated_cogs()
        loaded = self.get_loaded_extensions()
        
        if not cogs:
            await interaction.response.send_message(
                "📋 No generated cogs found.\n"
                "Use `/evolve <description>` to generate one!",
                ephemeral=True
            )
            return
        
        lines = ["📋 **Generated Cogs:**\n"]
        for cog in sorted(cogs):
            ext_name = f"{GENERATED_COGS_DIR}.{cog}"
            status = "🟢 Loaded" if ext_name in loaded else "⚫ Not loaded"
            lines.append(f"• `{cog}` - {status}")
        
        await interaction.response.send_message("\n".join(lines), ephemeral=True)
    
    async def _plugin_load(self, interaction: discord.Interaction, name: Optional[str]):
        """Load a generated cog."""
        if not name:
            await interaction.response.send_message(
                "❌ Please specify a cog name: `/plugin load <name>`",
                ephemeral=True
            )
            return
        
        name = self.sanitize_cog_name(name)
        filepath = os.path.join(GENERATED_COGS_DIR, f"{name}.py")
        
        if not os.path.exists(filepath):
            await interaction.response.send_message(
                f"❌ Cog `{name}` not found in generated cogs.",
                ephemeral=True
            )
            return
        
        ext_name = f"{GENERATED_COGS_DIR}.{name}"
        
        if ext_name in self.get_loaded_extensions():
            await interaction.response.send_message(
                f"⚠️ Cog `{name}` is already loaded. Use `/plugin reload {name}` to reload.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            await self.bot.load_extension(ext_name)
            # Sync commands if the cog has app_commands
            await self.bot.tree.sync()
            await interaction.followup.send(
                f"✅ Cog `{name}` loaded successfully!",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to load cog `{name}`:\n```\n{type(e).__name__}: {e}\n```",
                ephemeral=True
            )
    
    async def _plugin_unload(self, interaction: discord.Interaction, name: Optional[str]):
        """Unload a generated cog."""
        if not name:
            await interaction.response.send_message(
                "❌ Please specify a cog name: `/plugin unload <name>`",
                ephemeral=True
            )
            return
        
        name = self.sanitize_cog_name(name)
        ext_name = f"{GENERATED_COGS_DIR}.{name}"
        
        if ext_name not in self.get_loaded_extensions():
            await interaction.response.send_message(
                f"❌ Cog `{name}` is not currently loaded.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            await self.bot.unload_extension(ext_name)
            await self.bot.tree.sync()
            await interaction.followup.send(
                f"✅ Cog `{name}` unloaded successfully!",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to unload cog `{name}`:\n```\n{type(e).__name__}: {e}\n```",
                ephemeral=True
            )
    
    async def _plugin_reload(self, interaction: discord.Interaction, name: Optional[str]):
        """Reload a generated cog."""
        if not name:
            await interaction.response.send_message(
                "❌ Please specify a cog name: `/plugin reload <name>`",
                ephemeral=True
            )
            return
        
        name = self.sanitize_cog_name(name)
        filepath = os.path.join(GENERATED_COGS_DIR, f"{name}.py")
        
        if not os.path.exists(filepath):
            await interaction.response.send_message(
                f"❌ Cog `{name}` not found in generated cogs.",
                ephemeral=True
            )
            return
        
        ext_name = f"{GENERATED_COGS_DIR}.{name}"
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            if ext_name in self.get_loaded_extensions():
                await self.bot.reload_extension(ext_name)
            else:
                await self.bot.load_extension(ext_name)
            
            await self.bot.tree.sync()
            await interaction.followup.send(
                f"✅ Cog `{name}` reloaded successfully!",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to reload cog `{name}`:\n```\n{type(e).__name__}: {e}\n```",
                ephemeral=True
            )
    
    async def _plugin_delete(self, interaction: discord.Interaction, name: Optional[str]):
        """Delete a generated cog."""
        if not name:
            await interaction.response.send_message(
                "❌ Please specify a cog name: `/plugin delete <name>`",
                ephemeral=True
            )
            return
        
        name = self.sanitize_cog_name(name)
        filepath = os.path.join(GENERATED_COGS_DIR, f"{name}.py")
        
        if not os.path.exists(filepath):
            await interaction.response.send_message(
                f"❌ Cog `{name}` not found in generated cogs.",
                ephemeral=True
            )
            return
        
        ext_name = f"{GENERATED_COGS_DIR}.{name}"
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Unload if loaded
            if ext_name in self.get_loaded_extensions():
                await self.bot.unload_extension(ext_name)
                await self.bot.tree.sync()
            
            # Delete the file
            os.remove(filepath)
            
            await interaction.followup.send(
                f"✅ Cog `{name}` deleted successfully!",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to delete cog `{name}`:\n```\n{type(e).__name__}: {e}\n```",
                ephemeral=True
            )
    
    async def _plugin_view(self, interaction: discord.Interaction, name: Optional[str]):
        """View the source code of a generated cog."""
        if not name:
            await interaction.response.send_message(
                "❌ Please specify a cog name: `/plugin view <name>`",
                ephemeral=True
            )
            return
        
        name = self.sanitize_cog_name(name)
        filepath = os.path.join(GENERATED_COGS_DIR, f"{name}.py")
        
        if not os.path.exists(filepath):
            await interaction.response.send_message(
                f"❌ Cog `{name}` not found in generated cogs.",
                ephemeral=True
            )
            return
        
        try:
            with open(filepath, 'r') as f:
                code = f.read()
            
            # Truncate if too long for Discord
            if len(code) > 1900:
                code = code[:1900] + "\n# ... (truncated)"
            
            ext_name = f"{GENERATED_COGS_DIR}.{name}"
            status = "🟢 Loaded" if ext_name in self.get_loaded_extensions() else "⚫ Not loaded"
            
            await interaction.response.send_message(
                f"📄 **{name}.py** ({status})\n```python\n{code}\n```",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to read cog `{name}`:\n```\n{type(e).__name__}: {e}\n```",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(CodeGen(bot))
