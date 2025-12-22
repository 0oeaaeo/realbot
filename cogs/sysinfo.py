"""
Sysinfo Cog - Generates a visually spectacular system info image.

Gathers system stats, generates a creative prompt via Gemini, 
then creates a stunning visual representation.
"""

import discord
from discord.ext import commands
import io
import os
import platform
import asyncio
import logging
from datetime import datetime

import psutil
from google import genai
from google.genai import types
from dotenv import load_dotenv

from shared import ROLE_ADMIN

logger = logging.getLogger('realbot')

load_dotenv()
API_KEY = os.getenv("API_KEY")

# Initialize GenAI Client
try:
    genai_client = genai.Client(api_key=API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize GenAI client: {e}")
    genai_client = None


class SysinfoCog(commands.Cog):
    """System info command with AI-generated visualization."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("Sysinfo cog initialized")
    
    def is_admin(self, member: discord.Member) -> bool:
        """Check if user has admin role or is a bot admin."""
        has_role = any(role.id == ROLE_ADMIN for role in member.roles)
        is_bot_admin = hasattr(self.bot, 'bot_admins') and member.id in self.bot.bot_admins
        return has_role or is_bot_admin
    
    def _gather_system_info(self) -> str:
        """Gather comprehensive system information."""
        info_lines = []
        
        # Basic system info
        info_lines.append("=== SYSTEM INFO ===")
        info_lines.append(f"Hostname: {platform.node()}")
        info_lines.append(f"OS: {platform.system()} {platform.release()}")
        info_lines.append(f"Architecture: {platform.machine()}")
        info_lines.append(f"Python: {platform.python_version()}")
        
        # CPU info
        info_lines.append("\n=== CPU ===")
        info_lines.append(f"Processor: {platform.processor() or 'Unknown'}")
        info_lines.append(f"Physical Cores: {psutil.cpu_count(logical=False)}")
        info_lines.append(f"Logical Cores: {psutil.cpu_count(logical=True)}")
        
        cpu_freq = psutil.cpu_freq()
        if cpu_freq:
            info_lines.append(f"Max Frequency: {cpu_freq.max:.0f} MHz")
            info_lines.append(f"Current Frequency: {cpu_freq.current:.0f} MHz")
        
        cpu_percent = psutil.cpu_percent(interval=0.5, percpu=True)
        info_lines.append(f"CPU Usage (per core): {cpu_percent}")
        info_lines.append(f"CPU Usage (total): {psutil.cpu_percent()}%")
        
        # Memory info
        info_lines.append("\n=== MEMORY ===")
        mem = psutil.virtual_memory()
        info_lines.append(f"Total RAM: {mem.total / (1024**3):.1f} GB")
        info_lines.append(f"Available RAM: {mem.available / (1024**3):.1f} GB")
        info_lines.append(f"Used RAM: {mem.used / (1024**3):.1f} GB ({mem.percent}%)")
        
        swap = psutil.swap_memory()
        info_lines.append(f"Swap Total: {swap.total / (1024**3):.1f} GB")
        info_lines.append(f"Swap Used: {swap.used / (1024**3):.1f} GB ({swap.percent}%)")
        
        # Disk info
        info_lines.append("\n=== STORAGE ===")
        partitions = psutil.disk_partitions()
        for partition in partitions[:3]:  # Limit to first 3 partitions
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                info_lines.append(f"Disk {partition.mountpoint}:")
                info_lines.append(f"  Total: {usage.total / (1024**3):.1f} GB")
                info_lines.append(f"  Used: {usage.used / (1024**3):.1f} GB ({usage.percent}%)")
                info_lines.append(f"  Free: {usage.free / (1024**3):.1f} GB")
            except PermissionError:
                continue
        
        # Network info
        info_lines.append("\n=== NETWORK ===")
        net_io = psutil.net_io_counters()
        info_lines.append(f"Bytes Sent: {net_io.bytes_sent / (1024**3):.2f} GB")
        info_lines.append(f"Bytes Received: {net_io.bytes_recv / (1024**3):.2f} GB")
        info_lines.append(f"Packets Sent: {net_io.packets_sent:,}")
        info_lines.append(f"Packets Received: {net_io.packets_recv:,}")
        
        # Process info
        info_lines.append("\n=== PROCESSES ===")
        info_lines.append(f"Total Processes: {len(psutil.pids())}")
        
        # Uptime
        info_lines.append("\n=== UPTIME ===")
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        info_lines.append(f"System Uptime: {days}d {hours}h {minutes}m {seconds}s")
        info_lines.append(f"Boot Time: {boot_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Load average (Unix only)
        try:
            load1, load5, load15 = os.getloadavg()
            info_lines.append(f"\n=== LOAD AVERAGE ===")
            info_lines.append(f"1 min: {load1:.2f}")
            info_lines.append(f"5 min: {load5:.2f}")
            info_lines.append(f"15 min: {load15:.2f}")
        except (OSError, AttributeError):
            pass
        
        return "\n".join(info_lines)
    
    async def _generate_visual_prompt(self, system_info: str) -> str:
        """Use Gemini to generate a creative visual prompt based on system info."""
        if not genai_client:
            return None
        
        prompt = f"""You are a creative prompt engineer for AI image generators.

I have the following system information that I want to visualize as a stunning, futuristic infographic or data visualization image.

SYSTEM INFORMATION:
{system_info}

Your task: Create an incredibly detailed and creative prompt for an AI image generator (like DALL-E, Midjourney, or Imagen) that will produce a VISUALLY SPECTACULAR representation of this system data.

Guidelines:
- Make it look like a futuristic holographic display, sci-fi HUD, or cyberpunk dashboard
- Include visual representations of the key metrics (CPU usage as glowing cores, RAM as energy bars, etc.)
- Use neon colors, glowing effects, and high-tech aesthetics
- The image should be beautiful and impressive, not just functional
- Include the actual numerical values in creative ways (floating holographic text, digital readouts, etc.)
- Think: Iron Man's JARVIS interface, Blade Runner aesthetics, or futuristic command centers
- Make it look like something from a AAA video game or blockbuster sci-fi movie

Output ONLY the image generation prompt, nothing else. Make it detailed and specific."""

        try:
            loop = asyncio.get_running_loop()
            
            def generate():
                return genai_client.models.generate_content(
                    model="gemini-3-pro-preview",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.9
                    )
                )
            
            response = await loop.run_in_executor(None, generate)
            
            if response.candidates and response.candidates[0].content.parts:
                return response.candidates[0].content.parts[0].text
            return None
            
        except Exception as e:
            logger.error(f"Visual prompt generation error: {e}")
            return None
    
    async def _generate_image(self, prompt: str) -> io.BytesIO:
        """Generate an image using Gemini image model."""
        if not genai_client:
            return None
        
        try:
            loop = asyncio.get_running_loop()
            
            def generate():
                return genai_client.models.generate_content(
                    model="gemini-3-pro-image-preview",
                    contents=prompt
                )
            
            response = await loop.run_in_executor(None, generate)
            
            if response.candidates:
                for cand in response.candidates:
                    for part in cand.content.parts:
                        if part.inline_data and part.inline_data.data:
                            data = part.inline_data.data
                            if isinstance(data, bytes):
                                return io.BytesIO(data)
                            elif isinstance(data, str):
                                import base64
                                return io.BytesIO(base64.b64decode(data))
            
            return None
            
        except Exception as e:
            logger.error(f"Image generation error: {e}")
            return None
    
    @commands.command(name="sysinfo")
    @commands.guild_only()
    async def sysinfo(self, ctx: commands.Context):
        """
        Generate a stunning AI visualization of system information.
        
        Gathers system specs, creates a creative visual prompt,
        then generates a spectacular infographic image.
        """
        # Admin-only check
        if not self.is_admin(ctx.author):
            await ctx.send("❌ This command is admin-only.")
            return
        
        status_message = await ctx.send("> 📊 Gathering system information...")
        
        try:
            # Step 1: Gather system info
            loop = asyncio.get_running_loop()
            system_info = await loop.run_in_executor(None, self._gather_system_info)
            
            await status_message.edit(content=f"> 📊 System info gathered!\n> 🎨 Generating creative visual prompt...")
            
            # Step 2: Generate visual prompt using Gemini
            visual_prompt = await self._generate_visual_prompt(system_info)
            
            if not visual_prompt:
                await status_message.edit(content="> ❌ Failed to generate visual prompt.")
                return
            
            await status_message.edit(content=f"> 📊 System info gathered!\n> 🎨 Visual prompt created!\n> 🖼️ Generating stunning visualization...")
            
            # Step 3: Generate image using the visual prompt
            image_io = await self._generate_image(visual_prompt)
            
            if not image_io:
                await status_message.edit(content=f"> ❌ Failed to generate image.\n\n**Generated Prompt:**\n```\n{visual_prompt[:1500]}...\n```")
                return
            
            # Step 4: Send the final image
            await status_message.delete()
            
            # Send the image with a summary
            embed = discord.Embed(
                title="🖥️ System Visualization",
                description=f"**Quick Stats:**\n"
                           f"• CPU: {psutil.cpu_percent()}% usage\n"
                           f"• RAM: {psutil.virtual_memory().percent}% used\n"
                           f"• Uptime: {(datetime.now() - datetime.fromtimestamp(psutil.boot_time())).days}d",
                color=0x00ff88
            )
            
            await ctx.send(
                embed=embed,
                file=discord.File(image_io, filename="sysinfo_visualization.png")
            )
            
        except Exception as e:
            logger.error(f"Sysinfo command error: {e}")
            await status_message.edit(content=f"> ❌ Error: {str(e)[:200]}")


async def setup(bot):
    await bot.add_cog(SysinfoCog(bot))
