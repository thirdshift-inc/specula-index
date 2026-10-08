import gzip
import hashlib
import json
import re

SCHEMA = 1
SOURCE = "Wikidata via QLever"
LICENCE = "MIT"
ATTRIBUTION = "Film and series data comes from Wikidata, which dedicates it to the public domain under CC0 1.0."
MANIFEST_FILE = "manifest.json"
TAG_PREFIX = "index-"
PACK_SUFFIX = ".idx.gz"
SAFE_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
GZIP_LEVEL = 9


class UnsafeFileName(ValueError):
    pass


class ManifestMismatch(RuntimeError):
    pass


def checked_file_name(file):
    if not SAFE_FILE_NAME.fullmatch(file) or ".." in file:
        raise UnsafeFileName(f"{file!r} is not a plain file name")
    return file


def pack_file_name(name, version, pack_format):
    return checked_file_name(f"{name}-{version}.f{pack_format}{PACK_SUFFIX}")


def gzipped(data):
    return gzip.compress(data, compresslevel=GZIP_LEVEL, mtime=0)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def pack_entry(pack, file, compressed):
    return {
        "name": pack.name,
        "format": pack.format,
        "file": file,
        "bytes": len(pack.data),
        "sha256": sha256(pack.data),
        "gzipBytes": len(compressed),
        "gzipSha256": sha256(compressed),
        "rows": dict(pack.rows),
        "keys": pack.keys,
    }


def document(version, built, snapshot, entries):
    return {
        "schema": SCHEMA,
        "version": version,
        "tag": TAG_PREFIX + version,
        "built": built,
        "source": f"{SOURCE} ({snapshot})" if snapshot else SOURCE,
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "packs": entries,
    }


def observed(directory, file):
    compressed = (directory / checked_file_name(file)).read_bytes()
    data = gzip.decompress(compressed)
    return {
        "bytes": len(data),
        "sha256": sha256(data),
        "gzipBytes": len(compressed),
        "gzipSha256": sha256(compressed),
    }


def verify(entries, directory):
    for entry in entries:
        for field, value in observed(directory, entry["file"]).items():
            if entry[field] != value:
                raise ManifestMismatch(
                    f"{entry['file']}: {field} on disk is {value}, the manifest says {entry[field]}")


def write(directory, manifest):
    verify(manifest["packs"], directory)
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    (directory / MANIFEST_FILE).write_text(text, encoding="utf-8")
    return directory / MANIFEST_FILE
