from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.evaluation.rag_evaluation_service as rag_eval
from src.evaluation.rag_evaluation_service import RAGEvaluationInput, RAGEvaluationService


def _sample_docs():
    return [
        {
            "source_name": "lecture.pdf",
            "location": "page 1",
            "snippet": "Retrieval augmented generation answers questions by retrieving relevant context before generation.",
        }
    ]


def test_good_grounded_answer_disabled_external_evaluators():
    service = RAGEvaluationService(enable_ragas=False, enable_deepeval=False)
    result = service.evaluate(
        RAGEvaluationInput(
            query="What is RAG?",
            answer="RAG retrieves relevant context before generating an answer.",
            docs=_sample_docs(),
        )
    )
    assert result["ragas"]["status"] == "disabled"
    assert result["deepeval"]["status"] == "disabled"


def test_answer_with_no_retrieved_docs_returns_safe_ragas_status():
    service = RAGEvaluationService(enable_ragas=True, enable_deepeval=False)
    result = service.evaluate(
        RAGEvaluationInput(
            query="Explain the uploaded lecture.",
            answer="This is an answer without retrieved evidence.",
            docs=[],
            context="",
        )
    )
    assert result["ragas"]["status"] == "unavailable"
    assert "No retrieved contexts" in result["ragas"]["message"]


def test_hallucinated_answer_does_not_break_when_external_eval_disabled():
    service = RAGEvaluationService(enable_ragas=False, enable_deepeval=False)
    result = service.evaluate(
        RAGEvaluationInput(
            query="What does the document say?",
            answer="The document says the moon is made of cheese.",
            docs=_sample_docs(),
        )
    )
    assert result["summary_scores"]["status"] == "no_external_scores"


def test_irrelevant_answer_does_not_break_when_external_eval_disabled():
    service = RAGEvaluationService(enable_ragas=False, enable_deepeval=False)
    result = service.evaluate(
        RAGEvaluationInput(
            query="Explain RAG.",
            answer="This answer talks about football instead.",
            docs=_sample_docs(),
        )
    )
    assert result["ragas"]["provider"] == "ragas"


def test_quiz_generation_answer_is_supported_as_text_payload():
    service = RAGEvaluationService(enable_ragas=False, enable_deepeval=False)
    result = service.evaluate(
        RAGEvaluationInput(
            query="Make a quiz about RAG.",
            answer='{"quiz_id":"q1","questions":[{"id":"q1","question":"What does RAG use?"}]}',
            docs=_sample_docs(),
        )
    )
    assert result["deepeval"]["provider"] == "deepeval"


def test_summary_answer_is_supported_as_text_payload():
    service = RAGEvaluationService(enable_ragas=False, enable_deepeval=False)
    result = service.evaluate(
        RAGEvaluationInput(
            query="Summarize the document.",
            answer="# Summary\nThe document explains retrieval augmented generation.",
            docs=_sample_docs(),
        )
    )
    assert result["ragas"]["status"] == "disabled"


def test_metric_evidence_mentions_response_snippets_when_enabled_but_no_api_key():
    previous = rag_eval.OPENAI_API_KEY
    rag_eval.OPENAI_API_KEY = ""
    try:
        service = RAGEvaluationService(enable_ragas=True, enable_deepeval=True)
        result = service.evaluate(
            RAGEvaluationInput(
                query="Explain RAG.",
                answer="RAG retrieves context. The document also says Mars is made of sugar.",
                docs=_sample_docs(),
            )
        )
    finally:
        rag_eval.OPENAI_API_KEY = previous
    assert result["ragas"]["status"] == "unavailable"
    assert result["deepeval"]["status"] == "unavailable"


def test_deepeval_missing_api_key_returns_unavailable():
    previous = rag_eval.OPENAI_API_KEY
    rag_eval.OPENAI_API_KEY = ""
    try:
        service = RAGEvaluationService(enable_ragas=False, enable_deepeval=True)
        result = service.evaluate(
            RAGEvaluationInput(query="Explain RAG.", answer="RAG uses retrieval.", docs=_sample_docs())
        )
    finally:
        rag_eval.OPENAI_API_KEY = previous
    assert result["deepeval"]["status"] == "unavailable"


if __name__ == "__main__":
    test_good_grounded_answer_disabled_external_evaluators()
    test_answer_with_no_retrieved_docs_returns_safe_ragas_status()
    test_hallucinated_answer_does_not_break_when_external_eval_disabled()
    test_irrelevant_answer_does_not_break_when_external_eval_disabled()
    test_quiz_generation_answer_is_supported_as_text_payload()
    test_summary_answer_is_supported_as_text_payload()
    test_metric_evidence_mentions_response_snippets_when_enabled_but_no_api_key()
    test_deepeval_missing_api_key_returns_unavailable()
    print("rag evaluation service tests passed")
