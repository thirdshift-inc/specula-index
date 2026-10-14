# Pack usage

## Reading a pack

Download the manifest, then each pack from the release its `tag` names. Check the SHA-256, unpack it with gzip and read the sections. This reads every core record:

```python
import gzip, hashlib, json, struct, urllib.request

latest = "https://github.com/thirdshift-inc/specula-index/releases/latest/download/manifest.json"
manifest = json.load(urllib.request.urlopen(latest))
core = next(pack for pack in manifest["packs"] if pack["name"] == "core")
url = f"https://github.com/thirdshift-inc/specula-index/releases/download/{manifest['tag']}/{core['file']}"
packed = urllib.request.urlopen(url).read()
assert hashlib.sha256(packed).hexdigest() == core["gzipSha256"]
data = gzip.decompress(packed)

record_count = struct.unpack_from("<I", data, 16)[0]
records_at, pool_at = struct.unpack_from("<2I", data, 40)
for n in range(record_count):
    (qid, imdb, tmdb, tvdb, label_at, label_length, year, kind, flags,
     seasons, genre_at, genre_count, fame) = struct.unpack_from(
        "<IIIIIHHBBHIBxH", data, records_at + 36 * n)
    label = data[pool_at + label_at:pool_at + label_at + label_length].decode()
    print(f"Q{qid}", label, year, ("film", "series")[kind])
```

[`tests/packreader.py`](tests/packreader.py) reads every section of both packs.

## Layout

Both packs are little-endian. Header offsets count bytes from the start of the unpacked pack. Every section starts on a 4-byte boundary padded with zeros. The last offset is the end of the pack.

Text is UTF-8 in the pool section. It is addressed by a start relative to the pool and a length in bytes.

### Core

| Bytes | Header (84 bytes) |
| --- | --- |
| 0 | Magic `SPTI`, `u16` format `1`, `u16` reserved `0` and the name `core` padded with zeros to 8 bytes |
| 16 | 6 × `u32` counts: records, keys, postings, word starts, genres, genre references |
| 40 | 11 × `u32` offsets: records, pool, key text, key offsets, posting offsets, postings, word-start keys, word-start positions, genres, genre references, end |

| Bytes | Record (36 bytes), sorted by Wikidata id |
| --- | --- |
| 0 | `u32` Wikidata id without the `Q` |
| 4 | `u32` IMDb id without `tt`, `0` if none. Write it back as `tt` and at least seven digits |
| 8 | `u32` TMDB id, `0` if none |
| 12 | `u32` TVDB id, `0` if none |
| 16 | `u32` label start and `u16` label length |
| 22 | `u16` year |
| 24 | `u8` kind (`0` film, `1` series) and `u8` flags |
| 26 | `u16` seasons |
| 28 | `u32` first genre reference, `u8` genre count and 1 byte padding |
| 34 | `u16` fame |

- A genre is 12 bytes: `u32` Wikidata id, `u32` label start, `u16` label length and 2 bytes padding.
- Genre references are `u16` genre numbers.
- Key text is every search key sorted by bytes. Key offsets are `keys + 1` × `u32` into the key text, so key `n` runs from offset `n` to offset `n + 1`.
- Posting offsets are `keys + 1` × `u32` into postings. Postings are `u32` record numbers.
- Word starts find a word inside a key. Entry `n` pairs a `u32` key number from the word-start keys with a `u16` position from the word-start positions. Entries are sorted by the key's text from that position on.

### Details

| Bytes | Header (100 bytes) |
| --- | --- |
| 0 | Magic `SPTI`, `u16` format `1`, `u16` reserved `0` and the name `details` padded with zeros to 8 bytes |
| 16 | 8 × `u32` counts: records, entities, countries, relation references, country references, keys, postings, title postings |
| 48 | 13 × `u32` offsets: records, entities, countries, pool, relation references, country references, key text, key offsets, posting offsets, postings, title offsets, title postings, end |

| Bytes | Record (28 bytes), sorted by Wikidata id |
| --- | --- |
| 0 | `u32` Wikidata id |
| 4 | `u32` first relation reference |
| 8 | `u32` first country reference |
| 12 | `u32` episodes, `0` if unknown |
| 16 | `u16` running time in minutes, `0` if unknown |
| 18 | 6 × `u8` counts: cast, director, company, broadcaster, series, franchise |
| 24 | `u8` country count and 3 bytes padding |

- Only titles with at least one detail have a record.
- Relation references are `u32` entity numbers. The six kinds follow one another in the order of the counts.
- Country references are `u16` country numbers.
- An entity is 16 bytes: `u32` Wikidata id, `u32` label start, `u16` label length, `u16` fame, `u8` kind (`0` cast to `5` franchise in the order above) and 3 bytes padding. Entities are sorted by kind, then by Wikidata id. Someone who is both cast and director appears once as each.
- A country is 12 bytes: `u32` Wikidata id, `u32` label start, `u16` label length and its two-letter ISO code or two zero bytes.
- Keys work as in core. Their postings are entity numbers, most famous first.
- Title offsets are `entities + 1` × `u32` into title postings. Title postings are details record numbers, most famous first.

## Search keys

To make a key, read `&` as `and`, put the name in lower case and split it into words of letters and digits. Remove diacritics and turn `ł`, `đ`, `ø`, `ħ` and `ı` into `l`, `d`, `o`, `h` and `i`. Join the words with hyphens. `Léon: The Professional` becomes `leon-the-professional`.

Make the same key from a search to look it up. [`specula_index/normalise.py`](specula_index/normalise.py) is the reference.

A title is found by its original title, its English label, its English aliases and its label in its original language. An entity is found by its English label.
