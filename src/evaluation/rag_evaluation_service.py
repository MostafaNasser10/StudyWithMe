from __future__ import annotations

from dataclasses import dataclass
import re
from statistics import mean
from typing import Any

from src.config import ENABLE_DEEPEVAL_EVAL, ENABLE_RAGAS_EVAL, OPENAI_API_KEY


RAGAS_METRIC_DESCRIPTIONS = {
    # Faithfulness: answer is supported by retrieved context.
    "faithfulness": "Answer claims are supported by retrieved context.",
    # Answer Relevancy: answer addresses the user question.
    "answer_relevancy": "Answer addresses the user question.",
    # Context Precision: retrieved chunks are useful rather than noisy.
    "context_precision": "Retrieved chunks are useful for the answer.",
    # Context Recall: retrieval found enough required information.
    "context_recall": "Retrieved context contains enough information to answer.",
}

DEEPEVAL_METRIC_DESCRIPTIONS = {
    # Correctness: answer is factually correct according to the judge/reference context.
    "correctness": "Answer is factually correct according to the judge and context.",
    # Relevance: answer addresses the user question.
    "relevance": "Answer is relevant to the question.",
    # Hallucination: answer includes unsupported claims. Lower is better.
    "hallucination": "Answer contains unsupported claims. Lower is better.",
    # Helpfulness: answer is useful for the student.
    "helpfulness": "Answer is useful for studying.",
}


@dataclass
class RAGEvaluationInput:
    query: str
    answer: str
    docs: list[dict[str, Any]]
    context: str = ""
    web_sources: list[dict[str, Any]] | None = None


