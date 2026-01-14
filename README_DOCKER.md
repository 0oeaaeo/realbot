# Running RealBot with Docker

This project is now dockerized for easy deployment.

## Prerequisites
- Docker
- Docker Compose

## Quick Start
1.  **Configure Environment Variables**:
    Ensure you have a `.env` file in the root directory with your tokens:
    ```env
    DISCORD_TOKEN=your_token_here
    GEMINI_API_KEY=your_gemini_api_key_here
    ```

2.  **Run the setup script**:
    This ensures that the persistent files and directories exist on your host.
    ```bash
    ./setup_docker.sh
    ```

3.  **Start the bot**:
    ```bash
    docker-compose up -d
    ```

## Persistence
The following files and directories are mounted as volumes to ensure your bot's state (authorized users, generated cogs, etc.) is preserved across container restarts:
- `ask_users.json`
- `bot_admins.json`
- `forced_nicks.json`
- `nano_users.json`
- `noswifto.json`
- `personas.json`
- `data/`
- `generated_cogs/`

## Self-Evolution Support
The bot's self-evolution feature (creating new cogs) works within Docker because the `generated_cogs` directory is mounted to the host. Any new cogs created by the bot will be saved there.

If you want the `!admin` command (which modifies the bot's core code) to persist changes back to your host, you should modify `docker-compose.yml` to mount the entire project directory:
```yaml
    volumes:
      - .:/app
```
(Note: Be careful with this if you have a local `venv` as it might interfere with the container's environment).
