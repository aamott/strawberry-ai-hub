# Strawberry AI - Hub

Central server for the Strawberry AI platform. For the Client, see [Strawberry AI Client](https://github.com/aamott/strawberry-ai-client)

## Features

- **LLM Gateway**: Routes requests through TensorZero to multiple LLM providers
- **Device Management**: Register and authenticate Spoke devices
- **Skill Registry**: Track and route skill calls across devices
- **Session Management**: Maintain conversation history

## Quick Start

```bash
# Create and activate a shared repo venv (from repo root)
python -m venv .venv
.venv\Scripts\activate # windows
# Or
source .venv/bin/activate # linux

# Install dependencies
pip install -e ai-hub

# Run the server (from ai-hub/ or repo root)
strawberry-hub

# Or with uvicorn directly
uvicorn hub.main:app --reload

# Or run with a more thread-safe wrapper
python scripts/dev.py --port 8000
```

## Folder Layout (How to Navigate)

This repo is intentionally split into a Python backend ("Hub") and an optional React frontend. Most development work happens in `src/hub/` (backend) and `frontend/src/` (frontend source).

```text
ai-hub/
  src/
    hub/                 # FastAPI backend package (entrypoint, auth, DB, skills, prompts)
      routers/           # API route modules grouped by domain (chat/devices/skills/sessions/websocket/etc.)
  config/                # Runtime configuration (e.g. TensorZero gateway config)
  frontend/              # Vite/React UI
    src/                 # Frontend source (edit here)
    dist/                # Built static assets (backend serves these when present)
  scripts/               # Dev helpers (dev server wrapper, frontend build script, etc.)
  tests/                 # Pytest suite + fixtures (wire schemas, protocol tests, routing tests)
  logs/                  # Local runtime logs

  hub.db                 # Local SQLite database (dev/runtime artifact)
  pyproject.toml         # Python packaging + deps; defines the `strawberry-hub` entrypoint
  ruff.toml              # Ruff lint configuration
  .env*                  # Environment files (`.env.example` is the template)
```

Common "where do I change X?" pointers:

- **Add/modify API endpoints**: `src/hub/routers/` (and wiring in `src/hub/main.py`)
- **Skill routing / execution**: `src/hub/skill_service.py`
- **Prompting logic**: `src/hub/prompt.py`
- **Database / persistence**: `src/hub/database.py` (SQLite config defaults to `hub.db`)
- **LLM gateway config**: `config/tensorzero.toml` + `src/hub/tensorzero_gateway.py`
- **Frontend UI changes**: `frontend/src/` (then rebuild to refresh `frontend/dist/`)

## Frontend Setup

The frontend is included in the repository as pre-built static files in the `frontend/dist` directory. The backend automatically serves these files when present.

### Building the Frontend (if you make changes)

If you modify the frontend source code, you'll need to rebuild it:

```bash
# Option 1: Using the build script
./scripts/build_frontend.sh

# Option 2: Manual build
cd frontend
npm install
npm run build
```

This will update the `dist` directory with your changes. Make sure to commit the updated `dist` files if you want others to see your changes.

## API Endpoints

### Devices
- `GET /api/devices` - List devices for the current user
- `POST /api/devices/token` - Create a device token for a new device

### Device Auth
- `GET /auth/me` - Get current device info
- `POST /auth/refresh` - Refresh device token

### Chat
- `POST /api/v1/chat/completions` - OpenAI-compatible chat endpoint
- `POST /api/inference` - TensorZero inference endpoint

### Skills
- `GET /skills` - List registered skills
- `POST /skills/register` - Register device skills
- `POST /skills/heartbeat` - Keep skills alive
- `POST /skills/execute` - Execute a skill on a remote device

### Devices
- `GET /devices` - List connected devices
- `GET /devices/{id}` - Get device details

## Configuration

1. **Environment Setup**: Copy `.env.example` to `.env` and fill in your settings. The Hub always
   loads `.env` and `hub.db` from the `ai-hub/` directory, regardless of the working directory you
   launch from:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` with your actual API keys and configuration. Update `config/tensorzero.toml` for LLM configuration.

2. **Example Configuration**: Here's what a basic `.env` file looks like:

```bash
# Server
HOST=0.0.0.0
PORT=8000

# Security
SECRET_KEY=your-secret-key-here
ACCESS_TOKEN_EXPIRE_MINUTES=43200  # 30 days

# Database
DATABASE_URL=sqlite+aiosqlite:///./hub.db

# LLM (OpenAI-compatible)
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_MODEL=gpt-4o-mini
```

