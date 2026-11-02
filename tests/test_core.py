from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.core import DataStore, ToolBox, add_human_feedback, load_state, run_investigation, validate_fact_claim, validate_action, _verify_result, _new_state, _add_ledger_entries
from agent.evaluation import citations_are_verifiable, evidence_source_record_ids


class ToolBoxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.toolbox = ToolBox()

    def test_search_excludes_records_after_cutoff(self) -> None:
        result = self.toolbox.call("search_records", {"filters": {}}, "EA23003", "2023-08-01")
        self.assertTrue(result["ok"])
        self.assertTrue(all(row["received_date"] <= "2023-08-01" for row in result["data"]["records"]))

    def test_holdout_evidence_never_leaks_into_retrieval(self) -> None:
        result = self.toolbox.call("retrieve_evidence", {"query": "close resume EA23003"}, "EA23003", "2025-12-31")
        self.assertTrue(result["ok"])
        ids = [row["evidence_id"] for row in result["data"]["evidence"]]
        self.assertNotIn("GOLD-EA23003-CLOSE", ids)

    def test_action_cannot_override_task_cutoff(self) -> None:
        result = self.toolbox.call("search_records", {"cutoff_date": "2025-12-31", "filters": {}}, "EA23003", "2023-08-01")
        self.assertTrue(result["ok"])
        self.assertTrue(all(row["received_date"] <= "2023-08-01" for row in result["data"]["records"]))

    def test_invalid_date_is_readable_error(self) -> None:
        result = self.toolbox.call("search_records", {}, "EA23003", "2023/11/28")
        self.assertFalse(result["ok"])
        self.assertIn("YYYY-MM-DD", result["error"])

    def test_unknown_tool_fails_closed(self) -> None:
        result = self.toolbox.call("delete_records", {}, "EA23003", "2023-11-28")
        self.assertFalse(result["ok"])
        self.assertIn("未知工具", result["error"])

    def test_nonexistent_model_returns_empty(self) -> None:
        result = self.toolbox.call("search_records", {"filters": {"model": "not-real"}}, "EA23003", "2023-11-28")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["count"], 0)


class DataImportTests(unittest.TestCase):
    def test_import_requires_consistent_case_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cases.json").write_text('[{"case_id":"CASE-1","component":"brakes"}]', encoding="utf-8")
            (root / "records.json").write_text('[{"record_id":"R1","case_id":"CASE-2"}]', encoding="utf-8")
            (root / "evidence.json").write_text('[]', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "未声明的案例"):
                DataStore(root / "data").import_directory(root)

    def test_migration_selector_requires_close_material_and_different_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cases.json").write_text('[{"case_id":"A","component":"steering"},{"case_id":"B","component":"brakes"},{"case_id":"C","component":"tires"}]', encoding="utf-8")
            records = [
                {"record_id": "R1", "case_id": "B", "record_type": "complaint", "received_date": "2020-01-01"},
                {"record_id": "R2", "case_id": "C", "record_type": "complaint", "received_date": "2020-01-01"},
            ]
            (root / "records.json").write_text(__import__("json").dumps(records), encoding="utf-8")
            evidence = [
                {"evidence_id": "E1", "case_id": "B", "title": "final report", "published_date": "2021-01-01", "source_kind": "investigation_close"},
                {"evidence_id": "E2", "case_id": "C", "title": "service bulletin", "published_date": "2021-01-01", "source_kind": "bulletin"},
            ]
            (root / "evidence.json").write_text(__import__("json").dumps(evidence), encoding="utf-8")
            store = DataStore(root / "unused")
            store.imported_dir = root
            store.demo_dir = root / "missing"
            candidates = store.migration_candidates("A")
            self.assertEqual([case["case_id"] for case in candidates], ["B"])


class StageFourTests(unittest.TestCase):
    def test_action_schema_rejects_unknown_tool_and_wrong_arguments(self):
        for action in [
            {"type": "tool_call", "tool": "delete_records", "arguments": {}},
            {"type": "tool_call", "tool": "retrieve_evidence", "arguments": {}},
            {"type": "tool_call", "tool": "search_records", "arguments": {"filters": []}},
        ]:
            with self.assertRaises(ValueError):
                validate_action(action)

    def test_verifier_rejects_future_or_holdout_evidence(self):
        state = _new_state("EA23003", "2023-11-28", "test", "offline", "general")
        result = {"ok": True, "data": {"cutoff_date": state["cutoff_date"], "source_ids": ["E"], "source_urls": [], "evidence": [{"evidence_id": "E", "published_date": "2024-01-01", "source_url": "https://example.test"}]}}
        self.assertFalse(_verify_result(state, {"tool": "retrieve_evidence"}, result)["passed"])

    def test_stance_without_basis_is_not_accepted(self):
        state = _new_state("EA23003", "2023-11-28", "test", "offline", "general")
        _add_ledger_entries(state, {"data": {"evidence": [{"evidence_id": "E", "stance": "support"}]}})
        self.assertEqual(state["evidence_ledger"][0]["stance"], "needs_review")

    def test_failed_verification_replans_and_recovers(self):
        original = ToolBox.call
        calls = [0]
        def once_bad(box, name, arguments, case_id, cutoff):
            result = original(box, name, arguments, case_id, cutoff)
            if calls[0] == 0:
                result["data"]["cutoff_date"] = "invalid"
            calls[0] += 1
            return result
        with patch("agent.core.ToolBox.call", new=once_bad):
            state = run_investigation("EA23003", "replan", mode="offline")
        self.assertEqual(state["replan_count"], 1)
        self.assertTrue(any(p["subtask_id"] == "R1" and p["status"] == "completed" for p in state["plan"]))
        self.assertEqual(state["status"], "completed")
        saved = load_state(state["investigation_id"])
        self.assertEqual(saved["plan"], state["plan"])

    def test_verification_failure_stops_after_two_replans(self):
        original = ToolBox.call
        def always_bad(box, name, arguments, case_id, cutoff):
            result = original(box, name, arguments, case_id, cutoff)
            result["data"]["cutoff_date"] = "invalid"
            return result
        with patch("agent.core.ToolBox.call", new=always_bad):
            state = run_investigation("EA23003", "bounded replan", mode="offline")
        self.assertEqual(state["replan_count"], 2)
        self.assertEqual(state["status"], "needs_human_review")
        self.assertFalse(state["evidence_ledger"])
        self.assertLessEqual(state["steps"], 8)

    def test_resume_cannot_change_cutoff(self):
        state = _new_state("EA23003", "2023-11-28", "test", "offline", "general")
        with self.assertRaisesRegex(ValueError, "不可更换"):
            run_investigation("EA23003", "test", "2024-01-01", resume_state=state)


