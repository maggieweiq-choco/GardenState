#!/usr/bin/env python3
"""
Populate the care_knowledge collection with plant care documents + embeddings.

Run once from the project root:
    python -m garden_agent.seed_knowledge

After running, create an Atlas Vector Search index using the JSON printed at the end.
Atlas UI path: Database → Browse Collections → garden.care_knowledge
              → Search Indexes → Create Search Index → JSON Editor
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=False)
sys.path.insert(0, str(Path(__file__).parent.parent))

import pymongo
from google import genai

DOCS = [
    # Tomatoes
    {"plant": "tomato", "topic": "watering",
     "text": "Tomatoes need consistent moisture — about 1–2 inches of water per week. "
             "Water deeply and infrequently to encourage deep root growth. Irregular "
             "watering causes blossom-end rot and fruit cracking. Always water at the "
             "base; wet foliage promotes fungal disease like early blight."},
    {"plant": "tomato", "topic": "sunlight & soil",
     "text": "Tomatoes require at least 6–8 hours of direct sunlight daily. They thrive "
             "in well-drained, slightly acidic soil (pH 6.0–6.8) rich in organic matter. "
             "Use a balanced fertiliser at planting, then switch to a low-nitrogen, "
             "high-phosphorus feed once flowering begins."},
    {"plant": "tomato", "topic": "pests & disease",
     "text": "Common tomato pests: aphids, whiteflies, hornworms, and spider mites. "
             "Common diseases: early blight (brown spots with rings), late blight (dark "
             "water-soaked lesions), and fusarium wilt (yellowing from the bottom up). "
             "Remove infected leaves immediately; neem oil spray controls most soft-bodied pests."},

    # Roses
    {"plant": "rose", "topic": "watering",
     "text": "Roses need about 1 inch of water per week, more in hot weather. "
             "Water deeply at the base to reach the root zone. Avoid overhead watering "
             "to prevent black spot and powdery mildew. Mulch around the base to retain "
             "moisture and regulate soil temperature."},
    {"plant": "rose", "topic": "pruning & feeding",
     "text": "Prune roses in early spring when forsythia blooms. Remove dead wood, "
             "crossing branches, and thin canes. Feed with a rose-specific fertiliser "
             "every 4–6 weeks during the growing season. Deadhead spent blooms regularly "
             "to encourage continuous flowering."},

    # Basil
    {"plant": "basil", "topic": "watering & sunlight",
     "text": "Basil loves heat and full sun — at least 6 hours daily. Water when the "
             "top inch of soil is dry; basil wilts quickly but recovers fast. Avoid "
             "cold water or watering at night. Keep it away from cold drafts; temperatures "
             "below 10 °C damage leaves."},
    {"plant": "basil", "topic": "harvesting",
     "text": "Harvest basil by pinching off the top sets of leaves above a leaf node. "
             "This encourages bushy growth. Pinch off flower buds as soon as they appear "
             "to keep the plant producing flavorful leaves. Regular harvesting prevents "
             "bolting and extends the growing season."},

    # Lettuce
    {"plant": "lettuce", "topic": "watering & temperature",
     "text": "Lettuce prefers cool weather (7–24 °C) and bolts in heat above 27 °C. "
             "Keep soil consistently moist but not waterlogged. Water shallowly and "
             "frequently since lettuce has shallow roots. Shade cloth helps in warm "
             "climates; harvest outer leaves to extend production."},

    # Peppers
    {"plant": "pepper", "topic": "care",
     "text": "Peppers need full sun (8+ hours) and warm soil (above 18 °C). Water "
             "consistently — about 1 inch per week — but allow soil to dry slightly "
             "between waterings. Over-watering causes root rot. Use a balanced fertiliser "
             "at planting; switch to a low-nitrogen feed once flowering starts. "
             "Stake taller plants to support heavy fruit loads."},

    # Succulents
    {"plant": "succulent", "topic": "watering",
     "text": "The most common succulent killer is over-watering. Water thoroughly then "
             "let the soil dry completely — typically every 2–3 weeks in summer, once a "
             "month in winter. Use well-draining cactus or succulent mix. Signs of "
             "over-watering: mushy, translucent leaves. Under-watering: shrivelled, "
             "wrinkled leaves."},
    {"plant": "succulent", "topic": "sunlight",
     "text": "Most succulents need 4–6 hours of bright, indirect light. Direct midday "
             "sun can scorch leaves, causing brown patches. Leggy, stretched-out growth "
             "(etiolation) means insufficient light. Rotate pots regularly for even growth."},

    # Lavender
    {"plant": "lavender", "topic": "watering & soil",
     "text": "Lavender is drought-tolerant once established. Water young plants weekly "
             "for the first season; mature plants only need water every 2–3 weeks in "
             "summer. It requires very well-drained, slightly alkaline soil (pH 6.5–7.5). "
             "Overwatering and heavy clay soils cause root rot."},
    {"plant": "lavender", "topic": "pruning",
     "text": "Prune lavender twice a year: lightly after the first bloom in early summer "
             "and more heavily in late summer after the second flush. Never cut back into "
             "old woody stems — this prevents regrowth. Annual pruning keeps plants bushy "
             "and extends their lifespan."},

    # Cucumbers
    {"plant": "cucumber", "topic": "watering",
     "text": "Cucumbers are 96% water and need consistent, deep watering — about "
             "1 inch per week. Inconsistent moisture causes bitter fruit and blossom "
             "drop. Mulch heavily to retain moisture. Water at the base to prevent "
             "powdery mildew. Reduce watering once fruit is setting to concentrate flavour."},

    # Strawberries
    {"plant": "strawberry", "topic": "care",
     "text": "Strawberries need 6–8 hours of sunlight and consistently moist, well-drained "
             "soil. Water 1–1.5 inches per week; increase during fruiting. Remove runners "
             "unless propagating. Mulch with straw to protect fruit from soil contact and "
             "retain moisture. Feed with a potassium-rich fertiliser to promote fruiting."},

    # Mint
    {"plant": "mint", "topic": "growing",
     "text": "Mint spreads aggressively via underground runners — always grow in containers "
             "or use a root barrier to contain it. It prefers partial shade and consistently "
             "moist soil. Harvest frequently to prevent flowering and maintain leaf quality. "
             "Divide and repot every 2–3 years to prevent pot-binding."},

    # General pest management
    {"plant": "general", "topic": "pest management",
     "text": "Integrated pest management: (1) Monitor plants weekly for early signs. "
             "(2) Remove pests by hand when populations are small. (3) Use insecticidal "
             "soap or neem oil for soft-bodied pests (aphids, whiteflies, spider mites). "
             "(4) Introduce beneficial insects like ladybirds and lacewings. "
             "(5) Use row covers for severe infestations. Avoid broad-spectrum pesticides "
             "that kill beneficial insects."},

    # General composting
    {"plant": "general", "topic": "composting & soil health",
     "text": "Healthy soil is the foundation of a healthy garden. Add 2–3 inches of "
             "compost to beds each spring. Compost improves drainage in clay soils and "
             "water retention in sandy soils. A simple NPK test guides fertiliser choices. "
             "Avoid tilling excessively — it disrupts soil structure and beneficial "
             "microorganism networks."},
]


def main() -> None:
    print(f"Connecting to MongoDB...")
    mongo = pymongo.MongoClient(os.environ["MDB_MCP_CONNECTION_STRING"])
    col = mongo["garden"]["care_knowledge"]

    print(f"Generating embeddings for {len(DOCS)} documents via gemini-embedding-001...")
    client = genai.Client()
    texts = [d["text"] for d in DOCS]

    # Batch embed (API supports up to 100 texts per call)
    response = client.models.embed_content(model="gemini-embedding-001", contents=texts)

    docs_to_insert = [{**doc, "embedding": emb.values}
                      for doc, emb in zip(DOCS, response.embeddings)]

    col.delete_many({})
    col.insert_many(docs_to_insert)
    print(f"Inserted {len(docs_to_insert)} documents into garden.care_knowledge")

    dims = len(response.embeddings[0].values)
    print(f"\nEmbedding dimensions: {dims}")
    print("\n" + "="*60)
    print("NEXT STEP: Create the Atlas Vector Search index")
    print("="*60)
    print("Atlas UI: Database → Browse Collections → garden.care_knowledge")
    print("         → Search Indexes → Create Search Index → JSON Editor")
    print("\nPaste this definition:")
    print(f"""{{
  "name": "care_knowledge_vector_idx",
  "type": "vectorSearch",
  "fields": [{{
    "type": "vector",
    "path": "embedding",
    "numDimensions": {dims},
    "similarity": "cosine"
  }}]
}}""")
    print("\nThe index builds in ~1 minute. After that, search_care_knowledge() is live.")


def seed_if_empty() -> None:
    """Called at server startup: seeds care_knowledge only when the collection is empty.
    Safe to call on every restart — skips immediately if docs already exist."""
    try:
        mongo = pymongo.MongoClient(os.environ["MDB_MCP_CONNECTION_STRING"])
        col = mongo["garden"]["care_knowledge"]
        if col.count_documents({}) > 0:
            return   # already seeded
        print("[seed_knowledge] care_knowledge is empty — seeding now...")
        client = genai.Client()
        texts = [d["text"] for d in DOCS]
        response = client.models.embed_content(model="gemini-embedding-001", contents=texts)
        docs = [{**doc, "embedding": emb.values} for doc, emb in zip(DOCS, response.embeddings)]
        col.insert_many(docs)
        print(f"[seed_knowledge] Inserted {len(docs)} documents.")
    except Exception as e:
        print(f"[seed_knowledge] Warning: could not auto-seed care_knowledge: {e}")


if __name__ == "__main__":
    main()
