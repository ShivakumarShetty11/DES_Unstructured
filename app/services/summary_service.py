import re
import sys
from collections import Counter

try:
    import anthropic
except Exception:  # pragma: no cover
    anthropic = None

# Citation / reference line patterns — sentences matching these are noise
_CITATION_RE = re.compile(
    r"\b(arxiv|doi|et al\.?|vol\.|pp\.|fig\.|eq\.|isbn|issn|preprint|proceedings|conference)\b",
    re.IGNORECASE,
)
_REF_LINE_RE = re.compile(r"^\s*\[?\d+\]?\s*[A-Z][a-z]+.*\d{4}")  # "[1] Author Name 2020"


class SummaryService:
    def __init__(self, anthropic_api_key: str | None = None):
        self._client = None
        if anthropic_api_key and anthropic is not None:
            self._client = anthropic.Anthropic(api_key=anthropic_api_key)

    def generate_summary(self, title: str, text: str) -> str:
        content = (text or "").strip()
        if not content:
            return "No readable text could be extracted from this document."

        if self._client is not None:
            summary = self._llm_summary(title=title, text=content)
            if summary:
                return summary

        return self._extractive_summary(content)

    def _llm_summary(self, title: str, text: str) -> str | None:
        # Use the first 30 000 chars — enough for abstract + body without hitting limits.
        excerpt = text[:30000]
        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=600,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "You are a precise document analyst. "
                            "Summarize the following document in 4–6 concise, factual sentences. "
                            "Cover: the main purpose or objective, key points or findings, "
                            "target audience or beneficiaries, and any notable conclusions or directives. "
                            "Write in plain prose. Do not use bullet points or markdown.\n\n"
                            f"Title: {title}\n\n"
                            f"Document text:\n{excerpt}"
                        ),
                    }
                ],
            )
            result = " ".join(
                block.text for block in response.content if getattr(block, "text", None)
            ).strip()
            return result or None
        except Exception as exc:
            print(f"[SummaryService] LLM call failed: {exc}", file=sys.stderr)
            return None

    def _extractive_summary(self, text: str) -> str:
        # Work only on the first 10 000 chars — usually abstract / executive summary.
        working = text[:10000]

        # Split into sentences, filtering short fragments and citation lines.
        raw_sentences = re.split(r"(?<=[.!?])\s+", working)
        sentences: list[tuple[str, int]] = []
        for idx, s in enumerate(raw_sentences):
            s = s.strip()
            if len(s) < 60:
                continue
            if _CITATION_RE.search(s):
                continue
            if _REF_LINE_RE.match(s):
                continue
            sentences.append((s, idx))

        if not sentences:
            # Last resort: just return the opening text
            return re.sub(r"\s+", " ", working).strip()[:800]

        stopwords = {
            "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
            "have", "has", "had", "into", "their", "they", "will", "shall", "under", "all",
            "any", "such", "not", "but", "its", "his", "her", "our", "you", "your", "about",
            "also", "which", "been", "more", "than", "each", "can", "may", "use", "used",
        }

        words = re.findall(r"[a-zA-Z]{3,}", working.lower())
        freq = Counter(w for w in words if w not in stopwords)

        def score(sentence: str) -> float:
            tokens = re.findall(r"[a-zA-Z]{3,}", sentence.lower())
            if not tokens:
                return 0.0
            return sum(freq.get(t, 0) for t in tokens if t not in stopwords) / len(tokens)

        scored = [(s, score(s), idx) for s, idx in sentences]
        scored.sort(key=lambda x: x[1], reverse=True)
        top = sorted(scored[:5], key=lambda x: x[2])  # restore reading order
        return " ".join(x[0] for x in top)[:1800]
