import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from specula_index import build, floor, manifest, pack
from specula_index.normalise import index_key
from tests.packreader import RELATION_KINDS, read_core, read_details

REPOSITORY = Path(__file__).resolve().parent.parent
FIXTURE = REPOSITORY / "tests" / "fixture" / "raw"
VERSION = "2026-10-05"
HASH_SEEDS = (1, 2, 3, 4)

SAME_TITLE_1978 = "Q900000001"
SAME_TITLE_2018 = "Q900000002"
CAPPED_CAST = "Q900000003"
SERIES_WITH_SEASONS = "Q900000004"
ALIASED_FILM = "Q900000005"
ADULT_BY_CLASS = "Q900000006"
ADULT_BY_GENRE = "Q900000007"
NAMELESS = "Q900000008"
UNSEARCHABLE = "Q900000009"
SERIES_WITH_FILM_ID = "Q900000010"
ORIGINAL_TITLE_ONLY = "Q900000011"
ORIGINAL_LANGUAGE_LABEL_ONLY = "Q900000012"
POLISH_AND_ALIAS_ONLY = "Q900000013"
OBSCURE_COMPANY = "Q900500001"
FAMOUS_COMPANY = "Q900500002"
ADULT_TITLE_COMPANY = "Q900500003"
COMPANY_AND_BROADCASTER = "Q900600001"
FILM_SERIES = "Q900700001"
FRANCHISE = "Q900800001"
UNLABELLED_FRANCHISE = "Q900800002"
POLISH_LABELS = ("Także po polsku", "Obsada", "Tytuł z Ś", "Tytuł oryginalny", "W oryginale",
                 "Tylko po polsku")
ADULT_GENRE = "Q291"


def person(number):
    return f"Q9004000{number:02d}"


class FixtureBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        cls.document, cls.report = build.build(cls.out, VERSION, FIXTURE)
        cls.core_entry, cls.details_entry = cls.document["packs"]
        cls.core = read_core(cls.out / cls.core_entry["file"])
        cls.details = read_details(cls.out / cls.details_entry["file"])

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()


class Determinism(unittest.TestCase):
    def build_in_a_subprocess(self, out, hash_seed):
        environment = {**os.environ, "PYTHONHASHSEED": str(hash_seed)}
        subprocess.run(
            [sys.executable, "-m", "specula_index.build", "--out", str(out), "--date", VERSION,
             "--fixture", str(FIXTURE)],
            cwd=REPOSITORY, env=environment, check=True, capture_output=True)
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(out.iterdir())}

    def test_the_same_input_and_date_give_the_same_bytes(self):
        hashes = []
        for seed in HASH_SEEDS:
            with tempfile.TemporaryDirectory() as out:
                hashes.append(self.build_in_a_subprocess(Path(out), seed))
        self.assertEqual(3, len(hashes[0]))
        for other in hashes[1:]:
            self.assertEqual(hashes[0], other)


