import array
import struct
import sys
from dataclasses import dataclass

from .extract import RELATIONS, display_label, qnum, search_keys
from .normalise import index_key

MAGIC = b"SPTI"
FORMAT = 1
CORE = "core"
DETAILS = "details"

CORE_HEADER = struct.Struct("<4sHH8s6I11I")
CORE_RECORD = struct.Struct("<IIIIIHHBBHIBxH")
DETAILS_HEADER = struct.Struct("<4sHH8s8I13I")
DETAILS_RECORD = struct.Struct("<IIIIH7B3x")
LABELLED_ENTITY = struct.Struct("<IIH2x")
ENTITY = struct.Struct("<IIHHB3x")
COUNTRY = struct.Struct("<IIH2s")
RELATION_KINDS = tuple(RELATIONS)

U8_MAX = 0xFF
U16_MAX = 0xFFFF
U32_MAX = 0xFFFFFFFF
HYPHEN = 0x2D
FILM = 0
SERIES = 1
ID_OVERFLOW = 1
TMDB_OTHER_KIND = 2
SECTION_ALIGNMENT = 4


class OrphanDetails(ValueError):
    def __init__(self, qids):
        shown = ", ".join(qids[:10])
        super().__init__(f"details would hold {len(qids)} qids the core pack lacks: {shown}")
        self.qids = qids


class DoesNotFit(ValueError):
    pass


@dataclass(frozen=True)
class Pack:
    name: str
    format: int
    data: bytes
    rows: dict
    keys: int
    kinds: dict
    fames: dict
    stats: dict


def _little_endian(typecode, values):
    typed = array.array(typecode, values)
    if sys.byteorder != "little":
        typed.byteswap()
    return typed.tobytes()


def _u32s(values):
    return _little_endian("I", values)


def _u16s(values):
    return _little_endian("H", values)


def _utf8(text):
    encoded = (text or "").encode("utf-8")
    if len(encoded) <= U16_MAX:
        return encoded
    return encoded[:U16_MAX].decode("utf-8", "ignore").encode("utf-8")


def _qid_number(q):
    number = qnum(q)
    if not 0 < number <= U32_MAX:
        raise DoesNotFit(f"{q} is not a qid that fits the pack")
    return number


def _id_number(value, prefix=""):
    if not value:
        return 0, False
    digits = value[len(prefix):] if prefix and value.startswith(prefix) else value
    if not digits.isdigit():
        return 0, True
    number = int(digits)
    return (number, False) if number <= U32_MAX else (0, True)


def _assemble(header, leading, sections):
    at = header.size
    offsets, body = [], bytearray()
    for section in sections:
        padding = (-at) % SECTION_ALIGNMENT
        body += b"\0" * padding
        at += padding
        offsets.append(at)
        body += section
        at += len(section)
    offsets.append(at)
    return header.pack(*leading, *offsets) + bytes(body)


def _preamble(name):
    return (MAGIC, FORMAT, 0, name.encode("ascii"))


def _labelled_table(qids, labels, pool):
    table = bytearray()
    for q in qids:
        english = _utf8(labels.get(q))
        table += LABELLED_ENTITY.pack(_qid_number(q), len(pool), len(english))
        pool += english
    return bytes(table)


def _word_starts(keys):
    starts = []
    for number, key in enumerate(keys):
        for position in range(1, min(len(key), U16_MAX)):
            if key[position - 1] == HYPHEN and key[position] != HYPHEN:
                starts.append((number, position))
    starts.sort(key=lambda start: keys[start[0]][start[1]:])
    return starts


def _key_sections(keyed, posting_order):
    keys = sorted(keyed)
    blob, key_offsets, posting_offsets, postings = bytearray(), [0], [0], []
    for key in keys:
        blob += key
        key_offsets.append(len(blob))
        postings += sorted(keyed[key], key=posting_order)
        posting_offsets.append(len(postings))
    return keys, bytes(blob), key_offsets, posting_offsets, postings


def core_pack(rows, genre_labels):
    rows = sorted(rows, key=lambda row: qnum(row["qid"]))
    genre_qids = sorted({genre for row in rows for genre in row["genres"]}, key=qnum)
    if len(genre_qids) > U16_MAX:
        raise DoesNotFit(f"{len(genre_qids)} genres do not fit a u16 genre reference")
    genre_index = {genre: number for number, genre in enumerate(genre_qids)}

    records, pool, genre_refs, key_rows = bytearray(), bytearray(), [], {}
    overflows = other_kind_fallbacks = 0
    for number, row in enumerate(rows):
        for key in search_keys(row):
            key_rows.setdefault(key.encode("utf-8"), []).append(number)
        label = _utf8(display_label(row))
        imdb, imdb_overflow = _id_number(row["imdb"], "tt")
        tmdb, tmdb_overflow = _id_number(row["tmdb"])
        tvdb, tvdb_overflow = _id_number(row["tvdb"])
        overflow = imdb_overflow or tmdb_overflow or tvdb_overflow
        overflows += overflow
        tmdb_other_kind = bool(tmdb) and row["tmdb_other_kind"]
        other_kind_fallbacks += tmdb_other_kind
        flags = (ID_OVERFLOW if overflow else 0) | (TMDB_OTHER_KIND if tmdb_other_kind else 0)
        year = row["year"] if row["year"] and 0 < row["year"] <= U16_MAX else 0
        genres = [genre_index[genre] for genre in row["genres"]][:U8_MAX]
        records += CORE_RECORD.pack(
            _qid_number(row["qid"]), imdb, tmdb, tvdb, len(pool), len(label), year,
            SERIES if row["type"] == "series" else FILM, flags, row["seasons"] or 0,
            len(genre_refs), len(genres), row["fame"])
        pool += label
        genre_refs += genres
    genre_table = _labelled_table(genre_qids, genre_labels, pool)

    keys, blob, key_offsets, posting_offsets, postings = _key_sections(key_rows, int)
    starts = _word_starts(keys)

    data = _assemble(
        CORE_HEADER,
        (*_preamble(CORE), len(rows), len(keys), len(postings), len(starts), len(genre_qids),
         len(genre_refs)),
        [bytes(records), bytes(pool), bytes(blob), _u32s(key_offsets), _u32s(posting_offsets),
         _u32s(postings), _u32s(start[0] for start in starts),
         _u16s(start[1] for start in starts), genre_table, _u16s(genre_refs)])
    kinds = {row["qid"]: row["type"] for row in rows}
    return Pack(
        name=CORE,
        format=FORMAT,
        data=data,
        rows=_row_counts(kinds.values()),
        keys=len(keys),
        kinds=kinds,
        fames={row["qid"]: row["fame"] for row in rows},
        stats={"postings": len(postings), "word_starts": len(starts), "genres": len(genre_qids),
               "id_overflows": overflows,
               "tmdb_other_kind_fallbacks": other_kind_fallbacks,
               "records_with_fame_0": sum(row["fame"] == 0 for row in rows)},
    )


