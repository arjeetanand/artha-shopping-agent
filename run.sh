#!/usr/bin/env bash
set -e

# Change directory to the repository root
cd "$(dirname "$0")"

echo "=================================================="
echo "          Artha — Intelligent Shopping Agent       "
echo "=================================================="

# 1. Select Python interpreter (.venv preferred if present)
if [ -f ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "❌ Error: Python is not installed."
  exit 1
fi

# 2. Check for .env file
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    echo "⚠️  .env file not found. Creating from .env.example..."
    cp .env.example .env
    echo "ℹ️  Created .env. Please update it with your API keys if needed."
  else
    echo "❌ Error: Neither .env nor .env.example found."
    exit 1
  fi
fi

# 3. Check for Node dependencies
if [ ! -d "node_modules" ]; then
  echo "📦 Installing npm dependencies..."
  npm install
fi

# 4. Read configured ports from .env
BACKEND_PORT=$(grep -E "^SHOPPINGHELP_PORT=" .env | cut -d'=' -f2 | tr -d ' "\r\n' || echo "")
if [ -z "$BACKEND_PORT" ]; then
  BACKEND_PORT=8001
fi

APP_URL=$(grep -E "^SHOPPINGHELP_APP_URL=" .env | cut -d'=' -f2 | tr -d ' "\r\n' || echo "")
FRONTEND_PORT=$(echo "$APP_URL" | grep -oE ':[0-9]+' | tr -d ':' || echo "")
if [ -z "$FRONTEND_PORT" ]; then
  FRONTEND_PORT=5176
fi

export SHOPPINGHELP_PORT="$BACKEND_PORT"
export SHOPPINGHELP_API_TARGET="http://127.0.0.1:$BACKEND_PORT"

# 5. Clean termination on Ctrl+C (SIGINT) or kill (SIGTERM)
cleanup() {
  echo ""
  echo "🛑 Shutting down Artha services..."
  if [ -n "$BACKEND_PID" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -n "$FRONTEND_PID" ]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  echo "✅ Stopped all services cleanly."
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 6. Start Python Backend
echo "🚀 Starting Artha Backend on http://127.0.0.1:$BACKEND_PORT ($PYTHON_BIN)..."
$PYTHON_BIN backend/server.py &
BACKEND_PID=$!

# Wait for backend health check
echo "⏳ Waiting for backend to initialize..."
for i in {1..20}; do
  if curl -s "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    echo "✅ Backend is healthy at http://127.0.0.1:$BACKEND_PORT"
    break
  fi
  sleep 0.5
done

# 7. Start Vite Frontend
echo "🚀 Starting Vite Frontend on http://127.0.0.1:$FRONTEND_PORT..."
npx vite --host 127.0.0.1 --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

echo ""
echo "=================================================="
echo "🎉 Artha is running!"
echo "   🌐 Frontend: http://127.0.0.1:$FRONTEND_PORT"
echo "   ⚙️  Backend:  http://127.0.0.1:$BACKEND_PORT/api/health"
echo "   🛑 Press Ctrl+C at any time to stop both"
echo "=================================================="
echo ""

# Wait for both processes to keep script in foreground
wait "$BACKEND_PID" "$FRONTEND_PID"