class CorePack(FixtureBuild):
    def test_every_section_ends_where_the_header_says(self):
        self.assertEqual(self.core.size, self.core.end)
        self.assertEqual(self.core.header_size, self.core.offsets[0])
        self.assertEqual(list(self.core.offsets), sorted(self.core.offsets))
        self.assertEqual(self.core.keys, sorted(self.core.keys))
        self.assertEqual(self.core.word_suffixes(), sorted(self.core.word_suffixes()))

    def test_a_film_reads_back_with_its_genres(self):
        film = self.core.by_qid(SAME_TITLE_1978)
        self.assertEqual("Same Title", film["label"])
        self.assertEqual(1978, film["year"])
        self.assertEqual("tt9000001", film["imdb"])
        self.assertEqual(900001, film["tmdb"])
        self.assertEqual(
            [("Q900100001", "horror film"), ("Q900100002", "thriller film")],
            film["genres"])
        self.assertEqual(0, film["seasons"])

    def test_a_series_reads_back_with_its_genre_and_largest_season_count(self):
        series = self.core.by_qid(SERIES_WITH_SEASONS)
        self.assertEqual("series", series["type"])
        self.assertEqual(2011, series["year"])
        self.assertEqual(900004, series["tmdb"])
        self.assertEqual(90004, series["tvdb"])
        self.assertEqual(4, series["seasons"])
        self.assertEqual([("Q900100003", "drama television series")], series["genres"])

    def test_a_season_count_that_is_not_a_whole_number_is_dropped_and_counted(self):
        self.assertEqual(0, self.core.by_qid(SERIES_WITH_FILM_ID)["seasons"])
        self.assertEqual(3, self.report["counts"]["seasons_dropped"])

    def test_two_films_of_one_name_share_a_key(self):
        years = sorted(record["year"] for record in self.core.exact("same-title"))
        self.assertEqual([1978, 2018], years)

    def test_a_translated_title_is_reachable_through_its_alias(self):
        found = self.core.exact(index_key("Polski alias"))
        self.assertEqual([ALIASED_FILM], [record["qid"] for record in found])
        self.assertEqual("Aliased Film", found[0]["label"])

    def test_a_row_with_no_searchable_name_is_left_out(self):
        self.assertIsNone(self.core.by_qid(NAMELESS))
        self.assertIsNone(self.core.by_qid(UNSEARCHABLE))
        self.assertIsNone(self.details.by_qid(UNSEARCHABLE))

    def test_a_word_inside_a_title_is_a_word_start(self):
        self.assertIn(b"cast", self.core.word_suffixes())


class DisplayLabel(FixtureBuild):
    def test_the_english_label_is_shown(self):
        self.assertEqual("Same Title", self.core.by_qid(SAME_TITLE_1978)["label"])
        self.assertEqual("Aliased Film", self.core.by_qid(ALIASED_FILM)["label"])

    def test_without_english_the_original_title_is_shown(self):
        self.assertEqual("Titre original", self.core.by_qid(ORIGINAL_TITLE_ONLY)["label"])

    def test_without_either_the_label_in_the_original_language_is_shown(self):
        self.assertEqual("Originalsprache",
                         self.core.by_qid(ORIGINAL_LANGUAGE_LABEL_ONLY)["label"])

    def test_a_row_named_only_in_polish_or_by_alias_is_dropped_and_counted(self):
        self.assertIsNone(self.core.by_qid(POLISH_AND_ALIAS_ONLY))
        self.assertEqual([], self.core.exact(index_key("Tylko po polsku")))
        self.assertEqual(2, self.report["counts"]["no_display_label_dropped"])

    def test_no_polish_label_is_ever_shown(self):
        shown = {record["label"] for record in self.core.records}
        for label in POLISH_LABELS:
            with self.subTest(label=label):
                self.assertNotIn(label, shown)
                self.assertNotIn(label.encode("utf-8"), self.core.data)
                self.assertNotIn(label.encode("utf-8"), self.details.data)

    def test_a_polish_title_still_finds_the_film(self):
        for polish, q, shown in (("Także po polsku", SAME_TITLE_1978, "Same Title"),
                                 ("Tytuł oryginalny", ORIGINAL_TITLE_ONLY, "Titre original"),
                                 ("W oryginale", ORIGINAL_LANGUAGE_LABEL_ONLY, "Originalsprache")):
            with self.subTest(polish=polish):
                found = self.core.exact(index_key(polish))
                self.assertEqual([q], [record["qid"] for record in found])
                self.assertEqual(shown, found[0]["label"])


