#!/usr/bin/env bash
# Simple launcher that runs the worker in the background and then starts the web bot.
# This allows us to use a single Railway service while still processing the queue.

set -euo pipefail

# Запускаем воркер в фоне
python worker.py &
WORKER_PID=$!

echo "Worker запущен с PID $WORKER_PID"

# Запускаем основной бот (aiohttp web + aiogram)
python main.py
