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

    # ── Orchid / Phalaenopsis ──────────────────────────────────────────────────
    {"plant": "orchid", "topic": "watering",
     "text": "Phalaenopsis orchids (moth orchids) should be watered about once a week "
             "in summer and every 10–14 days in winter. Water thoroughly until it runs "
             "freely from the drainage holes, then let the medium dry slightly before "
             "the next watering. Never let roots sit in standing water — root rot is "
             "the number-one orchid killer. Yellow, mushy roots mean overwatering; "
             "silvery-grey, shrivelled roots mean underwatering. Use room-temperature "
             "water; cold tap water shocks tropical roots."},
    {"plant": "orchid", "topic": "light & temperature",
     "text": "Phalaenopsis thrive in bright indirect light — an east- or north-facing "
             "windowsill is ideal. Avoid direct afternoon sun, which scorches leaves. "
             "Ideal daytime temperature: 18–27 °C with a 10–15 °C drop at night to "
             "trigger reflowering. Keep away from cold drafts, heating vents, and "
             "ripening fruit (ethylene gas causes bud drop). Dark green leaves signal "
             "too little light; yellowish leaves signal too much."},
    {"plant": "orchid", "topic": "feeding & repotting",
     "text": "Feed Phalaenopsis with a balanced orchid fertiliser (20-20-20) at "
             "half-strength every 2 weeks during active growth; monthly in winter. "
             "'Weakly, weekly' is the grower's motto. Repot every 1–2 years when roots "
             "escape the pot or the bark medium decomposes. Use fresh orchid bark — "
             "never regular potting soil. After blooms drop, cut the spike 1 cm above "
             "a node for a secondary spike, or to the base to allow a new one next season."},

    # ── Lawn / turf ───────────────────────────────────────────────────────────
    {"plant": "lawn", "topic": "watering",
     "text": "Lawns need about 2.5–4 cm of water per week including rainfall. Water "
             "deeply 2–3 times a week rather than shallow daily watering, which promotes "
             "shallow roots. Water early morning to cut evaporation and fungal risk. "
             "Drought stress signals: grass turns blue-grey, footprints remain visible. "
             "Skip irrigating before forecast heavy rain. Established lawns survive short "
             "droughts by going dormant and recover quickly when rain returns."},
    {"plant": "lawn", "topic": "mowing & fertilising",
     "text": "Follow the one-third rule: never remove more than one-third of the blade "
             "height in a single mow. Cool-season grasses (fescue, bluegrass) at 7–9 cm; "
             "warm-season (bermuda, zoysia) at 2–4 cm. Keep blades sharp to avoid tearing. "
             "Fertilise cool-season lawns in autumn and spring; warm-season in late spring "
             "through summer. Nitrogen-rich (30-0-4) promotes green growth; potassium "
             "strengthens roots before winter. Leave short clippings on the lawn to "
             "return nitrogen naturally."},
    {"plant": "lawn", "topic": "weeds & pests",
     "text": "The best weed defence is a thick, healthy lawn — overseed thin patches "
             "each autumn. Apply pre-emergent herbicide in early spring to block crabgrass "
             "and annual weeds. Spot-treat broadleaf weeds (dandelion, clover) with "
             "selective herbicide. Common pests: grubs (brown patches that lift like "
             "carpet), chinch bugs (hot dry spots), armyworms. Treat grubs with beneficial "
             "nematodes or imidacloprid in late summer when larvae are young."},

    # ── Pothos ────────────────────────────────────────────────────────────────
    {"plant": "pothos", "topic": "care",
     "text": "Pothos (Epipremnum aureum) is one of the most forgiving houseplants. "
             "Water when the top 2–3 cm of soil are dry — typically every 1–2 weeks. "
             "Yellow leaves usually mean overwatering; brown crispy tips mean "
             "underwatering or low humidity. Tolerates low light but grows faster in "
             "bright indirect light. Feed monthly with balanced liquid fertiliser in "
             "spring/summer, skip in winter. Propagates easily in water — cut just "
             "below a node."},

    # ── Monstera ──────────────────────────────────────────────────────────────
    {"plant": "monstera", "topic": "care",
     "text": "Monstera deliciosa prefers bright indirect light but tolerates medium "
             "light. Water when the top 3–5 cm of soil dry out — roughly every 1–2 weeks. "
             "Humidity above 50% is ideal; mist leaves or use a pebble tray. Feed every "
             "2–4 weeks in spring/summer with balanced fertiliser. Brown edges indicate "
             "low humidity or salt build-up; yellowing means overwatering. Support with "
             "a moss pole to encourage larger, fenestrated leaves. Repot every 2 years."},

    # ── Snake plant (Sansevieria) ──────────────────────────────────────────────
    {"plant": "snake plant", "topic": "care",
     "text": "Snake plants (Dracaena trifasciata) are nearly indestructible. Water every "
             "2–4 weeks in summer, monthly in winter — let the soil dry completely between "
             "waterings. Tolerates low light but grows faster in bright indirect light; "
             "avoid prolonged direct sun. Use well-draining mix; never leave in soggy soil. "
             "Feed once or twice a year with balanced fertiliser. Root rot from "
             "overwatering is the only common killer."},

    # ── Fiddle-leaf fig ───────────────────────────────────────────────────────
    {"plant": "fiddle-leaf fig", "topic": "care",
     "text": "Fiddle-leaf figs need bright, consistent indirect light — south- or "
             "east-facing window. They hate being moved; find a spot and leave it. "
             "Water when the top 3–4 cm of soil are dry (roughly every 7–10 days). "
             "Over-watering causes large brown patches; under-watering causes brown "
             "leaf edges. Maintain 30–65% humidity; avoid cold drafts and heating "
             "vents. Feed monthly in spring/summer with high-nitrogen fertiliser. "
             "Leaf drop after moving is normal and temporary."},

    # ── Peace lily ────────────────────────────────────────────────────────────
    {"plant": "peace lily", "topic": "care",
     "text": "Peace lilies thrive in low to medium indirect light — one of few flowering "
             "plants that tolerates shade. Water when leaves just begin to droop slightly "
             "or when the top 3 cm are dry (roughly every 7–10 days). Sensitive to "
             "fluoride — use filtered or rain water if leaf tips brown. Feed every "
             "6 weeks in spring/summer. Dramatic wilting is a watering signal, not "
             "permanent damage; it recovers within hours of watering."},

    # ── Rosemary ──────────────────────────────────────────────────────────────
    {"plant": "rosemary", "topic": "care",
     "text": "Rosemary needs full sun (6+ hours) and excellent drainage — it thrives "
             "where most plants struggle. Water deeply but infrequently; let the soil "
             "dry out between waterings. Over-watering is the most common cause of death. "
             "Use sandy or gritty soil; add perlite to standard potting mix. Feed lightly "
             "in spring — too much nitrogen reduces essential oil concentration. Prune "
             "after flowering to keep bushy; never cut back past green growth into "
             "old woody stems."},

    # ── Thyme ─────────────────────────────────────────────────────────────────
    {"plant": "thyme", "topic": "care",
     "text": "Thyme is drought-tolerant and thrives in full sun with fast-draining soil. "
             "Water sparingly once established — every 10–14 days; soggy soil kills it "
             "quickly. Trim regularly after flowering to encourage new growth and prevent "
             "woodiness. Feed lightly with balanced fertiliser in spring only. Tolerates "
             "light frost; mulch roots before harsh winters. Harvest by cutting stem tips, "
             "leaving at least two-thirds of the plant intact."},

    # ── Blueberry ─────────────────────────────────────────────────────────────
    {"plant": "blueberry", "topic": "care",
     "text": "Blueberries require acidic soil (pH 4.5–5.5) — test and amend with sulphur "
             "if needed. Full sun (8+ hours) and consistent moisture, about 2.5 cm per "
             "week. Mulch with wood chips or pine needles to maintain acidity and "
             "moisture. Plant at least two cultivars within 2 metres for cross-pollination. "
             "Feed with acid-specific fertiliser (ammonium sulphate) in early spring and "
             "after fruit set. Prune out old canes (6+ years) each winter. Net when "
             "berries start to colour."},

    # ── Fruit tree / orchard ──────────────────────────────────────────────────
    {"plant": "fruit tree", "topic": "care",
     "text": "Young fruit trees need 15–20 litres of water per week; established trees "
             "need deep watering every 2–3 weeks in summer. Full sun and good air "
             "circulation prevent fungal disease. Prune in late winter before bud break: "
             "remove crossing branches, water sprouts, and open the centre. Feed with "
             "balanced fertiliser in early spring; avoid high nitrogen after mid-summer. "
             "Thin fruit clusters in early summer — one fruit per 15 cm — for larger "
             "fruit and to prevent biennial bearing."},

    # ── Fern ──────────────────────────────────────────────────────────────────
    {"plant": "fern", "topic": "care",
     "text": "Most ferns prefer indirect light and consistently moist — not waterlogged — "
             "soil. Water when the top 1–2 cm are dry; never let the root ball dry out "
             "completely. High humidity (50–80%) is essential: mist daily or use a "
             "pebble tray. Brown crispy fronds indicate low humidity or underwatering; "
             "yellow fronds usually mean overwatering. Feed monthly with diluted balanced "
             "fertiliser in spring/summer. Remove dead fronds at the base."},

    # ── Hibiscus ──────────────────────────────────────────────────────────────
    {"plant": "hibiscus", "topic": "care",
     "text": "Tropical hibiscus needs full sun (6+ hours) and consistently moist soil — "
             "water when the top 2–3 cm dry out; may need daily watering in containers "
             "during summer heat. Feed every 2 weeks with high-potassium, low-phosphorus "
             "fertiliser to promote blooming. Pinch growing tips in spring for bushier "
             "growth. Bring indoors before temperatures drop below 10 °C. Yellow leaves "
             "with green veins indicate iron chlorosis — treat with chelated iron."},

    # ── Zucchini ──────────────────────────────────────────────────────────────
    {"plant": "zucchini", "topic": "care",
     "text": "Zucchini are heavy feeders needing rich soil and full sun. Water deeply "
             "1–2 times per week (about 2.5 cm total) at the base to avoid powdery "
             "mildew. Feed with balanced fertiliser at planting, then low-nitrogen "
             "high-potassium once flowering starts. Hand-pollinate if few bees are "
             "present. Harvest every 2–3 days at 15–20 cm — leaving oversized fruits "
             "signals the plant to stop producing."},

    # ── General: when to water ─────────────────────────────────────────────────
    {"plant": "general", "topic": "when to water",
     "text": "The finger test: push a finger 3–5 cm into the soil. Dry = water; moist = "
             "wait. Wilting in the morning is a reliable drought signal; afternoon wilt "
             "in heat alone may not require action. Water in the morning so foliage dries "
             "before nightfall, reducing fungal disease. Deep infrequent watering builds "
             "drought-resistant roots; shallow daily watering keeps roots near the surface. "
             "Containers dry out 3–4× faster than beds — check them daily in summer."},

    # ── General: fertilising ───────────────────────────────────────────────────
    {"plant": "general", "topic": "fertilising guide",
     "text": "NPK: Nitrogen (N) drives leafy green growth. Phosphorus (P) supports "
             "roots, flowers, and fruit. Potassium (K) strengthens overall plant health "
             "and stress resistance. Leafy vegetables and lawns: use high-N (e.g. 30-5-5). "
             "Flowering/fruiting plants: balanced or high-K (e.g. 5-10-10). "
             "Over-fertilising causes salt burn (brown leaf edges) and soft, disease-prone "
             "growth. Slow-release granules feed for 3–6 months; liquids act within days. "
             "Always water in fertiliser to avoid root burn."},

    # ── General: seasonal care ─────────────────────────────────────────────────
    {"plant": "general", "topic": "seasonal care",
     "text": "Spring (Mar–May): start seeds 6–8 weeks before last frost; transplant "
             "after frost risk passes; apply pre-emergent weed control. "
             "Summer (Jun–Aug): water early morning; mulch to retain moisture; monitor "
             "pests; harvest regularly. "
             "Autumn (Sep–Nov): harvest root vegetables before hard frost; plant spring "
             "bulbs; cut back perennials; add compost to beds. "
             "Winter (Dec–Feb): protect tender plants with fleece or mulch; reduce "
             "watering for dormant plants; plan next season."},
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
    """Called at server startup: seeds (or re-seeds) care_knowledge when the stored
    document count is less than the current DOCS list — so adding new documents to
    DOCS automatically triggers a fresh seed on the next server restart."""
    try:
        mongo = pymongo.MongoClient(os.environ["MDB_MCP_CONNECTION_STRING"])
        col = mongo["garden"]["care_knowledge"]
        existing = col.count_documents({})
        if existing >= len(DOCS):
            return   # already up-to-date
        print(f"[seed_knowledge] {existing} docs in DB, {len(DOCS)} in DOCS — re-seeding...")
        client = genai.Client()
        texts = [d["text"] for d in DOCS]
        response = client.models.embed_content(model="gemini-embedding-001", contents=texts)
        docs = [{**doc, "embedding": emb.values} for doc, emb in zip(DOCS, response.embeddings)]
        col.delete_many({})
        col.insert_many(docs)
        print(f"[seed_knowledge] Inserted {len(docs)} documents.")
    except Exception as e:
        print(f"[seed_knowledge] Warning: could not auto-seed care_knowledge: {e}")


if __name__ == "__main__":
    main()
