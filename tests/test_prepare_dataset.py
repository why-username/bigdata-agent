from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_dataset.py"
SPEC = importlib.util.spec_from_file_location("prepare_dataset", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class PrepareDatasetTests(unittest.TestCase):
    def test_normalization_preserves_rows_and_marks_duplicate_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "in"; output = root / "out"; source.mkdir()
            (source / "cases.json").write_text('[{"case_id":"A","component":"steering"}]', encoding="utf-8")
            rows = [
                {"record_id":"1","case_id":"A","make":"Honda","model":"Civic","model_year":2023,"official_model":"CIVIC SEDAN","component":"STEERING, SUSPENSION","occurred_date":"2023-01-01","received_date":"2023-01-02","text":"Same text","source_id":"1","source_url":"https://example/1","saved_at":"2023-01-03"},
                {"record_id":"2","case_id":"A","make":"Honda","model":"Civic","model_year":2023,"official_model":"CIVIC SEDAN","component":"STEERING, SUSPENSION","occurred_date":"2023-01-01","received_date":"2023-01-02","text":"Same   text","source_id":"2","source_url":"https://example/2","saved_at":"2023-01-03"},
            ]
            (source / "records.json").write_text(json.dumps(rows), encoding="utf-8")
            (source / "evidence.json").write_text("[]", encoding="utf-8")
            result = MODULE.prepare(source, output)
            self.assertEqual(result["normalized_record_count"], 2)
            self.assertEqual(result["duplicate_candidate_groups"], 1)
            normalized = json.loads((output / "records_normalized.json").read_text())
            self.assertEqual(normalized[0]["normalized_components"], ["STEERING", "SUSPENSION"])
            self.assertEqual(normalized[0]["official_id_duplicate_count"], 1)

    def test_inverted_dates_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "in"; output = root / "out"; source.mkdir()
            (source / "cases.json").write_text('[{"case_id":"A","component":"steering"}]', encoding="utf-8")
            row = {"record_id":"1","case_id":"A","make":"Honda","model":"Civic","model_year":2023,"official_model":"CIVIC","component":"STEERING","occurred_date":"2023-02-01","received_date":"2023-01-01","text":"x","source_id":"1","source_url":"u","saved_at":"s"}
            (source / "records.json").write_text(json.dumps([row]), encoding="utf-8")
            (source / "evidence.json").write_text("[]", encoding="utf-8")
            MODULE.prepare(source, output)
            report = json.loads((output / "data_quality_report.json").read_text())
            self.assertEqual(report["invalid_or_inverted_date_record_ids"], ["1"])


if __name__ == "__main__":
    unittest.main()
