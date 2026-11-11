from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

UNSPLASH = "https://images.unsplash.com/photo-{}?auto=format&fit=crop&w=900&q=80"
SEED_EPOCH = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def merchant_id(slug: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"marketplace-pix:merchant:{slug}")


def product_id(slug: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"marketplace-pix:product:{slug}")


@dataclass(frozen=True, slots=True)
class SeedMerchant:
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class SeedProduct:
    slug: str
    name: str
    category: str
    merchant: str
    price_cents: int
    description: str
    tags: tuple[str, ...]
    rating: Decimal
    reviews_count: int
    photo: str | None = None

    @property
    def image_url(self) -> str | None:
        return UNSPLASH.format(self.photo) if self.photo else None


CATEGORIES: tuple[tuple[str, str], ...] = (
    ("tecnologia", "Tecnologia"),
    ("casa", "Casa e decoração"),
    ("esporte", "Esporte e aventura"),
)

MERCHANTS: tuple[SeedMerchant, ...] = (
    SeedMerchant("aurora-tech", "Aurora Tech"),
    SeedMerchant("casa-lume", "Casa Lume"),
    SeedMerchant("trilha-sports", "Trilha Sports"),
)


def _p(
    slug: str,
    name: str,
    category: str,
    merchant: str,
    price_cents: int,
    description: str,
    tags: tuple[str, ...],
    rating: str,
    reviews_count: int,
    photo: str | None,
) -> SeedProduct:
    return SeedProduct(
        slug, name, category, merchant, price_cents, description, tags, Decimal(rating),
        reviews_count, photo,
    )  # fmt: skip