class RAGEvaluationService:
    """Optional professional RAG evaluation service.

    The normal deterministic evaluator is fast and local. RAGAS and DeepEval are
    judge-based libraries that usually need extra packages and an LLM/API key.
    This service keeps them optional: if a package or model config is missing,
    chat continues and the evaluation object records a clear status.
    """

    def __init__(
        self,
        enable_ragas: bool = ENABLE_RAGAS_EVAL,
        enable_deepeval: bool = ENABLE_DEEPEVAL_EVAL,
    ) -> None:
        self.enable_ragas = enable_ragas
        self.enable_deepeval = enable_deepeval

    def evaluate(self, payload: RAGEvaluationInput) -> dict[str, Any]:
        contexts = _contexts_from_payload(payload)
        ragas_result = self.evaluate_ragas(payload.query, payload.answer, contexts)
        deepeval_result = self.evaluate_deepeval(payload.query, payload.answer, contexts)
        return {
            "ragas": ragas_result,
            "deepeval": deepeval_result,
            "summary_scores": _summary_scores(ragas_result, deepeval_result),
        }

    def evaluate_ragas(self, query: str, answer: str, contexts: list[str]) -> dict[str, Any]:
        if not self.enable_ragas:
            return _disabled("ragas")
        if not contexts:
            return _unavailable("ragas", "No retrieved contexts were available for RAGAS.")
        if not OPENAI_API_KEY:
            return _unavailable("ragas", "RAGAS usually needs a configured judge LLM/API key.")

        try:
            from datasets import Dataset
            from ragas import evaluate
            from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
        except Exception as exc:
            return _unavailable("ragas", f"Install ragas and datasets to enable this evaluator. {exc}")

        try:
            dataset = Dataset.from_dict(
                {
                    "question": [query],
                    "answer": [answer],
                    "contexts": [contexts],
                    # RAGAS context_recall normally needs a reference answer. In this app
                    # we often do not have gold references, so we use the generated answer
                    # as a weak reference and clearly mark that limitation.
                    "ground_truth": [answer],
                    "reference": [answer],
                }
            )
            result = evaluate(
                dataset,
                metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
            )
            scores = _extract_scores(
                result,
                ["faithfulness", "answer_relevancy", "context_precision", "context_recall"],
            )
            return {
                "status": "ok",
                **scores,
                "notes": "context_recall uses the generated answer as a weak reference unless you add gold answers.",
                "descriptions": RAGAS_METRIC_DESCRIPTIONS,
                "evidence": _metric_evidence(query, answer, contexts),
            }
        except Exception as exc:
            return _error("ragas", exc)

    def evaluate_deepeval(self, query: str, answer: str, contexts: list[str]) -> dict[str, Any]:
        if not self.enable_deepeval:
            return _disabled("deepeval")
        if not OPENAI_API_KEY:
            return _unavailable("deepeval", "DeepEval needs a configured judge LLM/API key.")

        try:
            from deepeval.metrics import AnswerRelevancyMetric, GEval, HallucinationMetric
            from deepeval.test_case import LLMTestCase, LLMTestCaseParams
        except Exception as exc:
            return _unavailable("deepeval", f"Install deepeval to enable this evaluator. {exc}")

        try:
            test_case = LLMTestCase(
                input=query,
                actual_output=answer,
                retrieval_context=contexts,
                context=contexts,
            )
            relevance = AnswerRelevancyMetric(threshold=0.5)
            hallucination = HallucinationMetric(threshold=0.5)
            correctness = GEval(
                name="Correctness",
                criteria="Score whether the answer is factually correct using the retrieval context when available.",
                evaluation_params=[
                    LLMTestCaseParams.INPUT,
                    LLMTestCaseParams.ACTUAL_OUTPUT,
                    LLMTestCaseParams.RETRIEVAL_CONTEXT,
                ],
            )
            helpfulness = GEval(
                name="Helpfulness",
                criteria="Score whether the answer is useful, clear, and educational for a student.",
                evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
            )

            metrics = {
                "correctness": correctness,
                "relevance": relevance,
                "hallucination": hallucination,
                "helpfulness": helpfulness,
            }
            scores: dict[str, float] = {}
            reasons: dict[str, str] = {}
            for name, metric in metrics.items():
                metric.measure(test_case)
                scores[name] = _normalize_score(getattr(metric, "score", None))
                reason = getattr(metric, "reason", None)
                if reason:
                    reasons[name] = str(reason)[:600]

            return {
                "status": "ok",
                **scores,
                "reasons": reasons,
                "descriptions": DEEPEVAL_METRIC_DESCRIPTIONS,
                "evidence": _metric_evidence(query, answer, contexts),
            }
        except Exception as exc:
            return _error("deepeval", exc)


def _contexts_from_payload(payload: RAGEvaluationInput) -> list[str]:
    contexts: list[str] = []
    for doc in payload.docs or []:
        snippet = str(doc.get("snippet") or doc.get("content") or "").strip()
        if snippet:
            contexts.append(snippet)
    for source in payload.web_sources or []:
        snippet = str(source.get("snippet") or "").strip()
        if snippet:
            contexts.append(snippet)
    if not contexts and payload.context:
        contexts.extend(part.strip() for part in payload.context.split("\n\n") if part.strip())
    return [item[:3000] for item in contexts if item][:8]


def _disabled(provider: str) -> dict[str, Any]:
    return {"status": "disabled", "provider": provider}


def _unavailable(provider: str, message: str) -> dict[str, Any]:
    return {"status": "unavailable", "provider": provider, "message": message}


def _error(provider: str, exc: Exception) -> dict[str, Any]:
    return {"status": "error", "provider": provider, "error": str(exc)[:1000]}


def _extract_scores(result: Any, names: list[str]) -> dict[str, float]:
    raw: dict[str, Any] = {}
    if hasattr(result, "to_pandas"):
        frame = result.to_pandas()
        if not frame.empty:
            raw = frame.iloc[0].to_dict()
    elif isinstance(result, dict):
        raw = result
    else:
        for name in names:
            raw[name] = getattr(result, name, None)
    return {name: _normalize_score(raw.get(name)) for name in names}


