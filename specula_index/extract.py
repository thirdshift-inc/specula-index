import collections
import http.client
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from .normalise import index_key

DEFAULT_ENDPOINT = "https://qlever.dev/api/wikidata"
USER_AGENT = "SpeculaTitleIndex/1 (+https://github.com/thirdshift-inc/specula-index)"
FETCH_ATTEMPTS = 3
FETCH_TIMEOUT_SECONDS = 900
RETRY_PAUSE_SECONDS = 10

CLASSES = {
    "Q11424": "film",
    "Q24869": "film",
    "Q202866": "film",
    "Q24862": "film",
    "Q93204": "film",
    "Q506240": "film",
    "Q20650540": "film",
    "Q5398426": "series",
    "Q581714": "series",
    "Q63952888": "series",
    "Q1259759": "series",
    "Q526877": "series",
}

ADULT_CLASS = "Q18011172"
ADULT_GENRE = "Q291"

CAST_LIMIT = 8

MINUTE = "Q7727"
SECOND = "Q11574"
HOUR = "Q25235"
MINUTES_PER_UNIT = {MINUTE: (1, 1), SECOND: (1, 60), HOUR: (60, 1)}
LARGEST_PLAUSIBLE_AMOUNT = Decimal(10) ** 9

MAX_FAME = 0xFFFF
MAX_MINUTES = 0xFFFF
MAX_SEASONS = 0xFFFF
MAX_EPISODES = 0xFFFFFFFF

PREFIXES = "\n".join([
    "PREFIX wd: <http://www.wikidata.org/entity/>",
    "PREFIX wdt: <http://www.wikidata.org/prop/direct/>",
    "PREFIX p: <http://www.wikidata.org/prop/>",
    "PREFIX ps: <http://www.wikidata.org/prop/statement/>",
    "PREFIX psv: <http://www.wikidata.org/prop/statement/value/>",
    "PREFIX pq: <http://www.wikidata.org/prop/qualifier/>",
    "PREFIX wikibase: <http://wikiba.se/ontology#>",
    "PREFIX schema: <http://schema.org/>",
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>",
    "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>",
    "",
])
MEMBERS = "VALUES ?class { " + " ".join(f"wd:{q}" for q in CLASSES) + " } ?item wdt:P31 ?class ."

GENRE_OF_ITEM = "?item wdt:P136 ?entity ."
RELATIONS = {
    "cast": "P161",
    "director": "P57",
    "company": "P272",
    "broadcaster": "P449",
    "series": "P179",
    "franchise": "P8345",
}
RELATED_ENTITY = " UNION ".join(
    f"{{ ?item wdt:{prop} ?entity }}" for prop in RELATIONS.values())
COUNTRY_OF_ITEM = "?item wdt:P495 ?entity ."


@dataclass(frozen=True)
class Query:
    variables: str
    text: str

    @property
    def header(self):
        return [name.lstrip("?") for name in self.variables.split()]


def _select(variables, pattern, over_members=True):
    scope = f"{MEMBERS} " if over_members else ""
    return Query(variables, f"{PREFIXES}SELECT DISTINCT {variables} WHERE {{ {scope}{pattern} }}")


def _pairs(pattern, variables="?item ?value"):
    return _select(variables, pattern)


def _labels(reach):
    return _select(
        "?entity ?value", f"{reach} ?entity rdfs:label ?value . FILTER (LANG(?value) = \"en\")")


