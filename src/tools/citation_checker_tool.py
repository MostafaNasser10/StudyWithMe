from __future__ import annotations


class CitationCheckerTool:
    name = "citation_checker"

    def check(self, answer: str, docs: list[dict] | None = None, web_sources: list[dict] | None = None) -> dict:
        docs = docs or []
        web_sources = web_sources or []
        sources_exist = bool(docs or web_sources)
        text = answer or ""
        has_source_section = any(
            marker in text
            for marker in (
                "# قائمة المصادر",
                "# المصادر",
                "# المصدر",
                "# المصادر والدليل",
                "# المراجع المستخدمة",
                "# المراجع",
                "# الدليل من الملف",
                "# الدليل من المصادر",
                "من الملفات",
                "من الويب",
                "ملفات",
            )
        )
        passed = not sources_exist or has_source_section
        return {
            "name": "citation_checker",
            "passed": passed,
            "sources_exist": sources_exist,
            "message": "" if passed else "توجد مصادر مستخدمة، لكن الإجابة لا تحتوي على قسم مصادر واضح.",
        }
