"""
buildFoodAccessLayer.py

Goal:
- Read U.S. census tract shapes (from a zipped shapefile)
- Keep ONLY Allegheny County tracts
- Read USDA Food Access Research Atlas data (Excel)
- Add a LILA (low-income + low-access) indicator to each tract
- Output a GeoJSON you can overlay on a Folium map
"""

import json
import zipfile
from pathlib import Path

import pandas as pd
import shapefile  # pyshp


alleghenyPrefix = "42003"  # PA (42) + Allegheny County (003)

tractsZipPath = Path("data/raw/cb_2020_us_tract_500k.zip")
faraExcelPath = Path("data/raw/FoodAccessResearchAtlasData2019.xlsx")

outputGeojsonPath = Path("data/processed/allegheny_food_access.geojson")


def unzipTractShapefile(zipPath, outputFolder):
    """
    Unzips the tract shapefile zip into outputFolder.
    Returns the path to the first .shp file found.
    """
    outputFolder.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zipPath, "r") as zipFile:
        zipFile.extractall(outputFolder)

    shpFiles = list(outputFolder.glob("*.shp"))
    if len(shpFiles) == 0:
        raise FileNotFoundError("No .shp file found after unzipping tract data.")

    # Usually there is only one .shp file in this dataset
    return shpFiles[0]


def loadLilaLookup(excelPath):
    """
    Loads the USDA Food Access Research Atlas Excel file,
    finds a LILATracts* column, and builds a lookup dict:
        lookup[geoid] = 0 or 1
    """
    df = pd.read_excel(excelPath, sheet_name="Food Access Research Atlas")

    # CensusTract in the Excel sometimes looks like 42003010300.0
    # We convert to string, strip trailing .0, and zero-pad to 11 digits.
    df["CensusTract"] = (
        df["CensusTract"]
        .astype("string")
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(11)
    )

    # Find a column that starts with "LILATracts"
    lilaColumns = []
    for col in df.columns:
        if str(col).lower().startswith("lilatracts"):
            lilaColumns.append(col)

    if len(lilaColumns) == 0:
        raise KeyError("Could not find any column starting with 'LILATracts' in the USDA file.")

    lilaColumnName = lilaColumns[0]

    # Build lookup: geoid -> int (0/1)
    lilaLookup = {}
    for geoid, lilaValue in zip(df["CensusTract"], df[lilaColumnName]):
        if pd.isna(lilaValue):
            lilaValue = 0
        lilaLookup[str(geoid)] = int(lilaValue)

    return lilaLookup, lilaColumnName


def buildAlleghenyGeojson(shpPath, lilaLookup):
    """
    Reads the shapefile and returns a GeoJSON dict for only
    Allegheny County tracts. Each feature includes:
        properties: GEOID, LILA
    """
    reader = shapefile.Reader(str(shpPath))

    # pyshp stores fields in reader.fields; first entry is a deletion flag, so skip it
    fieldNames = [f[0] for f in reader.fields[1:]]

    if "GEOID" not in fieldNames:
        raise KeyError(f"Expected a GEOID field in shapefile. Found: {fieldNames}")

    geoidIndex = fieldNames.index("GEOID")

    features = []

    for shapeRecord in reader.iterShapeRecords():
        geoid = str(shapeRecord.record[geoidIndex])

        # Keep only Allegheny County tracts
        if not geoid.startswith(alleghenyPrefix):
            continue

        # LILA is 1 or 0 depending on USDA file, default 0 if missing
        lilaValue = int(lilaLookup.get(geoid, 0))

        feature = {
            "type": "Feature",
            "geometry": shapeRecord.shape.__geo_interface__,
            "properties": {
                "GEOID": geoid,
                "LILA": lilaValue
            }
        }
        features.append(feature)

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    return geojson


def main():
    # Make sure output folder exists
    outputGeojsonPath.parent.mkdir(parents=True, exist_ok=True)

    # 1) Unzip tract shapefile
    tractsFolder = Path("data/raw/tracts_shp")
    shpPath = unzipTractShapefile(tractsZipPath, tractsFolder)

    # 2) Load USDA data and make a lookup dict
    lilaLookup, usedLilaColumn = loadLilaLookup(faraExcelPath)
    print(f"Using LILA column: {usedLilaColumn}")

    # 3) Build GeoJSON for Allegheny County only
    geojson = buildAlleghenyGeojson(shpPath, lilaLookup)

    # 4) Save GeoJSON to file
    outputGeojsonPath.write_text(json.dumps(geojson))
    print(f"Saved {outputGeojsonPath} with {len(geojson['features'])} tracts")


if __name__ == "__main__":
    main()
