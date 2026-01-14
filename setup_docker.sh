#!/bin/bash

# Ensure stateful files exist so docker-compose doesn't create directories for them
touch ask_users.json bot_admins.json forced_nicks.json nano_users.json noswifto.json personas.json verification_logs.txt

# Ensure data directories exist
mkdir -p data generated_cogs

echo "Setup complete. You can now run: docker-compose up -d"
