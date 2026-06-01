import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "garden_agent" / ".env", override=False)

sys.path.insert(0, str(Path(__file__).parent.parent))

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

session_service = InMemorySessionService()
runner = Runner(agent=root_agent, app_name="garden", session_service=session_service)

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


class ChatRequest(BaseModel):
    message: str
    session_id: str


@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        await session_service.create_session(
            app_name="garden",
            user_id="user",
            session_id=req.session_id,
        )
    except Exception:
        pass

    async def generate():
        try:
            async for event in runner.run_async(
                user_id="user",
                session_id=req.session_id,
                new_message=Content(role="user", parts=[Part(text=req.message)]),
            ):
                if event.is_final_response() and event.content:
                    for part in event.content.parts:
                        if part.text:
                            yield part.text
        except Exception as e:
            yield f"\n\n[Error: {e}]"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


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
