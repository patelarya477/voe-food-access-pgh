import os
import folium
import googlemaps
from dotenv import load_dotenv
from folium.plugins import MarkerCluster
from address_score import loadTractFeatures, scoreAddress


from nearest_store import loadPlaces, haversineMiles
tractGeojsonPath = "data/processed/allegheny_food_access.geojson"
scoreRadiusMiles = 1.0

placesCsvPath = "data/processed/places.csv"
outputHtmlPath = "userNearestPlaceMap.html"


def getGoogleMapsClient():
    load_dotenv()
    apiKey = os.getenv("GOOGLE_MAPS_API_KEY")
    if not apiKey:
        raise RuntimeError("Missing GOOGLE_MAPS_API_KEY in .env")
    return googlemaps.Client(key=apiKey)


def geocodeAddress(gmapsClient, address):
    results = gmapsClient.geocode(address)
    if not results:
        raise RuntimeError("Geocoding failed. Try a more specific address.")
    location = results[0]["geometry"]["location"]
    return float(location["lat"]), float(location["lng"])


def filterPlaces(places, mode):
    # mode: "restaurant" | "grocery" | "both"
    if mode == "both":
        return places
    return [p for p in places if p.get("category") == mode]


def findNearestN(userLatLng, places, n):
    scored = []
    for place in places:
        placeLatLng = (float(place["lat"]), float(place["lng"]))
        d = haversineMiles(userLatLng, placeLatLng)
        scored.append((d, place))

    scored.sort(key=lambda x: x[0])

    nearest = []
    for d, place in scored[:n]:
        copyPlace = dict(place)
        copyPlace["straightMiles"] = d
        nearest.append(copyPlace)

    return nearest


def buildMap(userLatLng, restaurants, groceries, nearestList, scoreInfo):
    myMap = folium.Map(location=userLatLng, zoom_start=13)

    # User marker
    folium.Marker(
        location=userLatLng,
        popup="Your location",
        tooltip="Your location",
        icon=folium.Icon(icon="home"),
    ).add_to(myMap)

    # Draw the scoring radius circle
    folium.Circle(
        location=userLatLng,
        radius=scoreInfo["summary"]["radiusMiles"] * 1609.34,
        weight=2,
        fill=False,
        opacity=0.6,
    ).add_to(myMap)

    # Add an on-map summary box
    s = scoreInfo["summary"]
    b = scoreInfo["breakdown"]

    summaryHtml = f"""
    <div style="
        position: fixed;
        top: 20px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 9999;
        background: white;
        padding: 10px 14px;
        border: 2px solid #444;
        border-radius: 10px;
        font-size: 14px;">
    <b>Food Access Vulnerability (within {s['radiusMiles']} mi)</b><br>
    <b>Score:</b> {scoreInfo['score1to10']}/10<br>
    Groceries: {s['groceryCount']}<br>
    Restaurants: {s['restaurantCount']}<br>
    Fast food (chain proxy): {s['fastFoodCount']} ({int(round(100*s['fastFoodShare']))}%)<br>
    LILA tract: {b['tractLila']}
    </div>
    """
    myMap.get_root().html.add_child(folium.Element(summaryHtml))


    # Separate layer groups (toggles)
    restaurantLayer = folium.FeatureGroup(name="Restaurants").add_to(myMap)
    groceryLayer = folium.FeatureGroup(name="Grocery stores").add_to(myMap)

    restaurantCluster = MarkerCluster().add_to(restaurantLayer)
    groceryCluster = MarkerCluster().add_to(groceryLayer)

    # Add restaurant points (blue)
    for place in restaurants:
        placeLatLng = (float(place["lat"]), float(place["lng"]))
        popupText = f"{place.get('name','')}<br>{place.get('address','')}"
        folium.CircleMarker(
            location=placeLatLng,
            radius=4,
            popup=popupText,
            tooltip=place.get("name", ""),
            color="blue",
            fill=True,
            fill_color="blue",
            fill_opacity=0.7,
        ).add_to(restaurantCluster)

    # Add grocery points (green)
    for place in groceries:
        placeLatLng = (float(place["lat"]), float(place["lng"]))
        popupText = f"{place.get('name','')}<br>{place.get('address','')}"
        folium.CircleMarker(
            location=placeLatLng,
            radius=4,
            popup=popupText,
            tooltip=place.get("name", ""),
            color="green",
            fill=True,
            fill_color="green",
            fill_opacity=0.7,
        ).add_to(groceryCluster)

    # Highlight nearest (red star) and draw lines to top N
    for i, place in enumerate(nearestList):
        placeLatLng = (float(place["lat"]), float(place["lng"]))
        label = "Nearest" if i == 0 else f"#{i+1} nearest"

        popupText = (
            f"<b>{label}</b><br>"
            f"{place.get('name','')}<br>"
            f"{place.get('category','')}<br>"
            f"{place.get('address','')}<br>"
            f"Straight-line distance: {place['straightMiles']:.2f} miles"
        )

        folium.Marker(
            location=placeLatLng,
            popup=popupText,
            tooltip=label,
            icon=folium.Icon(color="red", icon="star"),
        ).add_to(myMap)

        folium.PolyLine(locations=[userLatLng, placeLatLng], weight=2).add_to(myMap)

    # Legend (simple HTML overlay)
    legendHtml = """
    <div style="
        position: fixed;
        bottom: 30px;
        left: 30px;
        z-index: 9999;
        background: white;
        padding: 10px;
        border: 2px solid #444;
        border-radius: 8px;
        font-size: 14px;">
      <b>Legend</b><br>
      <span style="color:blue;">●</span> Restaurant<br>
      <span style="color:green;">●</span> Grocery store<br>
      <span style="color:red;">★</span> Nearest options
    </div>
    """
    myMap.get_root().html.add_child(folium.Element(legendHtml))

    folium.LayerControl(collapsed=True).add_to(myMap)
    return myMap


def main():
    if not os.path.exists(placesCsvPath):
        raise RuntimeError("places.csv not found. Run python3 build_places.py first.")

    userAddress = input("Enter an address in Pittsburgh: ").strip()

    print("\nChoose what you want to search:")
    print("1) Restaurants")
    print("2) Grocery stores")
    print("3) Both")
    choice = input("Enter 1/2/3: ").strip()

    if choice == "1":
        mode = "restaurant"
    elif choice == "2":
        mode = "grocery"
    else:
        mode = "both"

    gmapsClient = getGoogleMapsClient()
    userLatLng = geocodeAddress(gmapsClient, userAddress)

    places = loadPlaces(placesCsvPath)
    tractFeatures = loadTractFeatures(tractGeojsonPath)
    scoreInfo = scoreAddress(userLatLng, places, tractFeatures, scoreRadiusMiles)


    restaurants = [p for p in places if p.get("category") == "restaurant"]
    groceries = [p for p in places if p.get("category") == "grocery"]

    filtered = filterPlaces(places, mode)
    nearestList = findNearestN(userLatLng, filtered, 5)

    myMap = buildMap(userLatLng, restaurants, groceries, nearestList, scoreInfo)
    myMap.save(outputHtmlPath)

    print(f"\nSaved map to: {outputHtmlPath}")
    print(f"Top result: {nearestList[0].get('name','')} ({nearestList[0]['straightMiles']:.2f} mi)")


if __name__ == "__main__":
    main()
