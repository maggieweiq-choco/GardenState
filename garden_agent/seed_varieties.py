"""Seed extra variety documents into garden.plants_knowledge.

The bulk of plants_knowledge (~2K docs) was loaded from the variety catalog
export ("variety_<id>" string _id, flat spec fields). This script adds the
varieties the demo needs that the catalog lacks — Phalaenopsis (moth orchid)
and the cool-season lawn grasses used in the Northeast US — in the SAME schema,
so get_variety_specifications() finds them exactly like catalog entries.

Idempotent: upserts by _id, safe to run repeatedly.

Run once from the repo root (reads garden_agent/.env):
    python -m garden_agent.seed_varieties
"""

import os
from pathlib import Path

import pymongo
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

# New ids start at 5001 — far above the catalog range (~1972) so they can
# never collide with a future catalog re-import.
NEW_DOCS = [
    {
        "_id": "variety_5001",
        "id": 5001,
        "category": "orchid",
        "name": "Phalaenopsis Orchid (Moth Orchid)",
        "slug": "phalaenopsis-orchid",
        "scientific_name": "Phalaenopsis spp.",
        "description": "The most popular houseplant orchid. Epiphytic — grows on bark, "
                       "not in soil. Long-lasting arching sprays of flowers in white, "
                       "pink, purple, or yellow; each bloom flush lasts 2-3 months. "
                       "Tolerant of normal home conditions, making it the best beginner orchid.",
        "days_to_harvest": None,
        "days_to_germination": "Not grown from seed at home",
        "plant_height": "1-3 feet including flower spike",
        "plant_spacing": "Single specimen per pot",
        "sun_requirement": "Bright indirect light — east or north windowsill; no direct afternoon sun",
        "water_requirement": "Low-moderate — weekly in summer, every 10-14 days in winter; let medium dry slightly",
        "soil_type": "Coarse orchid bark or sphagnum moss — never regular potting soil",
        "soil_ph": "5.5-6.5",
        "growing_difficulty": "Easy",
        "is_container_friendly": True,
        "growing_season": "Year-round indoors; typically blooms winter-spring",
        "sowing_method": "Buy established plants; propagate from keikis (plantlets on the "
                         "flower spike). Rebloom: cut spent spike above the 2nd-3rd node and "
                         "give 2-4 weeks of cooler nights (13-18 C).",
        "color": "White, pink, purple, yellow, or spotted blooms over dark green strap leaves",
        "size": "Blooms 5-12 cm across, 6-15 per spike",
        "shape": "Rosette of broad leaves with arching flower spikes",
        "flavor_profile": "N/A",
        "culinary_uses": "N/A — ornamental only",
        "is_heirloom": False,
    },
    {
        "_id": "variety_5002",
        "id": 5002,
        "category": "grass",
        "name": "Kentucky Bluegrass",
        "slug": "kentucky-bluegrass",
        "scientific_name": "Poa pratensis",
        "description": "The classic dense, dark-green cool-season lawn grass of the "
                       "Northeast US. Spreads by rhizomes, so it self-repairs bare spots "
                       "and knits into a thick carpet. Slower to establish than ryegrass "
                       "but the most attractive cool-season turf.",
        "days_to_harvest": None,
        "days_to_germination": "14-30",
        "plant_height": "Mow at 2.5-3.5 inches",
        "plant_spacing": "Broadcast 2-3 lbs per 1000 sq ft",
        "sun_requirement": "Full sun to light shade (6+ hours best)",
        "water_requirement": "Moderate-high — 1 inch/week; goes dormant in drought and recovers",
        "soil_type": "Fertile, well-drained loam",
        "soil_ph": "6.0-7.0",
        "growing_difficulty": "Moderate",
        "is_container_friendly": False,
        "growing_season": "Cool season perennial — peak growth spring and autumn",
        "sowing_method": "Seed in early autumn (best) or early spring onto prepared, "
                         "raked soil; keep surface moist 3-4 weeks. Slow to germinate — "
                         "often blended with ryegrass for quick cover.",
        "color": "Dark blue-green fine blades",
        "size": "Fine-medium texture",
        "shape": "Dense spreading sod via rhizomes",
        "flavor_profile": "N/A",
        "culinary_uses": "N/A",
        "is_heirloom": False,
    },
    {
        "_id": "variety_5003",
        "id": 5003,
        "category": "grass",
        "name": "Tall Fescue",
        "slug": "tall-fescue",
        "scientific_name": "Festuca arundinacea",
        "description": "The workhorse cool-season lawn grass: deep roots make it the most "
                       "drought- and heat-tolerant choice for Northeast and transition-zone "
                       "lawns. Modern turf-type cultivars are fine-bladed and dense. "
                       "Bunch-forming, so thin areas need overseeding.",
        "days_to_harvest": None,
        "days_to_germination": "7-14",
        "plant_height": "Mow at 3-4 inches",
        "plant_spacing": "Broadcast 6-8 lbs per 1000 sq ft",
        "sun_requirement": "Full sun to moderate shade",
        "water_requirement": "Low-moderate — most drought-tolerant cool-season turf",
        "soil_type": "Adaptable; tolerates clay and poor soils",
        "soil_ph": "5.5-7.5",
        "growing_difficulty": "Easy",
        "is_container_friendly": False,
        "growing_season": "Cool season perennial — peak growth spring and autumn",
        "sowing_method": "Seed early autumn or spring; germinates in 1-2 weeks. Overseed "
                         "annually in September to keep the stand dense (bunch grass — no "
                         "self-repair).",
        "color": "Medium-dark green",
        "size": "Medium-coarse blades (fine in turf-type cultivars)",
        "shape": "Upright bunch grass with very deep roots",
        "flavor_profile": "N/A",
        "culinary_uses": "N/A",
        "is_heirloom": False,
    },
    {
        "_id": "variety_5004",
        "id": 5004,
        "category": "grass",
        "name": "Perennial Ryegrass",
        "slug": "perennial-ryegrass",
        "scientific_name": "Lolium perenne",
        "description": "The fastest-establishing cool-season lawn grass — germinates in "
                       "under a week, making it the standard choice for overseeding and "
                       "quick repairs. Shiny fine blades and excellent wear tolerance; "
                       "usually blended with bluegrass and fescue in Northeast mixes.",
        "days_to_harvest": None,
        "days_to_germination": "5-10",
        "plant_height": "Mow at 2.5-3 inches",
        "plant_spacing": "Broadcast 5-9 lbs per 1000 sq ft",
        "sun_requirement": "Full sun to light shade",
        "water_requirement": "Moderate — 1 inch/week; less drought-tolerant than fescue",
        "soil_type": "Fertile, well-drained soil",
        "soil_ph": "6.0-7.0",
        "growing_difficulty": "Very easy",
        "is_container_friendly": False,
        "growing_season": "Cool season perennial — peak growth spring and autumn",
        "sowing_method": "Seed any time soil is above 10 C; fastest germination of all "
                         "lawn grasses. Ideal for overseeding thin patches in September.",
        "color": "Bright glossy green",
        "size": "Fine-medium texture",
        "shape": "Upright bunch grass",
        "flavor_profile": "N/A",
        "culinary_uses": "N/A",
        "is_heirloom": False,
    },
]


def main() -> None:
    mongo = pymongo.MongoClient(os.environ["MDB_MCP_CONNECTION_STRING"])
    col = mongo["garden"]["plants_knowledge"]

    # Schema guard: mirror the field set of a real catalog doc so our docs
    # always match the live schema, even if the catalog adds fields later.
    sample = col.find_one({"_id": {"$regex": "^variety_"}}) or {}
    extra_fields = set(sample) - set(NEW_DOCS[0]) if sample else set()

    for doc in NEW_DOCS:
        for f in extra_fields:
            doc.setdefault(f, None)
        col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        print(f"upserted {doc['_id']}: {doc['name']}")

    if extra_fields:
        print(f"note: filled catalog-only fields with None: {sorted(extra_fields)}")

    # Verify retrieval exactly the way the agent tool queries
    for probe in ("phalaenopsis", "kentucky bluegrass", "tall fescue", "ryegrass"):
        n = col.count_documents({"$or": [
            {"name": {"$regex": probe, "$options": "i"}},
            {"scientific_name": {"$regex": probe, "$options": "i"}},
        ]})
        print(f"probe '{probe}': {n} doc(s)")


if __name__ == "__main__":
    main()