class TmdbKind(FixtureBuild):
    TMDB_OTHER_KIND = 2

    def tmdb_and_flags(self, q):
        record = self.core.by_qid(q)
        return record["tmdb"], record["flags"]

    def test_a_film_with_its_own_kind_of_id_is_not_flagged(self):
        self.assertEqual((900001, 0), self.tmdb_and_flags(SAME_TITLE_1978))

    def test_a_series_with_its_own_kind_of_id_is_not_flagged(self):
        self.assertEqual((900004, 0), self.tmdb_and_flags(SERIES_WITH_SEASONS))

    def test_a_film_with_both_kinds_keeps_its_own_and_is_not_flagged(self):
        self.assertEqual((900002, 0), self.tmdb_and_flags(SAME_TITLE_2018))

    def test_a_film_holding_only_a_series_id_is_flagged(self):
        self.assertEqual((900003, self.TMDB_OTHER_KIND), self.tmdb_and_flags(CAPPED_CAST))

    def test_a_series_holding_only_a_film_id_is_flagged(self):
        self.assertEqual((900010, self.TMDB_OTHER_KIND), self.tmdb_and_flags(SERIES_WITH_FILM_ID))

    def test_a_record_with_no_tmdb_id_is_not_flagged(self):
        self.assertEqual((None, 0), self.tmdb_and_flags(ALIASED_FILM))

    def test_the_fallbacks_are_counted(self):
        self.assertEqual(2, self.report["core"]["tmdb_other_kind_fallbacks"])


class Fame(FixtureBuild):
    def test_fame_reads_back_per_record(self):
        self.assertEqual(12, self.core.by_qid(SAME_TITLE_1978)["fame"])
        self.assertEqual(55, self.core.by_qid(SAME_TITLE_2018)["fame"])

    def test_a_missing_or_unreadable_fame_reads_zero(self):
        self.assertEqual(0, self.core.by_qid(SERIES_WITH_FILM_ID)["fame"])
        self.assertEqual(0, self.core.by_qid(ORIGINAL_LANGUAGE_LABEL_ONLY)["fame"])
        self.assertEqual(1, self.report["counts"]["fame_dropped"])
        self.assertEqual(2, self.report["core"]["records_with_fame_0"])

    def test_fame_saturates_at_the_largest_u16(self):
        self.assertEqual(0xFFFF, self.core.by_qid(ORIGINAL_TITLE_ONLY)["fame"])


class Entities(FixtureBuild):
    def named(self, name, kind=None):
        return [(number, entity) for number, entity in self.details.entities_named(index_key(name))
                if kind is None or entity["kind"] == kind]

    def test_every_entity_section_is_in_order(self):
        self.assertEqual(self.details.keys, sorted(self.details.keys))
        order = [(RELATION_KINDS.index(e["kind"]), int(e["qid"][1:]))
                 for e in self.details.entities]
        self.assertEqual(sorted(order), order)

    def test_a_company_name_finds_its_titles_in_fame_order(self):
        number, company = self.named("Same Named Company")[0]
        self.assertEqual((FAMOUS_COMPANY, "company", 40),
                         (company["qid"], company["kind"], company["fame"]))
        self.assertEqual([SAME_TITLE_2018, CAPPED_CAST, SAME_TITLE_1978],
                         self.details.titles_of(number))

    def test_same_named_entities_are_resolved_by_fame(self):
        named = self.named("Same Named Company")
        self.assertEqual([FAMOUS_COMPANY, OBSCURE_COMPANY], [entity["qid"] for _, entity in named])
        self.assertEqual([ALIASED_FILM], self.details.titles_of(named[1][0]))

    def test_a_broadcaster_search_returns_only_what_it_broadcast(self):
        [(number, _)] = self.named("Company And Broadcaster", "broadcaster")
        self.assertEqual([SERIES_WITH_SEASONS, SERIES_WITH_FILM_ID], self.details.titles_of(number))
        [(produced, _)] = self.named("Company And Broadcaster", "company")
        self.assertEqual([ALIASED_FILM], self.details.titles_of(produced))

    def test_series_and_franchise_find_their_titles(self):
        [(film_series, _)] = self.named("Film Series", "series")
        self.assertEqual([SAME_TITLE_2018, SAME_TITLE_1978], self.details.titles_of(film_series))
        [(franchise, _)] = self.named("Franchise", "franchise")
        self.assertEqual([CAPPED_CAST, ALIASED_FILM], self.details.titles_of(franchise))

    def test_relations_read_back_per_record(self):
        aliased = self.details.by_qid(ALIASED_FILM)
        self.assertEqual([(OBSCURE_COMPANY, "Same Named Company"),
                          (COMPANY_AND_BROADCASTER, "Company And Broadcaster")], aliased["company"])
        self.assertEqual([(FRANCHISE, "Franchise")], aliased["franchise"])
        film = self.details.by_qid(SAME_TITLE_1978)
        self.assertEqual([(FILM_SERIES, "Film Series")], film["series"])
        self.assertEqual([(COMPANY_AND_BROADCASTER, "Company And Broadcaster")],
                         self.details.by_qid(SERIES_WITH_SEASONS)["broadcaster"])

    def test_an_entity_without_an_english_label_is_kept_unnamed(self):
        franchises = self.details.by_qid(SAME_TITLE_2018)["franchise"]
        self.assertEqual([(UNLABELLED_FRANCHISE, None)], franchises)
        self.assertEqual(len(self.details.keys), len(set(self.details.keys)))

    def test_an_entity_known_only_from_an_adult_title_is_absent(self):
        self.assertNotIn(ADULT_TITLE_COMPANY, [entity["qid"] for entity in self.details.entities])
        self.assertEqual([], self.named("Adult Title Company"))

    def test_no_reverse_posting_reaches_an_adult_title(self):
        reached = {q for number in range(self.details.entity_count)
                   for q in self.details.titles_of(number)}
        self.assertNotIn(ADULT_BY_CLASS, reached)
        self.assertNotIn(ADULT_BY_GENRE, reached)

    def test_the_counts_for_the_real_run_are_reported(self):
        self.assertEqual({"cast": 8, "director": 2, "company": 3, "broadcaster": 1, "series": 1,
                          "franchise": 2}, self.report["details"]["entities_per_kind"])
        self.assertEqual({"cast": 10, "director": 3, "company": 5, "broadcaster": 2, "series": 2,
                          "franchise": 3}, self.report["details"]["refs_per_kind"])


