# GardenState

A personal garden management assistant powered by Google ADK + Gemini 2.5 Flash, MongoDB Atlas, and FastAPI — deployable to Cloud Run.

---

## Architecture

```
Browser (SPA)
  │  HTTPS · REST / SSE / NDJSON
  ▼
FastAPI  ─── app/main.py
  │  auth · cards · chat · upload · geocode · notifications
  ▼
ADK Runner  ─── garden_agent/agent.py
  │  Gemini 2.5 Flash · tool orchestration · per-card history
  ├── get_weather()           Open-Meteo geocoding + forecast (city-only fallback)
  ├── get_plant_care()        Perenual plant database API
  ├── read_sensors()          Time-of-day physics model (simulated IoT)
  ├── control_smart_home()    Simulated irrigation zones + garden camera
  ├── save_memory()           MongoDB user_memories (long-term, cross-session)
  ├── forget_memory()         Remove facts from long-term memory on request
  ├── search_care_knowledge() Atlas Vector Search RAG (gemini-embedding-001)
  ├── Vision                  HEIC/JPEG/PNG → Gemini multimodal plant diagnosis
  └── MongoDB MCP             CRUD on plant records, sensor logs, tasks
        └── garden DB (Atlas)
              ├── users
              ├── plants               ← care cards
              ├── chat_history         ← per-card transcript (persistent across sessions)
              ├── sensor_readings
              ├── tasks
              ├── care_knowledge       ← RAG knowledge base (18 docs, 3072-dim embeddings)
              ├── user_memories        ← per-user long-term memory
              └── notification_prefs   ← per-user notification schedule
```

---

## Features

| Capability | How it works |
|---|---|
| **Chat** | Streaming NDJSON via ADK + Gemini 2.5 Flash; history replays on card re-open |
| **Care cards** | Add, edit, delete plants/areas; photo auto-identifies species via Gemini |
| **Garden types** | User-managed type list (flower, vegetable, herb, etc.) drives sidebar filter tabs |
| **Weather** | Open-Meteo (free, no key) — retries with city-only name if "City, State" fails |
| **Plant care lookup** | Perenual API — watering frequency, sunlight needs, care level |
| **Sensor data** | Simulated soil moisture / temp / light via time-of-day physics model |
| **Smart home control** | `control_smart_home()` — start/stop irrigation zones, take camera snapshots |
| **Vision** | Upload any photo (HEIC, JPEG, PNG) → converted to JPEG → Gemini diagnoses plant health |
| **Real-time location** | Browser Geolocation → `/api/geocode` → Google Maps API or Nominatim fallback |
| **RAG** | `search_care_knowledge()` embeds query with `gemini-embedding-001`, runs `$vectorSearch` |
| **Long-term memory** | Facts learned across sessions stored in `user_memories`, injected as context every turn |
| **Chat history** | Per-card transcripts persisted in MongoDB; restored on login across browser restarts |
| **Notifications** | Garden care check across all cards (sensors + weather); configurable frequency + time window |
| **Guest mode** | Full functionality without login; data not persisted to MongoDB |

---

## Project Structure

```
GardenState/
├── app/
│   ├── main.py              FastAPI server — all endpoints
│   ├── static/index.html    Single-page frontend (vanilla JS)
│   └── uploads/             Uploaded photos (ephemeral on Cloud Run; GCS migration path)
├── garden_agent/
│   ├── agent.py             ADK Agent — model, tools list, system instruction
│   ├── tools.py             Python tools (weather, sensors, memory, RAG, smart home)
│   ├── seed_knowledge.py    Embed + load care_knowledge; seed_if_empty() called at startup
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
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=<ai-studio-key>
MDB_MCP_CONNECTION_STRING=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/
PERENUAL_API_KEY=<optional>
GOOGLE_MAPS_API_KEY=<optional — leave empty to use Nominatim fallback>

# 3. Create Atlas Vector Search index (one-time, after first run seeds the collection)
# The server auto-seeds care_knowledge on startup if the collection is empty.
# After seeding, create the index manually in Atlas UI:
#   Database → Browse Collections → garden.care_knowledge
#   → Search Indexes → Create Search Index → JSON Editor → paste definition below

# 4. Run
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

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

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/login` | Sign in or create user (email + username) |
| `POST` | `/api/gardens` | Add a garden type to user |
| `DELETE` | `/api/gardens` | Remove a garden type |
| `PATCH` | `/api/user/location` | Update user's location |
| `GET` | `/api/geocode?lat=&lng=` | Reverse-geocode coordinates to city name |
| `GET` | `/api/cards?user_id=` | List user's care cards |
| `POST` | `/api/cards` | Create a care card |
| `PATCH` | `/api/cards/{card_id}` | Edit a care card |
| `DELETE` | `/api/cards/{card_id}` | Delete a care card |
| `POST` | `/api/identify` | Identify a plant from a photo (Gemini vision) |
| `GET` | `/api/notif-prefs?user_id=` | Get notification preferences |
| `POST` | `/api/notif-prefs` | Save notification preferences |
| `POST` | `/api/check` | Run a whole-garden care check (streaming NDJSON) |
| `GET` | `/api/history?user_id=&session_id=` | Replay a card's chat transcript |
| `POST` | `/chat` | Send a chat message (streaming NDJSON) |
| `POST` | `/upload` | Upload a plant photo; returns `photo_id` |

