import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ZIP_PATH = ROOT / "data" / "cities5000.zip"
OUT_PATH = ROOT / "cities.json"

# GeoNames cities5000.txt columns (readme.txt):
# 0 geonameid, 1 name, 2 asciiname, 4 latitude, 5 longitude, 8 country code, 14 population
IDX_ID = 0
IDX_NAME = 1
IDX_ASCII = 2
IDX_LAT = 4
IDX_LON = 5
IDX_COUNTRY = 8
IDX_POP = 14

def main():
    if not ZIP_PATH.exists():
        raise SystemExit(f"Missing file: {ZIP_PATH}")

    cities = []

    with zipfile.ZipFile(ZIP_PATH, "r") as z:
        txt_name = None
        for n in z.namelist():
            if n.endswith(".txt"):
                txt_name = n
                break
        if not txt_name:
            raise SystemExit("No .txt found inside zip")

        with z.open(txt_name) as f:
            for raw in f:
                line = raw.decode("utf-8", errors="ignore").rstrip("\n")
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 15:
                    continue

                try:
                    pop = int(parts[IDX_POP] or 0)
                    if pop < 3000:
                        continue
                    cities.append({
                        "id": parts[IDX_ID],
                        "name": parts[IDX_NAME],
                        "country": parts[IDX_COUNTRY],
                        "lat": float(parts[IDX_LAT]),
                        "lon": float(parts[IDX_LON]),
                        "population": pop,
                        # wikiTitle: use ASCII name (usually best for EN)
                        "wikiTitle": parts[IDX_ASCII] or parts[IDX_NAME],
                    })
                except Exception:
                    continue

    cities.sort(key=lambda x: x.get("population", 0), reverse=True)
    OUT_PATH.write_text(json.dumps(cities, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(cities)} cities -> {OUT_PATH}")

if __name__ == "__main__":
    main()