class DetailsPack(FixtureBuild):
    def test_every_section_ends_where_the_header_says(self):
        self.assertEqual(self.details.size, self.details.end)
        self.assertEqual(self.details.header_size, self.details.offsets[0])
        self.assertEqual(list(self.details.offsets), sorted(self.details.offsets))

    def test_every_details_qid_is_in_core(self):
        core_qids = {record["qid"] for record in self.core.records}
        self.assertTrue({record["qid"] for record in self.details.records} <= core_qids)

    def test_duration_in_seconds_reads_in_minutes(self):
        self.assertEqual(90, self.details.by_qid(SAME_TITLE_1978)["minutes"])

    def test_duration_in_hours_reads_in_minutes(self):
        self.assertEqual(120, self.details.by_qid(SAME_TITLE_2018)["minutes"])

    def test_duration_in_an_unknown_unit_is_dropped_and_counted(self):
        self.assertEqual(95, self.details.by_qid(CAPPED_CAST)["minutes"])
        self.assertEqual(1, self.report["counts"]["duration_unit_dropped"])

    def test_cast_is_ordered_by_ordinal_then_qid_and_capped(self):
        cast = [qid for qid, _ in self.details.by_qid(CAPPED_CAST)["cast"]]
        expected = [person(n) for n in (5, 3, 9, 1, 2, 4, 6, 7)]
        self.assertEqual(expected, cast)

    def test_people_carry_their_labels(self):
        film = self.details.by_qid(SAME_TITLE_1978)
        self.assertEqual([(person(2), "Cast Two"), (person(1), "Cast One")], film["cast"])
        self.assertEqual([(person(11), "Director One")], film["director"])

    def test_country_carries_its_code_and_labels(self):
        self.assertEqual([("Q30", "US", "United States")],
                         self.details.by_qid(SAME_TITLE_1978)["countries"])

    def test_episodes_belong_to_series_only(self):
        self.assertEqual(40, self.details.by_qid(SERIES_WITH_SEASONS)["episodes"])
        self.assertIsNone(self.details.by_qid(CAPPED_CAST)["episodes"])
        self.assertEqual(1, self.report["counts"]["episodes_on_film_dropped"])


