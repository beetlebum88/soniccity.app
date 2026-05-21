import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Tuple

import app as audia_app


ROOT = Path(__file__).resolve().parent
Target = Tuple[str, str, str, str]


def csv_items(value: str) -> List[str]:
    return [x.strip().lower() for x in str(value or "").split(",") if x.strip()]


def target_audio_ready(
    *,
    kind: str,
    country_slug: str,
    city_slug: str,
    place_slug: str,
    audio_version: str,
    langs: List[str],
    genders: List[str],
) -> bool:
    for lang in langs:
        for gender in genders:
            manifest_path = audia_app.audio_manifest_path(
                version=audio_version,
                lang=lang,
                gender=gender,
                country_slug=country_slug,
                city_slug=city_slug,
                place_slug=place_slug if kind == "place" else None,
            )
            if not audia_app.is_siri_audio_manifest(manifest_path):
                return False
    return True


def pick_country_hub_city(country_slug: str) -> str:
    cities = list(audia_app.target_country_cities(country_slug, 1) or [])
    if not cities:
        return ""
    return str(cities[0].get("citySlug") or "")


def collect_country_targets() -> List[Tuple[str]]:
    out: List[Tuple[str]] = []
    excluded = set(getattr(audia_app, "EXCLUDED_COUNTRY_CODES", set()) or set())
    for country_slug, country in sorted(audia_app.COUNTRY_BY_SLUG.items()):
        code = str(country.get("code") or "").strip().lower()
        if country_slug and code not in excluded:
            out.append((country_slug,))
    return out


def collect_targets(mode: str, limit: int) -> List[Tuple[str, str]]:
    targets: List[Tuple[str, str]] = []
    if mode == "all-cities":
        for country_slug, city_slug in sorted(audia_app.CITY_BY_COUNTRYSLUG_CITYSLUG.keys()):
            if country_slug and city_slug:
                targets.append((country_slug, city_slug))
    elif mode == "target-cities":
        for c in audia_app.europe_countries():
            country_slug = str(c.get("slug") or "").strip().lower()
            if not country_slug:
                continue
            for row in audia_app.target_country_cities(country_slug, audia_app.TARGET_CITIES_PER_COUNTRY):
                city_slug = str(row.get("citySlug") or "").strip().lower()
                if city_slug:
                    targets.append((country_slug, city_slug))
    elif mode == "indexed":
        for country_slug, rows in sorted(audia_app.INDEXED_CITIES_BY_COUNTRYSLUG.items()):
            for row in rows:
                city_slug = str(row.get("citySlug") or "").strip().lower()
                if city_slug:
                    targets.append((country_slug, city_slug))
    else:
        for c in audia_app.europe_countries():
            country_slug = str(c.get("slug") or "").strip().lower()
            if not country_slug:
                continue
            city_slug = pick_country_hub_city(country_slug)
            if city_slug:
                targets.append((country_slug, city_slug))

    if limit > 0:
        targets = targets[:limit]
    return targets


def collect_place_targets(
    mode: str,
    city_targets: List[Tuple[str, str]],
    limit: int,
) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    if mode == "all-cities":
        for country_slug, city_slug, place_slug in sorted(audia_app.PLACE_BY_COUNTRYSLUG_CITYSLUG_PLACESLUG.keys()):
            if country_slug and city_slug and place_slug:
                out.append((country_slug, city_slug, place_slug))
    else:
        for country_slug, city_slug in city_targets:
            places = audia_app.CITY_PLACES_BY_COUNTRYSLUG_CITYSLUG.get((country_slug, city_slug), []) or []
            for p in audia_app.dedupe_places(places)[:audia_app.TARGET_PLACES_PER_CITY]:
                place_slug = str(p.get("slug") or "").strip().lower()
                if place_slug:
                    out.append((country_slug, city_slug, place_slug))

    if limit > 0:
        out = out[:limit]
    return out


def target_id(target: Target) -> str:
    kind, country_slug, city_slug, place_slug = target
    if kind == "country":
        return country_slug
    return f"{country_slug}/{city_slug}" + (f"/{place_slug}" if kind == "place" else "")


def lock_file_name(target: Target) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "_", f"{target[0]}--{target_id(target)}".lower()) + ".lock"


