# Strawberry AI - Hub

Central server for the Strawberry AI platform.

## Features

- **LLM Gateway**: Routes requests through TensorZero to multiple LLM providers
- **Device Management**: Register and authenticate Spoke devices
- **Skill Registry**: Track and route skill calls across devices
- **Session Management**: Maintain conversation history

## Quick Start

```bash
# Install dependencies
pip install -e .

# Run the server
strawberry-hub

# Or with uvicorn directly
uvicorn hub.main:app --reload
```

## API Endpoints

### Authentication
- `POST /auth/token` - Get device token
- `POST /auth/register` - Register new device

### Chat
- `POST /v1/chat/completions` - OpenAI-compatible chat endpoint
- `POST /inference` - TensorZero inference endpoint

### Skills
- `GET /skills` - List registered skills
- `POST /skills/register` - Register device skills
- `POST /skills/heartbeat` - Keep skills alive
- `POST /skills/call` - Execute a skill

### Devices
- `GET /devices` - List connected devices
- `GET /devices/{id}` - Get device details

## Configuration

1. **Environment Setup**: Copy `.env.example` to `.env` and fill in your settings:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` with your actual API keys and configuration.

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

