from __future__ import annotations

import importlib.util
import unittest
import urllib.parse
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "fetch_nhtsa.py"
SPEC = importlib.util.spec_from_file_location("fetch_nhtsa", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class NHTSAFetchTests(unittest.TestCase):
    def test_civic_maps_only_after_catalog_confirms_base_model(self) -> None:
        variants = MODULE.expand_official_models("Civic", "Honda", 2023, ["ACCORD", "CIVIC", "CR-V"])
        self.assertEqual(variants, ["CIVIC SEDAN", "CIVIC HATCHBACK", "CIVIC SEDAN SI", "CIVIC HATCHBACK TYPE R"])

    def test_civic_mapping_rejects_unconfirmed_catalog(self) -> None:
        with self.assertRaisesRegex(ValueError, "未确认"):
            MODULE.expand_official_models("Civic", "Honda", 2023, ["ACCORD"])

    def test_url_encodes_spaces_in_official_model(self) -> None:
        query = urllib.parse.urlencode({"make": "Honda", "model": "CIVIC HATCHBACK TYPE R", "modelYear": 2023})
        self.assertIn("model=CIVIC+HATCHBACK+TYPE+R", query)
        self.assertNotIn("model=CIVIC HATCHBACK TYPE R", query)

    def test_empty_success_message_is_unverified(self) -> None:
        self.assertEqual(MODULE.classify_complaints_response({"count": 0, "message": "Results returned successfully"}, 400), "EMPTY_RESPONSE_UNVERIFIED")

    def test_other_400_is_failed(self) -> None:
        self.assertEqual(MODULE.classify_complaints_response({"count": 0, "message": "Bad model"}, 400), "failed")

    def test_unverified_models_are_not_complete(self) -> None:
        required = set(MODULE.HONDA_CIVIC_VARIANTS)
        statuses = {name: "ok" for name in MODULE.HONDA_CIVIC_VARIANTS[:-1]}
        self.assertFalse(required.issubset(statuses) and all(statuses.get(name) in {"ok", "EMPTY_RESPONSE_UNVERIFIED"} for name in required))


if __name__ == "__main__":
    unittest.main()
