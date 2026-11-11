from dataclasses import dataclass


@dataclass(frozen=True)
class Concept:
    triggers: tuple[str, ...]
    expansions: tuple[str, ...]


CONCEPTS: tuple[Concept, ...] = (
    Concept(
        ("ouvir", "musica", "escutar", "podcast", "audio", "som"),
        ("fone", "headphone", "bluetooth", "caixa", "audio"),
    ),
    Concept(
        ("frio", "inverno", "esquentar", "aquecer", "quentinho", "aconchegante", "cobertor"),
        ("manta", "cobertor", "algodao", "aconchego"),
    ),
    Concept(
        ("exercitar", "exercicio", "treinar", "treino", "malhar", "academia", "musculacao"),
        ("elastico", "tapete", "corda", "yoga", "forca", "treino"),
    ),
    Concept(
        ("correr", "corrida", "maratona", "caminhada", "running", "cooper"),
        ("tenis", "corrida", "relogio", "gps", "esporte"),
    ),
    Concept(("cafe", "expresso", "cappuccino"), ("cafeteira", "prensa", "cafe")),
    Concept(
        ("cozinhar", "cozinha", "cortar", "culinaria", "churrasco", "chef"),
        ("faca", "facas", "cozinha", "inox"),
    ),
    Concept(("luz", "iluminar", "iluminacao", "claridade", "abajur"), ("luminaria", "led")),
    Concept(
        ("decorar", "decoracao", "enfeite", "enfeitar", "ambiente"),
        ("vaso", "luminaria", "relogio", "decoracao", "parede"),
    ),
    Concept(
        ("computador", "notebook", "pc", "escritorio", "digitar", "digitacao"),
        ("teclado", "mouse", "webcam", "hub", "usb-c"),
    ),
    Concept(
        ("reuniao", "videochamada", "chamada", "live", "streaming", "stream"),
        ("webcam", "camera", "4k"),
    ),
    Concept(
        ("bateria", "carregar", "recarregar", "tomada", "energia"),
        ("carregador", "usb-c", "gan", "rapido"),
    ),
    Concept(
        ("agua", "hidratar", "hidratacao", "gelada", "gelado", "gelar", "termica"),
        ("garrafa", "termica", "aco", "isolamento"),
    ),
    Concept(
        ("bicicleta", "pedalar", "ciclismo", "bike", "ciclista"), ("capacete", "bike", "protecao")
    ),
    Concept(
        ("acampar", "camping", "trilha", "trilhas", "aventura", "mochilar"),
        ("mochila", "trilha", "gps", "impermeavel"),
    ),
    Concept(
        ("relaxar", "relaxamento", "aroma", "aromaterapia", "estresse", "meditar", "calmo"),
        ("difusor", "aromas", "calma", "yoga", "oleos"),
    ),
    Concept(
        ("organizar", "organizacao", "bagunca", "arrumar", "guardar"),
        ("organizador", "bambu", "set"),
    ),
    Concept(("pulso", "horas", "hora", "ponteiro"), ("relogio", "smartwatch")),
    Concept(
        ("saude", "batimento", "cardiaco", "passos", "monitorar", "monitoramento"),
        ("smartwatch", "relogio", "gps"),
    ),
    Concept(("gamer", "jogar", "jogos", "games"), ("teclado", "mouse", "rgb", "mecanico")),
    Concept(("celular", "smartphone", "iphone", "android"), ("usb-c", "carregador", "fone")),
    Concept(("wireless", "bluetooth"), ("sem", "fio")),
    Concept(("headphone", "headset", "fones"), ("fone", "bluetooth", "audio")),
    Concept(("tapete", "yoga", "pilates", "alongar", "alongamento"), ("tapete", "yoga", "grip")),
    Concept(("planta", "plantas", "flor", "flores", "jardim"), ("vaso", "ceramica", "decoracao")),
)

SHOPPING_WORDS = frozenset(
    {
        "comprar", "compra", "barato", "barata", "baratos", "caro", "cara", "preco", "precos",
        "custa", "custam", "valor", "avaliado", "avaliada", "avaliacao", "avaliacoes", "nota",
        "compare", "comparar", "comparacao", "diferenca", "presente", "presentear", "recomenda",
        "recomendacao", "indicar", "oferta", "promocao", "desconto", "marca", "modelo",
    }
)  # fmt: skip
