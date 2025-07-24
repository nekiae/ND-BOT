FROM python:3.11-slim

# Install system dependencies
# Install system dependencies for OpenCV and other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libtbb-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency file
COPY requirements.txt ./

# Install dependencies one by one to isolate the problem
RUN pip install --no-cache-dir aiogram==3.0.0
RUN pip install --no-cache-dir sqlmodel==0.0.19
RUN pip install --no-cache-dir httpx==0.27.0
RUN pip install --no-cache-dir yookassa==2.1.0
RUN pip install --no-cache-dir aioredis==2.0.1
RUN pip install --no-cache-dir asyncpg==0.29.0
RUN pip install --no-cache-dir python-dotenv==1.0.0
RUN pip install --no-cache-dir requests==2.31.0

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run the bot
CMD ["python", "bot.py"]
