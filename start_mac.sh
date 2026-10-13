#!/bin/bash
set -e
echo "🔧 Checking Homebrew & FFmpeg..."
if ! command -v ffmpeg &> /dev/null; then
    brew install ffmpeg
fi

if [ ! -d ".venv" ]; then
    echo "🐍 Creating M5 Python virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "📦 Installing Apple Silicon MLX dependencies..."
pip install --upgrade pip
pip install -r requirements-mac.txt

echo "🚀 Starting M5 Native Orchestrator..."
python orchestrator.py