QUERIES = {
    "members": _select("?item ?class", ""),
    "adult": _pairs(
        f"{{ ?item wdt:P31 wd:{ADULT_CLASS} . BIND(\"class\" AS ?value) }} UNION "
        f"{{ ?item wdt:P136 wd:{ADULT_GENRE} . BIND(\"genre\" AS ?value) }}"),
    "imdb": _pairs("?item wdt:P345 ?value ."),
    "tmdb_movie": _pairs("?item wdt:P4947 ?value ."),
    "tmdb_tv": _pairs("?item wdt:P4983 ?value ."),
    "tvdb": _pairs("?item wdt:P4835 ?value ."),
    "published": _pairs("?item wdt:P577 ?value ."),
    "start": _pairs("?item wdt:P580 ?value ."),
    "original_title": _pairs("?item wdt:P1476 ?value ."),
    "original_language": _pairs(
        "?item wdt:P364 ?value . OPTIONAL { ?value wdt:P218 ?code }", "?item ?value ?code"),
    "label_en": _pairs("?item rdfs:label ?value . FILTER (LANG(?value) = \"en\")"),
    "label_pl": _pairs("?item rdfs:label ?value . FILTER (LANG(?value) = \"pl\")"),
    "alias_en": _pairs("?item skos:altLabel ?value . FILTER (LANG(?value) = \"en\")"),
    "alias_pl": _pairs("?item skos:altLabel ?value . FILTER (LANG(?value) = \"pl\")"),
    "label_original": _pairs(
        "?item wdt:P364 ?language . ?language wdt:P218 ?code . "
        "?item rdfs:label ?value . FILTER (LANG(?value) = ?code)"),
    "genre": _pairs("?item wdt:P136 ?value ."),
    "genre_label_en": _labels(GENRE_OF_ITEM),
    "seasons": _pairs("?item wdt:P2437 ?value ."),
    "cast": _pairs(
        "?item p:P161 ?statement . ?statement ps:P161 ?value ; a wikibase:BestRank . "
        "OPTIONAL { ?statement pq:P1545 ?ordinal }",
        "?item ?value ?ordinal"),
    "director": _pairs("?item wdt:P57 ?value ."),
    "entity_label_en": _labels(RELATED_ENTITY),
    "entity_fame": _select("?entity ?value", f"{RELATED_ENTITY} ?entity wikibase:sitelinks ?value ."),
    "fame": _pairs("?item wikibase:sitelinks ?value ."),
    "company": _pairs("?item wdt:P272 ?value ."),
    "broadcaster": _pairs("?item wdt:P449 ?value ."),
    "series": _pairs("?item wdt:P179 ?value ."),
    "franchise": _pairs("?item wdt:P8345 ?value ."),
    "country": _pairs(
        "?item wdt:P495 ?value . OPTIONAL { ?value wdt:P297 ?code }", "?item ?value ?code"),
    "country_label_en": _labels(COUNTRY_OF_ITEM),
    "duration": _pairs(
        "?item p:P2047 ?statement . ?statement a wikibase:BestRank ; psv:P2047 ?amount . "
        "?amount wikibase:quantityAmount ?value ; wikibase:quantityUnit ?unit .",
        "?item ?value ?unit"),
    "episodes": _pairs("?item wdt:P1113 ?value ."),
    "snapshot": _select("?value", "wikibase:Dump schema:dateModified ?value .", over_members=False),
}


class QLeverUnavailable(RuntimeError):
    pass


class MalformedAnswer(ValueError):
    pass


