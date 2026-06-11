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
  ├── get_weather()           Open-Meteo: current + 3-day forecast + frost/heat/rain alerts
  ├── get_plant_care()        Perenual plant database API
  ├── read_sensors()          Time-of-day physics model (simulated IoT)
  ├── control_smart_home()    Simulated irrigation zones + garden camera
  ├── save_memory()           MongoDB user_memories · general facts
  ├── forget_memory()         Remove facts from long-term memory on request
  ├── save_preference()       Store named preferences (experience level, watering time, etc.)
  ├── save_plant_note()       Store personal notes tied to a specific plant
  ├── search_care_knowledge() Atlas Vector Search RAG (gemini-embedding-001)
  ├── Vision                  HEIC/JPEG/PNG → Gemini multimodal plant diagnosis
  └── MongoDB MCP             CRUD on plant records, sensor logs, tasks, variety specs
        └── garden DB (Atlas)
              ├── users
              ├── plants               ← care cards
              ├── plants_knowledge     ← variety specs (days_to_harvest, spacing, pests, etc.)
              ├── chat_history         ← per-card transcript (persistent across sessions)
              ├── sensor_readings
              ├── tasks
              ├── care_knowledge       ← RAG knowledge base (39 docs, 3072-dim embeddings)
              ├── user_memories        ← per-user long-term memory (facts + preferences + plant notes)
              └── notification_prefs   ← per-user notification schedule
