FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Ensure data directory exists
RUN python -c "import os; os.makedirs('data', exist_ok=True)"

# Hugging Face Spaces exposes port 7860
EXPOSE 7860

# Launch Uvicorn server on 0.0.0.0:7860
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
