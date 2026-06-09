# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system deps + Node.js 20 (the MongoDB MCP server runs via `npx`)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# (Optional hardening) pre-install the MongoDB MCP server so the container does not
# fetch it from npm on first request — faster cold start, no runtime npm dependency.
# Uncomment to enable:
RUN npm install -g mongodb-mcp-server@latest

# Copy requirements first (better layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application
COPY . .

# Cloud Run expects the app to listen on 0.0.0.0:PORT
# Default PORT is 8080
ENV PORT=8080
EXPOSE 8080

# Run the FastAPI app with uvicorn
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
