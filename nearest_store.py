"""
nearest_store.py

Find the nearest grocery store to a fixed origin point in Pittsburgh.
We pick the nearest store by straight-line distance first, then use the
Distance Matrix API for driving distance/time to that store.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import googlemaps
from dotenv import load_dotenv

ORIGIN: Tuple[float, float] = (40.4406, -79.9959)  # Downtown Pittsburgh
SEARCH_RADIUS_METERS: int = 5000
PLACE_TYPE: str = "grocery_or_supermarket"
TRAVEL_MODE: str = "driving"


@dataclass(frozen=True)
class PlaceCandidate:
    name: str
    address: str
    lat: float
    lng: float
    straight_line_miles: float


def get_api_key() -> str:
    load_dotenv()
    key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not key:
        raise RuntimeError("Missing GOOGLE_MAPS_API_KEY. Check your .env file.")
    return key


def haversine_miles(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Straight-line distance (miles) between two latitude/longitude points."""
    lat1, lon1 = a
    lat2, lon2 = b
    r = 3958.7613  # Earth radius in miles

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    h = (math.sin(dphi / 2) ** 2) + math.cos(phi1) * math.cos(phi2) * (math.sin(dlambda / 2) ** 2)
    return 2 * r * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def fetch_places(
    gmaps: googlemaps.Client,
    origin: Tuple[float, float],
    radius_meters: int,
    place_type: str,
) -> List[Dict[str, Any]]:
    resp = gmaps.places_nearby(location=origin, radius=radius_meters, type=place_type)
    return resp.get("results", [])


def to_candidates(origin: Tuple[float, float], places: List[Dict[str, Any]]) -> List[PlaceCandidate]:
    candidates: List[PlaceCandidate] = []
    for p in places:
        loc = p.get("geometry", {}).get("location", {})
        lat = loc.get("lat")
        lng = loc.get("lng")
        if lat is None or lng is None:
            continue

        candidates.append(
            PlaceCandidate(
                name=p.get("name", "Unknown"),
                address=p.get("vicinity", "Unknown address"),
                lat=float(lat),
                lng=float(lng),
                straight_line_miles=haversine_miles(origin, (float(lat), float(lng))),
            )
        )
    return candidates


def driving_metrics(
    gmaps: googlemaps.Client,
    origin: Tuple[float, float],
    dest: Tuple[float, float],
    mode: str,
) -> Tuple[Optional[str], Optional[str]]:
    dm = gmaps.distance_matrix(origins=[origin], destinations=[dest], mode=mode)
    element = dm.get("rows", [{}])[0].get("elements", [{}])[0]
    if element.get("status") != "OK":
        return None, None
    return element["distance"]["text"], element["duration"]["text"]


def main() -> None:
    gmaps = googlemaps.Client(key=get_api_key())

    places = fetch_places(gmaps, ORIGIN, SEARCH_RADIUS_METERS, PLACE_TYPE)
    candidates = to_candidates(ORIGIN, places)
    if not candidates:
        raise RuntimeError("No grocery stores found. Try increasing SEARCH_RADIUS_METERS.")

    # Pick nearest cheaply via straight-line; call Distance Matrix only once.
    nearest = min(candidates, key=lambda c: c.straight_line_miles)

    print("Nearest (straight-line):")
    print(f"- {nearest.name} | {nearest.address}")
    print(f"- ~{nearest.straight_line_miles:.2f} miles away")

    dist_text, time_text = driving_metrics(gmaps, ORIGIN, (nearest.lat, nearest.lng), TRAVEL_MODE)
    print("Travel (driving):")
    if dist_text and time_text:
        print(f"- distance: {dist_text}")
        print(f"- time: {time_text}")
    else:
        print("- (Driving metrics unavailable)")


if __name__ == "__main__":
    main()

