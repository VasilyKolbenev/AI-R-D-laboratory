"""Bounded, standard-library CPU lexical retrieval and paired evaluation.

This module performs no I/O and grants no authority to run an experiment. The
caller owns dataset provenance and approval. Relevance labels are validated
before retrieval and used for evaluation only after all measured passes finish.
"""
from collections import Counter
from copy import deepcopy
import math
import platform
import re
import statistics
import sys
import time


VERSION = "lexical-cpu-v1"
SCHEMA_VERSION = "lexical-retrieval-v1"
TOKEN_PATTERN = r"(?u)\b\w\w+\b"
_TOKENIZER = re.compile(TOKEN_PATTERN)
ARMS = ("tfidf", "bm25")
METRICS = ("ndcg_at_10", "recall_at_100", "mrr_at_10")
LIMITS = {
    "documents": 6000, "queries": 350, "document_characters": 100000,
    "query_characters": 16000, "corpus_characters": 32000000,
    "document_tokens": 20000, "query_tokens": 1024,
    "corpus_tokens": 3000000, "vocabulary": 250000,
    "postings": 1500000, "term_characters": 256, "id_characters": 256,
}
PROTOCOL = {
    "tokenizer": TOKEN_PATTERN, "lowercase": True,
    "document_text": "title + '\\n' + text", "stemming": False,
    "stopwords": False, "tfidf_tf": "1 + ln(tf)",
    "tfidf_idf": "ln((N + 1) / (df + 1)) + 1",
    "tfidf_normalization": "L2 document and query; cosine",
    "bm25_k1": 1.2, "bm25_b": 0.75,
    "bm25_idf": "ln(1 + (N - df + 0.5) / (df + 0.5))",
    "bm25_query_tf": "raw count multiplier", "top_k": 100,
    "rank_order": "score descending, document ID string ascending; include zero scores",
    "query_order": "query ID string ascending", "repeats": 6,
    "warmup_passes": 1, "workers": 1, "result_cache": False,
    "max_elapsed_seconds": 180.0,
    "metric_aggregation": "macro average across every selected qrel query ID",
    "ndcg_at_10_gain": "2**relevance - 1", "ndcg_at_10_discount": "log2(rank + 1); rank starts at 1",
    "positive_relevance": "judgment > 0; unjudged documents have relevance 0",
    "recall_at_100": "unique positive documents in top 100 / all positive judgments for the query",
    "mrr_at_10": "reciprocal of first positive rank <= 10, otherwise 0",
    "outcome_metric": "ndcg_at_10",
    "acceptance": "BM25 mean nDCG@10 > TF-IDF and BM25 mean Recall@100 >= TF-IDF",
    "limits": LIMITS,
}


class LexicalEngineError(ValueError):
    """Invalid inputs or a violated execution contract."""
    code = "invalid_lexical_input"


class LexicalCancelled(LexicalEngineError):
    code = "lexical_cancelled"


class LexicalDeadlineExceeded(LexicalEngineError):
    code = "lexical_deadline_exceeded"


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _protocol(value):
    if not isinstance(value, dict):
        raise LexicalEngineError("protocol must be a dictionary")
    if type(value.get("repeats")) is not int or value["repeats"] != 6:
        raise LexicalEngineError("the frozen protocol requires exactly six measured passes")
    budget = value.get("max_elapsed_seconds")
    if not _finite(budget) or not 0 < budget <= 180:
        raise LexicalEngineError("max_elapsed_seconds must be positive and at most 180")
    if "test_only" in value and type(value["test_only"]) is not bool:
        raise LexicalEngineError("test_only must be a boolean")
    for key, expected in PROTOCOL.items():
        if key in {"max_elapsed_seconds", "repeats"}:
            continue
        if key in value and (value[key] != expected or type(value[key]) is not type(expected)):
            raise LexicalEngineError("frozen protocol setting differs: " + key)
    result = deepcopy(PROTOCOL)
    result["max_elapsed_seconds"] = float(budget)
    result["test_only"] = value.get("test_only", False)
    return result


