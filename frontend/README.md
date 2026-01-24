# Strawberry Hub Frontend

React + TypeScript + Vite SPA for the **Hub** admin/user UI.

## Quick start

From this folder:

```bash
npm install
npm run dev
```

Build / lint:

```bash
npm run build
npm run lint
```

## Auth model (important)

The frontend stores a JWT in `localStorage` under `admin_token` and sends it as:

```
Authorization: Bearer <token>
```

Login/setup endpoints are under `/api/users/*` and return `access_token`.

## API base path

All requests are scoped under `/api` via `src/lib/api.ts`:

- Sessions (chat history): `/api/sessions/*`
- Chat inference: `/api/v1/chat/completions`

## Chat: sessions vs inference

The UI uses two related systems:

- **Sessions API** stores durable history:
  - `POST /api/sessions` creates a session
  - `GET /api/sessions` lists sessions
  - `GET /api/sessions/{id}/messages` loads history
  - `POST /api/sessions/{id}/messages` persists messages
  - `DELETE /api/sessions/{id}` deletes a chat

- **Inference API** runs the model/tool loop:
  - `POST /api/v1/chat/completions`
  - The UI requests streaming (`stream: true`) so it can render tool calls/results in order.

## Chat streaming protocol (SSE)

When `stream: true`, the backend returns `text/event-stream` with `data: <json>`.
Events currently used by the UI:

- `{"type":"tool_call_started","tool_call_id":"...","tool_name":"...","arguments":{...}}`
- `{"type":"tool_call_result","tool_call_id":"...","tool_name":"...","success":true,"result":"...","cached":false}`
- `{"type":"assistant_message","content":"...","model":"...","usage":{...}}`
- `{"type":"error","error":"..."}`
- `{"type":"done"}`

Frontend helpers:

- `src/lib/sse.ts`: minimal SSE frame parser for `fetch()` streaming responses
- `src/lib/chatStream.ts`: typed generator that yields stream events

## Deleting chats

- **Single chat**: trash icon per session in the sidebar.
- **Bulk delete**: click **Select**, choose multiple chats, then click **Delete**.

## Folder layout (high-signal)

- `src/pages/*`: route pages (`/chat` is `Chat.tsx`)
- `src/components/chat/*`: chat UI primitives (sidebar, list, input, bubbles)
- `src/lib/*`: API helpers and streaming parsing
