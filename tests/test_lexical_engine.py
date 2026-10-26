"""TEST_ONLY synthetic fixtures; never load or execute the official dataset."""
from copy import deepcopy
import json
import math
import threading
import unittest
from unittest.mock import patch

from laboratory import lexical_engine as engine


class StepClock:
    def __init__(self, step=1000):
        self.value, self.step = 0, step

    def __call__(self):
        value = self.value
        self.value += self.step
        return value


class LexicalEngineTests(unittest.TestCase):
    def setUp(self):
        self.corpus = [
            {"_id": "10", "title": "Alpha", "text": "alpha beta"},
            {"_id": "2", "title": "", "text": "beta beta"},
            {"_id": "a", "title": "", "text": "gamma"},
        ]
        self.queries = {"TEST_ONLY_z": "unknown", "TEST_ONLY_a": "alpha beta beta"}
        self.qrels = {"TEST_ONLY_a": {"10": 2, "2": 1}, "TEST_ONLY_z": {"a": 1}}
        self.protocol = {"repeats": 6, "max_elapsed_seconds": 180, "test_only": True}

    def execute(self, **overrides):
        values = {"corpus": self.corpus, "queries": self.queries,
                  "qrels": self.qrels, "protocol": self.protocol}
        values.update(overrides)
        return engine.run(**values)

    def test_hand_calculated_scoring_uses_identical_title_and_text(self):
        result = self.execute()
        rows = result["rankings"]
        tfidf = {row["doc_id"]: row["score"] for row in rows["tfidf"]["TEST_ONLY_a"]}
        alpha, beta, sublinear = math.log(4 / 2) + 1, math.log(4 / 3) + 1, 1 + math.log(2)
        document_norm = math.hypot(sublinear * alpha, beta)
        query_norm = math.hypot(alpha, sublinear * beta)
        expected = ((sublinear * alpha) * alpha + beta * (sublinear * beta)) / document_norm / query_norm
        self.assertAlmostEqual(tfidf["10"], expected)
        self.assertAlmostEqual(tfidf["2"], sublinear * beta / query_norm)
        self.assertEqual(tfidf["a"], 0)
        bm25 = {row["doc_id"]: row["score"] for row in rows["bm25"]["TEST_ONLY_a"]}
        alpha_idf, beta_idf = math.log(1 + 2.5 / 1.5), math.log(1 + 1.5 / 2.5)
        norm_a = 1.2 * (0.25 + 0.75 * 3 / 2)
        expected_a = alpha_idf * 2 * 2.2 / (2 + norm_a) + 2 * beta_idf * 2.2 / (1 + norm_a)
        self.assertAlmostEqual(bm25["10"], expected_a)
        self.assertAlmostEqual(bm25["2"], 2 * beta_idf * 2 * 2.2 / (2 + 1.2))
        self.assertEqual(engine._tokens("A x BB, naïve_2 ßß 123 running runs", 20),
                         ["bb", "naïve_2", "ßß", "123", "running", "runs"])
        self.assertTrue(engine.validate_result(result, self.protocol))
        json.dumps(result, allow_nan=False)

    def test_graded_metrics_match_hand_calculation_and_cutoffs(self):
        rows = [{"doc_id": doc_id, "score": 0} for doc_id in ("b", "x", "a", "c")]
        metrics = engine.evaluate_ranking(rows, {"a": 3, "b": 2, "c": 1})
        dcg = 3 + 7 / 2 + 1 / math.log2(5)
        ideal = 7 + 3 / math.log2(3) + 1 / 2
        self.assertAlmostEqual(metrics["ndcg_at_10"], dcg / ideal)
        self.assertEqual(metrics["recall_at_100"], 1)
        self.assertEqual(metrics["mrr_at_10"], 1)
        rows = [{"doc_id": str(i), "score": 0} for i in range(101)]
        metrics = engine.evaluate_ranking(rows, {"10": 1, "100": 1})
        self.assertEqual(metrics, {"ndcg_at_10": 0, "recall_at_100": 0.5, "mrr_at_10": 0})
        for relevance in (1e-200, 1e308):
            best = engine.evaluate_ranking([{"doc_id": "a"}], {"a": relevance})
            self.assertEqual(best["ndcg_at_10"], 1)

    def test_zero_score_ties_use_string_ids_and_top100_is_unique(self):
        corpus = [{"_id": str(i), "title": "", "text": "constant"} for i in range(103)]
        expected = sorted(str(i) for i in range(103))[:100]
        result = self.execute(corpus=list(reversed(corpus)), queries={"TEST_ONLY": "unknown"},
                              qrels={"TEST_ONLY": {"99": 1}})
        for arm in engine.ARMS:
            ranking = result["rankings"][arm]["TEST_ONLY"]
            self.assertEqual([row["doc_id"] for row in ranking], expected)
            self.assertTrue(all(row["score"] == 0 for row in ranking))
            self.assertEqual(len(set(expected)), 100)
        self.assertTrue(result["completed"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["metrics"]["tfidf"]["recall_at_100"], 0)
        self.assertTrue(engine.validate_result(result))

    def test_no_query_is_dropped_and_invalid_ids_or_judgments_are_rejected(self):
        cases = [
            {"qrels": {"TEST_ONLY_a": {"10": 1}}},
            {"qrels": {**self.qrels, "unknown_query": {"10": 1}}},
            {"qrels": {**self.qrels, "TEST_ONLY_a": {"unknown_doc": 1}}},
            {"qrels": {**self.qrels, "TEST_ONLY_a": {"10": 0}}},
            {"corpus": self.corpus + [self.corpus[0]]},
            {"corpus": [{"_id": 1, "title": "", "text": "text"}]},
            {"queries": {1: "query"}, "qrels": {1: {"10": 1}}},
        ]
        for relevance in (-1, float("nan"), float("inf"), True, "1"):
            cases.append({"qrels": {**self.qrels, "TEST_ONLY_a": {"10": relevance}}})
        for case in cases:
            with self.subTest(case=case), self.assertRaises(engine.LexicalEngineError):
                self.execute(**case)

    def test_all_passes_recompute_rankings_before_any_evaluation(self):
        rank, evaluate = engine._rank, engine.evaluate_ranking
        calls, evaluated = [], []

        def recording_rank(index, text, guard):
            self.assertFalse(evaluated)
            calls.append((index["arm"], text))
            return rank(index, text, guard)

        def recording_evaluate(ranking, judgments):
            self.assertEqual(len(calls), 2 * 2 * (1 + 6))
            evaluated.append(True)
            return evaluate(ranking, judgments)

        with patch.object(engine, "_rank", recording_rank), patch.object(engine, "evaluate_ranking", recording_evaluate):
            result = self.execute(clock_ns=StepClock(), cpu_clock=StepClock(0.000001))
        self.assertEqual(calls[:4], [(arm, self.queries[qid])
                                    for arm in engine.ARMS for qid in sorted(self.queries)])
        self.assertEqual(len(evaluated), 4)
        self.assertTrue(result["timings"]["rankings_identical_across_passes"])
        self.assertTrue(engine.validate_result(result))

    def test_timing_samples_quantiles_clock_provenance_and_arm_order(self):
        result = self.execute(clock_ns=StepClock(), cpu_clock=StepClock(0.000001))
        timings = result["timings"]
        self.assertEqual(timings["warmup"], {"passes_per_arm": 1, "order": ["tfidf", "bm25"], "measured": False})
        self.assertEqual([row["order"] for row in timings["passes"]], [["tfidf", "bm25"], ["bm25", "tfidf"]] * 3)
        for arm in engine.ARMS:
            measured = timings["arms"][arm]
            for values in measured["per_query_samples_ms"].values():
                self.assertEqual(len(values), 6)
                self.assertEqual(len(set(round(value, 12) for value in values)), 1)
            medians = sorted(measured["per_query_median_ms"].values())
            self.assertEqual(measured["query_latency_p50_ms"], sum(medians) / 2)
            self.assertEqual(measured["query_latency_p95_ms"], medians[-1])
            self.assertGreater(measured["index_build_ms"], 0)
            self.assertGreater(measured["index_build_cpu_ms"], 0)
        self.assertEqual(result["environment"]["wall_clock"], "injected TEST_ONLY")
        self.assertEqual(result["environment"]["evidence_scope"], "TEST_ONLY fixture")
        with self.assertRaises(engine.LexicalEngineError):
            self.execute(protocol={"repeats": 6, "max_elapsed_seconds": 180}, clock_ns=StepClock())

    def test_metrics_rankings_and_acceptance_are_deterministic_independent_of_timings(self):
        first, second = self.execute(), self.execute(corpus=list(reversed(self.corpus)))
        for key in ("metrics", "rankings", "per_query", "outcomes", "passed"):
            self.assertEqual(first[key], second[key])
        self.assertEqual(first["environment"]["wall_clock"], "time.perf_counter_ns")
        self.assertEqual(first["environment"]["cpu_clock"], "time.process_time")
        self.assertEqual(set(first["per_query"]), set(self.queries))
        expected = (first["metrics"]["bm25"]["ndcg_at_10"] > first["metrics"]["tfidf"]["ndcg_at_10"]
                    and first["metrics"]["bm25"]["recall_at_100"] >= first["metrics"]["tfidf"]["recall_at_100"])
        self.assertEqual(first["passed"], expected)

    def test_internal_screening_can_pass_without_an_absolute_quality_floor(self):
        corpus = [{"_id": "a", "title": "", "text": "alpha"},
                  {"_id": "b", "title": "", "text": "alpha alpha alpha"}]
        result = self.execute(corpus=corpus, queries={"TEST_ONLY": "alpha"},
                              qrels={"TEST_ONLY": {"b": 1}})
        self.assertEqual(result["rankings"]["tfidf"]["TEST_ONLY"][0]["doc_id"], "a")
        self.assertEqual(result["rankings"]["bm25"]["TEST_ONLY"][0]["doc_id"], "b")
        self.assertAlmostEqual(result["metrics"]["tfidf"]["ndcg_at_10"], 1 / math.log2(3))
        self.assertEqual(result["metrics"]["bm25"]["ndcg_at_10"], 1)
        self.assertEqual(result["outcomes"], {"win": 1, "tie": 0, "loss": 0})
        self.assertTrue(result["passed"])
        self.assertTrue(engine.validate_result(result))

    def test_cancellation_is_checked_immediately_and_inside_retrieval(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(engine.LexicalCancelled):
            self.execute(cancel=event)
        rank = engine._rank
        calls = []

        def recording(index, text, guard):
            calls.append(1)
            return rank(index, text, guard)

        with patch.object(engine, "_rank", recording), self.assertRaises(engine.LexicalCancelled):
            self.execute(cancel=lambda: len(calls) >= 6)
        self.assertEqual(len(calls), 6)

    def test_deadline_is_checked_before_work_and_inside_measured_passes(self):
        with self.assertRaises(engine.LexicalDeadlineExceeded):
            self.execute(protocol={**self.protocol, "max_elapsed_seconds": 0.001}, clock_ns=StepClock(1000000))
        rank, calls, clock = engine._rank, [], StepClock()

        def recording(index, text, guard):
            calls.append(1)
            return rank(index, text, guard)

        def deadline_clock():
            return 181000000000 if len(calls) >= 6 else clock()

        with patch.object(engine, "_rank", recording), self.assertRaises(engine.LexicalDeadlineExceeded):
            self.execute(clock_ns=deadline_clock)
        self.assertEqual(len(calls), 6)

    def test_protocol_and_resource_caps_are_hard_limits(self):
        for changed in ({"repeats": 2}, {"max_elapsed_seconds": 181}, {"max_elapsed_seconds": float("nan")},
                        {"workers": 2}, {"result_cache": True}, {"bm25_k1": 1.3}, {"top_k": 10}):
            with self.subTest(changed=changed), self.assertRaises(engine.LexicalEngineError):
                self.execute(protocol={**self.protocol, **changed})
        for text in ("word " * 1025, "x" * 257):
            with self.assertRaises(engine.LexicalEngineError):
                self.execute(queries={"TEST_ONLY": text}, qrels={"TEST_ONLY": {"10": 1}})
        with patch.dict(engine.LIMITS, {"postings": 1}), self.assertRaises(engine.LexicalEngineError):
            self.execute()
        with patch.dict(engine.LIMITS, {"corpus_tokens": 1}), self.assertRaises(engine.LexicalEngineError):
            self.execute()
        with self.assertRaises(engine.LexicalEngineError):
            self.execute(corpus=self.corpus * 2001)

    def test_receipt_validator_rejects_metrics_rankings_samples_and_provenance_tampering(self):
        original = self.execute()
        mutations = [
            lambda row: row["metrics"]["tfidf"].update(ndcg_at_10=0.123456),
            lambda row: row["rankings"]["tfidf"]["TEST_ONLY_z"].reverse(),
            lambda row: row["timings"]["arms"]["tfidf"]["per_query_samples_ms"]["TEST_ONLY_a"].pop(),
            lambda row: row["timings"]["passes"][1].update(order=["tfidf", "bm25"]),
            lambda row: row["environment"].update(evidence_scope="official independent benchmark"),
            lambda row: row.update(passed=not row["passed"]),
        ]
        for mutation in mutations:
            altered = deepcopy(original)
            mutation(altered)
            with self.assertRaises(engine.LexicalEngineError):
                engine.validate_result(altered)


if __name__ == "__main__":
    unittest.main()
