#!/usr/bin/env bash
set -e

# Change directory to the repository root
RUN_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$RUN_SCRIPT_DIR"

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

# Invoice text is parsed locally; install its runtime in the project virtual environment.
if [ ! -f ".venv/bin/python" ]; then
  "$PYTHON_BIN" -m venv .venv
fi
PYTHON_BIN=".venv/bin/python"
if ! "$PYTHON_BIN" -c 'import pypdf' >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip install -r backend/requirements.txt
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

# 4. Read configured ports from the environment or .env
BACKEND_PORT="${SHOPPINGHELP_PORT:-$(grep -E '^SHOPPINGHELP_PORT=' .env | cut -d'=' -f2 | tr -d ' "\r\n' || echo "")}"
if [ -z "$BACKEND_PORT" ]; then
  BACKEND_PORT=8001
fi

if [ -n "${SHOPPINGHELP_APP_URL:-}" ]; then
  APP_URL="$SHOPPINGHELP_APP_URL"
elif [ -n "${SHOPPINGHELP_FRONTEND_PORT:-}" ]; then
  APP_URL="http://127.0.0.1:$SHOPPINGHELP_FRONTEND_PORT"
else
  APP_URL=$(grep -E '^SHOPPINGHELP_APP_URL=' .env | cut -d'=' -f2 | tr -d ' "\r\n' || echo "")
fi
FRONTEND_PORT="${SHOPPINGHELP_FRONTEND_PORT:-$(echo "$APP_URL" | grep -oE ':[0-9]+' | tr -d ':' || echo "")}"
if [ -z "$FRONTEND_PORT" ]; then
  FRONTEND_PORT=5176
fi
if [ -z "$APP_URL" ]; then
  APP_URL="http://127.0.0.1:$FRONTEND_PORT"
fi

export SHOPPINGHELP_PORT="$BACKEND_PORT"
export SHOPPINGHELP_APP_URL="$APP_URL"
export SHOPPINGHELP_API_TARGET="http://127.0.0.1:$BACKEND_PORT"
ALLOWED_ORIGINS="${SHOPPINGHELP_CORS_ORIGIN:-$(grep -E '^SHOPPINGHELP_CORS_ORIGIN=' .env | cut -d'=' -f2 | tr -d ' "\r\n' || echo "")}"
case ",$ALLOWED_ORIGINS," in
  *",$APP_URL,"*) ;;
  *) ALLOWED_ORIGINS="${ALLOWED_ORIGINS:+$ALLOWED_ORIGINS,}$APP_URL" ;;
esac
export SHOPPINGHELP_CORS_ORIGIN="$ALLOWED_ORIGINS"

# 5. Stop a previous Artha listener on these ports, but leave unrelated services alone
stop_artha_listener() {
  local port="$1"
  local service="$2"
  local pids pid command process_dir stopped_pids="" still_running

  pids=$(lsof -a -ti -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  for pid in $pids; do
    command=$(ps -p "$pid" -o command= 2>/dev/null || true)
    process_dir=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)
    case "$service:$command" in
      backend:*backend/server.py*) ;;
      frontend:*vite*) ;;
      *) continue ;;
    esac
    if [ "$process_dir" != "$RUN_SCRIPT_DIR" ]; then
      continue
    fi

    echo "♻️ Stopping existing Artha $service (PID $pid)..."
    kill -TERM "$pid" 2>/dev/null || true
    stopped_pids="${stopped_pids}${stopped_pids:+ }$pid"
  done

  for pid in $stopped_pids; do
    still_running=true
    for i in {1..40}; do
      if ! kill -0 "$pid" 2>/dev/null; then
        still_running=false
        break
      fi
      sleep 0.25
    done
    if [ "$still_running" = "true" ]; then
      echo "❌ Artha $service (PID $pid) did not stop cleanly; refusing to start a duplicate."
      return 1
    fi
  done
}

check_port() {
  local port="$1"
  local desc="$2"
  local pids
  pids=$(lsof -a -ti -i :"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "❌ Port $port ($desc) is already in use by PID(s): $pids"
    echo "   Set SHOPPINGHELP_PORT and SHOPPINGHELP_FRONTEND_PORT to free ports."
    exit 1
  fi
}

stop_artha_listener "$BACKEND_PORT" "backend"
stop_artha_listener "$FRONTEND_PORT" "frontend"
check_port "$BACKEND_PORT" "backend"
check_port "$FRONTEND_PORT" "frontend"

# 6. Clean termination on Ctrl+C (SIGINT) or kill (SIGTERM)
cleanup() {
  trap - SIGINT SIGTERM EXIT
  echo ""
  echo "🛑 Shutting down Artha services..."
  if [ -n "$BACKEND_PID" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -n "$FRONTEND_PID" ]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  echo "✅ Stopped all services cleanly."
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 7. Start Python Backend
echo "🚀 Starting Artha Backend on http://127.0.0.1:$BACKEND_PORT ($PYTHON_BIN)..."
$PYTHON_BIN backend/server.py &
BACKEND_PID=$!

# Wait for backend health check
echo "⏳ Waiting for backend to initialize..."
backend_ready=false
for i in {1..20}; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "❌ Error: Backend process failed to start or crashed."
    exit 1
  fi
  if curl -s "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    echo "✅ Backend is healthy at http://127.0.0.1:$BACKEND_PORT"
    backend_ready=true
    break
  fi
  sleep 0.5
done

if [ "$backend_ready" != "true" ]; then
  echo "❌ Error: Backend failed to respond to health check in time."
  exit 1
fi

# 8. Start Vite Frontend
echo "🚀 Starting Vite Frontend on http://127.0.0.1:$FRONTEND_PORT..."
npx vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort &
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
