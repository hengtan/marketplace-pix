import re
import unicodedata

# fmt: off
STOPWORDS = frozenset(
    {
        "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "em",
        "no", "na", "nos", "nas", "num", "numa", "para", "pra", "por", "pelo", "pela", "com", "sem",
        "e", "ou", "que", "qual", "quais", "quero", "queria", "quer", "gostaria", "algo", "algum",
        "alguma", "alguns", "algumas", "tem", "tenho", "ter", "ha", "existe", "existem", "me",
        "mim", "meu", "minha", "meus", "minhas", "voce", "voces", "mostre", "mostra", "mostrar",
        "indica", "indique", "sugira", "sugere", "preciso", "precisa", "procuro", "busco", "ate",
        "menos", "abaixo", "acima", "mais", "muito", "muita", "se", "ao", "aos", "esse", "essa",
        "esses", "essas", "isso", "este", "esta", "estes", "estas", "isto", "ele", "ela", "eles",
        "elas", "dele", "dela", "deles", "delas", "quem", "como", "onde", "quando", "sao", "ser",
        "eh", "uso", "usar", "ja", "so", "ainda", "tambem", "entre", "sobre", "reais", "real", "r",
        "qualquer", "vale", "pode", "podem", "poderia", "gosto", "ver", "fazer", "faz", "produto",
        "produtos", "categoria", "categorias", "item", "itens", "opcao", "opcoes", "nome",
        "mostrando",
    }
)
# fmt: on

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.lower()


def tokenize(text: str) -> list[str]:
    return [tok for tok in _NON_WORD.split(normalize(text)) if tok]


def content_tokens(text: str) -> list[str]:
    return [tok for tok in tokenize(text) if tok not in STOPWORDS and len(tok) > 1]


_SUFFIXES = (
    "amentos", "imentos", "amento", "imento", "adoras", "adores", "adora", "ador", "acoes",
    "ucoes", "acao", "ucao", "encias", "encia", "idades", "idade", "mente", "istas", "ista",
    "aveis", "avel", "osos", "osas", "oso", "osa", "ando", "endo", "indo", "ados", "adas", "ado",
    "ada", "idos", "idas", "ido", "ida", "ar", "er", "ir", "as", "os", "es", "a", "o", "e", "s",
)  # fmt: skip
_MIN_STEM = 4


def stem(token: str) -> str:
    """Light suffix stripping for Portuguese (plural, gender, verb endings and a few
    derivations). Far simpler than RSLP or Snowball, but enough to connect correr and corrida."""
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= _MIN_STEM:
            return token[: -len(suffix)]
    return token


def format_brl(cents: int) -> str:
    reais, centavos = divmod(cents, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"
