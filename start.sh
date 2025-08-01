#!/bin/bash

# --- Force stop all related processes ---
echo "Stopping old processes..."
pkill -9 -f 'python main.py' || true
pkill -9 -f 'python worker.py' || true
pkill -9 -f 'redis-server' || true
sleep 2

# --- Activate virtual environment ---
source venv/bin/activate

# --- Start services ---
echo "Starting Redis server..."
redis-server & 
REDIS_PID=$!
sleep 2

echo "Starting Celery worker..."
python worker.py & 
WORKER_PID=$!
sleep 2

echo "Starting main bot application..."
python main.py

# --- Cleanup on exit ---
kill $REDIS_PID
kill $WORKER_PID
echo "Processes cleaned up."
