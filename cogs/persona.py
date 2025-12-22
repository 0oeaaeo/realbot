"""
Persona Management Cog

Provides commands for creating, listing, and selecting bot personas.
Features an interactive interview flow for persona creation.
"""

import discord
from discord.ext import commands
import json
import os
import asyncio
import logging
from typing import Optional, Dict, List
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger('realbot')

# Initialize Gemini client
try:
    genai_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception as e:
    logger.error(f"Failed to initialize GenAI client: {e}")
    genai_client = None

PERSONAS_FILE = "personas.json"

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

# Interview questions for persona creation
INTERVIEW_SYSTEM_PROMPT = """You are helping create a new AI persona. You will conduct a brief interview to understand the personality.

Ask questions ONE AT A TIME. After each user response, acknowledge it and ask the next question.
Keep questions focused and conversational. Ask about:
1. The persona's name and basic identity
2. How they speak (formal/casual, vocabulary, catchphrases)
3. Their personality traits and attitude
4. Their knowledge areas or expertise
5. Any quirks or unique behaviors
6. Their relationship with the user

After collecting all answers (usually 5-7 questions), say "INTERVIEW_COMPLETE" followed by a JSON block with your synthesis.

Format when complete:
INTERVIEW_COMPLETE
```json
{
    "name": "Persona Name",
    "prompt": "Full system prompt for this persona..."
}
```
"""


