from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.core import DataStore, _new_state, _required_next_action
from agent.evidence_graph import build_evidence_graph, graph_candidate_utilities
from agent.evaluation import decision_quality_score, dynamic_decision_metrics
from scripts.build_research_benchmark import build as build_research_benchmark


class ResearchFeatureTests(unittest.TestCase):
    def test_graph_excludes_future_records_and_holdout_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [{"case_id": "C1", "title": "case", "component": "steering"}]
            records = [
                {"record_id": "R1", "case_id": "C1", "received_date": "2023-01-01", "component": "steering", "text": "steering", "source_url": "u"},
                {"record_id": "R2", "case_id": "C1", "received_date": "2024-01-01", "component": "steering", "text": "future", "source_url": "u"},
            ]
            evidence = [
                {"evidence_id": "E1", "case_id": "C1", "title": "public", "content": "steering", "published_date": "2023-01-01", "source_url": "e", "source_kind": "public"},
                {"evidence_id": "E2", "case_id": "C1", "title": "holdout", "content": "steering", "published_date": "2023-01-01", "source_url": "h", "source_kind": "holdout", "holdout_only": True},
            ]
            for name, value in (("cases.json", cases), ("records.json", records), ("evidence.json", evidence)):
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            store = DataStore(root)
            store.imported_dir = root
            store.demo_dir = root / "missing"
            store.processed_dir = root / "missing"
            graph = build_evidence_graph(store, "C1", "2023-12-31")
            node_ids = {node["node_id"] for node in graph["nodes"]}
            self.assertIn("record:R1", node_ids)
            self.assertNotIn("record:R2", node_ids)
            self.assertIn("evidence:E1", node_ids)
            self.assertNotIn("evidence:E2", node_ids)

    def test_active_eig_candidates_are_sorted_and_deduplicated(self):
        state = _new_state("EA23003", "2023-11-28", "find counterevidence", "active_eig", "counterevidence")
        case = {"make": "Honda", "models": ["Civic"], "component": "steering"}
        candidates = graph_candidate_utilities(state, case)
        self.assertGreaterEqual(len(candidates), 4)
        self.assertEqual(candidates, sorted(candidates, key=lambda item: (-item["utility"], item["tool"], item["signature"])))
        state["action_signatures"].append(candidates[0]["signature"])
        reduced = graph_candidate_utilities(state, case)
        self.assertNotIn(candidates[0]["signature"], {item["signature"] for item in reduced})

    def test_research_benchmark_has_three_cutoffs_per_public_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_research_benchmark(Path(tmp) / "research_tasks.json")
            self.assertGreaterEqual(result["case_count"], 9)
            self.assertEqual(result["task_count"], result["case_count"] * 8 * 3)
            payload = json.loads((Path(tmp) / "research_tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload["tasks"]), result["task_count"])

    def test_v2_gate_requires_evidence_before_followup(self):
        state = _new_state("C1", "2023-01-01", "补查", "api", "followup")
        self.assertEqual(_required_next_action(state, {"component": "steering"})["tool"], "retrieve_evidence")
        state["evidence_ledger"].append({"evidence_id": "E1"})
        self.assertEqual(_required_next_action(state, {"component": "steering"})["tool"], "create_followup")

    def test_decision_value_rewards_actionable_counterevidence(self):
        task = {"focus": "counterevidence"}
        state = {"focus": "counterevidence", "tool_events": [
            {"tool": "retrieve_evidence", "ok": True, "verified": True, "arguments": {"query": "alternative explanation counterevidence"}, "signature": "a"},
            {"tool": "link_entities", "ok": True, "verified": True, "arguments": {"entity": "steering"}, "signature": "b"},
        ], "evidence_ledger": [{"evidence_id": "E1", "source_kind": "odi", "stance": "support"}, {"evidence_id": "E2", "source_kind": "manufacturer", "stance": "oppose"}], "followups": [], "errors": [], "stop_reason": "plan_verified"}
        score = decision_quality_score(state, task, True)
        self.assertGreaterEqual(score["score"], 90)
        self.assertNotIn("call_efficiency", score["components"])
        self.assertEqual(score["scoring"], "decision_value_v3")

    def test_dynamic_metrics_do_not_reward_extra_calls(self):
        task = {"scenario": "empty_recovery", "gold_next_action": "retrieve_evidence"}
        state = {"tool_events": [{"tool": "retrieve_evidence", "ok": True, "verified": True}], "stop_reason": "plan_verified", "decision_guards": []}
        metrics = dynamic_decision_metrics(state, task)
        self.assertEqual(metrics["branch_correct"], 1)
        state["tool_events"].append({"tool": "link_entities", "ok": True, "verified": True})
        self.assertEqual(dynamic_decision_metrics(state, task)["branch_correct"], 1)

    def test_v4_safety_gate_actions(self):
        state = _new_state("C1", "2023-01-01", "stop", "api", "evidence_sufficiency")
        state["dynamic_scenario"] = "evidence_sufficiency"
        state["steps"] = 1
        self.assertEqual(_required_next_action(state, {"component": "steering"})["type"], "done")
        state["dynamic_scenario"] = "followup_gap"
        self.assertEqual(_required_next_action(state, {"component": "steering"})["tool"], "create_followup")


if __name__ == "__main__":
    unittest.main()