class AdultExclusion(FixtureBuild):
    def test_neither_adult_row_reaches_core(self):
        qids = {record["qid"] for record in self.core.records}
        self.assertNotIn(ADULT_BY_CLASS, qids)
        self.assertNotIn(ADULT_BY_GENRE, qids)

    def test_neither_adult_row_reaches_details(self):
        qids = {record["qid"] for record in self.details.records}
        self.assertNotIn(ADULT_BY_CLASS, qids)
        self.assertNotIn(ADULT_BY_GENRE, qids)

    def test_no_lookup_by_an_adult_title_finds_anything(self):
        self.assertEqual([], self.core.exact(index_key("Adult By Class")))
        self.assertEqual([], self.core.exact(index_key("Adult By Genre")))
        self.assertNotIn(b"class", self.core.word_suffixes())

    def test_the_adult_genre_is_not_in_the_genre_table(self):
        self.assertNotIn(ADULT_GENRE, [qid for qid, _ in self.core.genres])


class OrphanRefusal(unittest.TestCase):
    def test_details_for_a_qid_core_lacks_are_refused_and_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as scratch:
            raw = Path(scratch) / "raw"
            shutil.copytree(FIXTURE, raw)
            with open(raw / "cast.tsv", "a", encoding="utf-8") as cast:
                cast.write("<http://www.wikidata.org/entity/Q900000099>\t"
                           "<http://www.wikidata.org/entity/Q900400001>\t\n")
            out = Path(scratch) / "out"
            with self.assertRaises(pack.OrphanDetails) as refusal:
                build.build(out, VERSION, raw)
            self.assertEqual(["Q900000099"], refusal.exception.qids)
            self.assertFalse(out.exists() and any(out.iterdir()))

    def test_a_relation_for_a_qid_core_lacks_is_refused(self):
        with tempfile.TemporaryDirectory() as scratch:
            raw = Path(scratch) / "raw"
            shutil.copytree(FIXTURE, raw)
            with open(raw / "company.tsv", "a", encoding="utf-8") as company:
                company.write("<http://www.wikidata.org/entity/Q900000097>\t"
                              "<http://www.wikidata.org/entity/Q900500002>\n")
            with self.assertRaises(pack.OrphanDetails) as refusal:
                build.build(Path(scratch) / "out", VERSION, raw)
            self.assertEqual(["Q900000097"], refusal.exception.qids)

    def test_the_command_exits_non_zero_on_an_orphan(self):
        with tempfile.TemporaryDirectory() as scratch:
            raw = Path(scratch) / "raw"
            shutil.copytree(FIXTURE, raw)
            with open(raw / "episodes.tsv", "a", encoding="utf-8") as episodes:
                episodes.write("<http://www.wikidata.org/entity/Q900000098>\t7\n")
            with contextlib.redirect_stderr(io.StringIO()):
                status = build.main(["--out", str(Path(scratch) / "out"), "--date", VERSION,
                                     "--fixture", str(raw)])
            self.assertEqual(1, status)


class PackRefusal(unittest.TestCase):
    def test_the_command_exits_non_zero_on_a_genre_that_is_not_a_qid(self):
        with tempfile.TemporaryDirectory() as scratch:
            raw = Path(scratch) / "raw"
            shutil.copytree(FIXTURE, raw)
            with open(raw / "genre.tsv", "a", encoding="utf-8") as genre:
                genre.write(f"<http://www.wikidata.org/entity/{SAME_TITLE_1978}>\t"
                            "<http://www.wikidata.org/.well-known/genid/0123abcd>\n")
            refusal = io.StringIO()
            with contextlib.redirect_stderr(refusal):
                status = build.main(["--out", str(Path(scratch) / "out"), "--date", VERSION,
                                     "--fixture", str(raw)])
            self.assertEqual(1, status)
            self.assertTrue(refusal.getvalue().startswith("build refused: "))


