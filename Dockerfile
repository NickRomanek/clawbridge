# ClawBridge MVP - Dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps for Playwright/Chromium
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libcups2 \
    libxss1 \
    libgtk-3-0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# Copy application
COPY clawbridge/ ./clawbridge/
COPY LICENSE.txt .

# Create logs directory
RUN mkdir -p /app/logs

EXPOSE 8765

CMD ["python", "-m", "clawbridge"]
