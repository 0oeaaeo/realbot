"""
Computer Use Cog - Browser automation using Gemini's Computer Use API.

This cog provides owner-only commands to automate browser tasks using
Gemini's computer use model. The browser state is displayed as an image
that updates via Discord message edits.
"""

import discord
from discord.ext import commands
from discord import ui
import asyncio
import io
import logging
import os
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

from google import genai
from google.genai import types
from google.genai.types import Content, Part

logger = logging.getLogger('realbot')

# Screen dimensions for the browser
SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900

# Maximum turns before stopping the agent loop
MAX_TURNS = 25

# Owner ID for fallback check
OWNER_ID = 1362274618953699370


@dataclass
class ComputerUseSession:
    """Represents an active computer use session."""
    playwright: Any = None
    browser: Any = None
    context: Any = None
    page: Any = None
    message: Optional[discord.Message] = None
    contents: List[Content] = field(default_factory=list)
    turn_count: int = 0
    is_running: bool = False
    task: str = ""


class SafetyConfirmationView(ui.View):
    """View for safety confirmation buttons."""
    
    def __init__(self, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.result: Optional[bool] = None
        self.event = asyncio.Event()
    
    @ui.button(label="✅ Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: ui.Button):
        self.result = True
        self.event.set()
        await interaction.response.defer()
    
    @ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: ui.Button):
        self.result = False
        self.event.set()
        await interaction.response.defer()
    
    async def wait_for_result(self) -> Optional[bool]:
        """Wait for user to click a button."""
        try:
            await asyncio.wait_for(self.event.wait(), timeout=self.timeout)
            return self.result
        except asyncio.TimeoutError:
            return None


class ComputerUseCog(commands.Cog):
    """Cog for browser automation using Gemini's Computer Use API."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions: Dict[int, ComputerUseSession] = {}  # channel_id -> session
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        logger.info("ComputerUseCog initialized")
    
    def cog_unload(self):
        """Cleanup when cog is unloaded."""
        # Schedule cleanup for all sessions
        for channel_id in list(self.sessions.keys()):
            asyncio.create_task(self._cleanup_session(channel_id))
    
    async def cog_check(self, ctx: commands.Context) -> bool:
        """Check if user is the bot owner."""
        return await self.bot.is_owner(ctx.author) or ctx.author.id == OWNER_ID
    
    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Handle cog-specific errors."""
        if isinstance(error, commands.CheckFailure):
            await ctx.reply("❌ This command is owner-only.")
        else:
            logger.exception(f"ComputerUse error: {error}")
            await ctx.reply(f"❌ Error: {error}")
    
    def _denormalize_x(self, x: int) -> int:
        """Convert normalized x coordinate (0-999) to actual pixel coordinate."""
        return int(x / 1000 * SCREEN_WIDTH)
    
    def _denormalize_y(self, y: int) -> int:
        """Convert normalized y coordinate (0-999) to actual pixel coordinate."""
        return int(y / 1000 * SCREEN_HEIGHT)
    
    async def _start_browser(self, session: ComputerUseSession) -> bool:
        """Start the Playwright browser."""
        try:
            from playwright.async_api import async_playwright
            
            session.playwright = await async_playwright().start()
            session.browser = await session.playwright.chromium.launch(headless=True)
            session.context = await session.browser.new_context(
                viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT}
            )
            session.page = await session.context.new_page()
            
            # Navigate to a starting page
            await session.page.goto("https://www.google.com")
            logger.info("Browser started successfully")
            return True
            
        except Exception as e:
            logger.exception(f"Failed to start browser: {e}")
            return False
    
    async def _cleanup_session(self, channel_id: int):
        """Clean up a session and its resources."""
        if channel_id not in self.sessions:
            return
        
        session = self.sessions[channel_id]
        session.is_running = False
        
        try:
            if session.browser:
                await session.browser.close()
            if session.playwright:
                await session.playwright.stop()
        except Exception as e:
            logger.error(f"Error cleaning up session: {e}")
        
        del self.sessions[channel_id]
        logger.info(f"Session cleaned up for channel {channel_id}")
    
    async def _take_screenshot(self, session: ComputerUseSession) -> bytes:
        """Take a screenshot of the current page."""
        return await session.page.screenshot(type="png")
    
    async def _update_message(self, session: ComputerUseSession, status: str, 
                             screenshot: Optional[bytes] = None, view: Optional[ui.View] = None):
        """Update the Discord message with new status and screenshot."""
        try:
            files = []
            if screenshot:
                files.append(discord.File(io.BytesIO(screenshot), filename="browser.png"))
            
            content = f"🖥️ **Computer Use Session**\n**Task:** {session.task[:100]}{'...' if len(session.task) > 100 else ''}\n**Turn:** {session.turn_count}/{MAX_TURNS}\n\n{status}"
            
            if session.message:
                await session.message.edit(content=content, attachments=files, view=view)
            
        except Exception as e:
            logger.error(f"Failed to update message: {e}")
    
    async def _execute_action(self, session: ComputerUseSession, function_call) -> Dict[str, Any]:
        """Execute a single action from the model."""
        fname = function_call.name
        args = function_call.args or {}
        result = {}
        
        logger.info(f"Executing action: {fname} with args: {args}")
        
        try:
            page = session.page
            
            if fname == "open_web_browser":
                # Already open
                pass
            
            elif fname == "wait_5_seconds":
                await asyncio.sleep(5)
            
            elif fname == "go_back":
                await page.go_back()
            
            elif fname == "go_forward":
                await page.go_forward()
            
            elif fname == "search":
                await page.goto("https://www.google.com")
            
            elif fname == "navigate":
                url = args.get("url", "")
                if url:
                    await page.goto(url)
            
            elif fname == "click_at":
                x = self._denormalize_x(args.get("x", 0))
                y = self._denormalize_y(args.get("y", 0))
                await page.mouse.click(x, y)
            
            elif fname == "hover_at":
                x = self._denormalize_x(args.get("x", 0))
                y = self._denormalize_y(args.get("y", 0))
                await page.mouse.move(x, y)
            
            elif fname == "type_text_at":
                x = self._denormalize_x(args.get("x", 0))
                y = self._denormalize_y(args.get("y", 0))
                text = args.get("text", "")
                press_enter = args.get("press_enter", True)
                clear_before = args.get("clear_before_typing", True)
                
                await page.mouse.click(x, y)
                
                if clear_before:
                    # Clear existing content
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                
                await page.keyboard.type(text)
                
                if press_enter:
                    await page.keyboard.press("Enter")
            
            elif fname == "key_combination":
                keys = args.get("keys", "")
                if keys:
                    await page.keyboard.press(keys)
            
            elif fname == "scroll_document":
                direction = args.get("direction", "down")
                if direction == "down":
                    await page.keyboard.press("PageDown")
                elif direction == "up":
                    await page.keyboard.press("PageUp")
                elif direction == "left":
                    await page.keyboard.press("Home")
                elif direction == "right":
                    await page.keyboard.press("End")
            
            elif fname == "scroll_at":
                x = self._denormalize_x(args.get("x", 500))
                y = self._denormalize_y(args.get("y", 500))
                direction = args.get("direction", "down")
                magnitude = args.get("magnitude", 800)
                
                # Convert magnitude to pixels
                scroll_amount = int(magnitude / 1000 * SCREEN_HEIGHT)
                
                await page.mouse.move(x, y)
                
                if direction == "down":
                    await page.mouse.wheel(0, scroll_amount)
                elif direction == "up":
                    await page.mouse.wheel(0, -scroll_amount)
                elif direction == "right":
                    await page.mouse.wheel(scroll_amount, 0)
                elif direction == "left":
                    await page.mouse.wheel(-scroll_amount, 0)
            
            elif fname == "drag_and_drop":
                x = self._denormalize_x(args.get("x", 0))
                y = self._denormalize_y(args.get("y", 0))
                dest_x = self._denormalize_x(args.get("destination_x", 0))
                dest_y = self._denormalize_y(args.get("destination_y", 0))
                
                await page.mouse.move(x, y)
                await page.mouse.down()
                await page.mouse.move(dest_x, dest_y)
                await page.mouse.up()
            
            else:
                logger.warning(f"Unknown action: {fname}")
                result["error"] = f"Unknown action: {fname}"
            
            # Wait for page to stabilize
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except:
                pass
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Error executing {fname}: {e}")
            result["error"] = str(e)
        
        return result
    
    async def _get_safety_confirmation(self, session: ComputerUseSession, 
                                       safety_decision: Dict) -> Tuple[bool, bool]:
        """
        Handle safety confirmation request.
        Returns (should_continue, was_approved)
        """
        explanation = safety_decision.get("explanation", "The model wants to perform a potentially risky action.")
        
        view = SafetyConfirmationView(timeout=120)
        screenshot = await self._take_screenshot(session)
        
        await self._update_message(
            session,
            f"⚠️ **Safety Confirmation Required**\n\n{explanation}\n\nClick a button to continue:",
            screenshot=screenshot,
            view=view
        )
        
        result = await view.wait_for_result()
        
        if result is None:
            # Timeout
            await self._update_message(session, "⏱️ Safety confirmation timed out. Stopping session.")
            return False, False
        elif result:
            return True, True  # Continue, approved
        else:
            await self._update_message(session, "🛑 Action denied by user. Stopping session.", screenshot=screenshot)
            return False, False
    
    async def _run_agent_loop(self, ctx: commands.Context, session: ComputerUseSession):
        """Run the main agent loop."""
        try:
            # Configure the model
            config = types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        computer_use=types.ComputerUse(
                            environment=types.Environment.ENVIRONMENT_BROWSER
                        )
                    )
                ],
            )
            
            # Take initial screenshot
            initial_screenshot = await self._take_screenshot(session)
            
            # Initialize conversation with user prompt and screenshot
            session.contents = [
                Content(role="user", parts=[
                    Part(text=session.task),
                    Part.from_bytes(data=initial_screenshot, mime_type="image/png")
                ])
            ]
            
            await self._update_message(session, "🤔 Analyzing task...", screenshot=initial_screenshot)
            
            # Agent loop
            while session.is_running and session.turn_count < MAX_TURNS:
                session.turn_count += 1
                
                # Generate content
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model="gemini-2.5-computer-use-preview-10-2025",
                    contents=session.contents,
                    config=config
                )
                
                if not response.candidates:
                    await self._update_message(session, "❌ No response from model.")
                    break
                
                candidate = response.candidates[0]
                session.contents.append(candidate.content)
                
                # Extract function calls and text
                function_calls = []
                thinking_text = []
                
                for part in candidate.content.parts:
                    if part.function_call:
                        function_calls.append(part.function_call)
                    if part.text:
                        thinking_text.append(part.text)
                
                thinking = " ".join(thinking_text)[:500] if thinking_text else ""
                
                # If no function calls, task is complete
                if not function_calls:
                    screenshot = await self._take_screenshot(session)
                    await self._update_message(
                        session,
                        f"✅ **Task Complete**\n\n{thinking}",
                        screenshot=screenshot
                    )
                    break
                
                # Execute each function call
                function_responses = []
                
                for fc in function_calls:
                    # Check for safety decision
                    args = fc.args or {}
                    extra_fields = {}
                    
                    if "safety_decision" in args:
                        safety_decision = args["safety_decision"]
                        if safety_decision.get("decision") == "require_confirmation":
                            should_continue, approved = await self._get_safety_confirmation(
                                session, safety_decision
                            )
                            if not should_continue:
                                session.is_running = False
                                return
                            if approved:
                                extra_fields["safety_acknowledgement"] = "true"
                    
                    # Update status
                    await self._update_message(
                        session,
                        f"🔧 Executing: `{fc.name}`\n📝 {thinking}",
                        screenshot=await self._take_screenshot(session)
                    )
                    
                    # Execute the action
                    result = await self._execute_action(session, fc)
                    result.update(extra_fields)
                    
                    # Capture new state
                    screenshot = await self._take_screenshot(session)
                    current_url = session.page.url
                    
                    # Build function response
                    response_data = {"url": current_url}
                    response_data.update(result)
                    
                    function_responses.append(
                        types.FunctionResponse(
                            name=fc.name,
                            response=response_data,
                            parts=[
                                types.FunctionResponsePart(
                                    inline_data=types.FunctionResponseBlob(
                                        mime_type="image/png",
                                        data=screenshot
                                    )
                                )
                            ]
                        )
                    )
                
                # Add function responses to conversation
                session.contents.append(
                    Content(role="user", parts=[
                        Part(function_response=fr) for fr in function_responses
                    ])
                )
                
                # Update message with latest screenshot
                await self._update_message(
                    session,
                    f"🔄 Processing... ({session.turn_count}/{MAX_TURNS})",
                    screenshot=screenshot
                )
            
            if session.turn_count >= MAX_TURNS:
                screenshot = await self._take_screenshot(session)
                await self._update_message(
                    session,
                    f"⚠️ Maximum turns ({MAX_TURNS}) reached. Session stopped.",
                    screenshot=screenshot
                )
        
        except Exception as e:
            logger.exception(f"Agent loop error: {e}")
            try:
                await self._update_message(session, f"❌ Error: {e}")
            except:
                pass
        
        finally:
            session.is_running = False
    
    @commands.command(name="cu")
    async def computer_use(self, ctx: commands.Context, *, task: str):
        """
        Start a computer use session to automate browser tasks.
        
        Usage: !cu <task description>
        Example: !cu Go to google.com and search for "hello world"
        """
        channel_id = ctx.channel.id
        
        # Check if there's already a session
        if channel_id in self.sessions and self.sessions[channel_id].is_running:
            await ctx.reply("❌ There's already an active session in this channel. Use `!custop` to stop it.")
            return
        
        # Create new session
        session = ComputerUseSession(task=task)
        self.sessions[channel_id] = session
        
        # Send initial message
        session.message = await ctx.send("🖥️ **Computer Use Session**\n⏳ Starting browser...")
        
        # Start browser
        if not await self._start_browser(session):
            await session.message.edit(content="❌ Failed to start browser. Make sure Playwright is installed:\n```\npip install playwright\nplaywright install chromium\n```")
            del self.sessions[channel_id]
            return
        
        session.is_running = True
        
        # Run agent loop in background
        asyncio.create_task(self._run_agent_loop(ctx, session))
    
    @commands.command(name="custop")
    async def computer_use_stop(self, ctx: commands.Context):
        """Stop the current computer use session."""
        channel_id = ctx.channel.id
        
        if channel_id not in self.sessions:
            await ctx.reply("❌ No active session in this channel.")
            return
        
        await self._cleanup_session(channel_id)
        await ctx.reply("✅ Computer use session stopped.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ComputerUseCog(bot))