class Manifest(FixtureBuild):
    def test_every_field_is_present_with_its_type(self):
        on_disk = json.loads((self.out / manifest.MANIFEST_FILE).read_text(encoding="utf-8"))
        self.assertEqual(self.document, on_disk)
        self.assertEqual(1, on_disk["schema"])
        self.assertEqual(VERSION, on_disk["version"])
        self.assertEqual(f"index-{VERSION}", on_disk["tag"])
        self.assertEqual(f"{VERSION}T00:00:00Z", on_disk["built"])
        self.assertEqual("Wikidata via QLever (2026-09-16T23:13:07Z)", on_disk["source"])
        self.assertEqual("MIT", on_disk["licence"])
        self.assertIsInstance(on_disk["attribution"], str)
        self.assertIn("Wikidata", on_disk["attribution"])
        self.assertEqual(["core", "details"], [entry["name"] for entry in on_disk["packs"]])
        for entry in on_disk["packs"]:
            self.assertEqual(
                {"name", "format", "file", "bytes", "sha256", "gzipBytes", "gzipSha256", "rows",
                 "keys"}, set(entry))
            self.assertEqual(1, entry["format"])
            self.assertEqual(f"{entry['name']}-{VERSION}.f1.idx.gz", entry["file"])
            for field in ("bytes", "gzipBytes", "keys"):
                self.assertIsInstance(entry[field], int)
            for field in ("sha256", "gzipSha256"):
                self.assertRegex(entry[field], r"^[0-9a-f]{64}$")
            self.assertEqual({"films", "series"}, set(entry["rows"]))

    def test_rows_and_keys_match_the_packs(self):
        self.assertEqual({"films": 6, "series": 2}, self.core_entry["rows"])
        self.assertEqual(8, floor.core_records(self.out / manifest.MANIFEST_FILE))
        self.assertEqual(len(self.core.keys), self.core_entry["keys"])
        self.assertEqual({"films": 4, "series": 2}, self.details_entry["rows"])
        self.assertEqual(len(self.details.keys), self.details_entry["keys"])

    def test_the_hashes_are_the_hashes_of_the_files(self):
        for entry in self.document["packs"]:
            compressed = (self.out / entry["file"]).read_bytes()
            self.assertEqual(entry["gzipSha256"], hashlib.sha256(compressed).hexdigest())
            self.assertEqual(entry["gzipBytes"], len(compressed))

    def test_a_pack_rewritten_after_its_hash_was_taken_is_refused(self):
        with tempfile.TemporaryDirectory() as scratch:
            out = Path(scratch)
            document, _ = build.build(out, VERSION, FIXTURE)
            before = (out / manifest.MANIFEST_FILE).read_bytes()
            core_file = out / document["packs"][0]["file"]
            core_file.write_bytes(manifest.gzipped(b"SPTI rewritten"))
            with self.assertRaises(manifest.ManifestMismatch):
                manifest.write(out, document)
            self.assertEqual(before, (out / manifest.MANIFEST_FILE).read_bytes())