def acquire_target_lock(lock_dir: Path, target: Target, stale_minutes: int) -> Path | None:
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / lock_file_name(target)
    if path.exists() and stale_minutes > 0:
        age = time.time() - path.stat().st_mtime
        if age > stale_minutes * 60:
            try:
                path.unlink()
            except OSError:
                pass
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"pid={os.getpid()}\nstarted={int(time.time())}\ntarget={target_id(target)}\n")
    return path


def release_target_lock(path: Path | None) -> None:
    if not path:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def build_generate_cmd(args: argparse.Namespace, target: Target, source_mode: str) -> List[str]:
    kind, country_slug, city_slug, place_slug = target
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "generate_audio_guides.py"),
        "--country-slug",
        country_slug,
        "--city-slug",
        "__country__" if kind == "country" else city_slug,
        "--target-kind",
        kind,
        "--audio-version",
        args.audio_version,
        "--langs",
        args.langs,
        "--genders",
        args.genders,
        "--tts-backend",
        "edge",
        "--edge-profile",
        "siri",
        f"--edge-rate={args.edge_rate}",
        f"--edge-pitch={args.edge_pitch}",
        f"--edge-volume={args.edge_volume}",
        "--edge-concurrency",
        str(int(args.edge_concurrency or 1)),
        "--source-mode",
        source_mode,
        "--chunk-chars",
        str(int(args.chunk_chars)),
        "--sleep",
        "0",
    ]
    if source_mode == "linked-local":
        cmd.append("--no-rewrite")
    if kind == "place":
        cmd.extend(["--place-slug", place_slug])
    if int(args.max_sections or 0) > 0:
        cmd.extend(["--max-sections", str(int(args.max_sections))])
    if args.force:
        cmd.append("--force")
    return cmd


def run_command_stream(cmd: List[str], prefix: str, print_lock: threading.Lock) -> int:
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout is not None:
        for line in proc.stdout:
            with print_lock:
                print(f"{prefix} {line.rstrip()}", flush=True)
    return proc.wait()


