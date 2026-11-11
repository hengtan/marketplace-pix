import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from assistant.domain.lexicon import CONCEPTS, GENERIC_WORDS, SHOPPING_WORDS
from assistant.domain.policies import (
    POLICIES,
    POLICY_TRIGGERS,
    WEAK_POLICY_TRIGGERS,
    PolicyEntry,
)
from assistant.domain.text import STOPWORDS, content_tokens, normalize, stem, tokenize

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
STOCK_WORDS = frozenset(
    {
        "estoque", "disponivel", "disponiveis", "disponibilidade", "unidades", "unidade",
        "quantas", "quantos", "restam", "sobrando", "falta",
    }
)  # fmt: skip
ORDER_WORDS = frozenset({"pedido", "pedidos", "encomenda", "compra"})
_ORDER_STRONG = frozenset({"pedido", "pedidos", "encomenda"})
REFERENCES = frozenset(
    {
        "esse", "essa", "desse", "dessa", "deste", "desta", "este", "esta", "dele", "dela",
        "aquele", "deles", "delas", "desses", "dessas", "destes", "destas", "esses", "essas",
    }
)  # fmt: skip
_NEGATION_MARKERS = (
    "nao quero", "nao precisa", "nao pode ser", "que nao seja", "que nao sejam", "exceto",
    "tirando", "menos o", "menos a", "menos os", "menos as", "sem ser", "nao me mostre",
    "nao mostre", "diferente de",
)  # fmt: skip
_NEGATION = re.compile(
    r"(?:" + "|".join(re.escape(m) for m in _NEGATION_MARKERS) + r")\s+(?P<target>[a-z0-9 ]+?)"
    r"(?=\s*(?:,|;|\.|\?|!|\bmas\b|\bporem\b|\bpara\b|\bque\b|\bate\b|$))"
)
_SPLIT = re.compile(
    r"\s*(?:;|\?\s+|\be tambem\b|\balem disso\b|\balem de\b|\be ainda\b|\be depois\b)\s*"
)
_AND = re.compile(r"\s+e\s+")


class Intent(StrEnum):
    CATALOG = "catalog"
    ORDER = "order"
    STOCK = "stock"
    POLICY = "policy"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True)
class Vocabulary:
    doc_freq: Mapping[str, int]
    documents: int
    stems: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_documents(cls, documents: Iterable[str]) -> "Vocabulary":
        counter: Counter[str] = Counter()
        total = 0
        for text in documents:
            total += 1
            counter.update(set(content_tokens(text)))
        return cls(dict(counter), total, frozenset(stem(t) for t in counter))

    @classmethod
    def empty(cls) -> "Vocabulary":
        return cls({}, 0)

    def knows(self, token: str) -> bool:
        return token in self.doc_freq or stem(token) in self.stems

    def is_domain_term(self, token: str, max_share: float = 0.15) -> bool:
        if not self.documents or token in GENERIC_WORDS:
            return False
        limit = max(3, int(self.documents * max_share))
        return 1 <= self.doc_freq.get(token, 0) <= limit


def edit_distance(a: str, b: str, limit: int) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous2: list[int] = []
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                value = min(value, previous2[j - 2] + 1)
            current.append(value)
        previous2, previous = previous, current
    return previous[-1]


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    reason: str
    policy: PolicyEntry | None = None


class IntentClassifier:
    def __init__(self, vocabulary: Vocabulary) -> None:
        self._vocab = vocabulary
        self._concept_stems = frozenset(
            stem(t) for concept in CONCEPTS for t in (*concept.triggers, *concept.expansions)
        )

    def classify(
        self, question: str, has_remembered_products: bool = False, has_filters: bool = False
    ) -> IntentResult:
        tokens = set(tokenize(question))
        if _UUID.search(question):
            return IntentResult(Intent.ORDER, "order code")
        if tokens & _ORDER_STRONG:
            return IntentResult(Intent.ORDER, "order word")
        if tokens & STOCK_WORDS:
            return IntentResult(Intent.STOCK, "stock word")
        policy = self._policy(tokens)
        if policy is not None and self._weak_only(tokens) and self._mentions_product(question):
            policy = None
        if policy is not None:
            return IntentResult(Intent.POLICY, f"policy {policy.topic}", policy)
        if has_remembered_products and tokens & (REFERENCES | SHOPPING_WORDS):
            return IntentResult(Intent.CATALOG, "follow-up")
        if has_filters or tokens & SHOPPING_WORDS:
            return IntentResult(Intent.CATALOG, "shopping words or filters")
        for token in content_tokens(question):
            if (
                self._vocab.is_domain_term(token)
                or token in self._concept_stems
                or stem(token) in self._concept_stems
            ):
                return IntentResult(Intent.CATALOG, "domain term")
        return IntentResult(Intent.OUT_OF_SCOPE, "no domain term")

    @staticmethod
    def _weak_only(tokens: set[str]) -> bool:
        return not (tokens & POLICY_TRIGGERS) - WEAK_POLICY_TRIGGERS

    def _mentions_product(self, question: str) -> bool:
        return any(
            (self._vocab.is_domain_term(t) or stem(t) in self._concept_stems)
            and t not in POLICY_TRIGGERS
            for t in content_tokens(question)
        )

    @staticmethod
    def _policy(tokens: set[str]) -> PolicyEntry | None:
        if not tokens & POLICY_TRIGGERS:
            return None
        best: tuple[int, PolicyEntry] | None = None
        for entry in POLICIES:
            overlap = len(tokens & entry.triggers)
            if overlap and (best is None or overlap > best[0]):
                best = (overlap, entry)
        return best[1] if best else None


