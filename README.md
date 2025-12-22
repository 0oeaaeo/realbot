# RealBot 🤖✨

**RealBot** is a next-generation Discord agent powered by Google's **Gemini 3 Pro** and **Veo** models. Unlike traditional bots that simply respond to commands, RealBot operates as an **autonomous agent**, capable of thinking, planning, and executing complex workflows to fulfill user requests.

It doesn't just "generate images"; it can read the chat, understand the vibe, look up what users look like, and create contextually relevant media.

---

## 🧠 The Agentic Core (`!ask`)

At the heart of RealBot is the `!ask` command, driven by the `gemini-3-pro-preview` model. When you ask a question, the bot enters a **reasoning loop**:

1.  **Analyze:** It evaluates your request against its available tools.
2.  **Plan:** It decides which tools (if any) it needs to call to get the job done.
3.  **Execute:** It runs the tools (e.g., searching chat history, fetching a URL, generating media).
4.  **Observe:** It reads the tool outputs (e.g., search results, status of a generation).
5.  **Iterate:** It repeats this process (up to 5 times) until the task is complete.

### Available Tools
The agent has access to a powerful suite of tools:

*   🔍 **`search_discord`**: A deep-search tool that can query message history across channels and servers. It filters by author, content, media type, and date, allowing the bot to "remember" past conversations.
*   🎨 **`generate_image`**: Creates high-fidelity images using `gemini-3-pro-image-preview`.
*   ✏️ **`edit_image`**: Modifies existing images or attachments based on natural language instructions.
*   🎥 **`generate_video`**: Creates AI videos using Google's **Veo 3.1** model.
*   🎵 **`generate_music`**: Composes full songs (lyrics + audio) or instrumentals using **Suno AI**.
*   🔊 **`generate_sound_effect`**: Creates custom sound effects using **ElevenLabs**.
*   🌐 **`fetch_url`**: Browses the web to read articles, documentation, or checking facts.
*   🖼️ **`remove_background`** & **`upscale_image`**: Utility tools for image processing.
*   👤 **`get_user_avatars`**: Fetches user profile pictures to use as reference material.

---

## 🎨 Contextual Generative AI

RealBot stands out because it is **context-aware**. It doesn't generate in a void; it generates based on *your* server's reality.

### How It "Sees" Context
When you run a command like `!ask draw a scene of what happened in chat yesterday`, the bot:
1.  **Calls `search_discord`** to retrieve the actual message history from the previous day.
2.  **Analyzes the text** to understand the topics, mood, and key participants.
3.  **Constructs a prompt** that accurately reflects the events described in the chat logs.

### Avatar Integration
RealBot can "see" users. If you ask it to "make a movie poster starring @User1 and @User2":
1.  It identifies the mentioned users.
2.  It uses the **`get_user_avatars`** tool (or extracts them from search results) to fetch their actual Discord profile pictures.
3.  It converts these avatars into a format the AI model can understand.
4.  It feeds these images into the generation model as **reference images**, allowing it to generate output that visually resembles the actual users in your server.

---

## 🛠️ Advanced Features

### 🧬 Code Evolution (`/evolve`)
RealBot is self-improving. Using the `/evolve` command, you can describe a new feature in plain English, and the bot will:
1.  **Write the Code:** Generate a valid Python Discord Cog.
2.  **Validate:** Check for syntax errors and structural validity.
3.  **Hot-Load:** Instantly load the new feature into the running bot via its dynamic plugin system (`/plugin`).

### 🖥️ Computer Use (`!cu`)
*(Owner Only)* RealBot can control a headless browser using the `gemini-2.5-computer-use` model. It can navigate websites, click elements, type text, and scroll, providing a screenshot feed of its actions. This allows for complex automation tasks like "Go to this website and screenshot the pricing table."

### 😈 Chaos Mode (`/chaos`)
A fun moderation tool that uses AI to "troll" specific users. When enabled, it intercepts a target's messages and uses Gemini to rewrite them into their "opposite" or an "unhinged" version before reposting them via a webhook, effectively making the user say things they didn't intend.

---

## 🚀 Setup & Installation

### Prerequisites
*   Python 3.12+
*   [Google Gemini API Key](https://aistudio.google.com/)
*   Discord Bot Token

### Installation
1.  **Clone the repository:**
    ```bash
    git clone https://github.com/0oeaaeo/realbot.git
    cd realbot
    ```

2.  **Set up Virtual Environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configuration:**
    Create a `.env` file in the root directory:
    ```env
    DISCORD_TOKEN=your_discord_bot_token
    API_KEY=your_gemini_api_key
    # Optional Keys for specific features:
    SUNO_API_KEY=your_suno_key  # For Music/SFX/Upscaling (via kie.ai)
    DISCORD_USER_TOKEN=your_user_token # For advanced search capabilities
    ```

5.  **Run the Bot:**
    ```bash
    python bot.py
    ```

---

## 🎮 Command Reference

### Core
*   `!ask <prompt>`: The main agentic interface. Ask anything!
    *   *"Analyze the vibe of #general"*
    *   *"Make a song about @User"*
    *   *"Search for the last time we talked about pizza"*

### Evolution (Slash Commands)
*   `/evolve <description>`: Create a new bot feature.
*   `/plugin <list|load|unload|view>`: Manage generated plugins.

### Fun & Utility
*   `!cu <task>`: Browser automation (Owner only).
*   `/chaos <user>`: Toggle chaos mode for a user.
*   `!shell <command>`: Execute system shell commands (Owner only).