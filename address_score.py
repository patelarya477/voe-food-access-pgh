"""
address_score.py

Computes a local "Food Access Vulnerability Score" (1–10) around a user location.

Key idea:
- Use your cached places.csv (restaurants + groceries) for counts within a radius
- Use tract-level LILA (0/1) from allegheny_food_access.geojson as a neighborhood vulnerability proxy
- Make the score transparent: return a breakdown of components

This is NOT a perfect measure of food insecurity.
It is an explainable local access proxy you can improve later.
"""

import json
import math


# -------------------------
# Distance + geometry helpers
# -------------------------

def haversineMiles(pointA, pointB):
    lat1, lng1 = pointA
    lat2, lng2 = pointB

    earthRadiusMiles = 3958.7613

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    deltaPhi = math.radians(lat2 - lat1)
    deltaLambda = math.radians(lng2 - lng1)

    a = (
        math.sin(deltaPhi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(deltaLambda / 2) ** 2
    )

    c = 2 * math.asin(math.sqrt(a))
    return earthRadiusMiles * c


def bboxCentroid(geometry):
    """
    Approx centroid using bbox midpoint.
    Works for Polygon / MultiPolygon and is good enough for neighborhood-level comparisons.
    """
    coords = []

    def collect(x):
        # If x looks like [lon, lat]
        if isinstance(x, (list, tuple)) and len(x) == 2 and isinstance(x[0], (int, float)):
            lon, lat = x
            coords.append((lat, lon))
        elif isinstance(x, (list, tuple)):
            for y in x:
                collect(y)

    collect(geometry.get("coordinates", []))

    if len(coords) == 0:
        return (40.44, -79.99)

    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    return ((min(lats) + max(lats)) / 2, (min(lngs) + max(lngs)) / 2)


# -------------------------
# Tract loading + LILA lookup
# -------------------------

def loadTractFeatures(geojsonPath):
    """
    Loads the Allegheny tract GeoJSON and returns a list of tract features.
    Each feature must have properties.GEOID and properties.LILA (0/1).
    """
    with open(geojsonPath, "r") as f:
        tractData = json.load(f)
    return tractData.get("features", [])


def getNearestTractLila(userLatLng, tractFeatures):
    """
    Approx: assign the user to the nearest tract centroid and return that tract's LILA (0/1).

    This is not exact point-in-polygon, but it’s easy to explain and good enough for MVP.
    """
    bestLila = 0
    bestDistance = None

    for feature in tractFeatures:
        center = bboxCentroid(feature.get("geometry", {}))
        d = haversineMiles(userLatLng, center)

        if bestDistance is None or d < bestDistance:
            bestDistance = d
            bestLila = int(feature.get("properties", {}).get("LILA", 0))

    return bestLila


# -------------------------
# Place categorization
# -------------------------

fastFoodChainKeywords = [
    "mcdonald",
    "wendy",
    "burger king",
    "taco bell",
    "kfc",
    "popeyes",
    "chipotle",
    "subway",
    "domino",
    "domino's",
    "pizza hut",
    "papa john",
    "dunkin",
    "starbucks",
    "five guys",
    "shake shack",
    "panera",
    "chick-fil-a",
    "chick fil a",
    "arbys",
    "arby's",
]

restaurantTypeHints = {
    "restaurant",
    "cafe",
    "bakery",
    "meal_takeaway",
    "meal_delivery",
}

groceryTypeHints = {
    "grocery_or_supermarket",
    "supermarket",
}

convenienceTypeHints = {
    "convenience_store",
}


def categorizePlace(place):
    """
    Returns a dict of boolean tags for a place.

    We keep categories simple and explainable:
    - grocery (based on Google 'types')
    - convenience (based on Google 'types')
    - restaurant (based on Google 'types')
    - fastFood (restaurant AND name matches a chain keyword list)
    """
    name = str(place.get("name", "")).lower()
    typesString = str(place.get("types", "")).lower()

    # types in your CSV are stored like "restaurant,food,point_of_interest,..."
    typesSet = set([t.strip() for t in typesString.split(",") if t.strip() != ""])

    isGrocery = len(typesSet.intersection(groceryTypeHints)) > 0
    isConvenience = len(typesSet.intersection(convenienceTypeHints)) > 0
    isRestaurant = len(typesSet.intersection(restaurantTypeHints)) > 0

    isFastFood = False
    if isRestaurant:
        for kw in fastFoodChainKeywords:
            if kw in name:
                isFastFood = True
                break

    return {
        "isGrocery": isGrocery,
        "isConvenience": isConvenience,
        "isRestaurant": isRestaurant,
        "isFastFood": isFastFood,
    }


# -------------------------
# Radius summarization
# -------------------------

def getPlacesWithinRadius(userLatLng, places, radiusMiles):
    inRadius = []

    for place in places:
        placeLatLng = (float(place["lat"]), float(place["lng"]))
        d = haversineMiles(userLatLng, placeLatLng)

        if d <= radiusMiles:
            copyPlace = dict(place)
            copyPlace["straightMiles"] = d
            inRadius.append(copyPlace)

    return inRadius


def summarizeRadius(userLatLng, places, radiusMiles):
    """
    Counts key categories inside radius and returns a summary dict.
    """
    inRadius = getPlacesWithinRadius(userLatLng, places, radiusMiles)

    groceryCount = 0
    convenienceCount = 0
    restaurantCount = 0
    fastFoodCount = 0

    for place in inRadius:
        tags = categorizePlace(place)

        if tags["isGrocery"]:
            groceryCount += 1
        if tags["isConvenience"]:
            convenienceCount += 1
        if tags["isRestaurant"]:
            restaurantCount += 1
        if tags["isFastFood"]:
            fastFoodCount += 1

    fastFoodShare = 0.0
    if restaurantCount > 0:
        fastFoodShare = fastFoodCount / restaurantCount

    return {
        "radiusMiles": radiusMiles,
        "placesInRadius": inRadius,
        "groceryCount": groceryCount,
        "convenienceCount": convenienceCount,
        "restaurantCount": restaurantCount,
        "fastFoodCount": fastFoodCount,
        "fastFoodShare": fastFoodShare,
    }


# -------------------------
# Scoring
# -------------------------

def clamp01(x):
    return max(0.0, min(1.0, float(x)))


def computeLocalVulnerabilityScore(summary, tractLila):
    """
    Builds a 0–1 score from interpretable components, then converts to 1–10.

    Components (0=good, 1=bad):
    - groceryPenalty: fewer groceries => worse
    - fastFoodShare: higher share => worse
    - tractPenalty: LILA => worse (0/1)

    Weights are transparent and easy to adjust later.
    """
    groceryCount = summary["groceryCount"]
    fastFoodShare = summary["fastFoodShare"]

    # If you have 3+ groceries within the radius, penalty becomes 0.
    groceryPenalty = 1.0 - min(groceryCount / 3.0, 1.0)

    tractPenalty = 1.0 if int(tractLila) == 1 else 0.0

    wGrocery = 0.45
    wFastFood = 0.30
    wTract = 0.25

    score0to1 = (
        wGrocery * groceryPenalty
        + wFastFood * clamp01(fastFoodShare)
        + wTract * tractPenalty
    )
    score0to1 = clamp01(score0to1)

    score1to10 = int(round(1 + 9 * score0to1))

    breakdown = {
        "groceryPenalty": groceryPenalty,
        "fastFoodShare": fastFoodShare,
        "tractLila": int(tractLila),
        "weights": {"groceryPenalty": wGrocery, "fastFoodShare": wFastFood, "tractLila": wTract},
        "score0to1": score0to1,
        "score1to10": score1to10,
    }

    return score1to10, breakdown


def scoreAddress(userLatLng, places, tractFeatures, radiusMiles):
    """
    Main entry point:
    - summarize places within radius
    - get tract LILA near user
    - compute score + breakdown
    """
    summary = summarizeRadius(userLatLng, places, radiusMiles)
    tractLila = getNearestTractLila(userLatLng, tractFeatures)

    score1to10, breakdown = computeLocalVulnerabilityScore(summary, tractLila)

    return {
        "score1to10": score1to10,
        "breakdown": breakdown,
        "summary": summary,
    }
