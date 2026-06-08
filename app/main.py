import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "garden_agent" / ".env", override=True)

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import pymongo
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from garden_agent.agent import root_agent
from garden_agent.tools import load_memories, _get_genai, save_preference
from garden_agent.seed_knowledge import seed_if_empty
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part, Blob, GenerateContentConfig

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── ADK runner ──
session_service = InMemorySessionService()
runner = Runner(agent=root_agent, app_name="garden", session_service=session_service)

# ── MongoDB (direct, for user management) ──
_mongo = pymongo.MongoClient(os.environ["MDB_MCP_CONNECTION_STRING"])
_db = _mongo["garden"]
users_col = _db["users"]
users_col.create_index("email", unique=True)

# Cards = care subjects (one plant → whole garden). Reuse the `plants` collection
# the agent's MongoDB MCP CRUD already targets, so cards and agent state share storage.
cards_col = _db["plants"]
cards_col.create_index("user_id")

# Per-card chat transcript, persisted so history survives restarts and replays
# on card open (the ADK SessionService is still in-memory; that's accepted for now).
chat_history_col = _db["chat_history"]
chat_history_col.create_index([("user_id", 1), ("session_id", 1), ("ts", 1)])

notif_prefs_col = _db["notification_prefs"]
notif_prefs_col.create_index("user_id", unique=True)

# Auto-seed care_knowledge on first deploy (no-op if already populated)
seed_if_empty()

# Card "kind" facet — must match the frontend KIND set.
CARD_KINDS = {"plant", "bed", "lawn", "indoor", "garden"}

# Legacy `users.gardens` type ids → display label, mirroring the frontend TYPES list.
# Used by the GET /api/cards migration shim.
_LEGACY_TYPE_LABELS = {
    "flower": "Flower Garden", "lawn": "Lawn & Grass", "orchard": "Orchard",
    "vegetable": "Vegetable Garden", "tree": "Trees & Shrubs", "herb": "Herb Garden",
    "berry": "Berry Garden", "tropical": "Tropical Plants",
}

# Photos are stored on local disk. On Cloud Run this is ephemeral but safe as long
# as min-instances=1 (no cold-start data loss within a session). GCS migration is
# the correct long-term fix when multi-instance or persistence across restarts is needed.
_preferred_uploads = Path(__file__).parent / "uploads"
try:
    _preferred_uploads.mkdir(exist_ok=True)
    UPLOADS_DIR = _preferred_uploads
except OSError:
    import tempfile, warnings
    UPLOADS_DIR = Path(tempfile.gettempdir()) / "garden_uploads"
    UPLOADS_DIR.mkdir(exist_ok=True)
    warnings.warn(f"Could not create uploads dir at {_preferred_uploads}; using {UPLOADS_DIR}")


# ════════════════════════════════
#  Models
# ════════════════════════════════
class LoginRequest(BaseModel):
    email: str
    username: str

class GardenRequest(BaseModel):
    email: str
    garden_type: str

class LocationRequest(BaseModel):
    email: str
    location: str

class CardRequest(BaseModel):
    user_id: str            # email
    name: str
    kind: str               # plant | bed | lawn | indoor | garden
    tags: list[str] = []
    species: str = ""
    photo_id: str = ""

class IdentifyRequest(BaseModel):
    photo_id: str           # photo_id returned by /upload

_MIME_MAP = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".gif": "image/gif", ".webp": "image/webp",
             ".heic": "image/heic", ".heif": "image/heif"}


class ChatRequest(BaseModel):
    message: str
    session_id: str
    user_id: str = ""   # stable per-user identifier (email); falls back to session_id for guests
    photo_id: str = ""  # optional: photo_id returned by /upload
    card_id: str = ""   # optional: the card (care subject) this turn is about
    tag: str = ""       # optional: a tag-group thread spanning all cards with this tag
    garden_type: str = ""   # legacy, kept for back-compat
    username: str = ""
    location: str = ""
    save_user: bool = True  # set False to skip persisting the user message (e.g. the
                            # auto-generated care-plan prompt, which shouldn't replay)


class CheckRequest(BaseModel):
    user_id: str
    location: str = ""
    card_ids: list[str] = []   # empty = check all cards


class NotifPrefsRequest(BaseModel):
    user_id: str
    enabled_card_ids: list[str] = []   # empty = watch all cards
    frequency_hours: int = 24          # 24 | 48 | 168
    time_of_day: str = "morning"       # morning | afternoon | evening