class Floor(unittest.TestCase):
    MINIMUM = floor.MINIMUM_CORE_RECORDS
    PREVIOUS = MINIMUM * 10

    def test_fewer_records_than_the_minimum_are_refused(self):
        with self.assertRaisesRegex(floor.TooFewRecords, "minimum"):
            floor.check(self.MINIMUM - 1)

    def test_without_a_previous_release_only_the_minimum_applies(self):
        floor.check(self.MINIMUM)

    def test_a_drop_of_more_than_a_tenth_is_refused(self):
        for records in (self.PREVIOUS * 9 // 10 - 1, self.PREVIOUS // 2):
            with self.subTest(records=records), \
                    self.assertRaisesRegex(floor.TooFewRecords, "previous release"):
                floor.check(records, self.PREVIOUS)

    def test_a_small_drop_and_a_rise_are_allowed(self):
        for records in (self.PREVIOUS * 9 // 10, self.PREVIOUS - 1, self.PREVIOUS,
                        self.PREVIOUS * 2):
            with self.subTest(records=records):
                floor.check(records, self.PREVIOUS)

    def test_a_drop_does_not_excuse_a_count_below_the_minimum(self):
        with self.assertRaisesRegex(floor.TooFewRecords, "minimum"):
            floor.check(self.MINIMUM - 1, self.MINIMUM)


class RealBuild(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.cache = self.scratch / "cache"
        shutil.copytree(FIXTURE, self.cache)
        self.out = self.scratch / "out"
        self.previous = self.scratch / "previous.json"

    def run_build(self, *options):
        said = io.StringIO()
        with contextlib.redirect_stderr(said), contextlib.redirect_stdout(io.StringIO()):
            status = build.main(["--out", str(self.out), "--date", VERSION, *options])
        return status, said.getvalue()

    def run_real_build(self, *options):
        return self.run_build("--cache", str(self.cache), *options)

    def previous_with(self, films, series):
        rows = {"films": films, "series": series}
        self.previous.write_text(json.dumps({"packs": [{"name": "core", "rows": rows}]}),
                                 encoding="utf-8")
        return ("--previous-manifest", str(self.previous))

    def test_a_real_build_below_the_minimum_is_refused_and_nothing_is_written(self):
        status, said = self.run_real_build()
        self.assertEqual(1, status)
        self.assertIn("build refused: 8 core records, fewer than the minimum", said)
        self.assertFalse(self.out.exists())

    def test_a_real_build_that_lost_more_than_a_tenth_is_refused_and_nothing_is_written(self):
        with mock.patch.object(floor, "MINIMUM_CORE_RECORDS", 8):
            status, said = self.run_real_build(*self.previous_with(films=7, series=2))
        self.assertEqual(1, status)
        self.assertIn("build refused: 8 core records, more than 10 percent fewer", said)
        self.assertFalse(self.out.exists())

    def test_a_real_build_no_smaller_than_the_previous_one_is_written(self):
        with mock.patch.object(floor, "MINIMUM_CORE_RECORDS", 8):
            status, _ = self.run_real_build(*self.previous_with(films=6, series=2))
        self.assertEqual(0, status)
        self.assertEqual(8, floor.core_records(self.out / manifest.MANIFEST_FILE))

    def test_a_previous_manifest_that_cannot_be_read_is_refused(self):
        unreadable = ("", "[]", '{"packs": []}',
                      '{"packs": [{"name": "core", "rows": {"films": "many", "series": 0}}]}')
        for text in unreadable:
            with self.subTest(text=text):
                self.previous.write_text(text, encoding="utf-8")
                status, said = self.run_real_build("--previous-manifest", str(self.previous))
                self.assertEqual(1, status)
                self.assertTrue(said.startswith("build refused: "))
                self.assertFalse(self.out.exists())

    def test_a_previous_manifest_that_is_missing_is_refused(self):
        status, said = self.run_real_build("--previous-manifest", str(self.previous))
        self.assertEqual(1, status)
        self.assertTrue(said.startswith("build refused: "))

    def test_the_fixture_build_is_exempt(self):
        status, _ = self.run_build("--fixture", str(FIXTURE),
                                   *self.previous_with(films=1000000, series=0))
        self.assertEqual(0, status)
        self.assertEqual(8, floor.core_records(self.out / manifest.MANIFEST_FILE))


class FileNames(unittest.TestCase):
    def test_a_file_name_carrying_a_slash_is_refused(self):
        with self.assertRaises(manifest.UnsafeFileName):
            manifest.pack_file_name("core", "2026/10/05", 1)
        with self.assertRaises(manifest.UnsafeFileName):
            manifest.checked_file_name("packs/core.idx.gz")

    def test_a_file_name_climbing_out_is_refused(self):
        for name in ("..", "../core.idx.gz", ".hidden", ""):
            with self.subTest(name=name), self.assertRaises(manifest.UnsafeFileName):
                manifest.checked_file_name(name)

    def test_the_manifest_is_not_read_through_an_unsafe_name(self):
        with tempfile.TemporaryDirectory() as scratch:
            with self.assertRaises(manifest.UnsafeFileName):
                manifest.verify([{"file": "../outside.idx.gz"}], Path(scratch))

    def test_a_date_that_is_not_a_plain_date_is_refused(self):
        for date in ("2026/10/05", "2026-10-05/..", "2026-13-01"):
            with self.subTest(date=date), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit):
                build.arguments(["--out", "dist", "--date", date])


if __name__ == "__main__":
    unittest.main()
