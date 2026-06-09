import re


DISALLOWED_SCRIPT_RE = re.compile(
    r"[\u0400-\u04FF\u0590-\u05FF\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uAC00-\uD7AF]"
)
LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+.-]*")

ALLOWED_LATIN_TERMS = {
    "ai",
    "api",
    "bert",
    "crag",
    "csv",
    "docx",
    "f1",
    "faiss",
    "flare",
    "gpt",
    "gpu",
    "html",
    "ircot",
    "json",
    "llm",
    "llms",
    "mcq",
    "pdf",
    "qa",
    "rag",
    "ragbench",
    "rouge",
    "self-rag",
    "top-k",
    "transformer",
    "transformers",
    "url",
}


def _is_allowed_latin_word(word: str) -> bool:
    normalized = word.lower().strip("_+-.")
    if normalized in ALLOWED_LATIN_TERMS:
        return True
    if normalized.startswith("file_"):
        return True
    if normalized.endswith((".pdf", ".docx", ".txt", ".csv", ".md")):
        return True
    if word.isupper() and 2 <= len(word) <= 12:
        return True
    if any(char.isdigit() for char in word) and len(word) <= 16:
        return True
    return False


def contains_disallowed_language(text: str) -> bool:
    if DISALLOWED_SCRIPT_RE.search(text or ""):
        return True
    return any(not _is_allowed_latin_word(word) for word in LATIN_WORD_RE.findall(text or ""))


def disallowed_language_details(text: str, limit: int = 12) -> dict:
    raw_text = text or ""
    scripts_found = sorted(set(DISALLOWED_SCRIPT_RE.findall(raw_text)))
    latin_words: list[str] = []
    occurrences: list[dict[str, str | int]] = []
    seen = set()
    for match in LATIN_WORD_RE.finditer(raw_text):
        word = match.group(0)
        if _is_allowed_latin_word(word):
            continue
        normalized = word.lower().strip("_+-.")
        if normalized in seen:
            continue
        seen.add(normalized)
        latin_words.append(word)
        start = max(match.start() - 35, 0)
        end = min(match.end() + 35, len(raw_text))
        occurrences.append(
            {
                "word": word,
                "position": match.start(),
                "context": raw_text[start:end].replace("\n", " ").strip(),
            }
        )
        if len(latin_words) >= limit:
            break
    return {
        "disallowed_latin_words": latin_words,
        "disallowed_latin_occurrences": occurrences,
        "disallowed_script_samples": scripts_found[:limit],
    }


def strip_disallowed_language(text: str) -> str:
    text = DISALLOWED_SCRIPT_RE.sub(" ", text or "")

    def replace_latin(match):
        word = match.group(0)
        return word if _is_allowed_latin_word(word) else " "

    text = LATIN_WORD_RE.sub(replace_latin, text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def enforce_arabic_answer(answer: str, query: str, llm) -> str:
    current = answer or ""

    for _ in range(2):
        if not contains_disallowed_language(current):
            return current

        repair_prompt = f"""
أعد كتابة الإجابة التالية بالعربية الفصحى المبسطة فقط.

القواعد:
- لا تضف معلومات جديدة.
- أبق المصطلحات التقنية الإنجليزية القصيرة فقط عند الحاجة، مثل RAG وLLM وTransformer.
- لا تنسخ أي جملة أجنبية طويلة.
- حافظ على نفس البنية العامة والعناوين إن أمكن.

سؤال المستخدم:
{query}

الإجابة التي تحتاج إلى إصلاح:
{current}
"""
        current = llm.invoke(repair_prompt).content

    return strip_disallowed_language(current)
