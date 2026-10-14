# Pack example

Built from the test fixture in `tests/fixture/raw`.

## Manifest

```json
{
  "schema": 1,
  "version": "2026-10-12",
  "tag": "index-2026-10-12",
  "built": "2026-10-12T04:51:09Z",
  "source": "Wikidata via QLever (2026-09-16T23:13:07Z)",
  "licence": "MIT",
  "attribution": "Film and series data comes from Wikidata, which dedicates it to the public domain under CC0 1.0.",
  "packs": [
    {
      "name": "core",
      "format": 1,
      "file": "core-2026-10-12.f1.idx.gz",
      "bytes": 922,
      "sha256": "b5e2861ec0330aca99f73dbc851a5a4e4b9c415d8cbefcb104a5534415039851",
      "gzipBytes": 504,
      "gzipSha256": "1bc5c0be999049e62214cb3a5aa8e1bda72cfde561ce6f09d703333706e6e2c0",
      "rows": { "films": 6, "series": 2 },
      "keys": 10
    }
  ]
}
```

The `details` entry has the same fields. `bytes` and `sha256` describe the unpacked pack. `gzipBytes` and `gzipSha256` describe the downloaded file.

## Decoded title

```json
{
  "qid": "Q900000001",
  "label": "Same Title",
  "year": 1978,
  "type": "film",
  "imdb": "tt9000001",
  "tmdb": 900001,
  "tvdb": null,
  "seasons": 0,
  "fame": 12,
  "flags": 0,
  "genres": [["Q900100001", "horror film"], ["Q900100002", "thriller film"]],

  "minutes": 90,
  "episodes": null,
  "countries": [["Q30", "US", "United States"]],
  "cast": [["Q900400002", "Cast Two"], ["Q900400001", "Cast One"]],
  "director": [["Q900400011", "Director One"]],
  "company": [["Q900500002", "Same Named Company"]],
  "broadcaster": [],
  "series": [["Q900700001", "Film Series"]],
  "franchise": []
}
```

The fields up to `genres` come from core. The rest come from details.

- `label` is the English label, else the original title, else the label in the original language.
- `year` is the earliest publication year, else the earliest start year. `0` means unknown.
- `fame` is the number of Wikidata sitelinks, capped at 65,535.
- `tmdb` is a TMDB movie id for a film and a TV id for a series. A title that only has the other kind gets that id with `flags` bit 1 set.
- `flags` bit 0 marks an IMDb, TMDB or TVDB id that could not be stored as a number. That id reads as 0.
- `cast` holds up to eight people in billing order when Wikidata gives one.
- Adult titles are in neither pack.
