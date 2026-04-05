# Use a lightweight Python image
FROM python:3.11-slim-bullseye

# Prevent Python from writing .pyc files & enable stdout flushing
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory inside container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files (This copies main.py directly into /app)
COPY . .

# Set PYTHONPATH so imports work cleanly
ENV PYTHONPATH=/app

# Default command: 
# Changed from 'app.main:app' to 'main:app' because main.py is in the root of /app
# CMD ["python", "app.main_telegram:app", "--host", "0.0.0.0", "--port", "8000"]
CMD ["python", "app/main_telegram.py"]