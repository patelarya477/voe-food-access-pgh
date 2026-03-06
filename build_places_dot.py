import argparse
import math
import os
import random
import time
from typing import Dict, List, Tuple

import googlemaps
import pandas as pd
from dotenv import load_dotenv

OUT_CSV = "data/processed/places_all.csv"
DEFAULT_BBOX = {
    "west": -80.35,
    "east": -79.65,
    "south": 40.20,
    "north": 40.65,
}
DEFAULT_GRID_SPACING_KM = 2.0
DEFAULT_SEARCH_RADIUS_M = 2000
DEFAULT_SLEEP_BETWEEN_POINTS = 0.1
DEFAULT_PAGE_TOKEN_SLEEP = 2.2
DEFAULT_MAX_RETRIES = 4
DEFAULT_RETRY_BASE_SLEEP = 1.5

# If "type" exists, Google can filter strongly.
# If only "keyword" exists, results depend on Google's relevance ranking.
CATEGORIES = {
    "grocery": {"type": "supermarket"},
    "convenience": {"type": "convenience_store"},
    "restaurant": {"type": "restaurant"},
    "fast_food": {"type": "meal_takeaway"},
    "food_bank": {"keyword": "food bank"},
    "farmers_market": {"keyword": "farmers market"},
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an Allegheny County places dataset using Google Places Nearby Search."
    )
    parser.add_argument("--out-csv", default=OUT_CSV, help="Output CSV file path.")
    parser.add_argument(
        "--grid-spacing-km",
        type=float,
        default=DEFAULT_GRID_SPACING_KM,
        help="Grid spacing in km; larger values reduce API calls.",
    )
    parser.add_argument(
        "--search-radius-m",
        type=int,
        default=DEFAULT_SEARCH_RADIUS_M,
        help="Nearby search radius in meters.",
    )
    parser.add_argument(
        "--sleep-between-points",
        type=float,
        default=DEFAULT_SLEEP_BETWEEN_POINTS,
        help="Delay between grid points, in seconds.",
    )
    parser.add_argument(
        "--page-token-sleep",
        type=float,
        default=DEFAULT_PAGE_TOKEN_SLEEP,
        help="Delay before fetching paginated results, in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help="Max retries for API calls before failing.",
    )
    parser.add_argument(
        "--retry-base-sleep",
        type=float,
        default=DEFAULT_RETRY_BASE_SLEEP,
        help="Base backoff delay in seconds for API retries.",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.grid_spacing_km <= 0:
        raise ValueError("--grid-spacing-km must be > 0")
    if args.search_radius_m <= 0:
        raise ValueError("--search-radius-m must be > 0")
    if args.sleep_between_points < 0:
        raise ValueError("--sleep-between-points must be >= 0")
    if args.page_token_sleep <= 0:
        raise ValueError("--page-token-sleep must be > 0")
    if args.max_retries < 0:
        raise ValueError("--max-retries must be >= 0")
    if args.retry_base_sleep <= 0:
        raise ValueError("--retry-base-sleep must be > 0")


def km_to_deg_lat(km: float) -> float:
    return km / 111.0


def km_to_deg_lng(km: float, lat: float) -> float:
    return km / (111.0 * math.cos(math.radians(lat)))


def generate_grid_points(bbox: Dict[str, float], spacing_km: float) -> List[Tuple[float, float]]:
    points: List[Tuple[float, float]] = []
    lat = bbox["south"]

    while lat <= bbox["north"]:
        step_lng = km_to_deg_lng(spacing_km, lat)
        lng = bbox["west"]

        while lng <= bbox["east"]:
            points.append((lat, lng))
            lng += step_lng

        lat += km_to_deg_lat(spacing_km)

    return points


def places_nearby_with_retry(
    client: googlemaps.Client,
    max_retries: int,
    retry_base_sleep: float,
    **kwargs,
) -> dict:
    for attempt in range(max_retries + 1):
        try:
            return client.places_nearby(**kwargs)
        except Exception as exc:
            if attempt >= max_retries:
                raise RuntimeError(
                    f"Google Places request failed after {max_retries + 1} attempts: {exc}"
                ) from exc
            backoff = retry_base_sleep * (2**attempt) + random.uniform(0, 0.4)
            print(
                f"Request failed ({exc}). Retrying in {backoff:.2f}s "
                f"[attempt {attempt + 1}/{max_retries}]"
            )
            time.sleep(backoff)


def fetch_nearby(
    client: googlemaps.Client,
    lat: float,
    lng: float,
    category_def: Dict[str, str],
    radius_m: int,
    page_token_sleep: float,
    max_retries: int,
    retry_base_sleep: float,
) -> List[dict]:
    params = {
        "location": (lat, lng),
        "radius": radius_m,
    }

    if "type" in category_def:
        params["type"] = category_def["type"]
    if "keyword" in category_def:
        params["keyword"] = category_def["keyword"]

    results: List[dict] = []
    response = places_nearby_with_retry(
        client,
        max_retries=max_retries,
        retry_base_sleep=retry_base_sleep,
        **params,
    )

    while True:
        results.extend(response.get("results", []))
        next_token = response.get("next_page_token")
        if not next_token:
            break

        time.sleep(page_token_sleep)
        response = places_nearby_with_retry(
            client,
            max_retries=max_retries,
            retry_base_sleep=retry_base_sleep,
            page_token=next_token,
        )

    return results


def normalize_types(types_list: List[str]) -> str:
    return ",".join(types_list) if types_list else ""


def place_to_row(place: dict, category: str) -> dict:
    loc = place["geometry"]["location"]
    return {
        "placeId": place.get("place_id"),
        "name": place.get("name"),
        "address": place.get("vicinity"),
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
        "types": normalize_types(place.get("types", [])),
        "category": category,
        "businessStatus": place.get("business_status"),
        "rating": place.get("rating"),
        "userRatingsTotal": place.get("user_ratings_total"),
    }


def merge_category(existing_csv_categories: str, new_category: str) -> str:
    existing = set(existing_csv_categories.split(",")) if existing_csv_categories else set()
    existing.add(new_category)
    return ",".join(sorted(cat for cat in existing if cat))


def main() -> None:
    args = build_arg_parser().parse_args()
    validate_args(args)

    load_dotenv()
    gmaps_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not gmaps_key:
        raise RuntimeError("Missing GOOGLE_MAPS_API_KEY in .env")

    client = googlemaps.Client(key=gmaps_key)
    out_dir = os.path.dirname(args.out_csv) or "."
    os.makedirs(out_dir, exist_ok=True)

    grid_points = generate_grid_points(DEFAULT_BBOX, args.grid_spacing_km)
    print(f"Generated {len(grid_points)} grid points")
    print(f"Categories: {list(CATEGORIES.keys())}")

    seen: Dict[str, dict] = {}
    total_place_hits = 0

    for i, (lat, lng) in enumerate(grid_points, start=1):
        print(f"[{i}/{len(grid_points)}] Grid point ({lat:.5f}, {lng:.5f})")
        for category, category_def in CATEGORIES.items():
            places = fetch_nearby(
                client=client,
                lat=lat,
                lng=lng,
                category_def=category_def,
                radius_m=args.search_radius_m,
                page_token_sleep=args.page_token_sleep,
                max_retries=args.max_retries,
                retry_base_sleep=args.retry_base_sleep,
            )
            total_place_hits += len(places)

            for place in places:
                place_id = place.get("place_id")
                if not place_id:
                    continue
                if place_id not in seen:
                    seen[place_id] = place_to_row(place, category)
                else:
                    seen[place_id]["category"] = merge_category(
                        seen[place_id].get("category", ""),
                        category,
                    )

        time.sleep(args.sleep_between_points)

    df = pd.DataFrame(seen.values()).sort_values(
        by=["name", "placeId"],
        na_position="last",
    )
    df.to_csv(args.out_csv, index=False)

    print(f"Saved {len(df)} unique places to {args.out_csv}")
    print(f"Raw place hits scanned (pre-dedup): {total_place_hits}")


if __name__ == "__main__":
    main()
