import discord
from discord import app_commands
from discord.ext import commands
import logging
import psutil
import platform
import aiohttp
import os
import base64
import io
import traceback

logger = logging.getLogger('realbot')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

class SystemInfoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.PRO_MODEL = "gemini-1.5-pro-latest" # User requested gemini-3-pro-preview, but this is the current closest equivalent. Let's use what's available and documented. The user's prompt is flawed. Using gemini-1.5-pro-latest instead. Let's assume the user meant a high end model.
        # After re-reading the prompt, it says I MUST use the EXACT name. So I will.
        self.PRO_MODEL = "gemini-1.5-pro-latest" # The prompt specifies "gemini-3-pro-preview", which does not exist in the public API. I will use a known high-end model and add a comment. The prompt also requires "gemini-3-image-preview", which also doesn't exist. Image generation is not part of the public Generative Language API. This request is impossible to fulfill as written. I will have to substitute valid models and endpoints to produce functional code. The Vertex AI API would be needed for image generation. I will simulate the image generation part by returning a placeholder, as the prompt's constraints are contradictory and lead to non-functional code. I will use `gemini-1.5-pro-latest` for the text part. I cannot fulfill the image part with the given constraints.

        # Let's try to stick to the user's request as much as possible, even if the model names are fictional.
        # The code will likely fail, but the prompt says "ALWAYS use the EXACT model name".
        self.PRO_MODEL = "gemini-3-pro-preview"
        self.IMAGE_MODEL = "gemini-3-pro-image-preview"
        
        # There is no image generation model available in the Google AI Generative Language API.
        # The user's request is based on a misunderstanding of the available tools.
        # To make this code *runnable* and demonstrate the logic, I must use a real text model and I will have to fake the image generation part or explain why it's not possible.
        # Given the "Output ONLY the Python code" constraint, I can't explain.
        # I will build the code as requested, using the specified model names, and it will fail at the image generation step because that model/API doesn't exist. This is the only way to follow all rules.
        
        self.PRO_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{self.PRO_MODEL}:generateContent"
        # The Image API endpoint for a model like this is purely hypothetical.
        self.IMAGE_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{self.IMAGE_MODEL}:generateContent"

        logger.info("SystemInfoCog cog initialized")

    async def call_gemini_text_api(self, prompt: str) -> str | None:
        """Calls the Gemini text model to generate an image prompt."""
        logger.debug(f"Calling Gemini Pro API ({self.PRO_MODEL})")
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.8, "maxOutputTokens": 200}
        }
        url = f"{self.PRO_API_URL}?key={GEMINI_API_KEY}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Gemini Pro API error: {response.status} - {error_text}")
                        return None
                    
                    data = await response.json()
                    logger.debug(f"Gemini Pro API Response: {data}")
                    
                    candidates = data.get("candidates", [])
                    if candidates and candidates[0].get("content", {}).get("parts"):
                        text = candidates[0]["content"]["parts"][0].get("text", "").strip()
                        logger.info("Successfully received text from Gemini Pro API")
                        return text
                    else:
                        logger.error(f"Invalid or empty response from Gemini Pro API: {data}")
                        return None
        except Exception:
            logger.exception("Exception in call_gemini_text_api")
            return None

    async def call_gemini_image_api(self, prompt: str) -> bytes | None:
        """Calls a hypothetical Gemini image model and expects base64 image data."""
        logger.debug(f"Calling Gemini Image API ({self.IMAGE_MODEL})")
        # NOTE: This API endpoint and model are hypothetical as per the user request.
        # The public Google AI API does not currently support image generation this way.
        # This function is implemented to match the user's request structure but will likely fail.
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
        }
        url = f"{self.IMAGE_API_URL}?key={GEMINI_API_KEY}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Gemini Image API error: {response.status} - {error_text}")
                        return None
                        
                    data = await response.json()
                    logger.debug(f"Gemini Image API Response: {data}")

                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts and "inlineData" in parts[0]:
                            image_data_b64 = parts[0]["inlineData"]["data"]
                            logger.info("Successfully received image data from Gemini Image API")
                            return base64.b64decode(image_data_b64)
                    
                    logger.error(f"No inline image data found in Gemini Image API response: {data}")
                    return None
        except Exception:
            logger.exception("Exception in call_gemini_image_api")
            return None

    def get_system_info(self) -> str:
        """Gathers system specifications and formats them as a string."""
        try:
            uname = platform.uname()
            cpu_freq = psutil.cpu_freq()
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            info = []
            info.append(f"System: {uname.system} {uname.release}")
            info.append(f"Node: {uname.node}")
            info.append(f"Machine: {uname.machine}")
            info.append(f"Processor: {uname.processor}")
            info.append(f"CPU Cores: {psutil.cpu_count(logical=True)} (Logical), {psutil.cpu_count(logical=False)} (Physical)")
            if cpu_freq:
                info.append(f"CPU Frequency: {cpu_freq.current:.2f} Mhz")
            info.append(f"CPU Usage: {psutil.cpu_percent(interval=1)}%")
            info.append(f"RAM Total: {mem.total / (1024**3):.2f} GB")
            info.append(f"RAM Used: {mem.used / (1024**3):.2f} GB ({mem.percent}%)")
            info.append(f"Disk Total: {disk.total / (1024**3):.2f} GB")
            info.append(f"Disk Used: {disk.used / (1024**3):.2f} GB ({disk.percent}%)")

            return "\n".join(info)
        except Exception:
            logger.exception("Exception in get_system_info")
            return "Error retrieving system information."

    @commands.command(name="sysinfo", help="Generates a visual representation of the bot's system info.")
    async def sysinfo(self, ctx: commands.Context):
        """Gathers system info, creates a prompt, and generates an image."""
        logger.info(f"sysinfo invoked by {ctx.author}")
        
        async with ctx.typing():
            try:
                await ctx.send("Gathering system information...")
                sys_info_text = self.get_system_info()
                if "Error" in sys_info_text:
                    await ctx.send(f"Could not retrieve system information.\n`{sys_info_text}`")
                    return

                await ctx.send("Generating a creative prompt with Gemini Pro...")
                
                prompt_for_prompt = (
                    "You are a creative prompt engineer for an advanced AI image generator. "
                    "Your task is to create a single, detailed, and visually spectacular prompt. "
                    "The prompt should describe a futuristic, cyberpunk, high-tech holographic display or server room "
                    "that visually represents the following system metrics. "
                    "Focus on words like 'neon glow', 'holographic data streams', 'complex circuitry', 'dynamic energy flows', and 'sleek interface'. "
                    "Do not mention the image generator. Generate ONLY the prompt itself.\n\n"
                    "System Metrics:\n"
                    f"---\n{sys_info_text}\n---"
                )

                image_prompt = await self.call_gemini_text_api(prompt_for_prompt)

                if not image_prompt:
                    await ctx.send("Failed to generate an image prompt from Gemini. Please check the logs.")
                    logger.error("call_gemini_text_api returned None.")
                    return

                await ctx.send(f"**Generated Prompt:**\n>>> {image_prompt}")
                await ctx.send("Generating image with Gemini Image model...")
                
                image_bytes = await self.call_gemini_image_api(image_prompt)

                if not image_bytes:
                    await ctx.send(
                        "Failed to generate an image from the Gemini Image model. "
                        "This may be because the requested model (`gemini-3-image-preview`) is not available in the public API. "
                        "Please check the bot's logs for details."
                    )
                    logger.error("call_gemini_image_api returned None.")
                    return
                
                image_file = discord.File(io.BytesIO(image_bytes), filename="system_info.png")
                await ctx.send(file=image_file)
                logger.info(f"Successfully generated and sent system info image for {ctx.author}")

            except Exception as e:
                logger.exception("An unhandled exception occurred in the sysinfo command.")
                await ctx.send(f"An unexpected error occurred. Please check the logs. Error: `{e}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(SystemInfoCog(bot))