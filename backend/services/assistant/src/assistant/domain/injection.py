import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass

_ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠-⁤﻿­]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACED = re.compile(r"(?<![a-z0-9])(?:[a-z0-9][\s.\-_*]){4,}[a-z0-9](?![a-z0-9])")
_BASE64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/=])")
_HOMOGLYPHS = str.maketrans(
    {"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "і": "i", "ѕ": "s", "ј": "j",
     "ο": "o", "ν": "v", "ɑ": "a", "ⅼ": "l", "ⅰ": "i"}
)  # fmt: skip
_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)
_WORD = r"[a-z]*"


@dataclass(frozen=True)
class Detection:
    score: float
    categories: tuple[str, ...]
    matches: tuple[str, ...]

    @property
    def flagged(self) -> bool:
        return self.score > 0


def canonical(text: str) -> str:
    cleaned = _CONTROL.sub(" ", _ZERO_WIDTH.sub("", text)).translate(_HOMOGLYPHS)
    decomposed = unicodedata.normalize("NFKD", cleaned)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    return " ".join(stripped.split())


def _despace(text: str) -> str:
    return _SPACED.sub(lambda m: re.sub(r"[\s.\-_*]", "", m.group(0)), text)


def _rules() -> list[tuple[str, float, re.Pattern[str]]]:
    ignore = (
        r"(?:ignor\w*|desconsider\w*|esquec\w*|descart\w*|disregard|forget|override|bypass|skip)"
    )
    target = (
        r"(?:instruc\w*|regra\w*|ordens|orientac\w*|prompt\w*|diretriz\w*|instruction\w*|"
        r"rules?|guidelines?|context\w*|restric\w*|restrictions?|filtros?|seguranca|safety)"
    )
    reveal = (
        r"(?:revel\w*|mostr\w*|exib\w*|repit\w*|imprim\w*|print|show|reveal|repeat|display|"
        r"output|leak|dump|copie|copy|vaz\w*)"
    )
    secret = (
        r"(?:prompt\w*\s+(?:do\s+)?(?:sistema|system|inicial)|system\s*prompt|"
        r"(?:suas?|your|seus?)\s+(?:instruc\w*|instruction\w*|regras|rules|prompt)|"
        r"(?:texto|mensagem|text|message)\s+(?:acima|anterior|inicial|above|before)|"
        r"instruc\w*\s+(?:iniciais|originais|internas)|initial\s+instruction\w*)"
    )
    rules: list[tuple[str, float, str]] = [
        (
            "override_instructions",
            0.9,
            rf"\b{ignore}\s+(?:\w+\s+){{0,3}}{target}"
            rf"|\b{target}\s+(?:anteriores|acima|previas|previous|above|prior)\b"
            rf"|\b(?:ignore|disregard|forget|esquec\w*)\s+(?:all|everything|tudo|todas?|isso)\b"
            r"|\bapague\s+(?:tudo|sua\s+memoria|o\s+contexto)",
        ),
        (
            "role_hijack",
            0.8,
            r"\b(?:voce|tu|you)\s+(?:agora\s+|now\s+)?(?:e|eh|sera|are|will\s+be)\s+(?:um|uma|o|a|an?|the)\s+\w+"
            r"|\b(?:finja|simule|aja\s+como|atue\s+como|pretend|act\s+as|roleplay|role-play|assuma\s+o\s+papel)\b"
            r"|\ba\s+partir\s+de\s+agora\b|\bfrom\s+now\s+on\b"
            r"|\b(?:dan|jailbreak|developer\s+mode|modo\s+desenvolvedor|sem\s+restric\w*|no\s+restrictions|unrestricted)\b",
        ),
        (
            "prompt_exfiltration",
            0.9,
            rf"\b{reveal}\s+(?:\w+\s+){{0,4}}{secret}"
            rf"|\b(?:qual|quais|what)\s+(?:e|sao|is|are)\s+(?:\w+\s+){{0,2}}{secret}"
            r"|\b(?:repita|repeat)\s+(?:o\s+)?(?:texto|text|tudo|everything)\s+(?:acima|above)",
        ),
        (
            "delimiter_spoof",
            0.8,
            r"</?\s*(?:contexto|trecho|observacoes|ferramenta|system|sistema|instrucoes|assistant|user)\b"
            r"|<\|[a-z_]+\|>|\[\s*/?\s*(?:inst|system|sys)\b|<<\s*sys\s*>>"
            r"|(?:^|\n|\.\s)\s*(?:system|sistema|assistant|assistente)\s*:"
            r"|#{2,}\s*(?:system|sistema|instruction|instrucao)",
        ),
        (
            "tool_abuse",
            0.7,
            r"\b(?:chame|chamar|execute|executar|invoque|use|utilize|call|invoke|run)\s+(?:\w+\s+){0,2}"
            r"(?:ferramenta|tool|funcao|function|get_order_status|get_stock|search_products|get_policy)\b"
            r"|\b(?:todos\s+os\s+pedidos|all\s+orders|pedido\s+de\s+outr[oa]|another\s+customer)"
            r"|\b(?:drop|delete|truncate)\s+table\b|\bunion\s+select\b|;\s*--",
        ),
        (
            "exfil_channel",
            0.8,
            r"!\[[^\]]*\]\s*\(\s*(?:https?:)?//"
            r"|<\s*(?:img|iframe|script|a|link)\b[^>]*(?:src|href)\s*="
            r"|\b(?:envie|enviar|mande|send|post|forward|exfiltr\w*|upload)\b[^.]{0,60}\b(?:https?://|para\s+o\s+(?:e-?mail|site|servidor)|to\s+(?:the\s+)?(?:server|email))"
            r"|\b(?:curl|wget|fetch)\s+https?://",
        ),
        (
            "output_forcing",
            0.6,
            r"\b(?:responda|answer|reply|respond)\s+(?:\w+\s+){0,2}(?:apenas|somente|sempre|only|always|exatamente)\s+(?:com|with)\b"
            r"|\b(?:diga|dizer|say|tell)\s+(?:ao|para\s+o|the)?\s*(?:usuario|cliente|user|customer)?\s*que\b"
            r"|\b(?:voce\s+deve|you\s+must|sempre\s+recomende|always\s+recommend|recomende\s+(?:apenas|somente|este|esse))\b",
        ),
        (
            "authority_claim",
            0.5,
            r"\b(?:sou|eu\s+sou|i\s+am|this\s+is)\s+(?:o\s+|a\s+|the\s+|an?\s+)?(?:administrador|admin|desenvolvedor|developer|dono|owner|operador|sysadmin|mantenedor)"
            r"|\b(?:mensagem|ordem|autorizacao)\s+(?:do|da|de)\s+(?:administrador|sistema|desenvolvedor|equipe)"
            r"|\b(?:autorizado|authorized)\s+(?:pelo|by\s+the)\s+(?:sistema|system|admin)",
        ),
        (
            "price_manipulation",
            0.7,
            r"\b(?:tudo|todos\s+os\s+produtos|everything|all\s+products)\s+(?:e|eh|sao|esta|estao|is|are|custa\w*|cost\w*)\s+(?:de\s+)?(?:gratis|gratuito\w*|free|zero|r\$\s*0)"
            r"|\b(?:preco|price)\s+(?:e|eh|is|=)\s*(?:zero|0|gratis|free)"
            r"|\bdesconto\s+de\s+100\s*%|\b100\s*%\s+(?:de\s+)?desconto",
        ),
    ]
    return [(name, weight, re.compile(pattern)) for name, weight, pattern in rules]


