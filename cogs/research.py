import discord
from discord.ext import commands
import asyncio
import time
import logging
import api_calls

logger = logging.getLogger('realbot')

class ResearchCog(commands.Cog):
    """Deep Research Agent - Plans, executes, and synthesizes multi-step research tasks."""
    
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="research")
    async def research(self, ctx, *, prompt: str):
        """
        Deep Research Agent - Plans, executes, and synthesizes multi-step research.
        Usage: !research <topic/question>
        """
        status_msg = await ctx.send("🔍 **Initializing Deep Research...**")
        
        last_update = time.time()
        accumulation_report = ""
        current_thought = ""
        all_thoughts = []
        interaction_id = "Unknown"
        
        try:
            async for event in api_calls.deep_research_stream(prompt):
                if event["type"] == "interaction_start":
                    interaction_id = event["id"]
                    await status_msg.edit(content=f"🔍 **Researching...** (ID: `{interaction_id}`)\nPreparing research plan...")
                
                elif event["type"] == "thought_delta":
                    current_thought = event["content"]
                    if current_thought and (not all_thoughts or all_thoughts[-1] != current_thought):
                        all_thoughts.append(current_thought)
                
                elif event["type"] == "text_delta":
                    accumulation_report += event["content"]
                
                elif event["type"] == "final_output":
                    # If we already have the report from deltas, don't overwrite
                    # but if we have nothing (or very little), use the final full output
                    if len(accumulation_report) < len(event["content"]):
                        accumulation_report = event["content"]
                
                elif event["type"] == "error":
                    await ctx.send(f"❌ **Deep Research Error:** {event['content']}")
                    return
                
                elif event["type"] == "complete":
                    break

                # Update status message with latest progress (throttled to avoid rate limits)
                now = time.time()
                if now - last_update > 3.0:
                    status_text = f"🔍 **Researching...** (ID: `{interaction_id}`)\n\n"
                    
                    if current_thought:
                        status_text += f"**Current Step:** *{current_thought}*\n"
                    
                    if accumulation_report:
                        # Show a snippet of the report as it builds
                        snippet = accumulation_report[-500:] # Show last 500 chars
                        status_text += f"\n**Generating Report...**\n```markdown\n...{snippet}\n```"
                    
                    await status_msg.edit(content=status_text[:2000])
                    last_update = now

            # Final Output
            if not accumulation_report:
                await status_msg.edit(content=f"✅ **Research Complete!** (ID: `{interaction_id}`)\nNo report content was generated.")
                return

            # If there are many thoughts, maybe summarize them or show in a separate embed/block
            # For now, let's just finalize the report message
            
            # Use chunks for the final report to handle Discord's 2000 char limit
            chunks = [accumulation_report[i:i+1900] for i in range(0, len(accumulation_report), 1900)]
            
            await status_msg.edit(content=f"✅ **Research Complete!** (ID: `{interaction_id}`)\n\nFinalizing report...")
            
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await ctx.send(f"### 📋 Research Report: {prompt[:100]}\n{chunk}")
                else:
                    await ctx.send(chunk)

        except Exception as e:
            logger.error(f"Error in !research command: {e}")
            await ctx.send(f"❌ **An unexpected error occurred during research:** {e}")

async def setup(bot):
    await bot.add_cog(ResearchCog(bot))
