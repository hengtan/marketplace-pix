import re

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class RecursiveChunker:
    """Splits text into chunks of at most `size` characters, breaking on paragraphs,
    then sentences, then words, and repeating up to `overlap` characters of the tail
    of each chunk at the start of the next one."""

    def __init__(self, size: int, overlap: int) -> None:
        if size < 20:
            raise ValueError("chunk size must be at least 20")
        if not 0 <= overlap < size // 2:
            raise ValueError("overlap must be between 0 and half of the chunk size")
        self._size = size
        self._overlap = overlap

    def split(self, text: str) -> list[str]:
        units = self._units(text)
        chunks: list[list[str]] = []
        current: list[str] = []
        for unit in units:
            if current and self._length(current + [unit]) > self._size:
                chunks.append(current)
                current = self._tail(current)
                while current and self._length(current + [unit]) > self._size:
                    current = current[1:]
            current.append(unit)
        if current:
            chunks.append(current)
        return [" ".join(chunk) for chunk in chunks]

    def _units(self, text: str) -> list[str]:
        units: list[str] = []
        for paragraph in text.split("\n"):
            for sentence in _SENTENCE_END.split(paragraph.strip()):
                sentence = sentence.strip()
                if not sentence:
                    continue
                units.extend(self._break_long(sentence))
        return units

    def _break_long(self, sentence: str) -> list[str]:
        if len(sentence) <= self._size:
            return [sentence]
        pieces: list[str] = []
        current = ""
        for word in sentence.split():
            while len(word) > self._size:
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(word[: self._size])
                word = word[self._size :]
            candidate = f"{current} {word}".strip()
            if len(candidate) > self._size:
                pieces.append(current)
                current = word
            else:
                current = candidate
        if current:
            pieces.append(current)
        return pieces

    def _tail(self, units: list[str]) -> list[str]:
        tail: list[str] = []
        for unit in reversed(units):
            if self._length([unit, *tail]) > self._overlap:
                break
            tail.insert(0, unit)
        return tail

    @staticmethod
    def _length(units: list[str]) -> int:
        return sum(len(u) for u in units) + max(len(units) - 1, 0)


def merge_overlapping(chunks: list[str]) -> str:
    """Rebuilds the parent document from ordered chunks: the contextual header is kept once
    and sentences repeated by the overlap are dropped."""
    if not chunks:
        return ""
    header = chunks[0].split("\n", 1)[0]
    seen: set[str] = set()
    sentences: list[str] = []
    for chunk in chunks:
        body = chunk.split("\n", 1)[1] if "\n" in chunk else chunk
        for sentence in _SENTENCE_END.split(body.replace("\n", " ")):
            clean = sentence.strip()
            if clean and clean not in seen:
                seen.add(clean)
                sentences.append(clean)
    return header + "\n" + " ".join(sentences)
