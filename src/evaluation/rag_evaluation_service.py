from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import math
import re
from statistics import mean
from typing import Any

from src.config import (
    ENABLE_DEEPEVAL_EVAL,
    ENABLE_RAGAS_EVAL,
    EXTERNAL_RAG_EVAL_MAX_ANSWER_CHARS,
    EXTERNAL_RAG_EVAL_MAX_CONTEXT_CHARS,
    EXTERNAL_RAG_EVAL_MAX_CONTEXTS,
    EXTERNAL_RAG_EVAL_TIMEOUT_SECONDS,
    EXTERNAL_RAG_EVAL_TRANSLATE_TO_ENGLISH,
    EXTERNAL_RAG_EVAL_TRANSLATION_TIMEOUT_SECONDS,
    OPENAI_MODEL,
    OPENAI_API_KEY,
)


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
        judge_query = str(payload.query or "")
        judge_answer = _clean_answer_for_external_eval(payload.answer)
        compact_contexts = _compact_contexts(contexts)
        translation = (
            _translate_eval_texts_to_english(judge_query, judge_answer)
            if compact_contexts and (self.enable_ragas or self.enable_deepeval)
            else {"query": judge_query, "answer": judge_answer, "translated": False, "status": "not_requested"}
        )
        judge_query = translation["query"]
        judge_answer = translation["answer"]
        with ThreadPoolExecutor(max_workers=2) as executor:
            ragas_future = executor.submit(self.evaluate_ragas, judge_query, judge_answer, compact_contexts)
            deepeval_future = executor.submit(self.evaluate_deepeval, judge_query, judge_answer, compact_contexts)
            ragas_result = ragas_future.result()
            deepeval_result = deepeval_future.result()
        ragas_result = _reconcile_ragas_with_deepeval(
            ragas_result,
            deepeval_result,
            judge_query,
            judge_answer,
            compact_contexts,
        )
        ragas_result = _attach_evaluation_metadata(
            ragas_result,
            judge_query,
            judge_answer,
            payload.answer,
            compact_contexts,
            translation,
        )
        deepeval_result = _attach_evaluation_metadata(
            deepeval_result,
            judge_query,
            judge_answer,
            payload.answer,
            compact_contexts,
            translation,
        )
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
            from ragas.run_config import RunConfig
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
                run_config=RunConfig(
                    timeout=EXTERNAL_RAG_EVAL_TIMEOUT_SECONDS,
                    max_retries=1,
                    max_workers=2,
                ),
                show_progress=False,
                batch_size=1,
            )
            scores = _extract_scores(
                result,
                ["faithfulness", "answer_relevancy", "context_precision", "context_recall"],
            )
            unreliable = _ragas_scores_look_unreliable(scores, query, answer, contexts)
            if unreliable:
                return _unreliable("ragas", unreliable, scores, query, answer, contexts)
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


def _unreliable(
    provider: str,
    message: str,
    scores: dict[str, float],
    query: str,
    answer: str,
    contexts: list[str],
) -> dict[str, Any]:
    return {
        "status": "unreliable",
        "provider": provider,
        "message": message,
        "raw_scores": scores,
        "descriptions": RAGAS_METRIC_DESCRIPTIONS if provider == "ragas" else {},
        "evidence": _metric_evidence(query, answer, contexts),
    }


def _error(provider: str, exc: Exception) -> dict[str, Any]:
    message = str(exc)
    if "OpenAIEmbeddings" in message and "embed_query" in message:
        return _unavailable(
            provider,
            "The external evaluator expected a LangChain embeddings interface that is not available in the current package versions. Keep this evaluator manual, or pin compatible ragas/deepeval/langchain versions.",
        )
    if "max_tokens" in message or "length limit" in message:
        return _unavailable(
            provider,
            "The external judge response exceeded its token limit. Try a shorter answer/context or reduce evaluator scope.",
        )
    return {"status": "error", "provider": provider, "error": message[:1000]}


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
    if not math.isfinite(score):
        return 0.0
    if score > 1:
        score = score / 10 if score <= 10 else score / 100
    return round(max(0.0, min(score, 1.0)), 3)


def _clean_answer_for_external_eval(answer: str) -> str:
    text = str(answer or "").strip()
    if not text:
        return ""
    cut_markers = [
        "\n# المصادر",
        "\n# المصدر",
        "\n# المراجع",
        "\n# المراجع المستخدمة",
        "\n# Sources",
        "\n## Sources",
        "\n> تنبيه المصادر:",
        "\n> Source warning:",
    ]
    for marker in cut_markers:
        index = text.find(marker)
        if index >= 0:
            text = text[:index].strip()
            break
    return text[:EXTERNAL_RAG_EVAL_MAX_ANSWER_CHARS]