def _identifier(value, label):
    if (not isinstance(value, str) or not value or len(value) > LIMITS["id_characters"]
            or "\x00" in value):
        raise LexicalEngineError(label + " must be a bounded, nonempty string")
    return value


class _Guard:
    def __init__(self, clock, start_ns, seconds, cancel):
        self.clock, self.deadline = clock, start_ns + int(seconds * 1e9)
        if cancel is None:
            self.cancel = lambda: False
        elif callable(cancel):
            self.cancel = cancel
        elif callable(getattr(cancel, "is_set", None)):
            self.cancel = cancel.is_set
        else:
            raise LexicalEngineError("cancel must be callable or expose is_set()")

    def check(self):
        if self.cancel():
            raise LexicalCancelled("lexical retrieval cancelled; no completed result")
        if self.clock() >= self.deadline:
            raise LexicalDeadlineExceeded("lexical retrieval exceeded its elapsed-time cap")


def _validate(corpus, queries, qrels, guard):
    if not isinstance(corpus, list) or not 1 <= len(corpus) <= LIMITS["documents"]:
        raise LexicalEngineError("corpus must contain 1..6000 documents")
    if not isinstance(queries, dict) or not 1 <= len(queries) <= LIMITS["queries"]:
        raise LexicalEngineError("queries must contain 1..350 queries")
    if not isinstance(qrels, dict) or len(qrels) != len(queries) or set(qrels) != set(queries):
        raise LexicalEngineError("queries and qrels must contain exactly the same query IDs")
    documents, seen, characters = [], set(), 0
    for document in corpus:
        guard.check()
        if not isinstance(document, dict):
            raise LexicalEngineError("each corpus row must be a dictionary")
        doc_id = _identifier(document.get("_id"), "document ID")
        if doc_id in seen:
            raise LexicalEngineError("duplicate document ID: " + doc_id)
        seen.add(doc_id)
        title, text = document.get("title"), document.get("text")
        if not isinstance(title, str) or not isinstance(text, str):
            raise LexicalEngineError("document title and text must be strings")
        combined = title + "\n" + text
        if len(combined) > LIMITS["document_characters"] or "\x00" in combined:
            raise LexicalEngineError("document text exceeds its character limit or contains NUL")
        characters += len(combined)
        if characters > LIMITS["corpus_characters"]:
            raise LexicalEngineError("corpus exceeds its total character limit")
        documents.append((doc_id, combined))
    checked_queries, checked_qrels = {}, {}
    for query_id in queries:
        guard.check()
        _identifier(query_id, "query ID")
        text = queries[query_id]
        if (not isinstance(text, str) or len(text) > LIMITS["query_characters"]
                or "\x00" in text):
            raise LexicalEngineError("query text exceeds its character limit or contains NUL")
        judgments = qrels[query_id]
        if not isinstance(judgments, dict) or not judgments or len(judgments) > len(documents):
            raise LexicalEngineError("each query needs bounded document judgments")
        checked = {}
        for position, (doc_id, relevance) in enumerate(judgments.items()):
            if position % 1024 == 0:
                guard.check()
            _identifier(doc_id, "judged document ID")
            if doc_id not in seen:
                raise LexicalEngineError("qrels refer to an unknown document: " + doc_id)
            if not _finite(relevance) or relevance < 0:
                raise LexicalEngineError("relevance must be finite and nonnegative")
            checked[doc_id] = float(relevance)
        if not any(value > 0 for value in checked.values()):
            raise LexicalEngineError("every query needs at least one positive relevance judgment")
        checked_queries[query_id], checked_qrels[query_id] = text, checked
    return sorted(documents), dict(sorted(checked_queries.items())), checked_qrels


def _tokens(text, limit):
    tokens = _TOKENIZER.findall(text.lower())
    if len(tokens) > limit or any(len(token) > LIMITS["term_characters"] for token in tokens):
        raise LexicalEngineError("text exceeds its token count or term length limit")
    return tokens