def _row_counts(kinds):
    kinds = list(kinds)
    return {"films": kinds.count("film"), "series": kinds.count("series")}


def details_pack(details, core, entity_labels, entity_fames, countries):
    orphans = sorted(set(details) - set(core.kinds), key=qnum)
    if orphans:
        raise OrphanDetails(orphans)
    entries = sorted(
        ((q, entry) for q, entry in details.items() if any(entry.values())),
        key=lambda item: qnum(item[0]))

    entities = sorted(
        {(kind, entity) for _, entry in entries for kind, name in enumerate(RELATION_KINDS)
         for entity in entry[name]},
        key=lambda pair: (pair[0], qnum(pair[1])))
    entity_index = {pair: number for number, pair in enumerate(entities)}
    country_qids = sorted({country for _, entry in entries for country in entry["countries"]},
                          key=qnum)
    if len(country_qids) > U16_MAX:
        raise DoesNotFit(f"{len(country_qids)} countries do not fit a u16 country reference")
    country_index = {country: number for number, country in enumerate(country_qids)}

    records, relation_refs, country_refs = bytearray(), [], []
    titles_of = [[] for _ in entities]
    refs_per_kind = dict.fromkeys(RELATION_KINDS, 0)
    clipped = 0
    for record, (q, entry) in enumerate(entries):
        counts = []
        relation_at = len(relation_refs)
        for kind, name in enumerate(RELATION_KINDS):
            refs = [entity_index[(kind, entity)] for entity in entry[name]]
            clipped += len(refs) > U8_MAX
            refs = refs[:U8_MAX]
            for ref in refs:
                titles_of[ref].append(record)
            relation_refs += refs
            refs_per_kind[name] += len(refs)
            counts.append(len(refs))
        origins = [country_index[country] for country in entry["countries"]]
        clipped += len(origins) > U8_MAX
        origins = origins[:U8_MAX]
        records += DETAILS_RECORD.pack(
            _qid_number(q), relation_at, len(country_refs), entry["episodes"] or 0,
            entry["minutes"] or 0, *counts, len(origins))
        country_refs += origins

    pool, entity_table, keyed = bytearray(), bytearray(), {}
    for number, (kind, entity) in enumerate(entities):
        label = _utf8(entity_labels.get(entity))
        entity_table += ENTITY.pack(
            _qid_number(entity), len(pool), len(label), entity_fames.get(entity, 0), kind)
        pool += label
        key = index_key(label.decode("utf-8"))
        if key:
            keyed.setdefault(key.encode("utf-8"), []).append(number)
    country_table = bytearray()
    for country in country_qids:
        code, english = countries.get(country, (None, None))
        english = _utf8(english)
        country_table += COUNTRY.pack(
            _qid_number(country), len(pool), len(english), (code or "").encode("ascii"))
        pool += english

    def by_entity_fame(number):
        return (-entity_fames.get(entities[number][1], 0), number)

    def by_title_fame(record):
        q = entries[record][0]
        return (-core.fames[q], qnum(q))

    keys, blob, key_offsets, posting_offsets, postings = _key_sections(keyed, by_entity_fame)
    title_offsets, title_postings = [0], []
    for records_of_entity in titles_of:
        title_postings += sorted(records_of_entity, key=by_title_fame)
        title_offsets.append(len(title_postings))

    data = _assemble(
        DETAILS_HEADER,
        (*_preamble(DETAILS), len(entries), len(entities), len(country_qids), len(relation_refs),
         len(country_refs), len(keys), len(postings), len(title_postings)),
        [bytes(records), bytes(entity_table), bytes(country_table), bytes(pool),
         _u32s(relation_refs), _u16s(country_refs), blob, _u32s(key_offsets),
         _u32s(posting_offsets), _u32s(postings), _u32s(title_offsets), _u32s(title_postings)])
    kinds = {q: core.kinds[q] for q, _ in entries}
    return Pack(
        name=DETAILS,
        format=FORMAT,
        data=data,
        rows=_row_counts(kinds.values()),
        keys=len(keys),
        kinds=kinds,
        fames={q: core.fames[q] for q, _ in entries},
        stats={"entities_per_kind": {name: sum(kind == number for kind, _ in entities)
                                     for number, name in enumerate(RELATION_KINDS)},
               "refs_per_kind": refs_per_kind,
               "entity_keys": len(keys),
               "title_postings": len(title_postings),
               "countries": len(country_qids),
               "lists_clipped": clipped},
    )
