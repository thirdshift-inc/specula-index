import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from . import extract, manifest, pack

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
DEFAULT_CACHE = Path(".qlever-cache")


def version_date(text):
    if not DATE.fullmatch(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not YYYY-MM-DD")
    try:
        datetime.date.fromisoformat(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return text


def utc_timestamp(text):
    if not TIMESTAMP.fullmatch(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not YYYY-MM-DDTHH:MM:SSZ")
    return text


def arguments(argv):
    parser = argparse.ArgumentParser(prog="python -m specula_index.build")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--date", type=version_date, required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--built", type=utc_timestamp)
    parser.add_argument("--endpoint", default=extract.DEFAULT_ENDPOINT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args(argv)


def build(out, version, raw, built=None):
    extracted = extract.load(raw)
    core = pack.core_pack(extracted.kept, extracted.genres)
    details = pack.details_pack(
        extracted.details, core, extracted.entities, extracted.entity_fames, extracted.countries)
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for built_pack in (core, details):
        file = manifest.pack_file_name(built_pack.name, version, built_pack.format)
        compressed = manifest.gzipped(built_pack.data)
        entries.append(manifest.pack_entry(built_pack, file, compressed))
        (out / file).write_bytes(compressed)
    document = manifest.document(
        version, built or f"{version}T00:00:00Z", extracted.snapshot, entries)
    manifest.write(out, document)
    report = {
        "counts": dict(sorted(extracted.counts.items())),
        "core": core.stats,
        "details": details.stats,
    }
    return document, report


def main(argv=None):
    args = arguments(argv)
    try:
        raw = args.fixture or extract.fetch_all(args.endpoint, args.cache, args.refresh)
        document, report = build(args.out, args.date, raw, args.built)
    except (extract.QLeverUnavailable, extract.MalformedAnswer, pack.OrphanDetails,
            pack.DoesNotFit, manifest.ManifestMismatch, manifest.UnsafeFileName,
            FileNotFoundError) as error:
        print(f"build refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"manifest": document, "report": report}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