# ════════════════════════════════
#  User / Garden endpoints
# ════════════════════════════════
def _user_doc(email: str) -> dict:
    doc = users_col.find_one({"email": email}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    return doc


@app.post("/api/login")
def login(req: LoginRequest):
    existing = users_col.find_one({"email": req.email}, {"_id": 0})
    if existing:
        return existing
    doc = {
        "email": req.email,
        "username": req.username,
        "gardens": [],
        "location": "",
        "created_at": datetime.utcnow().isoformat(),
    }
    users_col.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@app.post("/api/gardens")
def add_garden(req: GardenRequest):
    users_col.update_one(
        {"email": req.email},
        {"$addToSet": {"gardens": req.garden_type}},
    )
    return {"gardens": _user_doc(req.email)["gardens"]}


@app.patch("/api/user/location")
def update_location(req: LocationRequest):
    users_col.update_one({"email": req.email}, {"$set": {"location": req.location}})
    return {"location": req.location}


@app.get("/api/geocode")
async def geocode(lat: float = Query(...), lng: float = Query(...)):
    """Reverse-geocode coordinates to a city name.
    Uses Google Maps Geocoding API if GOOGLE_MAPS_API_KEY is set,
    otherwise falls back to Nominatim (OpenStreetMap, free).
    """
    maps_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    async with httpx.AsyncClient(timeout=8) as client:
        if maps_key:
            r = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"latlng": f"{lat},{lng}", "key": maps_key,
                        "result_type": "locality|administrative_area_level_1"},
            )
            data = r.json()
            if data.get("status") != "OK":
                raise HTTPException(400, f"Google Maps error: {data.get('status')}")
            components = {}
            for comp in data["results"][0]["address_components"]:
                if comp["types"]:
                    components[comp["types"][0]] = comp["long_name"]
            city  = components.get("locality") or components.get("sublocality") or components.get("administrative_area_level_2", "")
            state = components.get("administrative_area_level_1", "")
            location = f"{city}, {state}".strip(", ") if city else state
        else:
            # Free fallback: Nominatim
            r = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lng, "format": "json"},
                headers={"User-Agent": "GardenState/1.0"},
            )
            data = r.json()
            addr = data.get("address", {})
            city  = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county", "")
            state = addr.get("state", "")
            location = f"{city}, {state}".strip(", ") if city else state

    if not location:
        raise HTTPException(400, "Could not determine location from coordinates")
    return {"location": location}


@app.delete("/api/gardens")
def remove_garden(req: GardenRequest):
    users_col.update_one(
        {"email": req.email},
        {"$pull": {"gardens": req.garden_type}},
    )
    return {"gardens": _user_doc(req.email)["gardens"]}


# ════════════════════════════════
#  Cards (care subjects)
# ════════════════════════════════
def _migrate_legacy_gardens(user_id: str) -> list[dict]:
    """One-time shim: a user with legacy `users.gardens` but no cards gets one
    `kind="bed"` area card per legacy type. `users.gardens` is left untouched."""
    user = users_col.find_one({"email": user_id}, {"_id": 0, "gardens": 1})
    legacy = (user or {}).get("gardens") or []
    cards = []
    for type_id in legacy:
        cards.append({
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "name": _LEGACY_TYPE_LABELS.get(type_id, type_id),
            "kind": "bed",
            "species": "",
            "tags": [type_id],
            "photo_id": "",
            "created_at": datetime.utcnow().isoformat(),
        })
    if cards:
        cards_col.insert_many(cards)
    return cards


@app.get("/api/cards")
def list_cards(user_id: str = Query(...)):
    # `_id` is already a str (uuid), so the docs serialize as-is.
    cards = list(cards_col.find({"user_id": user_id}))
    if not cards:
        cards = _migrate_legacy_gardens(user_id)
    return {"cards": cards}


@app.post("/api/cards")
def create_card(req: CardRequest):
    if req.kind not in CARD_KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid kind: {req.kind}")
    card = {
        "_id": str(uuid.uuid4()),
        "user_id": req.user_id,
        "name": req.name,
        "kind": req.kind,
        "species": req.species,
        "tags": req.tags,
        "photo_id": req.photo_id,
        "created_at": datetime.utcnow().isoformat(),
    }
    cards_col.insert_one(card)
    return card


