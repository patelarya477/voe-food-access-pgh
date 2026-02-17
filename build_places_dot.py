# build_places_dot.py
# ---------------------------------------------
# Builds an Allegheny County "exhaustive-ish" places dataset
# using Google Places Nearby Search + dot/grid method.
#
# Output:
#   data/processed/places_all.csv
#
# Notes:
# - Uses "type=" when available (supermarket, restaurant, etc.)
# - Uses "keyword=" when Google doesn't have a clean type (food bank, farmers market)
# - Deduplicates by placeId
# ---------------------------------------------

import os
import time
import math
import pandas as pd
import googlemaps
from dotenv import load_dotenv

# ---- Configuration ----

OUT_CSV = "data/processed/places_all.csv"

# Allegheny County bounding box (rough, covers the county)
BBOX = {
    "west":  -80.35,
    "east":  -79.65,
    "south":  40.20,
    "north":  40.65,
}

GRID_SPACING_KM = 2.0      # bigger spacing = fewer API calls, less dense coverage
SEARCH_RADIUS_M = 2000     # larger radius = better coverage per point
SLEEP_BETWEEN_POINTS = 0.1 # small pause to be kind to the API
PAGE_TOKEN_SLEEP = 2.2     # token activation delay (required)


# Categories:
# - If "type" exists, Google can filter strongly.
# - If only "keyword" exists, results depend on Google's relevance ranking.
CATEGORIES = {
    "grocery":        {"type": "supermarket"},
    "convenience":    {"type": "convenience_store"},
    "restaurant":     {"type": "restaurant"},
    "fast_food":      {"type": "meal_takeaway"},   # catches a lot of fast food/takeout
    "food_bank":      {"keyword": "food bank"},
    "farmers_market": {"keyword": "farmers market"},
}


# ---- Environment Setup ----

load_dotenv()
GMAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if not GMAPS_KEY:
    raise RuntimeError("Missing GOOGLE_MAPS_API_KEY in .env")

gmaps = googlemaps.Client(key=GMAPS_KEY)


# ---- Helper Functions ----

def kmToDegLat(km: float) -> float:
    return km / 111.0


def kmToDegLng(km: float, lat: float) -> float:
    return km / (111.0 * math.cos(math.radians(lat)))


def generateGridPoints(bbox: dict, spacingKm: float) -> list:
    """
    Generate grid points across bounding box.
    """
    points = []
    lat = bbox["south"]

    while lat <= bbox["north"]:
        stepLng = kmToDegLng(spacingKm, lat)
        lng = bbox["west"]

        while lng <= bbox["east"]:
            points.append((lat, lng))
            lng += stepLng

        lat += kmToDegLat(spacingKm)

    return points


def fetchNearby(lat: float, lng: float, categoryDef: dict) -> list:
    """
    Fetch nearby places for one category at one grid point.
    """
    params = {
        "location": (lat, lng),
        "radius": SEARCH_RADIUS_M,
    }

    # Use type if available
    if "type" in categoryDef:
        params["type"] = categoryDef["type"]

    # Use keyword if available
    if "keyword" in categoryDef:
        params["keyword"] = categoryDef["keyword"]

    results = []
    response = gmaps.places_nearby(**params)

    while True:
        results.extend(response.get("results", []))

        nextToken = response.get("next_page_token")
        if not nextToken:
            break

        time.sleep(PAGE_TOKEN_SLEEP)
        response = gmaps.places_nearby(page_token=nextToken)

    return results


def normalizeTypes(typesList) -> str:
    if not typesList:
        return ""
    return ",".join(typesList)


def placeToRow(place: dict, category: str) -> dict:
    """
    Convert Google Place result to a CSV row.
    """
    loc = place["geometry"]["location"]
    return {
        "placeId": place.get("place_id"),
        "name": place.get("name"),
        "address": place.get("vicinity"),
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "types": normalizeTypes(place.get("types", [])),
        "category": category,
        "businessStatus": place.get("business_status"),
        "rating": place.get("rating"),
        "userRatingsTotal": place.get("user_ratings_total"),
    }


# ---- Main Pipeline ----

def main():
    os.makedirs("data/processed", exist_ok=True)

    gridPoints = generateGridPoints(BBOX, GRID_SPACING_KM)
    print(f"Generated {len(gridPoints)} grid points")
    print(f"Categories: {list(CATEGORIES.keys())}")

    # placeId -> row dict
    # NOTE: a place can belong to multiple categories, so we store categories as a set-like string
    seen = {}

    for i, (lat, lng) in enumerate(gridPoints, start=1):
        print(f"\n[{i}/{len(gridPoints)}] Grid point ({lat:.5f}, {lng:.5f})")

        for category, categoryDef in CATEGORIES.items():
            places = fetchNearby(lat, lng, categoryDef)

            for place in places:
                placeId = place.get("place_id")
                if not placeId:
                    continue

                if placeId not in seen:
                    seen[placeId] = placeToRow(place, category)
                else:
                    # Merge categories (so one place can be both restaurant + meal_takeaway, etc.)
                    existing = seen[placeId]
                    existingCats = set((existing.get("category") or "").split(",")) if existing.get("category") else set()
                    existingCats.add(category)
                    existing["category"] = ",".join(sorted([c for c in existingCats if c]))

        time.sleep(SLEEP_BETWEEN_POINTS)

    df = pd.DataFrame(seen.values())
    df.to_csv(OUT_CSV, index=False)
    print(f"\nSaved {len(df)} unique places to {OUT_CSV}")


if __name__ == "__main__":
    main()