def _build_index(documents, arm, guard):
    """Each arm independently tokenizes and indexes the identical document text."""
    postings, lengths = {}, []
    token_count = posting_count = 0
    for document_index, (_, text) in enumerate(documents):
        guard.check()
        counts = Counter(_tokens(text, LIMITS["document_tokens"]))
        length = sum(counts.values())
        lengths.append(length)
        token_count += length
        posting_count += len(counts)
        if token_count > LIMITS["corpus_tokens"] or posting_count > LIMITS["postings"]:
            raise LexicalEngineError("corpus exceeds its token or posting limit")
        for term, count in counts.items():
            postings.setdefault(term, []).append((document_index, count))
        if len(postings) > LIMITS["vocabulary"]:
            raise LexicalEngineError("corpus exceeds its vocabulary limit")
    size = len(documents)
    idfs, squared_norms = {}, [0.0] * size
    average_length = token_count / size
    for term, rows in postings.items():
        guard.check()
        df = len(rows)
        idf = (math.log((size + 1) / (df + 1)) + 1 if arm == "tfidf"
               else math.log(1 + (size - df + 0.5) / (df + 0.5)))
        idfs[term] = idf
        for position, (document_index, count) in enumerate(rows):
            if position % 1024 == 0:
                guard.check()
            if arm == "tfidf":
                weight = (1 + math.log(count)) * idf
                squared_norms[document_index] += weight * weight
            else:
                norm = 1.2 * (1 - 0.75 + 0.75 * lengths[document_index] / average_length)
                weight = idf * count * (1.2 + 1) / (count + norm)
            rows[position] = (document_index, weight)
    if arm == "tfidf":
        norms = [math.sqrt(value) for value in squared_norms]
        for rows in postings.values():
            guard.check()
            for position, (document_index, weight) in enumerate(rows):
                if position % 1024 == 0:
                    guard.check()
                rows[position] = (document_index, weight / norms[document_index])
    guard.check()
    return {"postings": postings, "idfs": idfs, "arm": arm,
            "document_ids": [doc_id for doc_id, _ in documents],
            "tokens": token_count, "vocabulary": len(postings), "postings_count": posting_count}


def _rank(index, text, guard):
    """No judgments are available here; every invocation recomputes the result."""
    guard.check()
    counts = Counter(_tokens(text, LIMITS["query_tokens"]))
    query_weights = {}
    for term, count in counts.items():
        if term in index["postings"]:
            query_weights[term] = ((1 + math.log(count)) * index["idfs"][term]
                                   if index["arm"] == "tfidf" else count)
    if index["arm"] == "tfidf" and query_weights:
        norm = math.sqrt(sum(value * value for value in query_weights.values()))
        query_weights = {term: weight / norm for term, weight in query_weights.items()}
    scores = [0.0] * len(index["document_ids"])
    for term, query_weight in query_weights.items():
        guard.check()
        for position, (document_index, weight) in enumerate(index["postings"][term]):
            if position % 1024 == 0:
                guard.check()
            scores[document_index] += query_weight * weight
    guard.check()
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], index["document_ids"][i]))[:100]
    result = [{"doc_id": index["document_ids"][i], "score": scores[i]} for i in order]
    guard.check()
    return result


def evaluate_ranking(ranking, judgments):
    """nDCG uses exponential gains; positive judgments define recall and MRR.

    Scaling gains by 2**(-max relevance) preserves the ratio and avoids overflow
    for all finite nonnegative relevance scores.
    """
    maximum = max(judgments.values())
    offset = 2.0 ** (-maximum)

    def gain(relevance):
        if maximum < 512:
            return math.expm1(relevance * math.log(2)) * math.exp(-maximum * math.log(2))
        return 2.0 ** (relevance - maximum) - offset

    ideal = sum(gain(relevance) / math.log2(rank + 2)
                for rank, relevance in enumerate(sorted(judgments.values(), reverse=True)[:10]))
    dcg = sum(gain(judgments.get(row["doc_id"], 0.0)) / math.log2(rank + 2)
              for rank, row in enumerate(ranking[:10]))
    relevant = {doc_id for doc_id, relevance in judgments.items() if relevance > 0}
    found = {row["doc_id"] for row in ranking[:100]} & relevant
    first = next((rank + 1 for rank, row in enumerate(ranking[:10])
                  if row["doc_id"] in relevant), None)
    return {"ndcg_at_10": dcg / ideal, "recall_at_100": len(found) / len(relevant),
            "mrr_at_10": 1.0 / first if first else 0.0}