def _normalize_score(value: Any) -> float:
    try:
        score = float(value)
    except Exception:
        return 0.0
    if score > 1:
        score = score / 10 if score <= 10 else score / 100
    return round(max(0.0, min(score, 1.0)), 3)


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]+|[\u0600-\u06FF]{2,}", text or "")
    stopwords = {
        "هذا",
        "هذه",
        "ذلك",
        "التي",
        "الذي",
        "على",
        "إلى",
        "الى",
        "في",
        "من",
        "عن",
        "and",
        "the",
        "for",
        "with",
        "that",
        "this",
    }
    return {word.lower() for word in words if len(word) >= 3 and word.lower() not in stopwords}


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!؟؛])\s+|\n+", text or "")
    return [part.strip(" -•\t") for part in parts if len(part.strip()) >= 35][:18]


def _overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left:
        return 0.0
    return len(left & right) / max(len(left), 1)


def _metric_evidence(query: str, answer: str, contexts: list[str]) -> dict[str, Any]:
    context_text = "\n".join(contexts)
    context_terms = _tokens(context_text)
    query_terms = _tokens(query)
    answer_terms = _tokens(answer)
    sentences = _sentences(answer)

    unsupported = []
    supported = []
    for sentence in sentences:
        ratio = _overlap_ratio(_tokens(sentence), context_terms)
        if ratio < 0.12:
            unsupported.append(sentence[:260])
        elif ratio >= 0.22:
            supported.append(sentence[:260])

    missing_query_terms = sorted(query_terms - answer_terms)[:8]
    answer_terms_not_in_context = sorted(answer_terms - context_terms)[:12]
    useful_contexts = []
    noisy_contexts = []
    for context in contexts[:6]:
        overlap = _overlap_ratio(query_terms | answer_terms, _tokens(context))
        item = context.strip().replace("\n", " ")[:240]
        if overlap >= 0.08:
            useful_contexts.append(item)
        else:
            noisy_contexts.append(item)

    has_source_section = any(word in answer for word in ["المراجع", "المصادر", "الدليل"])
    has_student_structure = any(word in answer for word in ["مثال", "خلاصة", "ماذا تذاكر", "خريطة"])
    return {
        "faithfulness": {
            "supported_snippets": supported[:3],
            "possibly_unsupported_snippets": unsupported[:4],
        },
        "answer_relevancy": {
            "missing_question_terms": missing_query_terms,
            "query_terms_found": sorted(query_terms & answer_terms)[:10],
        },
        "context_precision": {
            "useful_context_snippets": useful_contexts[:3],
            "possibly_noisy_context_snippets": noisy_contexts[:3],
        },
        "context_recall": {
            "answer_terms_not_seen_in_context": answer_terms_not_in_context,
        },
        "correctness": {
            "possibly_unsupported_response_snippets": unsupported[:4],
            "supported_response_snippets": supported[:3],
        },
        "relevance": {
            "missing_question_terms": missing_query_terms,
            "query_terms_found": sorted(query_terms & answer_terms)[:10],
        },
        "hallucination": {
            "possibly_unsupported_response_snippets": unsupported[:4],
        },
        "helpfulness": {
            "has_source_section": has_source_section,
            "has_student_study_structure": has_student_structure,
            "answer_length_chars": len(answer or ""),
        },
    }


def _summary_scores(ragas_result: dict[str, Any], deepeval_result: dict[str, Any]) -> dict[str, Any]:
    scores: list[float] = []
    for result in (ragas_result, deepeval_result):
        if result.get("status") != "ok":
            continue
        for key, value in result.items():
            if key in {"status", "provider", "notes", "descriptions", "reasons", "evidence"}:
                continue
            if key == "hallucination":
                scores.append(1 - _normalize_score(value))
            else:
                scores.append(_normalize_score(value))
    if not scores:
        return {"status": "no_external_scores"}
    return {"status": "ok", "average_quality": round(mean(scores), 3)}
