# Five-Person Presentation Plan

Use this split so every major part of the project is covered without overlap.
Each person should explain the problem, show the related files, and mention one
technical challenge or tradeoff.

## Person 1: Product Goal And System Overview

- Explain the StudyWithMe Arabic AI Tutor goal and target users.
- Cover the Streamlit entrypoint and main screens: `app.py`, `src/ui/`, `assets/`.
- Present the high-level architecture: UI, chat store, LangGraph, RAG, memory,
  tools, LLM, and evaluation.

## Person 2: Documents, Retrieval, And RAG

- Explain upload, document extraction, chunking, embeddings, and FAISS indexing.
- Cover `src/retrieval/`, `src/document_processing/`, `src/files/`, and
  `vector_store/`.
- Show how semantic vector search and optional BM25 retrieval improve grounded
  answers.

## Person 3: LLM, Prompts, Agents, And Tools

- Explain model configuration, OpenAI/Ollama provider support, and prompt design.
- Cover `src/llm/`, `src/prompts/`, `src/agents/`, and `src/tools/`.
- Mention tool calling examples: calculator, document search, quiz grading, web
  search, citations, flashcards, and concepts.

## Person 4: LangGraph Workflow And Memory

- Explain how the graph routes requests, retrieves context, runs agents, and
  saves state.
- Cover `src/graph/`, `src/memory/`, `src/chat/`, and `data/memory/`.
- Highlight recent chat memory, relevant old chat memory, and long-term
  preferences.

## Person 5: Quality, Evaluation, Guardrails, And Demo

- Explain Arabic guardrails, reflection, critic review, citation checks, and RAG
  evaluation.
- Cover `src/guardrails/`, `src/evaluation/`, and `src/tracing/`.
- Finish with a short demo flow: upload a file, ask for an explanation, generate
  a quiz, submit answers, and show evaluation or trace output.

## Suggested Closing Slide

- What works now: Arabic-first RAG, memory, agents, tools, quizzes, evaluation.
- What is next: Docker, CI, deployment guide, stronger demo assets, and public
  demo video.
