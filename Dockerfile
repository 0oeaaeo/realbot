# Use the official Playwright Python image which comes with all necessary system dependencies
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers and their dependencies
RUN playwright install chromium --with-deps

# Copy the rest of the application code
COPY . .

# Ensure the directories for persistence exist
RUN mkdir -p data generated_cogs

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the bot
CMD ["python3", "bot.py"]
