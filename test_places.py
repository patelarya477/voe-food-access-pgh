"""
test_places.py

Quick sanity check that the Google Maps API key works.
Lists grocery stores near a fixed Pittsburgh location.
"""

import os
from dotenv import load_dotenv
import googlemaps

load_dotenv()
API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "Missing GOOGLE_MAPS_API_KEY. "
        "Check your .env file."
    )

gmaps = googlemaps.Client(key=API_KEY)

# Fixed test point used only to verify API functionality
origin = (40.4406, -79.9959)

results = gmaps.places_nearby(
    location=origin,
    radius=5000,
    type="grocery_or_supermarket"
)

places = results.get("results", [])

print(f"Found {len(places)} grocery stores:")
for p in places[:5]:
    print("-", p.get("name"), "|", p.get("vicinity"))

