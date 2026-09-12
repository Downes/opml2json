FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port
EXPOSE 8000

# Run with gunicorn
CMD ["uvicorn", "hello:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "120"]