---

## Key Features in Detail

### Care Cards
Each card represents one thing you care for — a single plant, a bed, a lawn, or a whole garden. Cards have a name, kind, species, tags, and optional photo. Uploading a photo triggers Gemini to auto-identify the species and pre-fill the form.

### Garden Type Tabs
Users manage their garden type list (flower, vegetable, herb, lawn, orchard, trees, berry, tropical, indoor, succulent) via a picker in the sidebar. The filter tabs at the top update instantly to match the selected types.

### Long-Term Memory + Chat History
Two separate persistence layers:
- **Long-term memory** (`user_memories`): facts the agent learns about the user ("prefers organic pest control", "has aphids on roses"). Injected as context on every turn, survives logout.
- **Chat history** (`chat_history`): full per-card transcript. Session IDs stored in `localStorage` so history restores correctly after browser close or logout/login.

### Notifications
The **🔔 Check Now** button in the sidebar runs the agent across all (or selected) cards — it reads sensors, checks weather, and produces a plain-text report sectioned by:
- 💧 Needs Water Now
- 🌿 Fertilize This Week
- 🚨 Disease & Pest Watch
- ✅ All Looking Good

**⚙ Set Reminder** configures which cards to watch, frequency (daily / every 2 days / weekly), and preferred time window (morning / afternoon / evening). When you open the app during the configured window and a check is due, the red dot appears automatically.

### Smart Home Control (Simulated)
`control_smart_home(device, action, duration_minutes)` lets the agent control:
- `irrigation_zone_A` / `irrigation_zone_B` — start/stop watering
- `camera` — take a garden snapshot (returns a simulated observation)
- `soil_sensor` — status check

Say "start watering zone A for 20 minutes" or "take a photo of the garden" in chat.

### Vision
Photos are converted to JPEG in the browser (handles HEIC from iPhone) before upload. The backend passes image bytes as a `Blob` Part alongside the text to Gemini — the model sees the actual image for true multimodal analysis.

### RAG — Care Knowledge Base
18 plant-care documents (tomato, rose, basil, lavender, succulent, mint, pepper, strawberry, cucumber, lettuce, and general soil/pest guides) embedded with `gemini-embedding-001` (3072 dims) and stored in `garden.care_knowledge`. The collection is auto-seeded on first server startup if empty.

---

## Deployment — Cloud Run

```bash
# Set optional keys if you have them
export PERENUAL_API_KEY=sk-...
export GOOGLE_MAPS_API_KEY=AIza...

./deploy.sh <gcp-project-id> us-central1 garden-agent
```

`deploy.sh` sets optional env vars only when they are present in your shell — if empty, they are omitted and the app falls back gracefully (Nominatim for geocoding, no Perenual lookups).

Required env vars in Cloud Run:

| Variable | Required | Description |
|---|---|---|
| `MDB_MCP_CONNECTION_STRING` | Yes | MongoDB Atlas connection string |
| `GOOGLE_API_KEY` | Yes | Google AI Studio key (Gemini + embeddings) |
| `PERENUAL_API_KEY` | No | Perenual plant database API key |
| `GOOGLE_MAPS_API_KEY` | No | Google Maps Geocoding API key (Nominatim fallback if empty) |
| `PORT` | No | Server port (default 8080, set by Cloud Run) |

Cloud Run is configured with `--min-instances=1 --max-instances=1` so uploaded photos on local disk are not lost between requests. For multi-instance deployments, migrate uploads to GCS.
