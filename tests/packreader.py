import gzip
import struct

PREAMBLE = struct.Struct("<4sHH8s")
CORE_COUNTS = struct.Struct("<6I")
CORE_OFFSETS = struct.Struct("<11I")
CORE_RECORD = struct.Struct("<IIIIIHHBBHIBxH")
DETAILS_COUNTS = struct.Struct("<8I")
DETAILS_OFFSETS = struct.Struct("<13I")
DETAILS_RECORD = struct.Struct("<IIIIH7B3x")
LABELLED_ENTITY = struct.Struct("<IIH2x")
ENTITY = struct.Struct("<IIHHB3x")
COUNTRY = struct.Struct("<IIH2s")
RELATION_KINDS = ("cast", "director", "company", "broadcaster", "series", "franchise")


class NotAPack(ValueError):
    pass


def _array(data, at, count, typecode):
    return list(struct.unpack_from(f"<{count}{typecode}", data, at)) if count else []


def _text(pool, at, length):
    return pool[at:at + length].decode("utf-8") or None


def _preamble(data, expected_name):
    magic, pack_format, reserved, name = PREAMBLE.unpack_from(data, 0)
    if magic != b"SPTI" or pack_format != 1 or reserved != 0:
        raise NotAPack(f"magic {magic!r}, format {pack_format}, reserved {reserved}")
    if name.rstrip(b"\0").decode("ascii") != expected_name:
        raise NotAPack(f"named {name!r}, expected {expected_name}")
    return PREAMBLE.size


def _labelled(data, at, count, pool):
    entities = []
    for number in range(count):
        q, english_at, english_length = LABELLED_ENTITY.unpack_from(
            data, at + number * LABELLED_ENTITY.size)
        entities.append((f"Q{q}", _text(pool, english_at, english_length)))
    return entities


class CorePack:
    def __init__(self, data):
        self.data = data
        at = _preamble(data, "core")
        (self.record_count, self.key_count, self.posting_count, self.word_start_count,
         self.genre_count, self.genre_ref_count) = CORE_COUNTS.unpack_from(data, at)
        at += CORE_COUNTS.size
        offsets = CORE_OFFSETS.unpack_from(data, at)
        self.header_size = at + CORE_OFFSETS.size
        (records_at, pool_at, blob_at, key_offsets_at, posting_offsets_at, postings_at,
         word_keys_at, word_positions_at, genres_at, genre_refs_at, self.end) = offsets
        self.size = len(data)
        self.offsets = offsets
        pool = data[pool_at:blob_at]
        self.genres = _labelled(data, genres_at, self.genre_count, pool)
        genre_refs = _array(data, genre_refs_at, self.genre_ref_count, "H")
        self.records = []
        for number in range(self.record_count):
            (q, imdb, tmdb, tvdb, label_at, label_length, year, kind, flags, seasons, genre_at,
             genre_count, fame) = CORE_RECORD.unpack_from(data, records_at + number * CORE_RECORD.size)
            self.records.append({
                "qid": f"Q{q}",
                "imdb": f"tt{imdb:07d}" if imdb else None,
                "tmdb": tmdb or None,
                "tvdb": tvdb or None,
                "label": _text(pool, label_at, label_length),
                "year": year or None,
                "type": ("film", "series")[kind],
                "flags": flags,
                "seasons": seasons,
                "fame": fame,
                "genres": [self.genres[ref] for ref in genre_refs[genre_at:genre_at + genre_count]],
            })
        self.keys, self.postings = _keys_and_postings(
            data, blob_at, key_offsets_at, posting_offsets_at, postings_at, self.key_count,
            self.posting_count)
        word_keys = _array(data, word_keys_at, self.word_start_count, "I")
        word_positions = _array(data, word_positions_at, self.word_start_count, "H")
        self.word_starts = list(zip(word_keys, word_positions))

    def exact(self, key):
        target = key.encode("utf-8")
        for number, stored in enumerate(self.keys):
            if stored == target:
                return [self.records[r] for r in self.postings[number]]
        return []

    def word_suffixes(self):
        return [self.keys[key][position:] for key, position in self.word_starts]

    def by_qid(self, q):
        return next((record for record in self.records if record["qid"] == q), None)