```

---

## Features

| Capability | How it works |
|---|---|
| **Chat** | Streaming NDJSON via ADK + Gemini 2.5 Flash; history replays on card re-open |
| **Care cards** | Add, edit, delete plants/areas; photo identifies species + auto-matches to existing cards |
| **Garden types** | User-managed type list (flower, vegetable, herb, etc.) drives sidebar filter tabs; auto-prompted on first login |
| **Plant status dots** | Color-coded dot on each card (🟢 healthy · 🟡 needs attention · 🔴 urgent · ⚪ not checked); automatically updated after every care check |
| **Search** | Sidebar search box filters cards by name or species in real-time |
| **Weather** | Open-Meteo (free, no key) — current conditions + 3-day forecast; city-only fallback for "City, State" input |
| **Plant care lookup** | Perenual API — watering frequency, sunlight needs, care level; gracefully falls back to agent training knowledge when free-tier data is paywalled |
| **Sensor data** | Simulated soil moisture / temp / light via time-of-day physics model |
| **Smart home control** | `control_smart_home()` — start/stop irrigation zones, set recurring watering schedules, take camera snapshots |
| **Vision** | Upload any photo (HEIC, JPEG, PNG) → converted to JPEG → Gemini diagnoses plant health |
| **Real-time location** | Browser Geolocation → `/api/geocode` → Google Maps API or Nominatim fallback |
| **RAG** | `search_care_knowledge()` embeds query with `gemini-embedding-001`, runs `$vectorSearch` |
| **Long-term memory** | Facts, preferences, and plant notes stored in `user_memories`, injected as context every turn |
| **Behavioral adaptation** | Agent adapts tone and detail to the user's experience level (beginner / intermediate / expert) and season |
| **Chat history** | Per-card transcripts persisted in MongoDB; deterministic session IDs ensure history survives logout/login; photos are stored with each message and thumbnails are restored on replay |
| **Notifications** | **Check Now** and **Set Reminder** buttons in the chat header (top-right); care check runs across all cards (sensors + weather); configurable frequency + time window |
| **Live temperature** | Current temperature (°C / °F) fetched from Open-Meteo and displayed as a badge next to your location chip — updates whenever your location is set or changed |
| **Tasks** | Right-side slide-in task panel (📋); user-created and agent-written tasks in one list; pending count badge; filter by All / Pending / Done; agent logs tasks when it executes smart-home actions or confirms care actions mid-conversation |
| **Mobile-responsive UI** | Off-canvas sidebar, bottom-sheet modals, iOS zoom prevention, touch-friendly targets; works on phone and tablet |
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
| `POST` | `/api/identify` | Identify a plant from a photo; returns species, confidence, auto-matched card, and full card list |
| `GET` | `/api/notif-prefs?user_id=` | Get notification preferences |
| `POST` | `/api/notif-prefs` | Save notification preferences |
| `POST` | `/api/check` | Run a whole-garden care check (streaming NDJSON) |
| `GET` | `/api/history?user_id=&session_id=` | Replay a card's chat transcript |
| `POST` | `/chat` | Send a chat message (streaming NDJSON) |
| `POST` | `/upload` | Upload a plant photo; returns `photo_id` |
| `GET` | `/api/tasks?user_id=` | List all tasks for a user |
| `POST` | `/api/tasks` | Create a task (title, priority, due_date, card_id) |
| `PATCH` | `/api/tasks/{task_id}` | Update a task (done state, title, priority) |
| `DELETE` | `/api/tasks/{task_id}` | Delete a task |

---

## Key Features in Detail

### Care Cards
Each card represents one thing you care for — a single plant, a bed, a lawn, or a whole garden. Cards have a name, kind (Flower / Vegetable / Herb / Lawn / Orchard / Trees & Shrubs / Berry / Tropical / Indoor / Succulent), species, tags, and optional photo.

**Photo identification flow:**
1. Upload any photo (HEIC, JPEG, PNG) in the Add card modal
2. Gemini identifies the plant and returns a species name + confidence score
3. The app automatically matches the result against your existing cards:
   - **Auto-match found** → a highlighted button appears: "✅ Use existing card: [name]" — one click to confirm
   - **Manual override** → a dropdown lists all your cards so you can pick a different one
   - **No match / new plant** → "➕ Create new card" pre-fills the form with the identified name and species
4. Confirming an existing card updates it with the new photo; confirming a new card creates it

### Plant Status Dots
Every card in the sidebar shows a small color-coded dot at a glance:

| Dot | Color | Meaning |
|---|---|---|
| ⚪ | Grey | Not yet checked |
| 🟢 | Green | Healthy — all good |
| 🟡 | Yellow | Needs attention (fertilize, minor issue) |
| 🔴 | Red | Needs immediate action (watering, disease, pest) |

Status is automatically updated every time you run **Check Now**. The parser maps care-check sections (💧 Needs Water Now, 🚨 Disease & Pest Watch → red; 🌿 Fertilize This Week → yellow; ✅ All Looking Good → green) to individual card names.

### Sidebar Search
A search box above the card list filters by card name or species in real-time. Combined with the garden-type filter tabs, you can quickly find any plant in a large garden.

### Garden Type Tabs
Users manage their garden type list (Flower, Vegetable, Herb, Lawn, Orchard, Trees & Shrubs, Berry, Tropical, Indoor, Succulent) via a picker in the sidebar. The filter tabs update instantly, and new users are automatically prompted to choose their types on first login. The same type list is used in the Add/Edit card form so names stay consistent everywhere.

### Long-Term Memory + Chat History
Two separate persistence layers:

**Long-term memory** (`user_memories`) stores three types of information:
- **Facts** — general observations the agent records (`save_memory`): new plants added, pest sightings, care events, care style
- **Preferences** (`save_preference`) — named, reusable settings:
  - `experience_level` (beginner / intermediate / expert) — controls how detailed the agent's advice is
  - `watering_time` — preferred watering window the agent always suggests
  - `advice_style` — e.g. "no chemical fertilizer", "prefer organic"
  - `language_detail` — concise or detailed explanations
- **Plant notes** (`save_plant_note`) — personal notes tied to a specific plant (sentimental history, custom observations)

All three blocks are injected as context at the start of every turn and survive logout and browser close.

**Chat history** (`chat_history`): full per-card transcript. Session IDs are derived deterministically from `email + card_id` (format: `u::<email>::card::<id>`), so history is always recoverable after logout/login — no dependency on `localStorage` keys that could be cleared. Photos sent during chat are stored by `photo_id`; thumbnails are restored when history is replayed (images that no longer exist on disk are silently hidden).

### Behavioral Adaptation
The agent automatically adapts based on stored preferences:
- **Experience level**: if not set, the agent asks once early in the conversation and saves the answer. Beginners get step-by-step explanations with the "why"; experts get concise, direct advice.
- **Seasonal awareness**: the agent infers the current season from today's date and the user's location, automatically shifting focus to the most relevant tasks (e.g. frost protection in winter, watering frequency in summer).
- **Preference respect**: advice never recommends an approach the user has excluded, and watering suggestions always use the user's preferred time window.

### Notifications
**Check Now** and **Set Reminder** are pill buttons in the top-right corner of the chat header — visible at all times without opening the sidebar.

**Check Now** runs the agent across all (or selected) cards — it reads sensors, checks weather, and produces a plain-text report sectioned by:
- 💧 Needs Water Now
- 🌿 Fertilize This Week
- 🚨 Disease & Pest Watch
- ✅ All Looking Good

After the check completes, card status dots are updated automatically and any agent-recommended tasks are written to the Tasks panel.

**Set Reminder** configures which cards to watch, frequency (daily / every 2 days / weekly), and preferred time window (morning / afternoon / evening). When you open the app during the configured window and a check is due, the red dot appears automatically.

On mobile, both buttons show only their icons to save space.

### Live Temperature
A temperature badge (`22°C / 72°F`) is displayed next to the location chip in the header. It is fetched from Open-Meteo (free, no key) using the same geocoding flow as weather queries, and refreshes automatically whenever the user's location is updated.

### Tasks
The **📋** button in the chat header opens a right-side slide-in task panel. Tasks come from two sources:

- **User-created**: add any to-do with a title, optional due date, and priority (high / medium / low)
- **Agent-written**: the agent logs a task when it executes a `control_smart_home()` action (e.g. starts irrigation or sets a schedule) or when the user confirms a concrete care action mid-conversation (watering, fertilising, applying a treatment). Tasks are **not** auto-generated during routine care checks — only real conversational actions produce them.

The panel shows a pending count badge on the 📋 button. Filter between **All**, **Pending**, and **Done** tabs. Tasks can be checked off or deleted inline.

**Task schema in MongoDB (`garden.tasks`):**

| Field | Type | Description |
|---|---|---|
| `user_id` | string | Owner |
| `title` | string | What to do |
| `done` | bool | Completion state |
| `priority` | string | `high` / `medium` / `low` |
| `due_date` | string (ISO) | Optional due date |
| `card_id` | string | Optional — links task to a specific care card |
| `source` | string | `user` or `agent` |
| `created_at` | string (ISO) | Creation timestamp |

### Smart Home Control (Simulated)
`control_smart_home(device, action, duration_minutes, repeat_days, time_of_day)` lets the agent control:
- `irrigation_zone_A` / `irrigation_zone_B` — start/stop watering, or set a recurring schedule
- `camera` — take a garden snapshot (returns a simulated observation)
- `soil_sensor` — status check

Supported actions:

| Action | Description | Example phrase |
|---|---|---|
| `on` | Start irrigation now for `duration_minutes` | "water zone A for 10 minutes" |
| `off` | Stop irrigation | "stop watering" |
| `schedule` | Set a recurring watering schedule for `repeat_days` days at `time_of_day` | "water my lawn every morning for 5 days" |
| `snapshot` | Take a garden camera photo | "take a photo of the garden" |
| `status` | Check current device state | "is the irrigation running?" |

### Weather — Current + 3-Day Forecast
`get_weather(location)` returns current conditions and a 3-day daily forecast in a single Open-Meteo call (free, no API key). The response includes garden-specific derived alerts:

| Alert | Trigger | Agent behaviour |
|---|---|---|
| `frost_risk` | Any day's min temp < 2 °C | Warns about frost protection |
| `heat_stress` | Any day's max temp > 35 °C | Advises extra watering / shade |
| `rain_coming` | > 2 mm rain in next 3 days | Notes upcoming rain |
| `skip_watering` | > 2 mm rain expected today or tomorrow | Tells user to skip watering |

Example: asking "should I water today?" when rain is forecast returns *"8 mm of rain expected tomorrow — skip watering today."*

### Mobile UI
The app is fully responsive with two breakpoints:

| Breakpoint | Layout |
|---|---|
| ≤ 860px (tablet) | Sidebar narrows; chat panel adjusts |
| ≤ 620px (phone) | Sidebar becomes off-canvas (hamburger ☰); all modals slide up as bottom sheets with a drag-handle indicator; inputs locked at 16px to prevent iOS auto-zoom; card action buttons always visible (no hover required) |

On first open (mobile), tap ☰ to open the sidebar. Tap the overlay or swipe-dismiss to close it.

### Vision
Photos are converted to JPEG in the browser (handles HEIC from iPhone) before upload. The backend passes image bytes as a `Blob` Part alongside the text to Gemini — the model sees the actual image for true multimodal analysis.

### RAG — Care Knowledge Base
39 plant-care documents covering 24+ species (tomato, rose, basil, lavender, succulent, mint, pepper, strawberry, cucumber, lettuce, orchid / Phalaenopsis, pothos, monstera, snake plant, fiddle-leaf fig, peace lily, rosemary, thyme, blueberry, fruit trees, fern, hibiscus, zucchini, lawn/turf, and general watering / fertilising / seasonal guides) embedded with `gemini-embedding-001` (3072 dims) and stored in `garden.care_knowledge`. The collection is auto-seeded on startup and automatically re-seeded when the stored count is below the expected document count — no manual intervention needed when the knowledge base grows.

### Plant Care Lookup (Perenual + Fallback)
`get_plant_care(species)` queries the Perenual plant database API for watering frequency, sunlight requirements, and care level. The free tier occasionally returns paywalled placeholder values (`"Upgrade Plans"`); the tool detects these, strips them, and signals the agent to answer from its own training knowledge instead. The agent never tells users "I can't find information" — it always provides a best-effort answer.

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
