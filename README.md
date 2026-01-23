# Strawberry AI - Hub

Central server for the Strawberry AI platform.

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

