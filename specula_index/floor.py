import json
import operator

from . import pack

MINIMUM_CORE_RECORDS = 100_000
LARGEST_DROP_PERCENT = 10


class TooFewRecords(RuntimeError):
    pass


class UnreadableManifest(ValueError):
    pass


def core_records(path):
    text = path.read_text(encoding="utf-8")
    try:
        document = json.loads(text)
        [rows] = [entry["rows"] for entry in document["packs"] if entry["name"] == pack.CORE]
        return operator.index(rows["films"]) + operator.index(rows["series"])
    except (ValueError, KeyError, TypeError) as error:
        raise UnreadableManifest(f"{path} does not say how many core records it has") from error


def check(records, previous=None):
    if records < MINIMUM_CORE_RECORDS:
        raise TooFewRecords(
            f"{records} core records, fewer than the minimum of {MINIMUM_CORE_RECORDS}")
    if previous is not None and records * 100 < previous * (100 - LARGEST_DROP_PERCENT):
        raise TooFewRecords(
            f"{records} core records, more than {LARGEST_DROP_PERCENT} percent fewer than "
            f"the {previous} of the previous release")
