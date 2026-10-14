# specula-index

A weekly index of films and series built from Wikidata for Specula, free for anyone to use.

[Pack example](pack-example.md) · [Pack usage](pack-usage.md) · [Releases](https://github.com/thirdshift-inc/specula-index/releases)

## Quick start

The manifest of the latest release lists its packs:

```sh
curl -sL https://github.com/thirdshift-inc/specula-index/releases/latest/download/manifest.json
```

[Pack usage](pack-usage.md) shows how to download, verify and read them.

## Release files

| File | Holds |
| --- | --- |
| `manifest.json` | Release tag, build time, Wikidata snapshot, sizes and SHA-256 of each pack |
| `core-<date>.f1.idx.gz` | Title search keys and one record per film or series with its Wikidata, IMDb, TMDB and TVDB ids |
| `details-<date>.f1.idx.gz` | Cast, directors, companies, broadcasters, series, franchises, countries, running time and episodes |

## Building locally

Python 3.12 with no dependencies:

```sh
python -m unittest -v
python -m specula_index.build --fixture tests/fixture/raw --out dist --date 2026-10-08
```

Without `--fixture` the build queries QLever's Wikidata endpoint. It refuses a result under 100,000 titles or more than 10 percent below the previous release.

## Releases

`.github/workflows/build.yml` builds every Monday at 04:23 UTC and publishes `index-<date>` as the latest release. The five newest releases are kept. A refused build publishes nothing. Only one build per day can be published.

## Licence

The code is MIT, copyright (c) 2026 thirdshift-inc. See [LICENSE](LICENSE).

The data comes from Wikidata under CC0 1.0. Every release carries this line:

> Film and series data comes from Wikidata, which dedicates it to the public domain under CC0 1.0.
