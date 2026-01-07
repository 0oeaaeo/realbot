"""
Emotion Engine Utility

Tracks and manages emotional states for simulated personas and chatty mode.
Based on Plutchik's wheel of emotions with decay/amplification mechanics
and persistent memory journaling.
"""

import os
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum

logger = logging.getLogger('realbot')

# Data persistence path
DATA_DIR = Path(__file__).parent.parent / "data"
EMOTION_JOURNAL_FILE = DATA_DIR / "emotion_journal.json"


class Emotion(Enum):
    """Core emotions based on Plutchik's wheel (simplified)."""
    JOY = "joy"
    TRUST = "trust"
    FEAR = "fear"
    SURPRISE = "surprise"
    SADNESS = "sadness"
    DISGUST = "disgust"
    ANGER = "anger"
    ANTICIPATION = "anticipation"


# Emotion configuration
EMOTION_CONFIG = {
    Emotion.JOY: {"opposite": Emotion.SADNESS, "decay_rate": 0.1, "color": "🟡"},
    Emotion.TRUST: {"opposite": Emotion.DISGUST, "decay_rate": 0.05, "color": "🟢"},
    Emotion.FEAR: {"opposite": Emotion.ANGER, "decay_rate": 0.15, "color": "🟣"},
    Emotion.SURPRISE: {"opposite": Emotion.ANTICIPATION, "decay_rate": 0.2, "color": "🔵"},
    Emotion.SADNESS: {"opposite": Emotion.JOY, "decay_rate": 0.08, "color": "🔵"},
    Emotion.DISGUST: {"opposite": Emotion.TRUST, "decay_rate": 0.1, "color": "🟤"},
    Emotion.ANGER: {"opposite": Emotion.FEAR, "decay_rate": 0.12, "color": "🔴"},
    Emotion.ANTICIPATION: {"opposite": Emotion.SURPRISE, "decay_rate": 0.1, "color": "🟠"},
}

# Keywords that trigger emotional responses
EMOTION_TRIGGERS = {
    Emotion.JOY: [
        "awesome", "amazing", "love", "great", "happy", "yay", "lol", "lmao", 
        "haha", "nice", "cool", "thanks", "thank you", "appreciate", "beautiful",
        "perfect", "best", "wonderful", "fantastic", "excellent", "❤️", "😊", "😄"
    ],
    Emotion.SADNESS: [
        "sad", "sorry", "miss", "lost", "alone", "lonely", "depressed", "crying",
        "tears", "hurt", "pain", "goodbye", "gone", "never", "😢", "😭", "💔"
    ],
    Emotion.ANGER: [
        "hate", "angry", "mad", "furious", "stupid", "idiot", "dumb", "annoying",
        "pissed", "fuck", "shit", "damn", "wtf", "stfu", "😡", "🤬"
    ],
    Emotion.FEAR: [
        "scared", "afraid", "terrified", "worried", "anxious", "nervous", "panic",
        "danger", "threat", "scary", "creepy", "😰", "😱"
    ],
    Emotion.TRUST: [
        "trust", "believe", "honest", "reliable", "friend", "loyal", "support",
        "help", "together", "promise", "always", "🤝", "💪"
    ],
    Emotion.DISGUST: [
        "gross", "disgusting", "nasty", "ew", "eww", "yuck", "sick", "vile",
        "repulsive", "horrible", "🤮", "🤢"
    ],
    Emotion.SURPRISE: [
        "wow", "omg", "whoa", "what", "really", "seriously", "no way", "shocked",
        "unexpected", "crazy", "insane", "😮", "😲", "🤯"
    ],
    Emotion.ANTICIPATION: [
        "waiting", "excited", "can't wait", "soon", "ready", "looking forward",
        "hope", "maybe", "tomorrow", "next", "🤞", "⏳"
    ],
}


@dataclass
class EmotionalState:
    """Represents current emotional state of a persona."""
    
    # Emotion intensities (0.0 - 1.0)
    emotions: Dict[str, float] = field(default_factory=lambda: {
        e.value: 0.3 for e in Emotion  # Start at neutral baseline
    })
    
    # Derived properties
    stability: float = 0.7  # How stable/volatile the persona is (0.0-1.0)
    last_updated: str = ""
    
    # History tracking
    mood_history: List[Dict] = field(default_factory=list)  # {timestamp, dominant}
    
    def get_dominant_emotion(self) -> Tuple[str, float]:
        """Get the highest intensity emotion."""
        if not self.emotions:
            return ("neutral", 0.0)
        dominant = max(self.emotions.items(), key=lambda x: x[1])
        return dominant
    
    def get_mood_description(self) -> str:
        """Get a human-readable mood description."""
        dominant, intensity = self.get_dominant_emotion()
        
        if intensity < 0.3:
            return "neutral"
        elif intensity < 0.5:
            return f"slightly {dominant}"
        elif intensity < 0.7:
            return f"{dominant}"
        else:
            return f"very {dominant}"
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'EmotionalState':
        state = cls()
        state.emotions = data.get("emotions", state.emotions)
        state.stability = data.get("stability", 0.7)
        state.last_updated = data.get("last_updated", "")
        state.mood_history = data.get("mood_history", [])
        return state
    
    def to_prompt_block(self) -> str:
        """Convert emotional state to prompt injection."""
        dominant, intensity = self.get_dominant_emotion()
        mood = self.get_mood_description()
        
        # Get top 3 emotions
        sorted_emotions = sorted(self.emotions.items(), key=lambda x: x[1], reverse=True)[:3]
        emotion_list = [f"{e}({int(v*100)}%)" for e, v in sorted_emotions]
        
        return f"""=== CURRENT EMOTIONAL STATE ===
Dominant mood: {mood}
Emotional blend: {', '.join(emotion_list)}
Stability: {'stable' if self.stability > 0.6 else 'volatile' if self.stability < 0.4 else 'moderate'}
=== END EMOTIONAL STATE ==="""


