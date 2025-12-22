tools = [
    {
        "name": "search_discord",
        "description": "Searches for Discord messages and gathers user avatars based on various criteria. Use this to get context, find specific messages, or get information about users (including their avatars). Returns the message history and avatars found.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "guild_id": {"type": "STRING", "description": "The ID of the guild (server) to search in."},
                "channel_id": {"type": "STRING", "description": "Optional. The ID of the channel to search in."},
                "author_id": {"type": "STRING", "description": "Optional. The ID of the user (author) to search for."},
                "content": {"type": "STRING", "description": "Optional. Text content to search for in messages."},
                "mentions": {"type": "STRING", "description": "Optional. ID of a user mentioned in the messages."},
                "has": {"type": "STRING", "description": "Optional. Filter for messages containing specific content types (e.g., 'image', 'video', 'link')."},
                "limit": {"type": "NUMBER", "description": "Optional. The number of results to return. Defaults to 25."},
                "offset": {"type": "NUMBER", "description": "Optional. The offset for pagination. Defaults to 0."}
            },
            "required": ["guild_id"]
        }
    },
    {
        "name": "generate_image",
        "description": "Generates a new image based on a detailed textual prompt. Can also use images gathered with `search_discord`.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "prompt_text": {"type": "STRING", "description": "The detailed, final prompt for image generation."},
            },
            "required": ["prompt_text"]
        }
    },
    {
        "name": "generate_video",
        "description": "Generates a short video based on a detailed textual prompt. Can use an initial image gathered with `search_discord`.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "prompt_text": {"type": "STRING", "description": "The detailed, final prompt for video generation."},
                "to_gif": {"type": "BOOLEAN", "description": "Optional. If true, converts the generated video to an animated GIF."}
            },
            "required": ["prompt_text"]
        }
    },
    {
        "name": "generate_music",
        "description": "Generates music using Suno AI in custom mode. Requires a title, style, and a prompt up to 5000 characters. Can create songs with lyrics or instrumental tracks.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "prompt": {"type": "STRING", "description": "The detailed lyrics or musical description. MUST be under 5000 characters."},
                "title": {"type": "STRING", "description": "The title of the music track."},
                "style": {"type": "STRING", "description": "Specific music style tags (e.g., 'Upbeat Pop', 'Lo-fi Hip Hop')."},
                "instrumental": {"type": "BOOLEAN", "description": "If true, generates an instrumental track (no vocals). Defaults to false."},
                "model": {"type": "STRING", "description": "Model version: 'V3_5', 'V4', 'V4_5', 'V5'. Defaults to 'V5'."}
            },
            "required": ["prompt", "title", "style"]
        }
    }
]