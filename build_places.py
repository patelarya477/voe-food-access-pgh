import os
import time
import googlemaps
import pandas as pd
from dotenv import load_dotenv

outputCsvPath = "data/processed/places.csv"

searches = [
    {"category": "grocery", "query": "grocery store in Pittsburgh, PA"},
    {"category": "restaurant", "query": "restaurant in Pittsburgh, PA"},
]

maxPagesPerSearch = 3  # each page ~20 results


def getGoogleMapsClient():
    load_dotenv()
    apiKey = os.getenv("GOOGLE_MAPS_API_KEY")
    if not apiKey:
        raise RuntimeError("Missing GOOGLE_MAPS_API_KEY in .env")
    return googlemaps.Client(key=apiKey)


def textSearchAllPages(gmapsClient, query, category, maxPages):
    allResults = []

    response = gmapsClient.places(query=query)
    page = 1

    while True:
        results = response.get("results", [])
        for place in results:
            place["category"] = category
            allResults.append(place)

        nextToken = response.get("next_page_token")
        if (not nextToken) or (page >= maxPages):
            break

        time.sleep(2)  # token needs time to activate
        response = gmapsClient.places(query=query, page_token=nextToken)
        page += 1

    return allResults


def normalizePlaces(rawPlaces):
    rows = []

    for place in rawPlaces:
        placeId = place.get("place_id")
        name = place.get("name", "")
        address = place.get("formatted_address", "")
        types = ",".join(place.get("types", []))

        location = place.get("geometry", {}).get("location", {})
        lat = location.get("lat")
        lng = location.get("lng")

        if (not placeId) or (lat is None) or (lng is None):
            continue

        rows.append(
            {
                "placeId": placeId,
                "name": name,
                "address": address,
                "lat": float(lat),
                "lng": float(lng),
                "types": types,
                "category": place.get("category", ""),
            }
        )

    return rows


def main():
    os.makedirs("data/processed", exist_ok=True)

    gmapsClient = getGoogleMapsClient()

    allRawPlaces = []
    for s in searches:
        print(f"Searching: {s['query']}")
        batch = textSearchAllPages(
            gmapsClient,
            s["query"],
            s["category"],
            maxPagesPerSearch,
        )
        print(f"  got {len(batch)} results")
        allRawPlaces.extend(batch)

    df = pd.DataFrame(normalizePlaces(allRawPlaces))
    df = df.drop_duplicates(subset=["placeId"]).reset_index(drop=True)

    df.to_csv(outputCsvPath, index=False)
    print(f"\nSaved {len(df)} unique places to {outputCsvPath}")


if __name__ == "__main__":
    main()
