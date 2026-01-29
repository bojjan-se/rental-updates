# Rental Listings Scraper - Docker Image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for data persistence
RUN mkdir -p data logs output

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash rental && \
    chown -R rental:rental /app

# Switch to non-root user
USER rental

# Health check
HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=3 \
    CMD python3 -c "import sys; sys.path.insert(0, 'src'); from src.database import RentalDatabase; db = RentalDatabase('data/rentals.db'); stats = db.get_stats(); print(f'DB healthy: {stats.get(\"total_listings\", 0)} listings')"

# Default command
CMD ["python3", "rental_scheduler.py"]