class FollowupLoopTests(unittest.TestCase):
    def test_evidence_document_count_is_distinct_from_source_record_coverage(self) -> None:
        docs = [{"evidence_id": "E1", "source_record_ids": ["R1", "R2"]}, {"evidence_id": "E2", "source_record_ids": ["R2", "R3"]}]
        self.assertEqual(len(docs), 2)
        self.assertEqual(evidence_source_record_ids(docs), ["R1", "R2", "R3"])

    def test_citation_verification_checks_cutoff_and_record_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cases.json").write_text('[{"case_id":"C1"}]', encoding="utf-8")
            (root / "records.json").write_text('[{"record_id":"R1","case_id":"C1","received_date":"2023-01-01"}]', encoding="utf-8")
            (root / "evidence.json").write_text('[]', encoding="utf-8")
            store = DataStore(root)
            store.imported_dir = root
            store.demo_dir = root / "missing"
            store.processed_dir = root / "missing"
            ledger = [{"evidence_id": "E1", "published_date": "2023-01-01", "source_url": "https://example.test", "source_record_ids": ["R1"]}]
            self.assertTrue(citations_are_verifiable(ledger, store, "C1", "2023-11-28"))
            ledger[0]["source_record_ids"] = ["UNKNOWN"]
            self.assertFalse(citations_are_verifiable(ledger, store, "C1", "2023-11-28"))

    def test_unsourced_fact_claim_requires_review(self) -> None:
        result = validate_fact_claim("车辆存在安全缺陷", [], [])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["status"], "needs_review")

    def test_tool_result_has_audit_sources_and_cutoff(self) -> None:
        result = self.toolbox.call("search_records", {"filters": {}}, "EA23003", "2023-11-28") if hasattr(self, "toolbox") else ToolBox().call("search_records", {"filters": {}}, "EA23003", "2023-11-28")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["cutoff_date"], "2023-11-28")
        self.assertIsInstance(result["data"]["source_ids"], list)

    def test_human_feedback_is_saved_and_agent_continues(self) -> None:
        state = run_investigation("EA23003", "核查线索", mode="offline", focus="followup")
        self.assertTrue(state["followups"])
        before = len(state["tool_events"])
        updated = add_human_feedback(state["investigation_id"], state["followups"][0]["followup_id"], "维修记录显示无相关更换，仍需人工查看原单。")
        continued = run_investigation(updated["case_id"], updated["goal"], updated["cutoff_date"], updated["mode"], updated["focus"], updated)
        self.assertEqual(len(continued["human_feedback"]), 1)
        self.assertGreater(len(continued["tool_events"]), before)
        self.assertEqual(continued["status"], "completed")

    def test_failed_tool_is_retried_twice_then_stopped(self) -> None:
        action = {"type": "tool_call", "tool": "bad_tool", "arguments": {}}
        with patch("agent.core.OfflinePolicy.choose_action", return_value=action), patch("agent.core.ToolBox.call", return_value={"ok": False, "error": "synthetic failure"}):
            state = run_investigation("EA23003", "retry check", mode="offline")
        self.assertEqual(state["usage"]["tool_calls"], 3)
        self.assertEqual(state["status"], "needs_human_review")
        self.assertEqual(state["errors"][-1]["attempts"], 3)

    def test_model_filter_aliases_are_normalized_before_tool_call(self) -> None:
        action = {"type": "tool_call", "tool": "analyze_trend", "arguments": {"filters": {"modelYear": 2023, "case_id": "EA23003", "cutoff_date": "2099-01-01"}}}
        with patch.dict("os.environ", {"MODEL_API_KEY": "test", "MODEL_NAME": "/model"}), patch("agent.core.OpenAICompatibleClient.choose_action", return_value=action):
            state = run_investigation("EA23003", "alias normalization", mode="api", focus="trend")
        self.assertTrue(state["tool_events"])
        self.assertTrue(state["tool_events"][0]["ok"])
        self.assertEqual(state["tool_events"][0]["arguments"]["filters"]["model_year"], 2023)
        self.assertNotIn("case_id", state["tool_events"][0]["arguments"]["filters"])


if __name__ == "__main__":
    unittest.main()