def fetch(name, endpoint, cache, refresh=False):
    path = cache / f"{name}.tsv"
    if path.exists() and not refresh:
        return path
    body = urllib.parse.urlencode({"query": QUERIES[name].text, "action": "tsv_export"}).encode()
    request = urllib.request.Request(endpoint, data=body, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/tab-separated-values",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    partial = path.with_suffix(".part")
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response, \
                    open(partial, "wb") as out:
                while chunk := response.read(1 << 20):
                    out.write(chunk)
            partial.replace(path)
            print(f"{name}: {path.stat().st_size / 1e6:.1f} MB in "
                  f"{time.monotonic() - started:.1f} s", file=sys.stderr)
            return path
        except (OSError, http.client.HTTPException) as error:
            print(f"{name}: attempt {attempt} failed: {error}", file=sys.stderr)
            if attempt < FETCH_ATTEMPTS:
                time.sleep(RETRY_PAUSE_SECONDS * attempt)
    raise QLeverUnavailable(f"{name}: no answer from {endpoint} after {FETCH_ATTEMPTS} attempts")


def fetch_all(endpoint, cache, refresh=False):
    cache.mkdir(parents=True, exist_ok=True)
    print(f"querying {endpoint}", file=sys.stderr)
    for name in QUERIES:
        fetch(name, endpoint, cache, refresh)
    return cache


_ESCAPES = {"t": "\t", "n": "\n", "r": "\r", '"': '"', "\\": "\\"}


def term(cell):
    if not cell:
        return None, None
    if cell.startswith("<") and cell.endswith(">"):
        return cell[1:-1], None
    if not cell.startswith('"'):
        return cell, None
    out, i = [], 1
    while i < len(cell):
        ch = cell[i]
        if ch == "\\" and i + 1 < len(cell):
            out.append(_ESCAPES.get(cell[i + 1], cell[i + 1]))
            i += 2
            continue
        if ch == '"':
            break
        out.append(ch)
        i += 1
    rest = cell[i + 1:]
    return "".join(out), (rest[1:] if rest.startswith("@") else None)


def qid(value):
    return re.split(r"[/:]", value)[-1] if value else None


def qnum(q):
    return int(q[1:]) if q and q[1:].isdigit() else 0


def rows(path, query):
    expected = query.header
    with open(path, encoding="utf-8") as answer:
        header = [name.lstrip("?") for name in answer.readline().rstrip("\n").split("\t")]
        if header != expected:
            raise MalformedAnswer(f"{path.name}: header {header}, expected {expected}")
        for line in answer:
            if not line.strip():
                continue
            cells = line.rstrip("\n").split("\t")
            cells += [""] * (len(expected) - len(cells))
            yield [term(cell) for cell in cells[:len(expected)]]


_YEAR = re.compile(r"^([+-]?\d{1,4})-")


def year_of(value):
    match = _YEAR.match(value or "")
    return int(match.group(1)) if match else None


def decimal_of(value):
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def whole_number_of(value):
    number = decimal_of(value)
    if number is None or number < 0 or number != number.to_integral_value():
        return None
    return int(number)


def saturated_fame(sitelinks):
    return min(sitelinks, MAX_FAME)


def minutes_of(amount, unit):
    ratio = MINUTES_PER_UNIT.get(unit)
    if ratio is None:
        return None, "duration_unit_dropped"
    number = decimal_of(amount)
    if number is None or number <= 0 or number > LARGEST_PLAUSIBLE_AMOUNT:
        return None, "duration_value_dropped"
    multiplier, divisor = ratio
    minutes = int((number * multiplier / divisor).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if not 0 < minutes <= MAX_MINUTES:
        return None, "duration_value_dropped"
    return minutes, None


SEARCH_FIELDS = ("original_title", "label_en", "label_pl", "label_original")
DISPLAY_FIELDS = ("label_en", "original_title", "label_original")


def names(row):
    found = [row[field] for field in SEARCH_FIELDS if row[field]]
    return found + list(row["aliases"])


def search_keys(row):
    return {index_key(name) for name in names(row)} - {""}


def display_label(row):
    return next((row[field] for field in DISPLAY_FIELDS if row[field]), "")


@dataclass
class Extract:
    kept: list
    details: dict
    genres: dict
    entities: dict
    entity_fames: dict
    countries: dict
    snapshot: str | None
    counts: collections.Counter


def _answers(raw):
    paths = {name: raw / f"{name}.tsv" for name in QUERIES}
    missing = sorted(name for name, path in paths.items() if not path.exists())
    if missing:
        raise FileNotFoundError(f"{raw}: no answer for {', '.join(missing)}")
    return paths


def _join_core(paths, counts):
    items = {}
    for (item, _), (cls, _) in rows(paths["members"], QUERIES["members"]):
        items.setdefault(qid(item), {"classes": set()})["classes"].add(qid(cls))

    def each(name):
        for cells in rows(paths[name], QUERIES[name]):
            q = qid(cells[0][0])
            if q in items:
                yield items[q], cells[1:]

    for row, ((value, _),) in each("adult"):
        row.setdefault("adult", set()).add(value)
    for name in ("imdb", "tmdb_movie", "tmdb_tv", "tvdb"):
        for row, ((value, _),) in each(name):
            if name == "imdb" and not re.fullmatch(r"tt\d+", value or ""):
                counts["imdb_not_tt"] += 1
                continue
            row.setdefault(name, set()).add(value)
    for name in ("published", "start"):
        for row, ((value, _),) in each(name):
            year = year_of(value)
            if year is not None:
                row[name] = min(year, row.get(name, year))
    for row, ((value, lang),) in each("original_title"):
        row.setdefault("original_titles", set()).add((value, lang or ""))
    for row, ((value, _), (code, _)) in each("original_language"):
        row.setdefault("languages", set()).add(code or qid(value))
    for name in ("label_en", "label_pl"):
        for row, ((value, _),) in each(name):
            row[name] = min(value, row.get(name, value))
    for name in ("alias_en", "alias_pl"):
        for row, ((value, _),) in each(name):
            row.setdefault("aliases", set()).add(value)
    for row, ((value, lang),) in each("label_original"):
        row.setdefault("labels_original", {}).setdefault(lang or "", set()).add(value)
    for row, ((value, _),) in each("genre"):
        row.setdefault("genres", set()).add(qid(value))
    for row, ((value, _),) in each("fame"):
        fame = whole_number_of(value)
        if fame is None:
            counts["fame_dropped"] += 1
            continue
        row["fame"] = max(fame, row.get("fame", fame))
    for row, ((value, _),) in each("seasons"):
        seasons = whole_number_of(value)
        if seasons is None or seasons > MAX_SEASONS:
            counts["seasons_dropped"] += 1
            continue
        row["seasons"] = max(seasons, row.get("seasons", seasons))
    return items


def kind_of(classes):
    return "series" if any(CLASSES.get(c) == "series" for c in classes) else "film"


def shaped(q, row):
    kind = kind_of(row["classes"])
    same_kind, other_kind = (
        ("tmdb_tv", "tmdb_movie") if kind == "series" else ("tmdb_movie", "tmdb_tv"))
    tmdb = row.get(same_kind) or row.get(other_kind)
    languages = sorted(row.get("languages", ()))
    originals = sorted(row.get("original_titles", ()))
    preferred = [o for o in originals if o[1] and o[1] in languages] or originals
    original = preferred[0][0] if preferred else None
    aliases = set(row.get("aliases", ()))
    aliases.update(text for text, _ in originals if text != original)
    in_original_language = row.get("labels_original", {})
    label_original = next(
        (min(in_original_language[code]) for code in languages if code in in_original_language),
        None)
    year = row.get("published")
    if year is None:
        year = row.get("start")
    return {
        "qid": q,
        "type": kind,
        "year": year,
        "imdb": min(row["imdb"]) if row.get("imdb") else None,
        "tmdb": min(tmdb, key=lambda v: (len(v), v)) if tmdb else None,
        "tmdb_other_kind": bool(tmdb) and not row.get(same_kind),
        "tvdb": min(row["tvdb"], key=lambda v: (len(v), v)) if row.get("tvdb") else None,
        "original_title": original,
        "label_en": row.get("label_en"),
        "label_pl": row.get("label_pl"),
        "label_original": label_original,
        "aliases": sorted(aliases - {row.get("label_en"), row.get("label_pl"), original}),
        "genres": sorted(row.get("genres", ()), key=qnum),
        "seasons": row.get("seasons") if kind == "series" else None,
        "fame": saturated_fame(row.get("fame", 0)),
    }


def _english_labels(paths, prefix):
    labels = {}
    name = f"{prefix}_label_en"
    for (entity, _), (value, _) in rows(paths[name], QUERIES[name]):
        e = qid(entity)
        labels[e] = min(value, labels.get(e, value))
    return labels


def _entity_fames(paths, counts):
    fames = {}
    for (entity, _), (value, _) in rows(paths["entity_fame"], QUERIES["entity_fame"]):
        fame = whole_number_of(value)
        if fame is None:
            counts["entity_fame_dropped"] += 1
            continue
        e = qid(entity)
        fames[e] = saturated_fame(max(fame, fames.get(e, fame)))
    return fames


def _country_table(paths):
    codes = {}
    for (_, _), (country, _), (code, _) in rows(paths["country"], QUERIES["country"]):
        if code and re.fullmatch(r"[A-Z]{2}", code):
            c = qid(country)
            codes[c] = min(code, codes.get(c, code))
    labels = _english_labels(paths, "country")
    return {c: (codes.get(c), labels.get(c)) for c in set(codes) | set(labels)}


def _cast_order(pair):
    person, ordinal = pair
    return (ordinal is None, ordinal or 0, qnum(person))


def _collect_details(paths, counts):
    collected = collections.defaultdict(dict)

    def each(name):
        for cells in rows(paths[name], QUERIES[name]):
            yield collected[qid(cells[0][0])], cells[1:]

    for entry, ((person, _), (ordinal, _)) in each("cast"):
        cast = entry.setdefault("cast", {})
        number = whole_number_of(ordinal)
        p = qid(person)
        if p not in cast or (number is not None and (cast[p] is None or number < cast[p])):
            cast[p] = number
    for entry, ((person, _),) in each("director"):
        entry.setdefault("directors", set()).add(qid(person))
    for relation in ("company", "broadcaster", "series", "franchise"):
        for entry, ((value, _),) in each(relation):
            entry.setdefault(relation, set()).add(qid(value))
    for entry, ((country, _), _) in each("country"):
        entry.setdefault("countries", set()).add(qid(country))
    for entry, ((amount, _), (unit, _)) in each("duration"):
        minutes, dropped = minutes_of(amount, qid(unit))
        if dropped:
            counts[dropped] += 1
            continue
        entry["minutes"] = min(minutes, entry.get("minutes", minutes))
    for entry, ((value, _),) in each("episodes"):
        episodes = whole_number_of(value)
        if episodes is None or episodes > MAX_EPISODES:
            counts["episodes_dropped"] += 1
            continue
        entry["episodes"] = max(episodes, entry.get("episodes", episodes))

    shaped_details = {}
    for q, entry in collected.items():
        cast = sorted(entry.get("cast", {}).items(), key=_cast_order)
        if len(cast) > CAST_LIMIT:
            counts["cast_capped"] += 1
        shaped_details[q] = {
            "cast": [person for person, _ in cast][:CAST_LIMIT],
            "director": sorted(entry.get("directors", ()), key=qnum),
            "company": sorted(entry.get("company", ()), key=qnum),
            "broadcaster": sorted(entry.get("broadcaster", ()), key=qnum),
            "series": sorted(entry.get("series", ()), key=qnum),
            "franchise": sorted(entry.get("franchise", ()), key=qnum),
            "countries": sorted(entry.get("countries", ()), key=qnum),
            "minutes": entry.get("minutes"),
            "episodes": entry.get("episodes"),
        }
    return shaped_details


def load(raw):
    paths = _answers(Path(raw))
    counts = collections.Counter()
    items = _join_core(paths, counts)

    kept, dropped, adult = [], set(), 0
    for q in sorted(items, key=qnum):
        row = shaped(q, items[q])
        if items[q].get("adult"):
            adult += 1
            dropped.add(q)
        elif not display_label(row):
            counts["no_display_label_dropped"] += 1
            dropped.add(q)
        elif not search_keys(row):
            counts["unsearchable_dropped"] += 1
            dropped.add(q)
        else:
            kept.append(row)

    details = {}
    for q, entry in _collect_details(paths, counts).items():
        if q in dropped:
            continue
        if entry["episodes"] is not None and q in items and kind_of(items[q]["classes"]) != "series":
            counts["episodes_on_film_dropped"] += 1
            entry = {**entry, "episodes": None}
        details[q] = entry

    snapshot = next((cells[0][0] for cells in rows(paths["snapshot"], QUERIES["snapshot"])), None)
    counts.update({
        "items_in_classes": len(items),
        "kept": len(kept),
        "excluded_adult": adult,
        "details_rows": len(details),
    })
    return Extract(
        kept=kept,
        details=details,
        genres=_english_labels(paths, "genre"),
        entities=_english_labels(paths, "entity"),
        entity_fames=_entity_fames(paths, counts),
        countries=_country_table(paths),
        snapshot=snapshot,
        counts=counts,
    )