@app.delete("/api/cards/{card_id}")
def delete_card(card_id: str, user_id: str = Query(...)):
    res = cards_col.delete_one({"_id": card_id, "user_id": user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Card not found")
    return {"deleted": card_id}


class CardUpdateRequest(BaseModel):
    user_id: str
    name: str = ""
    kind: str = ""
    tags: list[str] = []
    species: str = ""
    photo_id: str = ""


@app.patch("/api/cards/{card_id}")
def update_card(card_id: str, req: CardUpdateRequest):
    updates = {k: v for k, v in {
        "name": req.name, "kind": req.kind,
        "tags": req.tags, "species": req.species, "photo_id": req.photo_id,
    }.items() if v != "" and v != []}
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = cards_col.update_one(
        {"_id": card_id, "user_id": req.user_id},
        {"$set": updates},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Card not found")
    doc = cards_col.find_one({"_id": card_id}, {"_id": 0})
    return {**doc, "id": card_id}


_IDENTIFY_INSTRUCTION = (
    "You are a horticulture expert. Identify the single main plant or garden subject "
    "shown in this photo for a garden-care app. Respond with JSON only — no prose, no "
    "markdown fences — using exactly these keys:\n"
    '{ "name": short friendly label a gardener would use (e.g. "Front-yard narcissus"),\n'
    '  "species": botanical/Latin name, or "" if unsure,\n'
    '  "kind": one of "plant" | "bed" | "lawn" | "indoor" | "garden" — pick by what the '
    "photo mostly shows (a single specimen = plant, a planted area = bed, turf = lawn, a "
    "potted houseplant = indoor, a whole yard = garden),\n"
    '  "tags": 1-4 lowercase facet tags such as "flower","tree","shrub","indoor","lawn",'
    '"vegetable","herb","succulent",\n'
    '  "confidence": number between 0 and 1 }'
)


@app.post("/api/identify")
def identify(req: IdentifyRequest):
    """Photo → suggested card fields via Gemini vision. The UI prefills these
    (all editable) and falls back to manual entry on any failure, so every error
    returns HTTP 200 with an `{"error": ...}` body rather than raising."""
    candidates = list(UPLOADS_DIR.glob(f"{req.photo_id}.*"))
    if not candidates:
        return {"error": "photo not found"}
    img_path = candidates[0]
    mime = _MIME_MAP.get(img_path.suffix.lower(), "image/jpeg")
    try:
        resp = _get_genai().models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                Part(inline_data=Blob(mime_type=mime, data=img_path.read_bytes())),
                Part(text=_IDENTIFY_INSTRUCTION),
            ],
            config=GenerateContentConfig(response_mime_type="application/json"),
        )
        data = json.loads(resp.text)
    except Exception as e:
        return {"error": str(e)}

    # Light normalisation — the model is told the schema, but keep the UI safe.
    kind = str(data.get("kind", "")).lower()
    tags = data.get("tags") or []
    return {
        "name": str(data.get("name", "")).strip(),
        "species": str(data.get("species", "")).strip(),
        "kind": kind if kind in CARD_KINDS else "plant",
        "tags": [str(t).strip().lower() for t in tags if str(t).strip()][:4],
        "confidence": data.get("confidence", 0),
    }


# ════════════════════════════════
#  Memory context builder
# ════════════════════════════════
def _memory_context(user_id: str) -> str:
    """Format all stored memory for `user_id` into context blocks for the agent."""
    mem = load_memories(user_id)
    block = ""
    if mem["facts"]:
        block += "[Long-term memory:\n" + "".join(f"- {f}\n" for f in mem["facts"]) + "]\n"
    if mem["preferences"]:
        prefs = "".join(f"- {k}: {v}\n" for k, v in mem["preferences"].items())
        block += f"[Preferences:\n{prefs}]\n"
    if mem["plant_notes"]:
        notes = "".join(f"- {plant}: {note}\n" for plant, note in mem["plant_notes"].items())
        block += f"[Plant notes:\n{notes}]\n"
    return block


# ════════════════════════════════
#  Chat
# ════════════════════════════════
def _save_history(user_id: str, session_id: str, card_id: str, role: str, text: str, tag: str = ""):
    """Append one message to a thread transcript (per-card, or per tag-group when
    `tag` is set). Best-effort: a logging failure must never break the chat stream."""
    if not text:
        return
    try:
        chat_history_col.insert_one({
            "user_id": user_id, "session_id": session_id, "card_id": card_id, "tag": tag,
            "role": role, "text": text, "ts": datetime.utcnow().isoformat(),
        })
    except Exception:
        pass


@app.get("/api/notif-prefs")
def get_notif_prefs(user_id: str = Query(...)):
    doc = notif_prefs_col.find_one({"user_id": user_id}, {"_id": 0})
    return doc or {"enabled_card_ids": [], "frequency_hours": 24, "time_of_day": "morning"}


@app.post("/api/notif-prefs")
def save_notif_prefs(req: NotifPrefsRequest):
    notif_prefs_col.update_one(
        {"user_id": req.user_id},
        {"$set": {
            "enabled_card_ids": req.enabled_card_ids,
            "frequency_hours": req.frequency_hours,
            "time_of_day": req.time_of_day,
            "updated_at": datetime.utcnow().isoformat(),
        }},
        upsert=True,
    )
    return {"status": "saved"}


@app.post("/api/check")
async def garden_check(req: CheckRequest):
    """Run a care check for the user, streaming the agent's report.
    If card_ids is provided, only those cards are checked."""
    user_id = req.user_id
    location = req.location or "your area"

    raw_cards = list(cards_col.find(
        {"user_id": user_id},
        {"_id": 1, "name": 1, "species": 1, "kind": 1},
    ))
    # Filter to selected cards if caller specified a subset
    if req.card_ids:
        allowed = set(req.card_ids)
        raw_cards = [c for c in raw_cards if str(c["_id"]) in allowed]

    def _ndjson(obj: dict) -> str:
        return json.dumps(obj, ensure_ascii=False) + "\n"

    if not raw_cards:
        async def _empty():
            yield _ndjson({"type": "text", "delta": "No plants or areas added yet — use '+ Add Plant or Area' to get started!"})
        return StreamingResponse(_empty(), media_type="application/x-ndjson")

    card_lines = "\n".join(
        f"- {c.get('name', '?')} ({c.get('species') or c.get('kind', 'plant')}), sensor_id={str(c['_id'])}"
        for c in raw_cards
    )

    prompt = (
        f"[Context: user_id={user_id}, location={location}]\n"
        f"{_memory_context(user_id)}"
        f"Quick care check on all my plants and areas.\n\n"
        f"Plants and areas:\n{card_lines}\n\n"
        f"Do this:\n"
        f'1. Call get_weather("{location}") — one call only\n'
        f"2. Call read_sensors() once per plant using its sensor_id\n\n"
        f"Reply using ONLY these four section headers in plain text (no asterisks, no markdown):\n\n"
        f"💧 Needs Water Now\n"
        f"(list plants with soil moisture under 35%, show the exact %, one sentence each)\n\n"
        f"🌿 Fertilize This Week\n"
        f"(what needs feeding now, one sentence each)\n\n"
        f"🚨 Disease & Pest Watch\n"
        f"(risks from weather + plant type — e.g. late blight, aphids — one sentence each)\n\n"
        f"✅ All Looking Good\n"
        f"(plants needing no action right now)\n\n"
        f"Rules: plain text only, no asterisks, no markdown. Name each plant. One sentence per item. Be direct."
    )

    check_session_id = f"check_{uuid.uuid4().hex}"
    try:
        await session_service.create_session(
            app_name="garden", user_id=user_id, session_id=check_session_id,
        )
    except Exception:
        pass

    async def generate():
        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=check_session_id,
                new_message=Content(role="user", parts=[Part(text=prompt)]),
            ):
                get_calls = getattr(event, "get_function_calls", None)
                if get_calls:
                    for call in get_calls() or []:
                        name = getattr(call, "name", "") or ""
                        args = getattr(call, "args", None) or {}
                        detail = ""
                        if isinstance(args, dict):
                            detail = str(
                                args.get("plant_id")
                                or args.get("query")
                                or args.get("location")
                                or args.get("plant_name")
                                or ""
                            )
                        yield _ndjson({"type": "status", "tool": name, "detail": detail})
                if event.is_final_response() and event.content:
                    for part in event.content.parts:
                        if part.text:
                            yield _ndjson({"type": "text", "delta": part.text})
        except Exception as e:
            yield _ndjson({"type": "error", "message": str(e)})

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/chat")
async def chat(req: ChatRequest):
    # Use stable user_id (email) for ADK user scoping; guests fall back to session_id
    user_id = req.user_id or req.session_id

    try:
        await session_service.create_session(
            app_name="garden",
            user_id=user_id,
            session_id=req.session_id,
        )
    except Exception:
        pass

    # Build context header
    user_part = f", user={req.username}" if req.username else ""
    card = cards_col.find_one({"_id": req.card_id, "user_id": user_id}) if req.card_id else None
    if card:
        # Per-card context: tell the agent the precise care subject.
        attrs = [f'kind={card.get("kind", "")}']
        if card.get("species"):
            attrs.append(f'species={card["species"]}')
        if card.get("tags"):
            attrs.append(f'tags={"/".join(card["tags"])}')
        card_part = f', card="{card.get("name", "")}" ({", ".join(attrs)})'
        loc = f", location={req.location}" if req.location else ""
        context = f"[Context: user_id={user_id}{user_part}{card_part}{loc}]\n"
    elif req.tag:
        # Tag-group thread: context spans every card the user has tagged `req.tag`.
        group = list(cards_col.find({"user_id": user_id, "tags": req.tag}).limit(20))
        descs = []
        for c in group:
            bits = [c.get("kind", "")] + ([c["species"]] if c.get("species") else [])
            descs.append(f'{c.get("name", "")} ({", ".join(b for b in bits if b)})')
        cards_str = "; ".join(descs) if descs else "(no cards yet)"
        loc = f", location={req.location}" if req.location else ""
        context = (
            f'[Context: user_id={user_id}{user_part}, tag-group="{req.tag}", '
            f'cards: {cards_str}{loc}]\n'
        )
    else:
        # Legacy garden context (kept byte-identical for back-compat).
        loc = f" in {req.location}" if req.location else ""
        garden_part = f", garden={req.garden_type}{loc}" if req.garden_type else ""
        context = f"[Context: user_id={user_id}{user_part}{garden_part}]\n"

    # Inject structured memory from MongoDB (facts + preferences + plant notes)
    context += _memory_context(user_id)

    full_message = context + req.message

    # Build multimodal parts: optional image first, then text
    parts: list[Part] = []
    image_loaded = False
    if req.photo_id:
        candidates = list(UPLOADS_DIR.glob(f"{req.photo_id}.*"))
        if candidates:
            img_path = candidates[0]
            mime = _MIME_MAP.get(img_path.suffix.lower(), "image/jpeg")
            parts.append(Part(inline_data=Blob(mime_type=mime, data=img_path.read_bytes())))
            image_loaded = True
    suffix = "\n[Photo attached — please analyse the plant in the image.]" if image_loaded else ""
    parts.append(Part(text=full_message + suffix))

    # Persist the user turn before the run (the care-plan prompt sets save_user=False
    # so its engineered text isn't replayed as a user bubble).
    if req.save_user:
        _save_history(user_id, req.session_id, req.card_id, "user", req.message, req.tag)

    def _ndjson(obj: dict) -> str:
        return json.dumps(obj, ensure_ascii=False) + "\n"

    async def generate():
        agent_text = ""
        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=req.session_id,
                new_message=Content(role="user", parts=parts),
            ):
                # Surface each tool call as a status line so the UI can show
                # live activity (incl. which MongoDB MCP collection is hit).
                get_calls = getattr(event, "get_function_calls", None)
                if get_calls:
                    for call in get_calls() or []:
                        name = getattr(call, "name", "") or ""
                        args = getattr(call, "args", None) or {}
                        detail = ""
                        if isinstance(args, dict):
                            detail = str(
                                args.get("collection")
                                or args.get("location")
                                or args.get("city")
                                or args.get("plant_name")
                                or ""
                            )
                        yield _ndjson({"type": "status", "tool": name, "detail": detail})
                if event.is_final_response() and event.content:
                    for part in event.content.parts:
                        if part.text:
                            agent_text += part.text
                            yield _ndjson({"type": "text", "delta": part.text})
        except Exception as e:
            yield _ndjson({"type": "error", "message": str(e)})
        finally:
            # Persist whatever the agent produced (also on error, with what accumulated).
            _save_history(user_id, req.session_id, req.card_id, "agent", agent_text, req.tag)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/api/history")
def get_history(user_id: str = Query(...), session_id: str = Query(...)):
    """Replay a card's transcript (oldest → newest, capped)."""
    cursor = (
        chat_history_col.find(
            {"user_id": user_id, "session_id": session_id},
            {"_id": 0, "role": 1, "text": 1, "ts": 1},
        )
        .sort("ts", 1)
        .limit(200)
    )
    return {"messages": list(cursor)}


# ════════════════════════════════
#  Photo upload
# ════════════════════════════════
@app.post("/upload")
async def upload_photo(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    photo_id = str(uuid.uuid4())
    suffix = Path(file.filename or "photo.jpg").suffix or ".jpg"
    save_path = UPLOADS_DIR / f"{photo_id}{suffix}"
    save_path.write_bytes(await file.read())
    return {"photo_id": photo_id, "url": f"/photos/{photo_id}{suffix}"}


app.mount("/photos", StaticFiles(directory=UPLOADS_DIR), name="photos")
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
