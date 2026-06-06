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
from garden_agent.tools import load_memories
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part, Blob

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

# TODO: move uploads to GCS for multi-instance (local disk is ephemeral per Cloud Run instance)
UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


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

_MIME_MAP = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".gif": "image/gif", ".webp": "image/webp",
             ".heic": "image/heic", ".heif": "image/heif"}


class ChatRequest(BaseModel):
    message: str
    session_id: str
    user_id: str = ""   # stable per-user identifier (email); falls back to session_id for guests
    photo_id: str = ""  # optional: photo_id returned by /upload
    garden_type: str = ""
    username: str = ""
    location: str = ""


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
#  Chat
# ════════════════════════════════
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
    loc = f" in {req.location}" if req.location else ""
    garden_part = f", garden={req.garden_type}{loc}" if req.garden_type else ""
    user_part = f", user={req.username}" if req.username else ""
    context = f"[Context: user_id={user_id}{user_part}{garden_part}]\n"

    # Inject long-term memory from MongoDB
    memories = load_memories(user_id)
    if memories:
        facts = "\n".join(f"- {f}" for f in memories)
        context += f"[Long-term memory:\n{facts}]\n"

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

    async def generate():
        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=req.session_id,
                new_message=Content(role="user", parts=parts),
            ):
                if event.is_final_response() and event.content:
                    for part in event.content.parts:
                        if part.text:
                            yield part.text
        except Exception as e:
            yield f"\n\n[Error: {e}]"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


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
