# Use stable Python
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (PostgreSQL + build tools)
RUN apt-get update && \
    apt-get install -y gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# =========================
# PERSISTENT DATA DIRECTORIES
# =========================
# These paths are mounted to a Render disk
RUN mkdir -p /data/static/avatars \
             /data/uploads/products \
             /data/uploads/payments

# Expose port (Render uses 10000)
EXPOSE 10000

# Start FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]