def _contains_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _translate_eval_texts_to_english(query: str, answer: str) -> dict[str, Any]:
    if not EXTERNAL_RAG_EVAL_TRANSLATE_TO_ENGLISH:
        return {"query": query, "answer": answer, "translated": False, "status": "disabled"}
    if not (_contains_arabic(query) or _contains_arabic(answer)):
        return {"query": query, "answer": answer, "translated": False, "status": "not_needed"}
    if not OPENAI_API_KEY:
        return {
            "query": query,
            "answer": answer,
            "translated": False,
            "status": "unavailable",
            "message": "OPENAI_API_KEY is missing, so Arabic-to-English evaluation translation was skipped.",
        }

    try:
        from src.llm import get_llm

        prompt = f"""
Translate the following RAG evaluation payload to concise English.
Preserve meaning, technical terms, claims, uncertainty markers, and source references.
Do not add new facts. Return valid JSON only with keys "query" and "answer".

QUERY:
{query}

ANSWER:
{answer}
"""
        raw = get_llm(
            provider="openai",
            model=OPENAI_MODEL or "gpt-4o-mini",
            temperature=0,
            timeout_seconds=EXTERNAL_RAG_EVAL_TRANSLATION_TIMEOUT_SECONDS,
        ).invoke(prompt).content
        import json

        payload = json.loads(_json_object_from_text(str(raw)))
        translated_query = str(payload.get("query") or query).strip()
        translated_answer = str(payload.get("answer") or answer).strip()
        if not translated_query or not translated_answer:
            raise ValueError("translation returned empty query or answer")
        return {
            "query": translated_query[:EXTERNAL_RAG_EVAL_MAX_ANSWER_CHARS],
            "answer": translated_answer[:EXTERNAL_RAG_EVAL_MAX_ANSWER_CHARS],
            "translated": True,
            "status": "ok",
            "source_language": "arabic",
            "evaluation_language": "english",
        }
    except Exception as exc:
        return {
            "query": query,
            "answer": answer,
            "translated": False,
            "status": "error",
            "message": f"Arabic-to-English evaluation translation failed: {str(exc)[:220]}",
        }


def _json_object_from_text(text: str) -> str:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped


def _compact_contexts(contexts: list[str]) -> list[str]:
    compacted: list[str] = []
    for context in contexts[:EXTERNAL_RAG_EVAL_MAX_CONTEXTS]:
        text = str(context or "").strip()
        if text:
            compacted.append(text[:EXTERNAL_RAG_EVAL_MAX_CONTEXT_CHARS])
    return compacted


def _ragas_scores_look_unreliable(scores: dict[str, float], query: str, answer: str, contexts: list[str]) -> str:
    faithfulness = _normalize_score(scores.get("faithfulness"))
    answer_relevancy = _normalize_score(scores.get("answer_relevancy"))
    context_precision = _normalize_score(scores.get("context_precision"))
    context_recall = _normalize_score(scores.get("context_recall"))
    if faithfulness > 0 or answer_relevancy > 0:
        return ""

    evidence = _metric_evidence(query, answer, contexts)
    supported = evidence.get("faithfulness", {}).get("supported_snippets") or []
    query_terms_found = evidence.get("answer_relevancy", {}).get("query_terms_found") or []
    retrieval_score = max(context_precision, context_recall)
    if retrieval_score >= 0.65 and (supported or query_terms_found):
        return (
            "RAGAS returned 0 for both generation-facing metrics while retrieval/context evidence looked usable. "
            "This usually means the external RAGAS judge or embeddings path failed/truncated, especially with long Arabic answers."
        )
    return ""


def _reconcile_ragas_with_deepeval(
    ragas_result: dict[str, Any],
    deepeval_result: dict[str, Any],
    query: str,
    answer: str,
    contexts: list[str],
) -> dict[str, Any]:
    if ragas_result.get("status") != "ok" or deepeval_result.get("status") != "ok":
        return ragas_result
    faithfulness = _normalize_score(ragas_result.get("faithfulness"))
    answer_relevancy = _normalize_score(ragas_result.get("answer_relevancy"))
    deepeval_relevance = _normalize_score(deepeval_result.get("relevance"))
    deepeval_hallucination = _normalize_score(deepeval_result.get("hallucination"))
    if faithfulness == 0 and answer_relevancy == 0 and deepeval_relevance >= 0.7 and deepeval_hallucination <= 0.2:
        return _unreliable(
            "ragas",
            "RAGAS disagreed sharply with DeepEval: generation metrics were 0%, but DeepEval found the answer relevant and not hallucinated. Treat the RAGAS numbers as unreliable for this run.",
            {
                "faithfulness": faithfulness,
                "answer_relevancy": answer_relevancy,
                "context_precision": _normalize_score(ragas_result.get("context_precision")),
                "context_recall": _normalize_score(ragas_result.get("context_recall")),
            },
            query,
            answer,
            contexts,
        )
    return ragas_result


def _attach_full_answer_evidence(
    result: dict[str, Any],
    query: str,
    full_answer: str,
    contexts: list[str],
) -> dict[str, Any]:
    if result.get("status") not in {"ok", "unreliable"}:
        return result
    updated = dict(result)
    updated["evidence"] = _metric_evidence(query, full_answer, contexts)
    return updated


def _attach_evaluation_metadata(
    result: dict[str, Any],
    judge_query: str,
    judge_answer: str,
    full_answer: str,
    contexts: list[str],
    translation: dict[str, Any],
) -> dict[str, Any]:
    if result.get("status") not in {"ok", "unreliable"}:
        return result
    updated = dict(result)
    evidence = _metric_evidence(judge_query, judge_answer, contexts)
    full_evidence = _metric_evidence(judge_query, full_answer, contexts)
    evidence.setdefault("helpfulness", {})["has_source_section"] = full_evidence.get("helpfulness", {}).get(
        "has_source_section",
        False,
    )
    evidence.setdefault("helpfulness", {})["answer_length_chars"] = len(full_answer or "")
    updated["evidence"] = evidence
    updated["evaluation_language"] = "english" if translation.get("translated") else "original"
    updated["translation"] = {key: value for key, value in translation.items() if key not in {"query", "answer"}}
    return updated


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
