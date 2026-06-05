# GardenState

A personal garden management assistant powered by Google ADK + Gemini, MongoDB Atlas, and FastAPI — deployable to Cloud Run.

---

## Architecture

```
Browser (SPA)
  │  HTTPS · REST / SSE
  ▼
FastAPI  ─── app/main.py
  │  user auth · chat · photo upload
  ▼
ADK Runner  ─── garden_agent/agent.py
  │  Gemini 2.5 Flash · tool orchestration · per-session history
  ├── get_weather()           open-meteo geocoding + forecast
  ├── get_plant_care()        Perenual plant database API
  ├── read_sensors()          time-of-day physics model (mocked)
  ├── save_memory()           MongoDB user_memories (long-term)
  ├── search_care_knowledge() Atlas Vector Search RAG
  ├── Vision                  inline image analysis via Gemini multimodal
  └── MongoDB MCP             read/write plant records, sensor logs, tasks
        └── garden DB (Atlas)
              ├── users
              ├── sensor_readings
              ├── care_knowledge   ← RAG knowledge base
              └── user_memories    ← per-user long-term memory
```

---

## Features

| Capability | How it works |
|---|---|
| **Chat** | Streaming SSE via ADK + Gemini 2.5 Flash |
| **Weather** | Open-Meteo (free, no key needed) |
| **Plant care lookup** | Perenual API — watering, sunlight, care level |
| **Sensor data** | Simulated soil moisture / temp / light (physics model) |
| **Vision** | Upload a plant photo → agent diagnoses health from image |
| **RAG** | `search_care_knowledge()` embeds query with `gemini-embedding-001`, runs `$vectorSearch` on Atlas |
| **Per-user memory** | Facts learned across sessions stored in `user_memories`, injected as context every turn |
| **Guest mode** | Works without login; `session_id` used as fallback `user_id` |

---

## Project Structure

```
garden/
├── app/
│   ├── main.py              FastAPI server, chat + user endpoints
│   └── static/index.html    Single-page frontend
├── garden_agent/
│   ├── agent.py             ADK Agent definition + tool list
│   ├── tools.py             Python tools (weather, sensors, memory, RAG)
│   ├── seed_knowledge.py    One-time script: embed + load care_knowledge
│   └── .env                 Local secrets (not committed)
├── Dockerfile
├── cloudbuild.yaml
├── deploy.sh
└── requirements.txt
```

---

## Local Setup

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Create garden_agent/.env
MDB_MCP_CONNECTION_STRING=mongodb+srv://...
GOOGLE_API_KEY=...
PERENUAL_API_KEY=...

# 3. Seed RAG knowledge base (run once)
python -m garden_agent.seed_knowledge
# → then create the Atlas Vector Search index using the printed JSON

# 4. Run
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/login` | Sign in or create user (email + username) |
| `POST` | `/api/gardens` | Add a garden type to a user |
| `DELETE` | `/api/gardens` | Remove a garden type |
| `PATCH` | `/api/user/location` | Update user's location |
| `POST` | `/chat` | Send a message; streams plain-text response |
| `POST` | `/upload` | Upload a plant photo; returns `photo_id` |

### Chat request body

```json
{
  "message": "How are my tomatoes doing?",
  "session_id": "<uuid>",
  "user_id": "user@example.com",
  "photo_id": "<optional — from /upload>",
  "username": "Alice",
  "garden_type": "vegetable",
  "location": "Toronto"
}
```

---

## Per-User Memory

Each turn the agent receives:

```
[Context: user_id=user@example.com, user=Alice, garden=vegetable in Toronto]
[Long-term memory:
- has cherry tomatoes planted since May
- prefers organic pest control
- aphid problem on roses noted 2025-06]
<user message>
```

When the agent learns something new it calls `save_memory(user_id, fact)` to persist it for future sessions. Facts are stored in `garden.user_memories` in MongoDB.

---

## RAG — Care Knowledge Base

`seed_knowledge.py` embeds 18 plant-care documents (tomato, rose, basil, lavender, succulents, etc.) using `gemini-embedding-001` (3072 dims) and stores them in `garden.care_knowledge`.

The agent calls `search_care_knowledge(query)` before answering any plant care question. It embeds the query and runs `$vectorSearch` to return the top 3 relevant passages.

**Atlas Vector Search index definition:**
```json
{
  "name": "care_knowledge_vector_idx",
  "type": "vectorSearch",
  "fields": [{
    "type": "vector",
    "path": "embedding",
    "numDimensions": 3072,
    "similarity": "cosine"
  }]
}
```

Atlas UI path: Database → Browse Collections → `garden.care_knowledge` → Search Indexes → Create Search Index → JSON Editor

---

## Deployment — Cloud Run

```bash
./deploy.sh <gcp-project-id> us-central1 garden-agent
```

Set `MDB_MCP_CONNECTION_STRING` and `GOOGLE_API_KEY` as environment variables in Cloud Run (via `--set-env-vars` in `deploy.sh` or as Secret Manager references).

The container listens on `$PORT` (default 8080).

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MDB_MCP_CONNECTION_STRING` | Yes | MongoDB Atlas connection string |
| `GOOGLE_API_KEY` | Yes | Google AI Studio key (Gemini + embeddings) |
| `PERENUAL_API_KEY` | No | Perenual plant database API key |
| `PORT` | No | Server port (default 8080, set by Cloud Run) |
