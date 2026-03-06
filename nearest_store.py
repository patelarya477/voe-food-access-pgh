"""
nearest_store.py

Helper functions for geographic distance and nearest-place lookup.

This file does NOT call any APIs.
It works entirely with local data (places.csv).
"""

import math
import pandas as pd


def haversineMiles(pointA, pointB):
    """
    Computes straight-line distance (in miles) between two points.

    pointA and pointB are tuples:
        (latitude, longitude)
    """
    lat1, lng1 = pointA
    lat2, lng2 = pointB

    # Radius of the Earth in miles
    earthRadiusMiles = 3958.7613

    # Convert degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    deltaPhi = math.radians(lat2 - lat1)
    deltaLambda = math.radians(lng2 - lng1)

    # Haversine formula
    a = (
        math.sin(deltaPhi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2)
        * math.sin(deltaLambda / 2) ** 2
    )

    c = 2 * math.asin(math.sqrt(a))
    return earthRadiusMiles * c


def loadPlaces(csvPath):
    """
    Loads places from a CSV file and returns a list of dictionaries.

    Each place dict contains keys like:
        name, address, lat, lng, category, etc.
    """
    dataFrame = pd.read_csv(csvPath)
    return dataFrame.to_dict(orient="records")


def findNearest(userLatLng, places):
    """
    Finds the nearest place to the user's location using haversine distance.

    userLatLng: (lat, lng)
    places: list of place dictionaries

    Returns:
        a dictionary representing the nearest place,
        with an added key 'straightMiles'
    """
    nearestPlace = None
    nearestDistance = float("inf")

    for place in places:
        placeLatLng = (float(place["lat"]), float(place["lng"]))
        distance = haversineMiles(userLatLng, placeLatLng)

        if distance < nearestDistance:
            nearestDistance = distance
            nearestPlace = place

    if nearestPlace is None:
        raise RuntimeError("No places found. Did you build places.csv?")

    # Make a copy so we don't mutate the original list
    nearestPlace = dict(nearestPlace)
    nearestPlace["straightMiles"] = nearestDistance

    return nearestPlace
