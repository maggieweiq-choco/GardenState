import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "garden_agent" / ".env", override=False)

sys.path.insert(0, str(Path(__file__).parent.parent))

import pymongo
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from garden_agent.agent import root_agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

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

class ChatRequest(BaseModel):
    message: str
    session_id: str
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
    try:
        await session_service.create_session(
            app_name="garden",
            user_id=req.session_id,
            session_id=req.session_id,
        )
    except Exception:
        pass

    # Prepend garden context so the agent knows what it's managing
    context = ""
    if req.username and req.garden_type:
        loc = f" in {req.location}" if req.location else ""
        context = f"[Context: Managing {req.username}'s {req.garden_type}{loc}]\n"
    full_message = context + req.message

    async def generate():
        try:
            async for event in runner.run_async(
                user_id=req.session_id,
                session_id=req.session_id,
                new_message=Content(role="user", parts=[Part(text=full_message)]),
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