@dataclass(frozen=True)
class Correction:
    original: str
    corrected: str


class TypoCorrector:
    def __init__(self, vocabulary: Vocabulary) -> None:
        self._vocab = vocabulary
        self._by_length: dict[int, list[str]] = {}
        for word in vocabulary.doc_freq:
            self._by_length.setdefault(len(word), []).append(word)

    def correct(self, tokens: Sequence[str]) -> tuple[list[str], list[Correction]]:
        out: list[str] = []
        fixes: list[Correction] = []
        for token in tokens:
            fixed = self._fix(token)
            if fixed != token:
                fixes.append(Correction(token, fixed))
            out.append(fixed)
        return out, fixes

    def _fix(self, token: str) -> str:
        if (
            len(token) < 5
            or token in STOPWORDS
            or token.isdigit()
            or self._vocab.knows(token)
            or token in SHOPPING_WORDS
            or token in POLICY_TRIGGERS
            or token in STOCK_WORDS
            or any(token in c.triggers or token in c.expansions for c in CONCEPTS)
        ):
            return token
        limit = 1 if len(token) <= 7 else 2
        best: tuple[int, int, str] | None = None
        for length in range(len(token) - limit, len(token) + limit + 1):
            for candidate in self._by_length.get(length, ()):
                distance = edit_distance(token, candidate, limit)
                if distance > limit or candidate[0] != token[0] and distance > 1:
                    continue
                rank = (distance, -self._vocab.doc_freq[candidate], candidate)
                if best is None or rank < best:
                    best = rank
        return best[2] if best else token


class SynonymExpander:
    def __init__(self, max_terms: int = 8) -> None:
        self._max = max_terms
        self._concepts = [(frozenset(stem(t) for t in c.triggers), c.expansions) for c in CONCEPTS]

    def expand(self, tokens: Sequence[str]) -> list[str]:
        stems = {stem(t) for t in tokens} | set(tokens)
        present = {t for t in tokens}
        found: list[str] = []
        for triggers, expansions in self._concepts:
            if stems & triggers:
                for term in expansions:
                    if term not in present and term not in found:
                        found.append(term)
        return found[: self._max]


def hypothetical_document(query_tokens: Sequence[str], expansions: Sequence[str]) -> str:
    subject = " ".join(query_tokens)
    related = ", ".join(expansions)
    text = f"Produto ideal para {subject}."
    if related:
        text += f" Palavras-chave: {related}."
    return text


@dataclass(frozen=True)
class SubQuery:
    text: str


class QueryDecomposer:
    def __init__(self, vocabulary: Vocabulary) -> None:
        self._vocab = vocabulary
        self._concept_stems = frozenset(
            stem(t) for concept in CONCEPTS for t in (*concept.triggers, *concept.expansions)
        )

    def decompose(self, question: str) -> list[str]:
        text = question.strip()
        if re.search(r"\b(compar\w+|diferenca|versus|vs)\b", normalize(text)):
            return [text]
        parts = [p for p in _SPLIT.split(text) if p.strip()]
        result: list[str] = []
        for part in parts:
            result.extend(self._split_and(part))
        return result if len(result) > 1 else [text]

    def _split_and(self, part: str) -> list[str]:
        pieces = _AND.split(normalize(part))
        original = _AND.split(part)
        if len(pieces) < 2 or len(pieces) != len(original):
            return [part]
        if all(self._is_product_phrase(p) for p in pieces):
            return [p.strip() for p in original]
        return [part]

    def _is_product_phrase(self, piece: str) -> bool:
        tokens = [t for t in content_tokens(piece) if t not in SHOPPING_WORDS]
        if len(tokens) < 1:
            return False
        strong = [
            t
            for t in tokens
            if self._vocab.is_domain_term(t, 0.08) or stem(t) in self._concept_stems
        ]
        return len(strong) >= 1 and len(tokens) >= 2


@dataclass(frozen=True)
class Negation:
    terms: tuple[str, ...]
    text: str


def extract_negations(question: str) -> Negation:
    text = normalize(question)
    terms: list[str] = []

    def take(match: re.Match[str]) -> str:
        terms.extend(t for t in content_tokens(match.group("target")))
        return " "

    cleaned = _NEGATION.sub(take, text)
    return Negation(tuple(terms), " ".join(cleaned.split()))
