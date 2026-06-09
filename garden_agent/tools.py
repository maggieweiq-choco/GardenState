import os
import math
import random
import httpx
import pymongo
from google import genai as _genai_module
from datetime import datetime

# Simulated smart-home device state (resets on restart, mirrors real IoT behaviour).
_device_state: dict = {
    "irrigation_zone_A": {"status": "off", "last_run": None},
    "irrigation_zone_B": {"status": "off", "last_run": None},
    "camera":            {"status": "online"},
    "soil_sensor":       {"status": "online"},
}

_mongo_client: pymongo.MongoClient | None = None
_genai_client = None


def _garden_db():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = pymongo.MongoClient(os.environ["MDB_MCP_CONNECTION_STRING"])
    return _mongo_client["garden"]


def _memory_col():
    return _garden_db()["user_memories"]


def _get_genai():
    global _genai_client
    if _genai_client is None:
        _genai_client = _genai_module.Client()
    return _genai_client


def save_memory(user_id: str, fact: str) -> dict:
    """Save an important fact about this user's garden to long-term memory for future sessions.

    Call this whenever you learn something new and lasting: new plants added, watering
    preferences, known pests or issues, care style (organic, etc.), or any preference
    the user expresses. Use the user_id from the [Context] header.
    """
    _memory_col().update_one(
        {"user_id": user_id},
        {
            "$addToSet": {"facts": fact},
            "$set": {"updated_at": datetime.utcnow().isoformat()},
        },
        upsert=True,
    )
    return {"status": "saved", "user_id": user_id, "fact": fact}


def load_memories(user_id: str) -> dict:
    """Return all stored memory for a user as a structured dict:
    { facts: [...], preferences: {...}, plant_notes: {...} }"""
    doc = _memory_col().find_one({"user_id": user_id}, {"facts": 1, "preferences": 1, "plant_notes": 1})
    if not doc:
        return {"facts": [], "preferences": {}, "plant_notes": {}}
    return {
        "facts":       doc.get("facts", []),
        "preferences": doc.get("preferences", {}),
        "plant_notes": doc.get("plant_notes", {}),
    }


def forget_memory(user_id: str, fact_query: str) -> dict:
    """Remove facts from this user's long-term memory that match fact_query
    (case-insensitive substring). Call when the user asks you to forget,
    delete, or stop remembering something. Returns the removed facts."""
    q = fact_query.strip().lower()
    if not q:  # guard: an empty query would substring-match (and wipe) every fact
        return {"removed": [], "count": 0}
    matched = [f for f in load_memories(user_id)["facts"] if q in f.lower()]
    if matched:
        _memory_col().update_one(
            {"user_id": user_id},
            {
                "$pull": {"facts": {"$in": matched}},
                "$set": {"updated_at": datetime.utcnow().isoformat()},
            },
        )
    return {"removed": matched, "count": len(matched)}


def save_preference(user_id: str, key: str, value: str) -> dict:
    """Save a user preference to long-term memory.

    Use this for structured, reusable preferences — NOT one-off facts.
    Common keys:
      experience_level  — "beginner" | "intermediate" | "expert"
      watering_time     — e.g. "morning", "evening"
      advice_style      — e.g. "no chemical fertilizer", "prefer organic"
      language_detail   — "concise" | "detailed"
    Call save_memory() for general facts; use this only for named preferences.
    """
    _memory_col().update_one(
        {"user_id": user_id},
        {
            "$set": {
                f"preferences.{key}": value,
                "updated_at": datetime.utcnow().isoformat(),
            }
        },
        upsert=True,
    )
    return {"status": "saved", "key": key, "value": value}


def save_plant_note(user_id: str, plant_name: str, note: str) -> dict:
    """Save a personal note about a specific plant (e.g. sentimental value, custom name,
    observation). plant_name is used as the key, so use a consistent short name.
    Examples: save_plant_note(user_id, "tomato", "grandma's heirloom variety, planted May 2024")
    """
    _memory_col().update_one(
        {"user_id": user_id},
        {
            "$set": {
                f"plant_notes.{plant_name}": note,
                "updated_at": datetime.utcnow().isoformat(),
            }
        },
        upsert=True,
    )
    return {"status": "saved", "plant": plant_name, "note": note}


def is_plant_care_query(query: str) -> bool:
    """Helper to classify if a query is related to plant care or gardening."""
    prompt = (
        "Classify if the following user query is asking for plant care advice, gardening instructions, "
        "watering schedules, sunlight, soil, pests, or plant species details.\n"
        "Respond with 'yes' or 'no' only.\n\n"
        f"Query: {query}"
    )
    try:
        resp = _get_genai().models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return resp.text.strip().lower().startswith("yes")
    except Exception:
        return True  # Default to True on error to ensure we don't break RAG