def _median(values):
    return float(statistics.median(values))


def _quantile95(values):
    return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)]


def run(corpus, queries, qrels, protocol, cancel=None, *, clock_ns=None, cpu_clock=None):
    """Run both fixed arms; return a JSON-safe receipt or raise without a result.

    Optional clock injection is restricted to explicitly labelled TEST_ONLY
    fixtures. Production measurement uses perf_counter_ns and process_time.
    """
    effective = _protocol(protocol)
    injected = clock_ns is not None or cpu_clock is not None
    if injected and not effective["test_only"]:
        raise LexicalEngineError("clock injection is restricted to TEST_ONLY fixtures")
    wall, cpu = clock_ns or time.perf_counter_ns, cpu_clock or time.process_time
    start, cpu_start = wall(), cpu()
    guard = _Guard(wall, start, effective["max_elapsed_seconds"], cancel)
    guard.check()
    documents, query_texts, judgments = _validate(corpus, queries, qrels, guard)
    # Global elapsed/CPU totals include validation and evaluation. Retrieval and
    # index/query measurements begin only after every qrel has been validated.
    retrieval_started, retrieval_cpu_started = wall(), cpu()
    indexes, arm_timings = {}, {}
    for arm in ARMS:
        guard.check()
        began, cpu_began = wall(), cpu()
        indexes[arm] = _build_index(documents, arm, guard)
        arm_timings[arm] = {
            "index_build_ms": (wall() - began) / 1e6,
            "index_build_cpu_ms": (cpu() - cpu_began) * 1000,
            "tokens": indexes[arm]["tokens"], "vocabulary": indexes[arm]["vocabulary"],
            "postings": indexes[arm]["postings_count"],
        }
    # Exactly one full pass per arm, excluded from all reported query samples.
    for arm in ARMS:
        for text in query_texts.values():
            _rank(indexes[arm], text, guard)
    samples = {arm: {query_id: [] for query_id in query_texts} for arm in ARMS}
    cpu_samples = {arm: {query_id: [] for query_id in query_texts} for arm in ARMS}
    rankings = {arm: {} for arm in ARMS}
    passes, identical = [], True
    for repeat in range(6):
        guard.check()
        order = list(ARMS if repeat % 2 == 0 else reversed(ARMS))
        pass_started, pass_cpu_started = wall(), cpu()
        pass_record = {"pass": repeat + 1, "order": order, "arms": {}}
        for arm in order:
            arm_started, arm_cpu_started = wall(), cpu()
            for query_id, text in query_texts.items():
                guard.check()
                began, cpu_began = wall(), cpu()
                ranking = _rank(indexes[arm], text, guard)
                duration, cpu_duration = (wall() - began) / 1e6, (cpu() - cpu_began) * 1000
                samples[arm][query_id].append(duration)
                cpu_samples[arm][query_id].append(cpu_duration)
                if repeat == 0:
                    rankings[arm][query_id] = ranking
                elif ranking != rankings[arm][query_id]:
                    identical = False
                    raise LexicalEngineError("rankings changed between measured passes")
            pass_record["arms"][arm] = {
                "elapsed_ms": (wall() - arm_started) / 1e6,
                "cpu_ms": (cpu() - arm_cpu_started) * 1000,
            }
        pass_record["elapsed_ms"] = (wall() - pass_started) / 1e6
        pass_record["cpu_ms"] = (cpu() - pass_cpu_started) * 1000
        passes.append(pass_record)
    # Freeze measurement data before any metric computation or qrel lookup.
    retrieval_elapsed_ms = (wall() - retrieval_started) / 1e6
    retrieval_cpu_ms = (cpu() - retrieval_cpu_started) * 1000
    for arm in ARMS:
        medians = {query_id: _median(values) for query_id, values in samples[arm].items()}
        arm_timings[arm].update({
            "query_latency_p50_ms": _median(list(medians.values())),
            "query_latency_p95_ms": _quantile95(list(medians.values())),
            "per_query_median_ms": medians, "per_query_samples_ms": samples[arm],
            "per_query_cpu_median_ms": {query_id: _median(values)
                                         for query_id, values in cpu_samples[arm].items()},
            "per_query_cpu_samples_ms": cpu_samples[arm],
        })
    per_query, outcomes = {}, {"win": 0, "tie": 0, "loss": 0}
    for query_id in query_texts:
        guard.check()
        row = {arm: evaluate_ranking(rankings[arm][query_id], judgments[query_id]) for arm in ARMS}
        row["delta"] = {metric: row["bm25"][metric] - row["tfidf"][metric] for metric in METRICS}
        delta = row["delta"]["ndcg_at_10"]
        row["outcome"] = "win" if delta > 0 else "loss" if delta < 0 else "tie"
        outcomes[row["outcome"]] += 1
        per_query[query_id] = row
    metrics = {arm: {metric: statistics.mean(row[arm][metric] for row in per_query.values())
                     for metric in METRICS} for arm in ARMS}
    metrics["delta"] = {metric: metrics["bm25"][metric] - metrics["tfidf"][metric] for metric in METRICS}
    guard.check()
    result = {
        "schema_version": SCHEMA_VERSION, "engine_version": VERSION, "completed": True,
        "passed": metrics["delta"]["ndcg_at_10"] > 0 and metrics["delta"]["recall_at_100"] >= 0,
        "metrics": metrics, "per_query": per_query, "outcomes": outcomes, "rankings": rankings,
        "counts": {"documents": len(documents), "queries": len(query_texts),
                   "judgments": sum(len(value) for value in judgments.values())},
        "protocol": effective,
        "timings": {
            "unit": "milliseconds", "repeats": 6,
            "warmup": {"passes_per_arm": 1, "order": list(ARMS), "measured": False},
            "arms": arm_timings, "passes": passes,
            "query_timing_scope": "tokenization, scoring, sorting, top-k materialization and deadline checks; no qrels",
            "pass_timing_scope": "queries plus sample storage and ranking consistency comparisons; no qrels",
            "quantile_definition": "per-query median of six samples; p50=median (middle pair averaged); p95=nearest rank ceil(0.95*n)",
            "rankings_identical_across_passes": identical,
            "retrieval_elapsed_ms": retrieval_elapsed_ms, "retrieval_cpu_ms": retrieval_cpu_ms,
            "total_elapsed_ms": (wall() - start) / 1e6, "total_cpu_ms": (cpu() - cpu_start) * 1000,
        },
        "environment": {
            "python_version": platform.python_version(), "python_implementation": platform.python_implementation(),
            "platform": platform.platform(), "machine": platform.machine(),
            "architecture_bits": 64 if sys.maxsize > 2**32 else 32,
            "workers": 1, "execution": "stdlib CPU lexical retrieval",
            "wall_clock": "injected TEST_ONLY" if clock_ns is not None else "time.perf_counter_ns",
            "cpu_clock": "injected TEST_ONLY" if cpu_clock is not None else "time.process_time",
            "evidence_scope": "TEST_ONLY fixture" if effective["test_only"] else "local CPU execution",
        },
    }
    guard.check()
    return result