def _keys_and_postings(data, blob_at, key_offsets_at, posting_offsets_at, postings_at,
                       key_count, posting_count):
    key_offsets = _array(data, key_offsets_at, key_count + 1, "I")
    keys = [data[blob_at + key_offsets[n]:blob_at + key_offsets[n + 1]] for n in range(key_count)]
    posting_offsets = _array(data, posting_offsets_at, key_count + 1, "I")
    postings = _array(data, postings_at, posting_count, "I")
    return keys, [postings[posting_offsets[n]:posting_offsets[n + 1]] for n in range(key_count)]


class DetailsPack:
    def __init__(self, data):
        self.data = data
        at = _preamble(data, "details")
        (self.record_count, self.entity_count, self.country_count, self.relation_ref_count,
         self.country_ref_count, self.key_count, self.posting_count,
         self.title_posting_count) = DETAILS_COUNTS.unpack_from(data, at)
        at += DETAILS_COUNTS.size
        offsets = DETAILS_OFFSETS.unpack_from(data, at)
        self.header_size = at + DETAILS_OFFSETS.size
        (records_at, entities_at, countries_at, pool_at, relation_refs_at, country_refs_at,
         blob_at, key_offsets_at, posting_offsets_at, postings_at, title_offsets_at,
         title_postings_at, self.end) = offsets
        self.size = len(data)
        self.offsets = offsets
        pool = data[pool_at:relation_refs_at]
        self.entities = []
        for number in range(self.entity_count):
            q, label_at, label_length, fame, kind = ENTITY.unpack_from(
                data, entities_at + number * ENTITY.size)
            self.entities.append({"qid": f"Q{q}", "label": _text(pool, label_at, label_length),
                                  "fame": fame, "kind": RELATION_KINDS[kind]})
        self.countries = []
        for number in range(self.country_count):
            q, english_at, english_length, code = COUNTRY.unpack_from(
                data, countries_at + number * COUNTRY.size)
            self.countries.append((f"Q{q}", code.rstrip(b"\0").decode("ascii") or None,
                                   _text(pool, english_at, english_length)))
        relation_refs = _array(data, relation_refs_at, self.relation_ref_count, "I")
        country_refs = _array(data, country_refs_at, self.country_ref_count, "H")
        self.records = []
        for number in range(self.record_count):
            (q, relation_at, origins_at, episodes, minutes, *counts) = DETAILS_RECORD.unpack_from(
                data, records_at + number * DETAILS_RECORD.size)
            *relation_counts, origin_count = counts
            record = {"qid": f"Q{q}", "minutes": minutes or None, "episodes": episodes or None,
                      "countries": [self.countries[r] for r in
                                    country_refs[origins_at:origins_at + origin_count]]}
            for kind, count in zip(RELATION_KINDS, relation_counts):
                record[kind] = [(self.entities[r]["qid"], self.entities[r]["label"])
                                for r in relation_refs[relation_at:relation_at + count]]
                relation_at += count
            self.records.append(record)
        self.keys, self.postings = _keys_and_postings(
            data, blob_at, key_offsets_at, posting_offsets_at, postings_at, self.key_count,
            self.posting_count)
        title_offsets = _array(data, title_offsets_at, self.entity_count + 1, "I")
        title_postings = _array(data, title_postings_at, self.title_posting_count, "I")
        self.title_postings = [title_postings[title_offsets[n]:title_offsets[n + 1]]
                               for n in range(self.entity_count)]

    def by_qid(self, q):
        return next((record for record in self.records if record["qid"] == q), None)

    def entities_named(self, key):
        target = key.encode("utf-8")
        for number, stored in enumerate(self.keys):
            if stored == target:
                return [(n, self.entities[n]) for n in self.postings[number]]
        return []

    def titles_of(self, entity_number):
        return [self.records[r]["qid"] for r in self.title_postings[entity_number]]


def read_core(path):
    return CorePack(gzip.decompress(path.read_bytes()))


def read_details(path):
    return DetailsPack(gzip.decompress(path.read_bytes()))
