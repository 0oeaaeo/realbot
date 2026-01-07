"""
Persona Analyzer Utility

Pre-processes user message history into structured persona profiles for efficient
simulation. Uses Gemini to extract linguistic patterns, vocabulary DNA, and 
behavioral signatures from raw message data.
"""

import os
import json
import hashlib
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path

from google import genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger('realbot')

# Initialize GenAI Client
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")
try:
    genai_client = genai.Client(api_key=API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize GenAI client for PersonaAnalyzer: {e}")
    genai_client = None

# Data persistence path
DATA_DIR = Path(__file__).parent.parent / "data"
PERSONA_CACHE_FILE = DATA_DIR / "persona_cache.json"


@dataclass
class PersonaProfile:
    """Structured representation of a user's communication style."""
    
    # Linguistic fingerprints
    avg_message_length: int = 50
    capitalization_pattern: str = "mixed"  # "lowercase", "normal", "CAPS", "mixed"
    punctuation_style: str = "minimal"     # "none", "minimal", "proper", "expressive"
    emoji_frequency: float = 0.1           # 0.0-1.0
    common_emojis: List[str] = field(default_factory=list)
    
    # Vocabulary DNA
    signature_phrases: List[str] = field(default_factory=list)
    slang_dictionary: Dict[str, str] = field(default_factory=dict)
    topic_affinities: List[str] = field(default_factory=list)
    
    # Behavioral patterns
    response_cadence: str = "moderate"     # "rapid-fire", "moderate", "thoughtful"
    emotional_baseline: str = "neutral"    # "chill", "intense", "melancholic", "chaotic"
    humor_style: str = "casual"            # "dry", "absurdist", "meme", "none"
    
    # Anti-repetition data
    banned_phrases: List[str] = field(default_factory=list)
    example_exchanges: List[Dict] = field(default_factory=list)
    
    # Metadata
    source_message_count: int = 0
    analysis_timestamp: str = ""
    profile_hash: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'PersonaProfile':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    def to_prompt_block(self) -> str:
        """Convert profile to a compact prompt injection block."""
        lines = [
            f"=== PERSONALITY PROFILE ===",
            f"Message style: {self.avg_message_length} chars avg, {self.capitalization_pattern} caps, {self.punctuation_style} punctuation",
            f"Emoji usage: {'frequent' if self.emoji_frequency > 0.3 else 'occasional' if self.emoji_frequency > 0.1 else 'rare'}",
        ]
        
        if self.common_emojis:
            lines.append(f"Favorite emojis: {' '.join(self.common_emojis[:5])}")
        
        if self.signature_phrases:
            lines.append(f"Signature phrases: {', '.join(self.signature_phrases[:5])}")
            
        if self.slang_dictionary:
            slang_examples = [f"{k}={v}" for k, v in list(self.slang_dictionary.items())[:5]]
            lines.append(f"Slang patterns: {', '.join(slang_examples)}")
            
        if self.topic_affinities:
            lines.append(f"Often talks about: {', '.join(self.topic_affinities[:5])}")
            
        lines.append(f"Vibe: {self.emotional_baseline}, {self.humor_style} humor, {self.response_cadence} responses")
        lines.append("=== END PROFILE ===")
        
        return "\n".join(lines)


# Prompt for Gemini to analyze messages
ANALYSIS_PROMPT = """Analyze these Discord messages from a user named "{name}" and extract their communication personality.

=== MESSAGES ===
{messages}
=== END MESSAGES ===

Analyze carefully and return a JSON object with EXACTLY this structure:
{{
    "avg_message_length": <integer: average character count per message>,
    "capitalization_pattern": "<lowercase|normal|CAPS|mixed>",
    "punctuation_style": "<none|minimal|proper|expressive>",
    "emoji_frequency": <float 0.0-1.0: what fraction of messages have emojis>,
    "common_emojis": ["<most used emojis, max 5>"],
    "signature_phrases": ["<unique recurring phrases they use, max 10>"],
    "slang_dictionary": {{"<abbreviation>": "<meaning>", ...}},
    "topic_affinities": ["<topics they frequently discuss, max 5>"],
    "response_cadence": "<rapid-fire|moderate|thoughtful>",
    "emotional_baseline": "<chill|intense|melancholic|chaotic|neutral>",
    "humor_style": "<dry|absurdist|meme|crude|supportive|none>",
    "banned_phrases": ["<exact notable phrases that should NEVER be repeated verbatim, max 15>"],
    "example_exchanges": [
        {{"context": "<hypothetical question>", "response": "<how they'd likely respond in their style>"}}
    ]
}}

IMPORTANT:
- signature_phrases should be UNIQUE phrases they repeat, not common words
- banned_phrases should be distinctive/memorable quotes that would be obvious if repeated
- example_exchanges should demonstrate their STYLE, not copy their actual messages
- Be precise with the capitalization and punctuation analysis

Return ONLY valid JSON, no markdown formatting or explanation."""


class PersonaAnalyzer:
    """Analyzes user message history and extracts structured persona profiles."""
    
    def __init__(self):
        self._cache: Dict[str, PersonaProfile] = {}
        self._load_cache()
    
    def _load_cache(self):
        """Load cached persona profiles from disk."""
        if PERSONA_CACHE_FILE.exists():
            try:
                with open(PERSONA_CACHE_FILE, 'r') as f:
                    data = json.load(f)
                for key, profile_data in data.items():
                    self._cache[key] = PersonaProfile.from_dict(profile_data)
                logger.info(f"Loaded {len(self._cache)} cached persona profiles")
            except Exception as e:
                logger.error(f"Failed to load persona cache: {e}")
    
    def _save_cache(self):
        """Save persona profiles to disk."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {key: profile.to_dict() for key, profile in self._cache.items()}
            with open(PERSONA_CACHE_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save persona cache: {e}")
    
    def _compute_hash(self, messages: List[str]) -> str:
        """Compute hash of message content for cache invalidation."""
        content = "".join(sorted(messages))
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def get_cached_profile(self, user_id: int, messages: List[str]) -> Optional[PersonaProfile]:
        """Get cached profile if messages haven't changed."""
        cache_key = str(user_id)
        if cache_key not in self._cache:
            return None
        
        profile = self._cache[cache_key]
        current_hash = self._compute_hash(messages)
        
        if profile.profile_hash == current_hash:
            logger.info(f"Using cached persona profile for user {user_id}")
            return profile
        
        return None
    
    async def analyze_messages(
        self, 
        user_id: int, 
        user_name: str, 
        messages: List[str],
        force_refresh: bool = False
    ) -> PersonaProfile:
        """
        Analyze messages and return a PersonaProfile.
        Uses cache if available and messages haven't changed.
        """
        # Check cache first
        if not force_refresh:
            cached = self.get_cached_profile(user_id, messages)
            if cached:
                return cached
        
        logger.info(f"Analyzing {len(messages)} messages for user {user_name}")
        
        if not genai_client:
            logger.error("GenAI client not available for persona analysis")
            return self._fallback_analysis(messages, user_name)
        
        try:
            # Prepare messages block (limit to avoid token overflow)
            message_block = "\n".join(messages[:200])  # Use top 200 for analysis
            
            prompt = ANALYSIS_PROMPT.format(name=user_name, messages=message_block)
            
            # Run analysis via Gemini
            response = await self._call_gemini(prompt)
            
            if not response:
                return self._fallback_analysis(messages, user_name)
            
            # Parse JSON response
            profile = self._parse_analysis_response(response, messages, user_id)
            
            # Cache the result
            self._cache[str(user_id)] = profile
            self._save_cache()
            
            return profile
            
        except Exception as e:
            logger.error(f"Persona analysis failed: {e}", exc_info=True)
            return self._fallback_analysis(messages, user_name)
    
    async def _call_gemini(self, prompt: str) -> Optional[str]:
        """Call Gemini API for analysis."""
        import asyncio
        
        loop = asyncio.get_running_loop()
        
        def make_request():
            response = genai_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config={
                    "temperature": 0.3,  # Lower temp for structured output
                    "max_output_tokens": 2000
                }
            )
            return response.text if response.text else None
        
        return await loop.run_in_executor(None, make_request)
    
    def _parse_analysis_response(
        self, 
        response: str, 
        messages: List[str],
        user_id: int
    ) -> PersonaProfile:
        """Parse Gemini's JSON response into PersonaProfile."""
        try:
            # Clean response (remove markdown code blocks if present)
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()
            
            data = json.loads(cleaned)
            
            profile = PersonaProfile(
                avg_message_length=data.get("avg_message_length", 50),
                capitalization_pattern=data.get("capitalization_pattern", "mixed"),
                punctuation_style=data.get("punctuation_style", "minimal"),
                emoji_frequency=data.get("emoji_frequency", 0.1),
                common_emojis=data.get("common_emojis", []),
                signature_phrases=data.get("signature_phrases", []),
                slang_dictionary=data.get("slang_dictionary", {}),
                topic_affinities=data.get("topic_affinities", []),
                response_cadence=data.get("response_cadence", "moderate"),
                emotional_baseline=data.get("emotional_baseline", "neutral"),
                humor_style=data.get("humor_style", "casual"),
                banned_phrases=data.get("banned_phrases", []),
                example_exchanges=data.get("example_exchanges", []),
                source_message_count=len(messages),
                analysis_timestamp=datetime.now().isoformat(),
                profile_hash=self._compute_hash(messages)
            )
            
            logger.info(f"Successfully parsed persona profile with {len(profile.banned_phrases)} banned phrases")
            return profile
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse analysis JSON: {e}")
            logger.debug(f"Raw response: {response[:500]}")
            return self._fallback_analysis(messages, str(user_id))
    
    def _fallback_analysis(self, messages: List[str], user_name: str) -> PersonaProfile:
        """Basic statistical analysis when Gemini is unavailable."""
        logger.warning("Using fallback statistical analysis")
        
        if not messages:
            return PersonaProfile()
        
        # Basic stats
        avg_len = sum(len(m) for m in messages) // len(messages)
        
        # Capitalization analysis
        lowercase_count = sum(1 for m in messages if m.islower())
        uppercase_count = sum(1 for m in messages if m.isupper())
        
        if lowercase_count > len(messages) * 0.7:
            cap_pattern = "lowercase"
        elif uppercase_count > len(messages) * 0.3:
            cap_pattern = "CAPS"
        else:
            cap_pattern = "mixed"
        
        # Emoji detection
        import re
        emoji_pattern = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]')
        emoji_messages = sum(1 for m in messages if emoji_pattern.search(m))
        emoji_freq = emoji_messages / len(messages)
        
        # Extract some notable phrases (3+ word sequences that appear multiple times)
        from collections import Counter
        words = " ".join(messages).split()
        trigrams = [" ".join(words[i:i+3]) for i in range(len(words)-2)]
        common_trigrams = [t for t, c in Counter(trigrams).most_common(10) if c > 2]
        
        return PersonaProfile(
            avg_message_length=avg_len,
            capitalization_pattern=cap_pattern,
            emoji_frequency=emoji_freq,
            banned_phrases=common_trigrams[:5],
            source_message_count=len(messages),
            analysis_timestamp=datetime.now().isoformat(),
            profile_hash=self._compute_hash(messages)
        )
    
    def invalidate_cache(self, user_id: int):
        """Remove cached profile for a user."""
        cache_key = str(user_id)
        if cache_key in self._cache:
            del self._cache[cache_key]
            self._save_cache()
            logger.info(f"Invalidated persona cache for user {user_id}")


# Singleton instance
_analyzer_instance: Optional[PersonaAnalyzer] = None

def get_persona_analyzer() -> PersonaAnalyzer:
    """Get the global PersonaAnalyzer instance."""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = PersonaAnalyzer()
    return _analyzer_instance
