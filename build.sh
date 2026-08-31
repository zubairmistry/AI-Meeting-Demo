#!/usr/bin/env bash
# Exit on error
set -o errexit

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Ensure FFmpeg is available on Linux
if ! command -v ffmpeg &> /dev/null; then
    echo "FFmpeg not found in PATH. Setting up standalone Linux FFmpeg binary..."
    mkdir -p bin
    if [ ! -f bin/ffmpeg ]; then
        curl -L -s https://github.com/eugeneware/ffmpeg-static/releases/latest/download/ffmpeg-linux-x64.tar.gz | tar -xz -C bin 2>/dev/null || \
        curl -L -s https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz | tar -xJ -C bin --wildcards '*/ffmpeg' --strip-components=1 2>/dev/null || true
        chmod +x bin/ffmpeg 2>/dev/null || true
    fi
    export PATH="$PWD/bin:$PATH"
fi

# Run database migrations
python manage.py migrate --noinput

# Collect static files with WhiteNoise
python manage.py collectstatic --noinput
