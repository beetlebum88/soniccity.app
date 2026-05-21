import unittest

from services.city_detection import clear_nearby_city_cache, detect_nearby_cities


COUNTRIES = {
    "es": {"name": "Spain", "code": "es", "slug": "spain", "flagUrl": "/flag/es.svg"},
    "fr": {"name": "France", "code": "fr", "slug": "france", "flagUrl": "/flag/fr.svg"},
}


def resolve_country(value):
    return COUNTRIES.get(str(value or "").lower())


def slugify(value):
    return str(value or "").strip().lower().replace(" ", "-")


def city_url(lang, country_slug, city_slug):
    return f"/{lang}/{country_slug}/{city_slug}"


def country_display_name(country, lang):
    return country["name"]


def city_display_name(city, lang):
    return city["name"]


class CityDetectionTests(unittest.TestCase):
    def setUp(self):
        clear_nearby_city_cache()

    def detect(self, cities, lat=39.4699, lon=-0.3763):
        return detect_nearby_cities(
            cities=cities,
            lat=lat,
            lon=lon,
            radius_km=20,
            limit=10,
            lang="en",
            resolve_country=resolve_country,
            slugify=slugify,
            city_url=city_url,
            country_display_name_for_lang=country_display_name,
            city_display_name_for_lang=city_display_name,
        )

    def test_filters_to_supported_cities_over_10000_population(self):
        rows = [
            {"id": "small", "name": "Small Town", "country": "es", "lat": 39.47, "lon": -0.37, "population": 10000},
            {"id": "city", "name": "Valencia", "country": "es", "lat": 39.4699, "lon": -0.3763, "population": 789000},
            {"id": "unsupported", "name": "Elsewhere", "country": "xx", "lat": 39.47, "lon": -0.37, "population": 900000},
        ]

        found = self.detect(rows)

        self.assertEqual([item["id"] for item in found], ["city"])
        self.assertEqual(found[0]["countrySlug"], "spain")
        self.assertEqual(found[0]["citySlug"], "valencia")

    def test_sorts_by_distance_and_applies_limit(self):
        rows = [
            {"id": "far", "name": "Far City", "country": "es", "lat": 39.58, "lon": -0.48, "population": 50000},
            {"id": "near", "name": "Near City", "country": "es", "lat": 39.47, "lon": -0.37, "population": 50000},
        ]

        found = self.detect(rows)

        self.assertEqual([item["id"] for item in found], ["near", "far"])


if __name__ == "__main__":
    unittest.main()
