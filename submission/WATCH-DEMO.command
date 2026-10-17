#!/bin/zsh
set -e
SCRIPT_DIR="${0:A:h}"
SDL_RENDER_DRIVER=software /opt/homebrew/bin/ffplay -hide_banner -loglevel warning -an -sync video -autoexit -window_title "Artha captioned demo" "$SCRIPT_DIR/artha-demo-captioned.mp4"