@dataclass 
class JournalEntry:
    """A single emotional memory entry."""
    timestamp: str
    trigger: str
    emotion_shift: Dict[str, float]
    context_snippet: str
    user_id: Optional[int] = None


class EmotionEngine:
    """
    Manages emotional states for simulations and chatty mode.
    Handles emotion triggers, decay, amplification, and persistence.
    """
    
    def __init__(self):
        # Active states: key -> EmotionalState
        # Key format: "sim_{user_id}" or "chatty_{channel_id}"
        self._states: Dict[str, EmotionalState] = {}
        
        # Journal entries for emotional memory
        self._journal: Dict[str, List[Dict]] = {}
        
        # User relationship tracking (for chatty): channel_id -> {user_id -> scores}
        self._relationships: Dict[str, Dict[str, Dict[str, float]]] = {}
        
        self._load_state()
    
    def _load_state(self):
        """Load emotional states from disk."""
        if EMOTION_JOURNAL_FILE.exists():
            try:
                with open(EMOTION_JOURNAL_FILE, 'r') as f:
                    data = json.load(f)
                
                # Load states
                for key, state_data in data.get("states", {}).items():
                    self._states[key] = EmotionalState.from_dict(state_data)
                
                # Load journal
                self._journal = data.get("journal", {})
                
                # Load relationships
                self._relationships = data.get("relationships", {})
                
                logger.info(f"Loaded emotion engine: {len(self._states)} states, {len(self._journal)} journals")
            except Exception as e:
                logger.error(f"Failed to load emotion journal: {e}")
    
    def _save_state(self):
        """Save emotional states to disk."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            
            data = {
                "states": {key: state.to_dict() for key, state in self._states.items()},
                "journal": self._journal,
                "relationships": self._relationships,
                "last_saved": datetime.now().isoformat()
            }
            
            with open(EMOTION_JOURNAL_FILE, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save emotion journal: {e}")
    
    def _get_state_key(self, mode: str, entity_id: int) -> str:
        """Generate state key."""
        return f"{mode}_{entity_id}"
    
    def get_state(self, mode: str, entity_id: int) -> EmotionalState:
        """Get or create emotional state for an entity."""
        key = self._get_state_key(mode, entity_id)
        
        if key not in self._states:
            self._states[key] = EmotionalState(last_updated=datetime.now().isoformat())
        
        return self._states[key]
    
    def analyze_message_sentiment(self, message: str) -> Dict[str, float]:
        """
        Analyze a message and return emotion trigger scores.
        Returns dict of emotion -> intensity change (-1.0 to 1.0).
        """
        message_lower = message.lower()
        triggers = {}
        
        for emotion, keywords in EMOTION_TRIGGERS.items():
            score = 0.0
            matches = 0
            
            for keyword in keywords:
                if keyword in message_lower:
                    matches += 1
                    # Weight longer matches more heavily
                    score += 0.1 + (len(keyword) * 0.01)
            
            if matches > 0:
                # Cap individual emotion trigger at 0.3
                triggers[emotion.value] = min(score, 0.3)
        
        return triggers
    
    def process_message(
        self, 
        mode: str, 
        entity_id: int, 
        message: str,
        user_id: Optional[int] = None,
        context: str = ""
    ) -> EmotionalState:
        """
        Process an incoming message and update emotional state.
        Returns the updated state.
        """
        state = self.get_state(mode, entity_id)
        key = self._get_state_key(mode, entity_id)
        
        # Apply time-based decay first
        self._apply_decay(state)
        
        # Analyze message for triggers
        triggers = self.analyze_message_sentiment(message)
        
        if triggers:
            # Apply emotion changes
            for emotion_name, change in triggers.items():
                if emotion_name in state.emotions:
                    # Amplify or dampen based on stability
                    modifier = 1.5 if state.stability < 0.4 else 1.0 if state.stability > 0.6 else 1.2
                    new_value = state.emotions[emotion_name] + (change * modifier)
                    state.emotions[emotion_name] = max(0.0, min(1.0, new_value))
                    
                    # Reduce opposite emotion
                    emotion_enum = Emotion(emotion_name)
                    opposite = EMOTION_CONFIG[emotion_enum]["opposite"]
                    if opposite.value in state.emotions:
                        state.emotions[opposite.value] = max(0.0, state.emotions[opposite.value] - (change * 0.5))
            
            # Log to journal
            self._add_journal_entry(
                key=key,
                trigger=message[:100],
                emotion_shift=triggers,
                context=context,
                user_id=user_id
            )
        
        # Update mood history
        dominant, intensity = state.get_dominant_emotion()
        state.mood_history.append({
            "timestamp": datetime.now().isoformat(),
            "dominant": dominant,
            "intensity": intensity
        })
        
        # Keep only last 50 mood entries
        state.mood_history = state.mood_history[-50:]
        
        state.last_updated = datetime.now().isoformat()
        self._save_state()
        
        return state
    
    def _apply_decay(self, state: EmotionalState):
        """Apply time-based decay to emotions."""
        if not state.last_updated:
            return
        
        try:
            last_update = datetime.fromisoformat(state.last_updated)
            elapsed = datetime.now() - last_update
            hours_elapsed = elapsed.total_seconds() / 3600
            
            if hours_elapsed < 0.1:  # Less than 6 minutes
                return
            
            for emotion_name in state.emotions:
                emotion_enum = Emotion(emotion_name)
                decay_rate = EMOTION_CONFIG[emotion_enum]["decay_rate"]
                
                # Decay toward baseline (0.3)
                current = state.emotions[emotion_name]
                baseline = 0.3
                
                if current > baseline:
                    decay = decay_rate * hours_elapsed
                    state.emotions[emotion_name] = max(baseline, current - decay)
                elif current < baseline:
                    recovery = decay_rate * hours_elapsed * 0.5  # Recover slower
                    state.emotions[emotion_name] = min(baseline, current + recovery)
                    
        except Exception as e:
            logger.debug(f"Decay calculation error: {e}")
    
    def _add_journal_entry(
        self,
        key: str,
        trigger: str,
        emotion_shift: Dict[str, float],
        context: str,
        user_id: Optional[int]
    ):
        """Add entry to emotional memory journal."""
        if key not in self._journal:
            self._journal[key] = []
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "trigger": trigger,
            "emotion_shift": emotion_shift,
            "context": context[:200] if context else "",
            "user_id": user_id
        }
        
        self._journal[key].append(entry)
        
        # Keep only last 100 entries per entity
        self._journal[key] = self._journal[key][-100:]
    
    def get_recent_triggers(self, mode: str, entity_id: int, limit: int = 5) -> List[Dict]:
        """Get recent emotional triggers for prompt context."""
        key = self._get_state_key(mode, entity_id)
        
        if key not in self._journal:
            return []
        
        return self._journal[key][-limit:]
    
    def get_user_relationship(
        self, 
        channel_id: int, 
        user_id: int
    ) -> Dict[str, float]:
        """Get relationship scores between chatty bot and a user."""
        channel_key = str(channel_id)
        user_key = str(user_id)
        
        if channel_key not in self._relationships:
            self._relationships[channel_key] = {}
        
        if user_key not in self._relationships[channel_key]:
            self._relationships[channel_key][user_key] = {
                "trust": 0.5,
                "familiarity": 0.0,
                "affinity": 0.5
            }
        
        return self._relationships[channel_key][user_key]
    
    def update_user_relationship(
        self,
        channel_id: int,
        user_id: int,
        trust_delta: float = 0.0,
        familiarity_delta: float = 0.0,
        affinity_delta: float = 0.0
    ):
        """Update relationship scores with a user."""
        scores = self.get_user_relationship(channel_id, user_id)
        
        scores["trust"] = max(0.0, min(1.0, scores["trust"] + trust_delta))
        scores["familiarity"] = max(0.0, min(1.0, scores["familiarity"] + familiarity_delta))
        scores["affinity"] = max(0.0, min(1.0, scores["affinity"] + affinity_delta))
        
        self._relationships[str(channel_id)][str(user_id)] = scores
        self._save_state()
    
    def boost_emotion(
        self, 
        mode: str, 
        entity_id: int, 
        emotion: str, 
        amount: float
    ):
        """Manually boost a specific emotion."""
        state = self.get_state(mode, entity_id)
        
        if emotion in state.emotions:
            state.emotions[emotion] = max(0.0, min(1.0, state.emotions[emotion] + amount))
            state.last_updated = datetime.now().isoformat()
            self._save_state()
    
    def set_stability(self, mode: str, entity_id: int, stability: float):
        """Set emotional stability for an entity."""
        state = self.get_state(mode, entity_id)
        state.stability = max(0.0, min(1.0, stability))
        self._save_state()
    
    def reset_state(self, mode: str, entity_id: int):
        """Reset emotional state to baseline."""
        key = self._get_state_key(mode, entity_id)
        
        if key in self._states:
            del self._states[key]
        if key in self._journal:
            del self._journal[key]
        
        self._save_state()
        logger.info(f"Reset emotional state for {key}")


# Singleton instance
_engine_instance: Optional[EmotionEngine] = None

def get_emotion_engine() -> EmotionEngine:
    """Get the global EmotionEngine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = EmotionEngine()
    return _engine_instance