PRODUCTS: tuple[SeedProduct, ...] = (
    _p(
        "fone-bluetooth-nova",
        "Fone Bluetooth Nova ANC",
        "tecnologia",
        "aurora-tech",
        34990,
        "Cancelamento ativo de ruído que silencia o metrô, o escritório e o que mais atrapalhar. "
        "Almofadas macias de espuma viscoelástica e até 40 horas de bateria com uma única carga. "
        "Conexão multiponto para alternar entre o celular e o notebook sem esforço.",
        ("fone", "bluetooth", "headphone", "anc", "áudio", "sem fio"),
        "4.7",
        1284,
        "1546435770-a3e426bf472b",
    ),
    _p(
        "caixa-som-pulse",
        "Caixa de Som Pulse 360",
        "tecnologia",
        "aurora-tech",
        21990,
        "Som que preenche o ambiente em todas as direções, com graves firmes e vozes nítidas. "
        "Resistente a respingos e poeira, acompanha você da varanda à beira da piscina. "
        "São 14 horas de reprodução e pareamento duplo para formar um par estéreo.",
        ("caixa de som", "bluetooth", "speaker", "áudio", "portátil"),
        "4.5",
        962,
        "1589003077984-894e133dabab",
    ),
    _p(
        "smartwatch-orbit",
        "Smartwatch Orbit S2",
        "tecnologia",
        "aurora-tech",
        49990,
        "Tela AMOLED luminosa, monitoramento de sono, frequência cardíaca e oxigenação do sangue. "
        "Mais de 100 modos de treino e GPS integrado para registrar cada trajeto. "
        "A bateria rende até 10 dias de uso e a caixa em aço mantém o visual elegante.",
        ("smartwatch", "relógio inteligente", "saúde", "gps", "wearable"),
        "4.4",
        731,
        "1546868871-7041f2a55e12",
    ),
    _p(
        "teclado-mecanico-forge",
        "Teclado Mecânico Forge 75%",
        "tecnologia",
        "aurora-tech",
        38990,
        "Formato compacto de 75% com switches lineares substituíveis a quente e som encorpado. "
        "Estrutura em alumínio, espuma de amortecimento interna e iluminação RGB por tecla. "
        "Conecta por cabo, Bluetooth ou receptor sem fio, com bateria para semanas.",
        ("teclado", "mecânico", "75%", "rgb", "periférico", "escritório"),
        "4.8",
        546,
        "1618384887929-16ec33fab9ef",
    ),
    _p(
        "mouse-glide-pro",
        "Mouse sem fio Glide Pro",
        "tecnologia",
        "aurora-tech",
        17990,
        "Design ergonômico que acomoda a mão em jornadas longas, com sensor de alta precisão. "
        "Cliques silenciosos, roda de rolagem suave e seis botões programáveis. "
        "Uma bateria recarregável dura até 70 dias e a carga rápida "
        "garante horas de uso em minutos.",
        ("mouse", "sem fio", "ergonômico", "periférico", "escritório"),
        "4.6",
        1103,
        "1563297007-0686b7003af7",
    ),
    _p(
        "webcam-clear-4k",
        "Webcam Clear 4K",
        "tecnologia",
        "aurora-tech",
        25990,
        "Imagem em 4K com foco automático rápido e correção de luz para reuniões sempre nítidas. "
        "Microfones duplos com redução de ruído e tampa física de privacidade. "
        "O clipe universal se ajusta a monitores, notebooks e tripés.",
        ("webcam", "4k", "videochamada", "home office", "streaming"),
        "4.3",
        418,
        "1760348213920-d2a90ed705fd",
    ),
    _p(
        "carregador-turbo-65w",
        "Carregador Turbo 65W GaN",
        "tecnologia",
        "aurora-tech",
        12990,
        "Tecnologia GaN que entrega 65 W em um corpo do tamanho de um cartão de crédito. "
        "Duas portas USB-C e uma USB-A recarregam notebook, celular e fones ao mesmo tempo. "
        "Proteção contra sobreaquecimento e plugue retrátil para caber em qualquer mochila.",
        ("carregador", "gan", "usb-c", "65w", "notebook", "celular"),
        "4.7",
        2210,
        "1583863788434-e58a36330cf0",
    ),
    _p(
        "hub-usbc-dock",
        "Hub USB-C Dock 8 em 1",
        "tecnologia",
        "aurora-tech",
        15990,
        "Transforme uma única porta em oito: HDMI 4K, USB 3.0, leitor SD, microSD "
        "e carga de 100 W. "
        "Corpo em alumínio que dissipa calor e combina com notebooks finos. "
        "Basta conectar e usar, sem drivers e sem configuração.",
        ("hub", "usb-c", "dock", "hdmi", "adaptador", "notebook"),
        "4.2",
        689,
        "1760376789487-994070337c76",
    ),
    _p(
        "luminaria-arco-dourado",
        "Luminária Arco Dourado",
        "casa",
        "casa-lume",
        28990,
        "Haste curva com acabamento dourado escovado que desenha um arco elegante sobre o sofá. "
        "Cúpula de tecido que difunde uma luz quente e acolhedora para leitura e conversas. "
        "Base estável de mármore sintético e interruptor de pedal no cabo.",
        ("luminária", "luminaria", "arco", "decoração", "iluminação", "sala"),
        "4.8",
        357,
        "1540932239986-30128078f3c5",
    ),
    _p(
        "cafeteira-prensa-francesa",
        "Cafeteira Prensa Francesa",
        "casa",
        "casa-lume",
        14990,
        "Jarra de vidro borossilicato resistente ao calor com estrutura em aço inox. "
        "O filtro de malha dupla preserva os óleos do café e entrega uma xícara encorpada. "
        "Capacidade de 1 litro, perfeita para a mesa do café da manhã.",
        ("cafeteira", "prensa francesa", "café", "cozinha", "inox"),
        "4.6",
        874,
        "1708127368781-cd5f069a90a5",
    ),
    _p(
        "vaso-ceramica-terra",
        "Vaso de Cerâmica Terra",
        "casa",
        "casa-lume",
        8990,
        "Peça modelada à mão em cerâmica com esmalte fosco em tom de terra. "
        "Cada vaso tem pequenas variações de textura que o tornam único. "
        "Ótimo para flores secas, folhagens ou como objeto de destaque na estante.",
        ("vaso", "cerâmica", "decoração", "artesanal", "plantas"),
        "4.5",
        421,
        "1485955900006-10f4d324d411",
    ),
    _p(
        "manta-algodao-nuvem",
        "Manta de Algodão Nuvem",
        "casa",
        "casa-lume",
        19990,
        "Algodão penteado em tecelagem aberta, leve no verão e aconchegante nas noites frias. "
        "Textura macia desde a primeira lavada e franjas feitas à mão. "
        "Combina com sofás, camas e poltronas, e vai direto à máquina de lavar.",
        ("manta", "algodão", "cama", "sofá", "têxtil", "decoração"),
        "4.7",
        638,
        "1637819976869-928427bd7380",
    ),
    _p(
        "jogo-facas-chef",
        "Jogo de Facas Chef",
        "casa",
        "casa-lume",
        32990,
        "Cinco lâminas em aço inoxidável de alto carbono com fio afiado de fábrica. "
        "Cabos de madeira com pegada firme e equilíbrio pensado para cortes longos sem cansaço. "
        "Acompanha estojo em tecido para guardar e transportar.",
        ("facas", "chef", "cozinha", "aço inox", "utensílios"),
        "4.9",
        296,
        "1544233726-9f1d2b27be8b",
    ),
    _p(
        "difusor-aromas-calma",
        "Difusor de Aromas Calma",
        "casa",
        "casa-lume",
        11990,
        "Névoa ultrafina que espalha o aroma dos seus óleos essenciais por até oito horas. "
        "Luz ambiente em tons quentes e desligamento automático quando a água acaba. "
        "Funcionamento silencioso, ideal para quarto, escritório e momentos de descanso.",
        ("difusor", "aromas", "óleos essenciais", "aromaterapia", "bem-estar"),
        "4.4",
        512,
        "1596461404969-9ae70f2830c1",
    ),
    _p(
        "relogio-parede-minimal",
        "Relógio de Parede Minimal",
        "casa",
        "casa-lume",
        9990,
        "Mostrador limpo, ponteiros finos e moldura preta que se encaixam em qualquer parede. "
        "Mecanismo silencioso que não faz o tique-taque incômodo dos modelos comuns. "
        "Diâmetro de 30 cm, funciona com uma pilha AA.",
        ("relógio", "parede", "minimalista", "decoração", "silencioso"),
        "4.3",
        389,
        "1495364141860-b0d03eccd065",
    ),
    _p(
        "organizador-bambu-set",
        "Organizador de Bambu Set",
        "casa",
        "casa-lume",
        7990,
        "Conjunto de três peças em bambu natural para mesas, gavetas e bancadas. "
        "Acabamento liso e resistente à umidade, com divisórias que acomodam "
        "do essencial ao miúdo. "
        "Um material renovável que traz calma e ordem à rotina.",
        ("organizador", "bambu", "escritório", "mesa", "sustentável"),
        "4.2",
        267,
        "1751107756600-fb136501dec7",
    ),
    _p(
        "tenis-corrida-vento",
        "Tênis de Corrida Vento",
        "esporte",
        "trilha-sports",
        45990,
        "Entressola de espuma responsiva que devolve energia a cada passada. "
        "Cabedal em malha respirável e solado com aderência para asfalto molhado. "
        "Leve, com apenas 240 g, e pronto para treinos longos e provas de rua.",
        ("tênis", "tenis", "corrida", "running", "calçado", "treino"),
        "4.6",
        1427,
        "1460353581641-37baddab0fa2",
    ),
    _p(
        "mochila-trilha-30l",
        "Mochila de Trilha 30L",
        "esporte",
        "trilha-sports",
        31990,
        "Tecido ripstop impermeável e costuras reforçadas para aguentar o peso e o tempo. "
        "Costas ventiladas, alças acolchoadas e compartimento para bolsa de hidratação. "
        "Cobertura de chuva embutida e bolsos laterais de fácil acesso.",
        ("mochila", "trilha", "30l", "camping", "aventura", "impermeável"),
        "4.7",
        583,
        "1581605405669-fcdf81165afa",
    ),
    _p(
        "garrafa-termica-aco-750",
        "Garrafa Térmica Aço 750 ml",
        "esporte",
        "trilha-sports",
        9990,
        "Parede dupla a vácuo que mantém a bebida gelada por 24 horas ou quente por 12. "
        "Aço inoxidável sem gosto residual, tampa que veda e boca larga para colocar gelo. "
        "Cabe no porta-copos do carro e na lateral da mochila.",
        ("garrafa", "térmica", "aço inox", "hidratação", "squeeze"),
        "4.8",
        1891,
        "1570831739435-6601aa3fa4fb",
    ),
    _p(
        "tapete-yoga-grip",
        "Tapete de Yoga Grip",
        "esporte",
        "trilha-sports",
        12990,
        "Superfície antiderrapante que mantém as mãos e os pés firmes "
        "até nas posturas mais suadas. "
        "Espessura de 6 mm para amortecer joelhos e punhos sem perder o equilíbrio. "
        "Material ecológico, fácil de limpar e acompanha alça de transporte.",
        ("tapete", "yoga", "pilates", "fitness", "antiderrapante"),
        "4.6",
        745,
        "1506126613408-eca07ce68773",
    ),
    _p(
        "relogio-gps-trail",
        "Relógio GPS Trail",
        "esporte",
        "trilha-sports",
        64990,
        "GPS de múltiplas bandas com mapas offline e navegação por trilhas para não se perder. "
        "Altímetro, bússola e barômetro calibrados, com alertas de tempestade. "
        "Bateria de até 30 dias no modo relógio e caixa resistente a impactos e água.",
        ("relógio", "gps", "trilha", "corrida", "outdoor", "altímetro"),
        "4.9",
        214,
        "1434493789847-2f02dc6ca35d",
    ),
    _p(
        "capacete-bike-aero",
        "Capacete de Bike Aero",
        "esporte",
        "trilha-sports",
        27990,
        "Casco aerodinâmico com 18 entradas de ar para manter a cabeça fresca em subidas longas. "
        "Ajuste fino por roda traseira e forro removível e lavável. "
        "Certificado para uso em ciclismo de estrada e urbano.",
        ("capacete", "bike", "ciclismo", "aero", "segurança"),
        "4.5",
        392,
        "1596731530340-64945278d9f6",
    ),
    _p(
        "corda-pular-speed",
        "Corda de Pular Speed",
        "esporte",
        "trilha-sports",
        4990,
        "Cabo de aço revestido com rolamentos que giram sem esforço para saltos rápidos. "
        "Cabos ergonômicos antiderrapantes e comprimento ajustável para qualquer altura. "
        "Pequena o bastante para levar na bolsa e treinar em qualquer lugar.",
        ("corda", "pular", "cardio", "crossfit", "treino"),
        "4.1",
        1630,
        "1516876345887-6dd74f80787a",
    ),
    _p(
        "kit-elasticos-forca",
        "Kit de Elásticos de Força",
        "esporte",
        "trilha-sports",
        6990,
        "Cinco níveis de resistência, do leve ao extra forte, para evoluir treino após treino. "
        "Látex natural durável que não enrola nem escorrega na pele. "
        "Acompanha bolsa de transporte e guia ilustrado de exercícios.",
        ("elásticos", "elasticos", "resistência", "treino", "musculação", "fitness"),
        "4.4",
        948,
        "1767404890803-228d5390fcd4",
    ),
)

CREATED_AT: dict[str, datetime] = {
    product.slug: SEED_EPOCH + timedelta(days=index) for index, product in enumerate(PRODUCTS)
}