def forget_memory(user_id: str, fact_query: str) -> dict:
    """Remove facts from this user's long-term memory that match fact_query
    (case-insensitive substring). Call when the user asks you to forget,
    delete, or stop remembering something. Returns the removed facts."""
    q = fact_query.strip().lower()
    if not q:  # guard: an empty query would substring-match (and wipe) every fact
        return {"removed": [], "count": 0}
    matched = [f for f in load_memories(user_id) if q in f.lower()]
    if matched:
        _memory_col().update_one(
            {"user_id": user_id},
            {
                "$pull": {"facts": {"$in": matched}},
                "$set": {"updated_at": datetime.utcnow().isoformat()},
            },
        )
    return {"removed": matched, "count": len(matched)}


def is_plant_care_query(query: str) -> bool:
    """Helper to classify if a query is related to plant care or gardening."""
    prompt = (
        "Classify if the following user query is asking for plant care advice, gardening instructions, "
        "watering schedules, sunlight, soil, pests, or plant species details.\n"
        "Respond with 'yes' or 'no' only.\n\n"
        f"Query: {query}"
    )
    try:
        resp = _get_genai().models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return resp.text.strip().lower().startswith("yes")
    except Exception:
        return True  # Default to True on error to ensure we don't break RAG


def search_care_knowledge(query: str) -> list[dict]:
    """Search the plant care knowledge base using semantic vector search.

    Call this for any question about plant care: watering schedules, sunlight needs,
    fertilising, common pests, pruning, soil type, etc. Returns the top matching passages.
    """
    if not is_plant_care_query(query):
        return [{"message": "Query routed away: not related to plant care."}]

    try:
        result = _get_genai().models.embed_content(
            model="gemini-embedding-001",
            contents=query,
        )
        vector = result.embeddings[0].values
    except Exception as e:
        return [{"error": f"Embedding failed: {e}"}]

    pipeline = [
        {
            "$vectorSearch": {
                "index": "care_knowledge_vector_idx",
                "path": "embedding",
                "queryVector": vector,
                "numCandidates": 50,
                "limit": 3,
            }
        },
        {
            "$project": {
                "_id": 0,
                "plant": 1,
                "topic": 1,
                "text": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]

    try:
        results = list(_garden_db()["care_knowledge"].aggregate(pipeline))
        return results if results else [{"message": "No relevant passages found."}]
    except Exception as e:
        return [{"error": str(e), "hint": "Run seed_knowledge.py then create the Atlas Vector Search index."}]


_WMO_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "icy fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "slight rain", 63: "rain", 65: "heavy rain",
    71: "slight snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "violent rain showers", 95: "thunderstorm",
}


async def get_weather(location: str) -> dict:
    """Get current weather for a location (city name, e.g. 'Toronto' or 'Seattle').

    Uses Open-Meteo (free, no API key). Returns temperature, humidity,
    precipitation, wind speed, and a text description.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            # Step 1: geocode location name → lat/lon
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location, "count": 1, "language": "en", "format": "json"},
            )
            geo.raise_for_status()
            results = geo.json().get("results")
            # Fallback: if "City, State" format not found, retry with just the city name
            if not results and "," in location:
                city_only = location.split(",")[0].strip()
                geo2 = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": city_only, "count": 1, "language": "en", "format": "json"},
                )
                results = geo2.json().get("results")
            if not results:
                return {"error": f"Location '{location}' not found"}

            place = results[0]
            lat, lon = place["latitude"], place["longitude"]

            # Step 2: fetch current weather
            wx = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": ",".join([
                        "temperature_2m", "relative_humidity_2m",
                        "apparent_temperature", "precipitation",
                        "weather_code", "cloud_cover", "wind_speed_10m",
                    ]),
                    "wind_speed_unit": "ms",
                    "timezone": "auto",
                },
            )
            wx.raise_for_status()
            cur = wx.json()["current"]

            code = cur.get("weather_code", 0)
            return {
                "location": place["name"],
                "country": place.get("country", ""),
                "temp_c": cur["temperature_2m"],
                "feels_like_c": cur["apparent_temperature"],
                "humidity_pct": cur["relative_humidity_2m"],
                "description": _WMO_CODES.get(code, f"weather code {code}"),
                "wind_speed_ms": cur["wind_speed_10m"],
                "precipitation_mm": cur["precipitation"],
                "clouds_pct": cur["cloud_cover"],
            }
        except httpx.HTTPStatusError as e:
            return {"error": f"Weather API error {e.response.status_code}", "location": location}
        except Exception as e:
            return {"error": str(e), "location": location}


async def get_plant_care(plant_name: str) -> dict:
    """Look up care requirements for a plant species using the Perenual plant database.

    Returns watering frequency, sunlight needs, care level, and a care guide summary.
    """
    key = os.getenv("PERENUAL_API_KEY", "")
    if not key:
        return {"error": "PERENUAL_API_KEY not configured", "plant": plant_name}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(
                "https://perenual.com/api/species-list",
                params={"key": key, "q": plant_name, "page": 1},
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                return {"error": f"No results for '{plant_name}'", "plant": plant_name}

            sp = data[0]

            # Try to fetch care guide for the first result
            care_sections: dict = {}
            try:
                cg = await client.get(
                    "https://perenual.com/api/care-guide-list",
                    params={"key": key, "species_id": sp["id"]},
                )
                if cg.status_code == 200:
                    guides = cg.json().get("data", [])
                    if guides:
                        care_sections = {
                            s["type"]: s["description"]
                            for s in guides[0].get("section", [])
                        }
            except Exception:
                pass

            return {
                "common_name": sp.get("common_name") or plant_name,
                "scientific_name": sp.get("scientific_name", []),
                "watering": sp.get("watering", "unknown"),
                "sunlight": sp.get("sunlight", []),
                "care_level": sp.get("care_level", "unknown"),
                "cycle": sp.get("cycle", "unknown"),
                "indoor": sp.get("indoor", False),
                "care_guide": care_sections,
            }
        except httpx.HTTPStatusError as e:
            return {"error": f"Perenual API error {e.response.status_code}", "plant": plant_name}
        except Exception as e:
            return {"error": str(e), "plant": plant_name}


def read_sensors(plant_id: str = "default") -> dict:
    """Read the latest sensor data for a plant: soil moisture (%), soil temperature (°C), and light level (%).

    Values are generated by a time-of-day physics model with realistic noise.
    Always call this tool instead of guessing sensor values.
    """
    now = datetime.now()
    h = now.hour + now.minute / 60.0

    # Light: sinusoidal sun curve, zero outside 6 AM – 7 PM
    if 6.0 <= h <= 19.0:
        raw_light = 100.0 * math.sin(math.pi * (h - 6.0) / 13.0)
    else:
        raw_light = 0.0
    light = round(max(0.0, min(100.0, raw_light + random.gauss(0, 4))), 1)

    # Soil moisture decreases under light/heat, slow night recovery
    moisture = round(max(10.0, min(95.0, 60.0 - light * 0.18 + random.gauss(0, 5))), 1)

    # Soil temperature lags air temp by ~2 h (peaks around 2 PM)
    soil_temp = 16.0 + 9.0 * math.sin(math.pi * max(0.0, h - 8.0) / 14.0)
    soil_temp = round(max(5.0, min(40.0, soil_temp + random.gauss(0, 1))), 1)

    return {
        "plant_id": plant_id,
        "timestamp": now.isoformat(timespec="seconds"),
        "soil_moisture_pct": moisture,
        "soil_temp_c": soil_temp,
        "light_level_pct": light,
        "sensor_battery_pct": random.randint(74, 99),
    }


_CAMERA_OBSERVATIONS = [
    "Plants look healthy with good leaf colour.",
    "Slight yellowing on lower leaves — possible nitrogen deficiency.",
    "Soil surface appears dry; consider watering soon.",
    "New growth visible — plants are actively growing.",
    "Spotted a few aphids on leaf undersides; monitor closely.",
    "Leaves look wilted — check soil moisture and temperature.",
    "Mulch layer is intact; moisture retention looks good.",
]


def control_smart_home(device: str, action: str, duration_minutes: int = 10) -> dict:
    """Control a smart garden device or request a camera snapshot.

    device: 'irrigation_zone_A', 'irrigation_zone_B', 'camera', or 'soil_sensor'
    action: 'on' | 'off' | 'status' | 'snapshot'
    duration_minutes: how long to run irrigation (only used when action='on')

    Call this when the user asks to water their garden, stop watering, check device
    status, or take a photo of the garden.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if device not in _device_state:
        available = ", ".join(_device_state)
        return {"error": f"Unknown device '{device}'. Available: {available}"}

    if action == "status":
        return {"device": device, "state": _device_state[device]}

    if action == "on" and "irrigation" in device:
        _device_state[device]["status"] = "running"
        _device_state[device]["last_run"] = now
        return {
            "device": device,
            "status": "started",
            "duration_minutes": duration_minutes,
            "started_at": now,
            "message": f"Irrigation {device} running for {duration_minutes} min.",
        }

    if action == "off" and "irrigation" in device:
        _device_state[device]["status"] = "off"
        return {
            "device": device,
            "status": "stopped",
            "stopped_at": now,
            "message": f"Irrigation {device} stopped.",
        }

    if action == "snapshot" and device == "camera":
        return {
            "device": "camera",
            "timestamp": now,
            "observation": random.choice(_CAMERA_OBSERVATIONS),
            "image_url": "simulated://garden_snapshot.jpg",
        }

    return {"error": f"Action '{action}' is not supported for device '{device}'."}
