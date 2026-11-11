import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_CPF = re.compile(r"(?<!\d)(?:\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})(?!\d)")
_CNPJ = re.compile(r"(?<!\d)(?:\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{14})(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+?55[\s\-]?)?\(?\d{2}\)?[\s\-]?9?\d{4}[\s\-]?\d{4}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")
_TOKEN = re.compile(
    r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_\-]{16,}\b|\bBearer\s+[A-Za-z0-9._\-]{20,}"
    r"|\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
)


def _luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value = value * 2 - 9 if value * 2 > 9 else value * 2
        total += value
    return total % 10 == 0


def _cpf_valid(digits: str) -> bool:
    if len(set(digits)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1), strict=True))
        check = (total * 10) % 11 % 10
        if check != int(digits[size]):
            return False
    return True


def _sub_cpf(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return "[CPF]" if _cpf_valid(digits) else match.group(0)


def _sub_card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return "[CARTAO]" if 13 <= len(digits) <= 19 and _luhn(digits) else match.group(0)


def redact(text: str) -> str:
    """Replaces personal data with labels so that logs and traces keep their shape but not
    the data: e-mail, CPF, CNPJ, phone, payment card (Luhn-checked) and secrets."""
    out = _TOKEN.sub("[TOKEN]", text)
    out = _EMAIL.sub("[EMAIL]", out)
    out = _CNPJ.sub("[CNPJ]", out)
    out = _CARD.sub(_sub_card, out)
    out = _CPF.sub(_sub_cpf, out)
    return _PHONE.sub("[TELEFONE]", out)
