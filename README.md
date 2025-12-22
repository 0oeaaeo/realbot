# RealBot

RealBot is a powerful, multi-purpose Discord bot driven by Google's Gemini API. It integrates advanced generative AI features ranging from image and video generation to code evolution and browser automation, making it a versatile assistant for Discord communities.

## Core Features

### 🎨 Generative AI
*   **Image Generation:** Create images from text prompts using the `gemini-pro-vision` model.
*   **Video Generation:** Generate videos from text prompts (and optional images) using the `veo-3.1-fast` model.
*   **Prompt Enhancement:** Automatically improves user prompts to yield better generation results.
*   **Chat Analysis:** Performs "psychoanalysis" on chat history to provide insights into user interactions.

### 🛠️ Advanced Tools
*   **Code Evolution (`/evolve`):** A self-modifying feature that allows the bot to write its own plugins (Cogs). Describe a feature in natural language, and the bot will generate the Python code, validate it, and hot-load it using the `/plugin` manager. Powered by `gemini-2.5-pro`.
*   **Computer Use (`!cu`):** Automates browser tasks using Gemini's computer use model (`gemini-2.5-computer-use-preview-10-2025`). The bot can navigate websites, click, type, and scroll, providing real-time visual feedback via screenshots. *(Owner only)*
*   **Chaos Mode (`/chaos`):** A fun (or terrifying) admin tool that replaces a target user's messages with AI-generated "opposites" or unhinged variations using `gemini-3-flash-preview`. Can be applied to specific users or entire channels.
*   **Shell Access (`!shell`):** Execute system shell commands directly from Discord. *(Owner only)*

### ⚙️ System
*   **Dynamic Plugin Management:** Load, unload, and reload generated cogs on the fly without restarting the bot.
*   **Robust Logging:** Comprehensive logging to both console and rotating files (`log.txt`) for easier debugging.
*   **Authorization:** Admin-based access control for sensitive commands.

## Prerequisites

*   Python 3.12+
*   A Discord Bot Token
*   A Google Gemini API Key

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd realbot
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # Linux/macOS
    source venv/bin/activate
    # Windows
    .\venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment:**
    Create a `.env` file in the root directory (use `.env.example` as a template):
    ```env
    DISCORD_TOKEN=your_discord_bot_token
    GEMINI_API_KEY=your_gemini_api_key
    ```
    *(Note: Some modules may require specific model permissions or additional keys)*

5.  **Run the bot:**
    ```bash
    python bot.py
    ```

## Usage

### Commands

**Prefix:** `!` (e.g., `!help`)

*   **Slash Commands:**
    *   `/evolve <description>`: Generate a new cog based on your description.
    *   `/plugin <action> [name]`: Manage generated cogs (list, load, unload, delete).
    *   `/chaos <user> [mode]`: Toggle chaos mode for a specific user.
    *   `/allchaos [mode]`: Toggle chaos mode for the current channel.
    
*   **Text Commands:**
    *   `!cu <task>`: Start a computer use session (e.g., "Go to google.com and search for cats").
    *   `!custop`: Stop the current computer use session.
    *   `!shell <command>`: Run a shell command (Owner only).

## Directory Structure

*   `bot.py`: Main entry point.
*   `cogs/`: Core extensions (Computer Use, Chaos, CodeGen, etc.).
*   `generated_cogs/`: Destination for AI-generated cogs.
*   `utils/`: Utility functions for API calls, search, etc.
*   `log.txt`: Runtime logs.

## Security Note

This bot includes powerful tools like Shell Access and Browser Automation. Ensure `OWNER_ID` is correctly set and sensitive commands are restricted to trusted users.
