#!/bin/bash
# Auto-commit and push ND BOT at 21:00 MSK
cd "$(dirname "$0")"

git add -A

git commit -m "Auto commit: update prices to 2000 RUB"

git push origin main
