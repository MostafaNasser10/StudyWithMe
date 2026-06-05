# StudyWithMe Repository Guide

This guide summarizes the repository layout and the main runtime flows for new
developers. It is intentionally concise; implementation details remain in the
source modules and tests.

## Project Structure

- `app.py`: Streamlit entrypoint. Configures the page, initializes session
  state, renders the home screen, and composes the chat workspace.
- `src/agents`: Agent classes and factory helpers for tutor answers, summaries,
  quizzes, study plans, feedback, web search, reflection, and critic review.
- `src/graph`: LangGraph state, routing schemas, node implementations, edge
  decisions, and graph runners.
- `src/tools`: Application tools that can be selected by the graph, including
  calculator, document search, quiz grading, citation checking, study helpers,
  and web search.
- `src/memory`: Three-layer memory system: recent messages, embedding-based
  relevant chat memory, and manually managed long-term preferences.
- `src/chat`: Persistent chat models, JSON chat store, and Streamlit session
  defaults.
- `src/files`: Upload persistence, per-chat asset paths, and background indexing
  job launcher.
- `src/document_processing`: OCR, image extraction, and table extraction hooks
  used during document loading.
- `src/evaluation`: Deterministic checks, rubric scoring, gold-standard checks,
  and optional RAGAS/DeepEval evaluation.
- `src/ui`: Streamlit layout, chat view, sidebars, upload controls, styles, and
  shared display helpers.
- `src/tracing`: Trace models and compatibility tracer for observability.
- `tests`: Regression tests for graph routing, retrieval, RAG, document loading,
  embeddings, vector store, and evaluation.
- `data` and `vector_store`: Runtime state and indexed artifacts. These are part
  of the current project snapshot, so cleanup should treat them conservatively.

## Main Runtime Flow

1. `app.py` configures Streamlit and initializes state.
2. `src/ui/sidebar_left.py` renders global navigation, chat history, and global
   long-term memory preferences.
3. `src/ui/chat_view.py` renders the active chat, collects user input, and calls
   the graph.
4. `src/graph/app_graph.py` runs LangGraph nodes from `src/graph/nodes.py`.
5. Graph nodes route the request, retrieve documents or web data when needed,
   build a memory-augmented prompt, call the LLM, apply guardrails, and evaluate
   the answer.
6. `src/chat/chat_store.py` persists messages, traces, evaluations, stats, and
   quiz state to JSON.
7. `src/ui/sidebar_right.py` renders per-chat files, runtime traces, evaluation
   panels, and statistics.

## Memory Flow

The memory system is intentionally simple:

1. Long-term user preferences are loaded from `data/memory/preferences.json`.
2. Recent messages are loaded from the active chat memory file.
3. Relevant older messages are found with embedding similarity.
4. `build_memory_augmented_messages()` creates the final message list.
5. New user and assistant messages are saved after each completed turn.

Memory is injected in one place only: `src/memory/memory_context_builder.py`.

## Cleanup Policy

- Remove generated files such as `__pycache__` directories and `*.pyc` files.
- Do not delete runtime data or vector-store files unless the product owner
  confirms they are no longer needed.
- Do not remove functions/classes that are exported, test-only, or referenced by
  compatibility docs unless the replacement path is verified.
- Prefer small documentation and import cleanups over broad rewrites.

## Verification Checklist

After cleanup or refactoring, run:

```powershell
.\.venv\Scripts\python.exe -m py_compile app.py src\ui\chat_view.py src\ui\sidebar_left.py src\ui\sidebar_right.py
.\.venv\Scripts\python.exe tests\test_graph_workflow.py
.\.venv\Scripts\python.exe tests\test_rag_evaluation_service.py
```

Also confirm the Streamlit server responds at `http://localhost:8501` when a
server is running locally.
