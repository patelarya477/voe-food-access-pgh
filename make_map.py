"""
make_map.py

Generate an interactive HTML map showing:
- origin point
- nearest grocery store
- a line between them
- popup with straight-line + driving metrics

Run:
    python make_map.py
Then open:
    open pgh_nearest_grocery_map.html
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Tuple

import folium
import googlemaps
from dotenv import load_dotenv

ORIGIN: Tuple[float, float] = (40.4406, -79.9959)
SEARCH_RADIUS_METERS: int = 5000
PLACE_TYPE: str = "grocery_or_supermarket"
TRAVEL_MODE: str = "driving"
OUTPUT_HTML: str = "pgh_nearest_grocery_map.html"


def get_api_key() -> str:
    load_dotenv()
    key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not key:
        raise RuntimeError("Missing GOOGLE_MAPS_API_KEY. Check your .env file.")
    return key


def haversine_miles(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 3958.7613

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    h = (math.sin(dphi / 2) ** 2) + math.cos(phi1) * math.cos(phi2) * (math.sin(dlambda / 2) ** 2)
    return 2 * r * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def fetch_places(gmaps: googlemaps.Client) -> List[Dict[str, Any]]:
    resp = gmaps.places_nearby(location=ORIGIN, radius=SEARCH_RADIUS_METERS, type=PLACE_TYPE)
    return resp.get("results", [])


def pick_nearest_place(places: List[Dict[str, Any]]) -> Dict[str, Any]:
    best: Optional[Dict[str, Any]] = None
    best_dist = float("inf")

    for p in places:
        loc = p.get("geometry", {}).get("location", {})
        lat = loc.get("lat")
        lng = loc.get("lng")
        if lat is None or lng is None:
            continue

        d = haversine_miles(ORIGIN, (float(lat), float(lng)))
        if d < best_dist:
            best = p
            best_dist = d

    if best is None:
        raise RuntimeError("No valid places found (missing coordinates).")

    best["_straight_line_miles"] = best_dist
    return best


def driving_metrics(
    gmaps: googlemaps.Client, dest: Tuple[float, float]
) -> Tuple[Optional[str], Optional[str]]:
    dm = gmaps.distance_matrix(origins=[ORIGIN], destinations=[dest], mode=TRAVEL_MODE)
    element = dm.get("rows", [{}])[0].get("elements", [{}])[0]
    if element.get("status") != "OK":
        return None, None
    return element["distance"]["text"], element["duration"]["text"]


def main() -> None:
    gmaps = googlemaps.Client(key=get_api_key())

    places = fetch_places(gmaps)
    if not places:
        raise RuntimeError("No grocery stores found. Try increasing SEARCH_RADIUS_METERS.")

    nearest = pick_nearest_place(places)
    name = nearest.get("name", "Nearest grocery store")
    addr = nearest.get("vicinity", "Unknown address")
    loc = nearest.get("geometry", {}).get("location", {})
    dest = (float(loc["lat"]), float(loc["lng"]))
    straight_line = float(nearest["_straight_line_miles"])

    dist_text, time_text = driving_metrics(gmaps, dest)

    # Center map roughly between origin and destination for a nicer view.
    center = ((ORIGIN[0] + dest[0]) / 2, (ORIGIN[1] + dest[1]) / 2)
    m = folium.Map(location=center, zoom_start=14)

    folium.Marker(location=ORIGIN, tooltip="Origin", popup="Origin").add_to(m)

    popup_lines = [
        f"<b>{name}</b>",
        addr,
        f"Straight-line: {straight_line:.2f} miles",
    ]
    if dist_text and time_text:
        popup_lines += [f"Driving distance: {dist_text}", f"Driving time: {time_text}"]

    folium.Marker(
        location=dest,
        tooltip="Nearest grocery store",
        popup="<br>".join(popup_lines),
    ).add_to(m)

    folium.PolyLine(locations=[ORIGIN, dest], weight=5, opacity=0.8).add_to(m)

    m.save(OUTPUT_HTML)
    print(f"Saved map to: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()