def run_target(
    *,
    args: argparse.Namespace,
    target: Target,
    index: int,
    total: int,
    langs: List[str],
    genders: List[str],
    print_lock: threading.Lock,
) -> Tuple[str, Target, int]:
    kind, country_slug, city_slug, place_slug = target
    display = target_id(target)
    prefix = f"[{index}/{total} {kind} {display}]"
    lock_path = acquire_target_lock(Path(args.lock_dir), target, int(args.stale_lock_minutes or 0))
    if not lock_path:
        with print_lock:
            print(f"{prefix} [SKIP] locked by another worker", flush=True)
        return "locked", target, 0

    try:
        if args.skip_ready and not args.force and target_audio_ready(
            kind=kind,
            country_slug=country_slug,
            city_slug="__country__" if kind == "country" else city_slug,
            place_slug=place_slug,
            audio_version=str(args.audio_version or "v7").strip(),
            langs=langs,
            genders=genders,
        ):
            with print_lock:
                print(f"{prefix} [SKIP] already ready", flush=True)
            return "ready", target, 0

        with print_lock:
            print(f"{prefix} [START]", flush=True)
        code = run_command_stream(build_generate_cmd(args, target, args.source_mode), prefix, print_lock)
        if code != 0 and args.source_mode == "en-master":
            with print_lock:
                print(f"{prefix} [FALLBACK] linked-local", flush=True)
            code = run_command_stream(build_generate_cmd(args, target, "linked-local"), prefix, print_lock)

        if code == 0:
            with print_lock:
                print(f"{prefix} [OK]", flush=True)
            return "ok", target, 0

        with print_lock:
            print(f"{prefix} [FAIL] exit={code}", flush=True)
        return "fail", target, code
    finally:
        release_target_lock(lock_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk Siri-style audio generation for countries/cities.")
    parser.add_argument("--mode", choices=["country-hubs", "target-cities", "indexed", "all-cities"], default="target-cities")
    parser.add_argument("--audio-version", default="v7")
    parser.add_argument("--langs", default="en,fr,es,it,ua,de")
    parser.add_argument("--genders", default="female,male")
    parser.add_argument("--chunk-chars", type=int, default=1800)
    parser.add_argument("--max-sections", type=int, default=0, help="0 = all sections")
    parser.add_argument("--limit", type=int, default=0, help="0 = no limit")
    parser.add_argument("--start-index", type=int, default=0, help="Skip first N targets (resume helper).")
    parser.add_argument(
        "--source-mode",
        choices=["en-master", "linked-local"],
        default="linked-local",
        help="Text source strategy for generation.",
    )
    parser.add_argument("--edge-rate", default="-6%", help="edge-tts speech rate.")
    parser.add_argument("--edge-pitch", default="+1Hz", help="edge-tts pitch.")
    parser.add_argument("--edge-volume", default="+0%", help="edge-tts volume.")
    parser.add_argument("--edge-concurrency", type=int, default=2, help="Concurrent edge-tts jobs per target.")
    parser.add_argument("--workers", type=int, default=1, help="Parallel target workers (default: 1).")
    parser.add_argument("--lock-dir", default=str(ROOT / "cache" / "audio_target_locks"))
    parser.add_argument("--stale-lock-minutes", type=int, default=360)
    parser.add_argument("--include-countries", action="store_true", help="Also generate country-level guides.")
    parser.add_argument("--include-places", action="store_true", help="Also generate place-level manifests/audio.")
    parser.add_argument("--places-only", action="store_true", help="Generate only places.")
    parser.add_argument("--skip-ready", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    langs = csv_items(args.langs)
    genders = csv_items(args.genders)

    city_targets = collect_targets(args.mode, 0)
    place_targets: List[Tuple[str, str, str]] = []
    if args.include_places or args.places_only:
        place_targets = collect_place_targets(args.mode, city_targets, 0)

    targets: List[Target] = []
    if args.include_countries:
        for (country_slug,) in collect_country_targets():
            targets.append(("country", country_slug, "__country__", ""))
    if not args.places_only:
        for country_slug, city_slug in city_targets:
            targets.append(("city", country_slug, city_slug, ""))
    if args.include_places or args.places_only:
        for country_slug, city_slug, place_slug in place_targets:
            targets.append(("place", country_slug, city_slug, place_slug))

    if int(args.start_index or 0) > 0:
        targets = targets[int(args.start_index or 0):]
    if int(args.limit or 0) > 0:
        targets = targets[: int(args.limit or 0)]

    if not targets:
        print("[WARN] No targets found.")
        return 2

    if args.skip_ready and not args.force:
        before = len(targets)
        targets = [
            target
            for target in targets
            if not target_audio_ready(
                kind=target[0],
                country_slug=target[1],
                city_slug=target[2],
                place_slug=target[3],
                audio_version=str(args.audio_version or "v7").strip(),
                langs=langs,
                genders=genders,
            )
        ]
        print(f"[OK] skip-ready removed {before - len(targets)} complete targets")

    if not targets:
        print("[DONE] Nothing to generate; all requested targets are ready.")
        return 0

    total = len(targets)
    ok = 0
    fail = 0

    print(
        f"[OK] mode={args.mode} targets={total} "
        f"(countries={sum(1 for x in targets if x[0]=='country')}, "
        f"cities={sum(1 for x in targets if x[0]=='city')}, "
        f"places={sum(1 for x in targets if x[0]=='place')})"
    )
    print(
        f"[OK] audio-version={args.audio_version} langs={','.join(langs)} genders={','.join(genders)} "
        f"source-mode={args.source_mode} edge-rate={args.edge_rate} edge-pitch={args.edge_pitch} "
        f"edge-concurrency={int(args.edge_concurrency or 1)}"
    )
    if args.dry_run:
        for i, target in enumerate(targets[:25], start=1):
            print(f"[DRY {i}/{total}] {target[0]}: {target_id(target)}")
        if total > 25:
            print(f"[DRY] ... {total - 25} more targets")
        return 0

    print_lock = threading.Lock()
    workers = max(1, int(args.workers or 1))
    if workers == 1:
        for i, target in enumerate(targets, start=1):
            status, _target, _code = run_target(
                args=args,
                target=target,
                index=i,
                total=total,
                langs=langs,
                genders=genders,
                print_lock=print_lock,
            )
            if status in {"ok", "ready"}:
                ok += 1
            elif status == "fail":
                fail += 1
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    run_target,
                    args=args,
                    target=target,
                    index=i,
                    total=total,
                    langs=langs,
                    genders=genders,
                    print_lock=print_lock,
                )
                for i, target in enumerate(targets, start=1)
            ]
            for future in as_completed(futures):
                status, _target, _code = future.result()
                if status in {"ok", "ready"}:
                    ok += 1
                elif status == "fail":
                    fail += 1

    print(f"[DONE] ok={ok} fail={fail} total={total}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