def validate_result(result, protocol=None):
    """Validate receipt structure and internal consistency without dataset access.

    This cannot establish dataset identity, relevance correctness, approval, or
    authenticity of timings. The caller must verify those against its immutable
    source, approval and artifact records.
    """
    def require(condition, message):
        if not condition:
            raise LexicalEngineError("invalid lexical receipt: " + message)

    def keys(value, expected, label):
        require(isinstance(value, dict) and set(value) == set(expected), label + " fields")

    def number(value, low=None, high=None):
        require(type(value) in (int, float) and _finite(value), "nonfinite/non-numeric value")
        require(low is None or value >= low, "value below range")
        require(high is None or value <= high, "value above range")

    def close(left, right):
        require(math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12), "inconsistent derived value")

    keys(result, ("schema_version", "engine_version", "completed", "passed", "metrics",
                  "per_query", "outcomes", "rankings", "counts", "protocol", "timings",
                  "environment"), "result")
    require(result["schema_version"] == SCHEMA_VERSION and result["engine_version"] == VERSION,
            "schema/engine version")
    require(result["completed"] is True and type(result["passed"]) is bool, "completion flags")
    effective = _protocol(result["protocol"])
    require(result["protocol"] == effective, "effective protocol")
    if protocol is not None:
        require(effective == _protocol(protocol), "approved protocol differs")
    keys(result["counts"], ("documents", "queries", "judgments"), "counts")
    counts = result["counts"]
    for key, maximum in (("documents", 6000), ("queries", 350), ("judgments", 6000 * 350)):
        require(type(counts[key]) is int and 1 <= counts[key] <= maximum, "count range")
    require(counts["queries"] <= counts["judgments"] <= counts["documents"] * counts["queries"],
            "judgment count")
    require(isinstance(result["per_query"], dict) and len(result["per_query"]) == counts["queries"],
            "per-query coverage")
    query_ids = set(result["per_query"])
    for query_id in query_ids:
        _identifier(query_id, "query ID")
    keys(result["metrics"], (*ARMS, "delta"), "metrics")
    keys(result["outcomes"], ("win", "tie", "loss"), "outcomes")
    computed_outcomes = {key: 0 for key in result["outcomes"]}
    for row in result["per_query"].values():
        keys(row, (*ARMS, "delta", "outcome"), "per-query row")
        for arm in (*ARMS, "delta"):
            keys(row[arm], METRICS, "per-query metrics")
            for value in row[arm].values():
                number(value, -1 if arm == "delta" else 0, 1)
        for metric in METRICS:
            close(row["delta"][metric], row["bm25"][metric] - row["tfidf"][metric])
        delta = row["delta"]["ndcg_at_10"]
        outcome = "win" if delta > 0 else "loss" if delta < 0 else "tie"
        require(row["outcome"] == outcome, "per-query outcome")
        computed_outcomes[outcome] += 1
    for key, value in result["outcomes"].items():
        require(type(value) is int and value == computed_outcomes[key], "outcome totals")
    for arm in (*ARMS, "delta"):
        keys(result["metrics"][arm], METRICS, "aggregate metrics")
        for metric, value in result["metrics"][arm].items():
            number(value, -1 if arm == "delta" else 0, 1)
            expected = (statistics.mean(row[arm][metric] for row in result["per_query"].values())
                        if arm in ARMS else result["metrics"]["bm25"][metric] - result["metrics"]["tfidf"][metric])
            close(value, expected)
    require(result["passed"] == (result["metrics"]["delta"]["ndcg_at_10"] > 0
                                and result["metrics"]["delta"]["recall_at_100"] >= 0), "acceptance criterion")
    keys(result["rankings"], ARMS, "rankings")
    for arm in ARMS:
        keys(result["rankings"][arm], query_ids, "ranking coverage")
        for ranking in result["rankings"][arm].values():
            require(isinstance(ranking, list) and len(ranking) == min(100, counts["documents"]),
                    "ranking length")
            seen, previous = set(), None
            for row in ranking:
                keys(row, ("doc_id", "score"), "ranking row")
                doc_id = _identifier(row["doc_id"], "ranked document ID")
                require(doc_id not in seen, "duplicate ranked document")
                seen.add(doc_id)
                number(row["score"], 0)
                order = (-row["score"], doc_id)
                require(previous is None or previous <= order, "ranking order")
                previous = order
    timings = result["timings"]
    keys(timings, ("unit", "repeats", "warmup", "arms", "passes", "query_timing_scope",
                   "pass_timing_scope", "quantile_definition", "rankings_identical_across_passes",
                   "retrieval_elapsed_ms", "retrieval_cpu_ms", "total_elapsed_ms", "total_cpu_ms"), "timings")
    require(timings["unit"] == "milliseconds" and type(timings["repeats"]) is int
            and timings["repeats"] == 6 and timings["rankings_identical_across_passes"] is True,
            "timing protocol")
    require(timings["warmup"] == {"passes_per_arm": 1, "order": list(ARMS), "measured": False},
            "warmup protocol")
    for name in ("query_timing_scope", "pass_timing_scope", "quantile_definition"):
        require(isinstance(timings[name], str) and 0 < len(timings[name]) < 1000, "timing description")
    for key in ("retrieval_elapsed_ms", "retrieval_cpu_ms", "total_elapsed_ms", "total_cpu_ms"):
        number(timings[key], 0)
    require(timings["retrieval_elapsed_ms"] <= timings["total_elapsed_ms"]
            <= effective["max_elapsed_seconds"] * 1000, "elapsed-time cap")
    keys(timings["arms"], ARMS, "timing arms")
    for arm in ARMS:
        row = timings["arms"][arm]
        keys(row, ("index_build_ms", "index_build_cpu_ms", "tokens", "vocabulary", "postings",
                   "query_latency_p50_ms", "query_latency_p95_ms", "per_query_median_ms",
                   "per_query_samples_ms", "per_query_cpu_median_ms", "per_query_cpu_samples_ms"), "arm timing")
        for name in ("tokens", "vocabulary", "postings"):
            maximum = LIMITS[{"tokens": "corpus_tokens", "postings": "postings"}.get(name, name)]
            require(type(row[name]) is int and 0 <= row[name] <= maximum, "index size")
        for name in ("index_build_ms", "index_build_cpu_ms", "query_latency_p50_ms", "query_latency_p95_ms"):
            number(row[name], 0)
        for prefix in ("per_query_", "per_query_cpu_"):
            samples, medians = row[prefix + "samples_ms"], row[prefix + "median_ms"]
            keys(samples, query_ids, "timing sample coverage")
            keys(medians, query_ids, "timing median coverage")
            for query_id in query_ids:
                values = samples[query_id]
                require(isinstance(values, list) and len(values) == 6, "six measured samples")
                for value in values:
                    number(value, 0)
                number(medians[query_id], 0)
                close(medians[query_id], _median(values))
        medians = list(row["per_query_median_ms"].values())
        close(row["query_latency_p50_ms"], _median(medians))
        close(row["query_latency_p95_ms"], _quantile95(medians))
    require(isinstance(timings["passes"], list) and len(timings["passes"]) == 6, "six measured passes")
    for repeat, row in enumerate(timings["passes"]):
        keys(row, ("pass", "order", "arms", "elapsed_ms", "cpu_ms"), "pass timing")
        require(type(row["pass"]) is int and row["pass"] == repeat + 1
                and row["order"] == list(ARMS if repeat % 2 == 0 else reversed(ARMS)), "alternating arm order")
        keys(row["arms"], ARMS, "pass arm coverage")
        for measured in (row, *row["arms"].values()):
            if measured is not row:
                keys(measured, ("elapsed_ms", "cpu_ms"), "pass arm timing")
            number(measured["elapsed_ms"], 0)
            number(measured["cpu_ms"], 0)
    environment = result["environment"]
    keys(environment, ("python_version", "python_implementation", "platform", "machine",
                       "architecture_bits", "workers", "execution", "wall_clock", "cpu_clock",
                       "evidence_scope"), "environment")
    require(type(environment["architecture_bits"]) is int and environment["architecture_bits"] in (32, 64)
            and type(environment["workers"]) is int and environment["workers"] == 1, "runtime architecture/workers")
    for key, value in environment.items():
        if key not in ("architecture_bits", "workers"):
            require(isinstance(value, str) and len(value) <= 1000, "runtime metadata")
    require(environment["execution"] == "stdlib CPU lexical retrieval", "execution metadata")
    require(environment["wall_clock"] in ("time.perf_counter_ns", "injected TEST_ONLY")
            and environment["cpu_clock"] in ("time.process_time", "injected TEST_ONLY"), "clock metadata")
    require(environment["evidence_scope"] == ("TEST_ONLY fixture" if effective["test_only"] else "local CPU execution"),
            "evidence scope")
    require(effective["test_only"] or (environment["wall_clock"] == "time.perf_counter_ns"
                                     and environment["cpu_clock"] == "time.process_time"), "production clock provenance")
    return True
