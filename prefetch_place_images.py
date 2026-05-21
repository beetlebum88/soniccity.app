import argparse
import time

import app


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prefetch and cache hero thumbnails for indexed places/cities/countries.",
    )
    parser.add_argument(
        "--kind",
        default="place",
        choices=["place", "city", "country", "all"],
        help="What to prefetch: place images, city hero images, country hero images, or all.",
    )
    parser.add_argument(
        "--lang",
        default="en",
        choices=list(app.SUPPORTED_LANGS.keys()),
        help="UI language (controls Wikipedia language + fallback behavior).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.15,
        help="Delay between requests (seconds). Use 0 to disable.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force refetch attempt even if a previous '.missing' marker exists (adds ?force=1).",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Only prefetch items that are missing an image in the local cache (faster).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of places (0 = all).",
    )
    args = parser.parse_args()

    client = app.app.test_client()

    def run_urls(urls):
        total = len(urls)
        if total == 0:
            return (0, 0, 0)

        ok = 0
        noimg = 0
        fail = 0
        fail_samples = []
        start = time.time()

        for i, url in enumerate(urls, start=1):
            resp = client.get(url)
            if resp.status_code == 200 and (
                not str(resp.content_type or "").startswith("image/svg")
                or resp.headers.get("X-Audia-Generated-Image") == "1"
            ):
                ok += 1
            elif resp.status_code == 200:
                noimg += 1
            else:
                fail += 1
                if len(fail_samples) < 15:
                    fail_samples.append((resp.status_code, url))

            if i % 50 == 0 or i == total:
                elapsed = max(0.001, time.time() - start)
                rate = i / elapsed
                print(f"{i}/{total} cached • ok={ok} • noimg={noimg} • fail={fail} • {rate:.1f}/s")

            if args.sleep:
                time.sleep(max(0.0, float(args.sleep)))

        if fail_samples:
            print("Sample failures:")
            for code, u in fail_samples:
                print(f"  - {code} {u}")
        return (total, ok, noimg, fail)

    def build_urls(kind: str):
        def with_force(u: str) -> str:
            return f"{u}?force=1" if args.force else u

        def cached_place_missing(country_slug: str, city_slug: str, place_slug: str) -> bool:
            wiki_lang = app.SUPPORTED_LANGS[args.lang]["wiki"]
            cache_dir_req = app.PLACE_IMAGE_CACHE_DIR / wiki_lang / country_slug / city_slug
            cache_dir_en = app.PLACE_IMAGE_CACHE_DIR / "en" / country_slug / city_slug
            # Cached image exists either in requested language cache
            # or in English fallback cache.
            for cache_dir in (cache_dir_req, cache_dir_en):
                for ext in (".jpg", ".png", ".webp", ".gif", ".svg"):
                    fp = cache_dir / f"{place_slug}{ext}"
                    if fp.exists() and fp.stat().st_size > 0:
                        return False
            # Missing marker exists or no image cached.
            return True

        if kind == "place":
            keys = list(app.PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG.keys())
            keys.sort()
            if args.limit and args.limit > 0:
                keys = keys[: args.limit]
            if args.only_missing:
                keys = [(c, ci, p) for (c, ci, p) in keys if cached_place_missing(c, ci, p)]
            return [with_force(f"/media/place/{args.lang}/{c}/{ci}/{p}") for (c, ci, p) in keys]

        if kind == "city":
            keys = list(app.CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.keys())
            keys.sort()
            if args.limit and args.limit > 0:
                keys = keys[: args.limit]
            if args.only_missing:
                wiki_lang = app.SUPPORTED_LANGS[args.lang]["wiki"]
                def city_missing(c: str, ci: str) -> bool:
                    for cache_dir in (app.CITY_IMAGE_CACHE_DIR / wiki_lang / c, app.CITY_IMAGE_CACHE_DIR / "en" / c):
                        for ext in (".jpg", ".png", ".webp", ".gif", ".svg"):
                            fp = cache_dir / f"{ci}{ext}"
                            if fp.exists() and fp.stat().st_size > 0:
                                return False
                    return True
                keys = [(c, ci) for (c, ci) in keys if city_missing(c, ci)]
            return [with_force(f"/media/city/{args.lang}/{c}/{ci}") for (c, ci) in keys]

        if kind == "country":
            slugs = list(app.INDEXED_CITIES_BY_COUNTRYSLUG.keys())
            slugs.sort()
            if args.limit and args.limit > 0:
                slugs = slugs[: args.limit]
            return [with_force(f"/media/country/{args.lang}/{c}") for c in slugs]

        if kind == "all":
            return (
                build_urls("country")
                + build_urls("city")
                + build_urls("place")
            )

        return []

    urls = build_urls(str(args.kind))
    if not urls:
        print("No items to prefetch. Check your data files and flags.")
        return 1

    total, ok, noimg, fail = run_urls(urls)
    if total == 0:
        print("No items to prefetch.")
        return 1
    if fail == 0 and noimg == 0:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