class PersonaCog(commands.Cog):
    """Manage bot personas with interactive creation."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.personas: List[Dict] = []
        self.active_persona_index: int = 0
        self.interview_sessions: Dict[int, dict] = {}  # channel_id -> session state
        self._load_personas()
        logger.info("Persona cog initialized")
    
    def _load_personas(self):
        """Load personas from file."""
        if os.path.exists(PERSONAS_FILE):
            try:
                with open(PERSONAS_FILE, 'r') as f:
                    data = json.load(f)
                    self.personas = data.get("personas", DEFAULT_PERSONAS["personas"])
                    self.active_persona_index = data.get("active_index", 0)
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"Failed to load personas: {e}")
                self.personas = DEFAULT_PERSONAS["personas"]
                self.active_persona_index = 0
        else:
            self.personas = DEFAULT_PERSONAS["personas"]
            self.active_persona_index = 0
            self._save_personas()
    
    def _save_personas(self):
        """Save personas to file."""
        data = {
            "active_index": self.active_persona_index,
            "personas": self.personas
        }
        with open(PERSONAS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    
    def get_active_persona(self) -> Dict:
        """Get the currently active persona."""
        if 0 <= self.active_persona_index < len(self.personas):
            return self.personas[self.active_persona_index]
        return self.personas[0] if self.personas else DEFAULT_PERSONAS["personas"][0]
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for the active persona."""
        return self.get_active_persona().get("prompt", "")
    
    @commands.group(name="persona", invoke_without_command=True)
    async def persona(self, ctx):
        """Manage bot personas. Subcommands: list, select, add, rawadd"""
        await ctx.send("> **Persona Commands:**\n"
                      "> `!persona list` - View all personas\n"
                      "> `!persona select <index>` - Switch to a persona\n"
                      "> `!persona add` - Create persona via interview\n"
                      "> `!persona rawadd <name>` - Add persona with raw prompt")
    
    @persona.command(name="list")
    async def persona_list(self, ctx):
        """List all available personas."""
        if not self.personas:
            await ctx.send("> No personas available.")
            return
        
        lines = ["**📋 Available Personas:**\n"]
        for i, p in enumerate(self.personas):
            name = p.get("name", f"Persona {i}")
            is_raw = " [Raw]" if p.get("raw") else ""
            is_active = " ✅ **ACTIVE**" if i == self.active_persona_index else ""
            lines.append(f"`{i}` - {name}{is_raw}{is_active}")
        
        await ctx.send("\n".join(lines))
    
    @persona.command(name="select")
    async def persona_select(self, ctx, index: int):
        """Select a persona by index."""
        if not 0 <= index < len(self.personas):
            await ctx.send(f"> ❌ Invalid index. Use 0-{len(self.personas)-1}")
            return
        
        self.active_persona_index = index
        self._save_personas()
        name = self.personas[index].get("name", f"Persona {index}")
        await ctx.send(f"> ✅ Switched to persona: **{name}**")
    
    @persona.command(name="rawadd")
    async def persona_rawadd(self, ctx, *, name: str):
        """Add a persona with a raw prompt (next message)."""
        await ctx.send(f"> 📝 Reply with the raw system prompt for **{name}**:")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            msg = await self.bot.wait_for('message', check=check, timeout=300.0)
        except asyncio.TimeoutError:
            await ctx.send("> ⏰ Timed out waiting for prompt.")
            return
        
        new_persona = {
            "name": name,
            "prompt": msg.content,
            "raw": True
        }
        self.personas.append(new_persona)
        self._save_personas()
        
        await ctx.send(f"> ✅ Created raw persona **{name}** (index: {len(self.personas)-1})")
    
    @persona.command(name="add")
    async def persona_add(self, ctx):
        """Create a persona through an interactive interview."""
        if not genai_client:
            await ctx.send("> ❌ AI client not available.")
            return
        
        # Create initial interview display
        interview_display = self._format_interview_block([], None, "Starting interview...")
        status_msg = await ctx.send(interview_display)
        
        # Interview state
        conversation = [
            {"role": "user", "parts": [{"text": INTERVIEW_SYSTEM_PROMPT}]},
            {"role": "user", "parts": [{"text": "Let's begin the persona interview. Ask me the first question."}]}
        ]
        qa_pairs = []
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        # Get first question from AI
        try:
            ai_response = await self._call_gemini(conversation)
            if not ai_response:
                await status_msg.edit(content="> ❌ Failed to start interview.")
                return
            
            conversation.append({"role": "model", "parts": [{"text": ai_response}]})
            current_question = ai_response
            
            # Update display with first question
            interview_display = self._format_interview_block(qa_pairs, current_question, "Awaiting your response...")
            await status_msg.edit(content=interview_display)
            
        except Exception as e:
            logger.error(f"Interview start error: {e}")
            await status_msg.edit(content=f"> ❌ Error starting interview: {e}")
            return
        
        # Interview loop
        max_turns = 15  # Safety limit
        for turn in range(max_turns):
            try:
                # Wait for user response
                user_msg = await self.bot.wait_for('message', check=check, timeout=180.0)
                user_answer = user_msg.content
                
                # Delete user message to keep channel clean (optional)
                try:
                    await user_msg.delete()
                except:
                    pass
                
                # Record Q&A
                qa_pairs.append({"q": current_question, "a": user_answer})
                
                # Update display showing answer received
                interview_display = self._format_interview_block(qa_pairs, None, "Thinking...")
                await status_msg.edit(content=interview_display)
                
                # Send to AI
                conversation.append({"role": "user", "parts": [{"text": user_answer}]})
                ai_response = await self._call_gemini(conversation)
                
                if not ai_response:
                    await status_msg.edit(content=self._format_interview_block(qa_pairs, None, "❌ AI error"))
                    return
                
                conversation.append({"role": "model", "parts": [{"text": ai_response}]})
                
                # Check if interview is complete
                if "INTERVIEW_COMPLETE" in ai_response:
                    # Extract JSON
                    persona_data = self._extract_persona_json(ai_response)
                    if persona_data:
                        # Show final result
                        final_display = self._format_interview_block(
                            qa_pairs, None, 
                            f"✅ Interview complete!\n\n**Persona: {persona_data.get('name', 'New Persona')}**"
                        )
                        await status_msg.edit(content=final_display)
                        
                        # Ask for confirmation
                        confirm_msg = await ctx.send(
                            f"> **Preview:**\n```\n{persona_data.get('prompt', '')[:500]}...\n```\n"
                            f"> React with ✅ to save or ❌ to cancel."
                        )
                        await confirm_msg.add_reaction("✅")
                        await confirm_msg.add_reaction("❌")
                        
                        def reaction_check(reaction, user):
                            return user == ctx.author and str(reaction.emoji) in ["✅", "❌"]
                        
                        try:
                            reaction, _ = await self.bot.wait_for('reaction_add', check=reaction_check, timeout=60.0)
                            if str(reaction.emoji) == "✅":
                                # Save persona
                                new_persona = {
                                    "name": persona_data.get("name", "New Persona"),
                                    "prompt": persona_data.get("prompt", ""),
                                    "raw": False
                                }
                                self.personas.append(new_persona)
                                self._save_personas()
                                await ctx.send(f"> ✅ Persona **{new_persona['name']}** saved! (index: {len(self.personas)-1})")
                            else:
                                await ctx.send("> ❌ Persona creation cancelled.")
                        except asyncio.TimeoutError:
                            await ctx.send("> ⏰ Confirmation timed out. Persona not saved.")
                        
                        return
                    else:
                        await status_msg.edit(content=self._format_interview_block(qa_pairs, None, "❌ Failed to parse persona"))
                        return
                
                # Continue interview with next question
                current_question = ai_response
                interview_display = self._format_interview_block(qa_pairs, current_question, "Awaiting your response...")
                await status_msg.edit(content=interview_display)
                
            except asyncio.TimeoutError:
                await status_msg.edit(content=self._format_interview_block(qa_pairs, None, "⏰ Interview timed out."))
                return
            except Exception as e:
                logger.error(f"Interview loop error: {e}")
                await status_msg.edit(content=self._format_interview_block(qa_pairs, None, f"❌ Error: {e}"))
                return
        
        await status_msg.edit(content=self._format_interview_block(qa_pairs, None, "⚠️ Interview reached max turns."))
    
    def _format_interview_block(self, qa_pairs: List[Dict], current_question: Optional[str], status: str) -> str:
        """Format the interview as a live-updating codeblock."""
        lines = ["```"]
        lines.append("🎭 PERSONA INTERVIEW")
        lines.append("─" * 40)
        
        for i, qa in enumerate(qa_pairs, 1):
            q = qa["q"][:80] + "..." if len(qa["q"]) > 80 else qa["q"]
            a = qa["a"][:60] + "..." if len(qa["a"]) > 60 else qa["a"]
            # Clean up multi-line questions
            q = q.replace("\n", " ").strip()
            lines.append(f"Q{i}: {q}")
            lines.append(f"A{i}: {a}")
            lines.append("")
        
        if current_question:
            q = current_question[:100] + "..." if len(current_question) > 100 else current_question
            q = q.replace("\n", " ").strip()
            lines.append(f"Q{len(qa_pairs)+1}: {q}")
            lines.append(f"A{len(qa_pairs)+1}: (awaiting response...)")
            lines.append("")
        
        lines.append("─" * 40)
        lines.append(f"Status: {status}")
        lines.append("```")
        
        # Truncate if too long for Discord
        result = "\n".join(lines)
        if len(result) > 1900:
            # Keep only recent Q&As
            return self._format_interview_block(qa_pairs[-3:], current_question, status)
        return result
    
    def _extract_persona_json(self, text: str) -> Optional[Dict]:
        """Extract persona JSON from AI response."""
        try:
            import re
            # Find JSON block
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            # Try without code block
            json_match = re.search(r'\{[^{}]*"name"[^{}]*"prompt"[^{}]*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except Exception as e:
            logger.error(f"Failed to extract persona JSON: {e}")
        return None
    
    async def _call_gemini(self, messages: List[Dict]) -> Optional[str]:
        """Call Gemini Flash for interview."""
        if not genai_client:
            return None
        
        try:
            loop = asyncio.get_running_loop()
            
            def run_generation():
                return genai_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=messages,
                    config=types.GenerateContentConfig(
                        temperature=0.8
                    )
                )
            
            response = await loop.run_in_executor(None, run_generation)
            
            if response.candidates:
                for cand in response.candidates:
                    for part in cand.content.parts:
                        if part.text:
                            return part.text
            return None
        except Exception as e:
            logger.error(f"Gemini call error: {e}")
            return None


async def setup(bot):
    await bot.add_cog(PersonaCog(bot))