_RULES = _rules()
_SQUASHED = [
    (
        "override_instructions",
        0.9,
        re.compile(
            r"(?:ignor(?:e|ar)?|desconsider(?:e|ar)?|esquec(?:a|er)?|disregard|forget)"
            r"(?:todas|todos|as|os|suas|seus|the|all|previous|anteriores|your)*"
            r"(?:instruc\w*|regras|rules|instruction\w*|prompt|ordens|tudo)"
        ),
    ),
    (
        "prompt_exfiltration",
        0.9,
        re.compile(
            r"(?:revel(?:e|ar)|mostr(?:e|ar)|show|reveal|repit(?:a|ir)|print|exib(?:a|ir))"
            r"(?:o|seu|suas|your|the|me)*(?:systemprompt|promptdosistema|instrucoes|prompt)"
        ),
    ),
]


class InjectionDetector:
    """Scores text for prompt injection. The text is canonicalized first (accents, case,
    zero-width characters, homoglyphs, spaced letters, leetspeak, base64 payloads) so that
    simple obfuscation does not hide an attack."""

    def scan(self, text: str) -> Detection:
        variants, squashed = self._variants(text)
        best: dict[str, tuple[float, str]] = {}

        def note(name: str, weight: float, found: str) -> None:
            if weight > best.get(name, (0.0, ""))[0]:
                best[name] = (weight, found.strip()[:80])

        for variant in variants:
            for name, weight, pattern in _RULES:
                match = pattern.search(variant)
                if match:
                    note(name, weight, match.group(0))
        for variant in squashed:
            for name, weight, pattern in _SQUASHED:
                match = pattern.search(variant)
                if match:
                    note(name, weight, match.group(0))
        if not best:
            return Detection(0.0, (), ())
        top = max(w for w, _ in best.values())
        score = min(1.0, top + 0.05 * (len(best) - 1))
        names = tuple(sorted(best))
        return Detection(round(score, 3), names, tuple(m for _, m in best.values()))

    @staticmethod
    def _variants(text: str) -> tuple[list[str], list[str]]:
        base = canonical(text)
        despaced = _despace(base)
        leet = base.translate(_LEET)
        variants = [base, despaced, leet, despaced.translate(_LEET)]
        for blob in _BASE64.findall(text):
            decoded = _decode(blob)
            if decoded:
                variants.append(canonical(decoded))
        squashed = [re.sub(r"[\s.\-_*]", "", despaced)] if despaced != base else []
        return list(dict.fromkeys(variants)), squashed


def _decode(blob: str) -> str | None:
    try:
        raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True)
        decoded = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    return decoded if decoded.isprintable() else None
