import type { Category, Product } from "@/api/schemas";
import { SEED_MERCHANTS } from "@/lib/merchants";

const merchantBySlug = Object.fromEntries(SEED_MERCHANTS.map((m) => [m.slug, m]));

const IMG = (id: string) => `https://images.unsplash.com/photo-${id}?w=800&q=70`;

interface Seed {
  slug: string;
  id: string;
  name: string;
  category: "tecnologia" | "casa" | "esporte";
  merchant: "aurora-tech" | "casa-lume" | "trilha-sports";
  price: number;
  rating: number;
  reviews: number;
  image: string | null;
  tags: string[];
  description: string;
  stock: number;
}

const SEEDS: Seed[] = [
  {
    slug: "fone-bluetooth-nova",
    id: "32017989-a5fa-52d8-a607-70ceaef25a06",
    name: "Fone Bluetooth Nova ANC",
    category: "tecnologia",
    merchant: "aurora-tech",
    price: 34990,
    rating: 4.7,
    reviews: 1284,
    image: IMG("1505740420928-5e560c06d30e"),
    tags: ["áudio", "cancelamento de ruído", "bluetooth 5.3"],
    description:
      "Cancelamento ativo de ruído que silencia o metrô e o escritório aberto. Até 42 horas de bateria, carga rápida de 10 minutos para 5 horas de música e modo transparência para ouvir o que importa.",
    stock: 25,
  },
  {
    slug: "caixa-som-pulse",
    id: "a0730ece-81d4-5627-9fc0-a8b774250737",
    name: "Caixa de Som Pulse 360",
    category: "tecnologia",
    merchant: "aurora-tech",
    price: 21990,
    rating: 4.4,
    reviews: 642,
    image: null,
    tags: ["áudio", "à prova d'água", "portátil"],
    description:
      "Som em 360 graus com graves marcados e resistência IPX7. Aguenta a piscina, a praia e o fim de semana inteiro com 18 horas de bateria. Pareie duas caixas para som estéreo.",
    stock: 25,
  },
  {
    slug: "smartwatch-orbit",
    id: "19be25ac-adc1-5662-b67c-89df92431933",
    name: "Smartwatch Orbit S2",
    category: "tecnologia",
    merchant: "aurora-tech",
    price: 49990,
    rating: 4.6,
    reviews: 903,
    image: IMG("1546868871-7041f2a55e12"),
    tags: ["wearable", "saúde", "amoled"],
    description:
      "Tela AMOLED sempre ligada, monitoramento de sono, frequência cardíaca e oxigenação. Notificações do celular no pulso e 7 dias de bateria em uso normal.",
    stock: 5,
  },
  {
    slug: "teclado-mecanico-forge",
    id: "2d3df549-5447-58eb-835a-5b28ef81295d",
    name: "Teclado Mecânico Forge 75%",
    category: "tecnologia",
    merchant: "aurora-tech",
    price: 38990,
    rating: 4.8,
    reviews: 517,
    image: null,
    tags: ["periféricos", "hot-swap", "sem fio"],
    description:
      "Formato 75% com switches lineares hot-swap, estrutura gasket que amortece o som e conexão por cabo, Bluetooth ou receptor de 2,4 GHz. Digitação macia e silenciosa.",
    stock: 25,
  },
  {
    slug: "mouse-glide-pro",
    id: "ce19d8d6-5421-5045-8aa3-77265b4657f9",
    name: "Mouse sem fio Glide Pro",
    category: "tecnologia",
    merchant: "aurora-tech",
    price: 17990,
    rating: 4.3,
    reviews: 388,
    image: null,
    tags: ["periféricos", "ergonômico"],
    description:
      "Formato ergonômico com sensor de 26.000 DPI e apenas 62 gramas. Dois dispositivos em um só mouse, com troca por botão e bateria que dura semanas.",
    stock: 25,
  },
  {
    slug: "webcam-clear-4k",
    id: "dddde828-e18e-5f9e-9cb8-90f930229920",
    name: "Webcam Clear 4K",
    category: "tecnologia",
    merchant: "aurora-tech",
    price: 25990,
    rating: 4.2,
    reviews: 214,
    image: null,
    tags: ["vídeo", "trabalho remoto"],
    description:
      "Imagem 4K com foco automático e correção de luz baixa. Dois microfones com redução de ruído e tampa de privacidade integrada para reuniões sem susto.",
    stock: 25,
  },
  {
    slug: "carregador-turbo-65w",
    id: "7cdffa41-f781-5064-bd34-70910ec12f05",
    name: "Carregador Turbo 65W GaN",
    category: "tecnologia",
    merchant: "aurora-tech",
    price: 12990,
    rating: 4.9,
    reviews: 2210,
    image: null,
    tags: ["energia", "usb-c", "compacto"],
    description:
      "Tecnologia GaN que cabe no bolso e carrega notebook, tablet e celular ao mesmo tempo. Duas portas USB-C e uma USB-A, com proteção contra superaquecimento.",
    stock: 25,
  },
  {
    slug: "hub-usbc-dock",
    id: "b3f7cd99-ae3b-5094-a932-2325eac3bbd8",
    name: "Hub USB-C Dock 8 em 1",
    category: "tecnologia",
    merchant: "aurora-tech",
    price: 15990,
    rating: 4.1,
    reviews: 276,
    image: null,
    tags: ["periféricos", "usb-c"],
    description:
      "HDMI 4K, leitor de cartões, três portas USB-A, Ethernet e passagem de energia de 100 W. Um cabo só para ligar o notebook à mesa inteira.",
    stock: 25,
  },
  {
    slug: "luminaria-arco-dourado",
    id: "c828004d-46c8-566d-928f-b0937b409a16",
    name: "Luminária Arco Dourado",
    category: "casa",
    merchant: "casa-lume",
    price: 28990,
    rating: 4.5,
    reviews: 189,
    image: null,
    tags: ["iluminação", "sala", "design"],
    description:
      "Haste em arco que alcança o sofá sem furar o teto. Acabamento dourado fosco, base em mármore sintético e cúpula de tecido que espalha uma luz quente.",
    stock: 25,
  },
  {
    slug: "cafeteira-prensa-francesa",
    id: "ec9d324e-2386-50e5-b505-1dec8b5b2058",
    name: "Cafeteira Prensa Francesa",
    category: "casa",
    merchant: "casa-lume",
    price: 14990,
    rating: 4.6,
    reviews: 731,
    image: null,
    tags: ["cozinha", "café", "vidro"],
    description:
      "Vidro borossilicato com estrutura em aço inox e filtro triplo. Faz 1 litro de café encorpado em quatro minutos e vai inteira na lava-louças.",
    stock: 25,
  },
  {
    slug: "vaso-ceramica-terra",
    id: "6a202054-b185-51fd-9c75-7fde0059533c",
    name: "Vaso de Cerâmica Terra",
    category: "casa",
    merchant: "casa-lume",
    price: 8990,
    rating: 4.4,
    reviews: 305,
    image: null,
    tags: ["decoração", "plantas", "artesanal"],
    description:
      "Feito à mão em cerâmica esmaltada, com tom terroso e pequenas variações em cada peça. Furo de drenagem e prato removível, ideal para suculentas e folhagens médias.",
    stock: 25,
  },
  {
    slug: "manta-algodao-nuvem",
    id: "5124dd87-c88d-5d08-acea-6c3968f31e6a",
    name: "Manta de Algodão Nuvem",
    category: "casa",
    merchant: "casa-lume",
    price: 19990,
    rating: 4.7,
    reviews: 458,
    image: null,
    tags: ["quarto", "têxtil", "algodão"],
    description:
      "Algodão penteado em trama aberta, leve no verão e aconchegante no inverno. Mede 1,50 m por 2,00 m e pode ir direto à máquina de lavar.",
    stock: 25,
  },
  {
    slug: "jogo-facas-chef",
    id: "25ce50c4-7259-5afb-9226-af0fa4b2e97f",
    name: "Jogo de Facas Chef",
    category: "casa",
    merchant: "casa-lume",
    price: 32990,
    rating: 4.8,
    reviews: 612,
    image: null,
    tags: ["cozinha", "aço inox", "kit"],
    description:
      "Cinco facas forjadas em aço inox de alto carbono, com cabo ergonômico e corte que dura. Acompanha bloco de madeira que mantém o fio protegido.",
    stock: 25,
  },
  {
    slug: "difusor-aromas-calma",
    id: "505be3a3-de83-567e-8fd9-a5e1a7cc0c8d",
    name: "Difusor de Aromas Calma",
    category: "casa",
    merchant: "casa-lume",
    price: 11990,
    rating: 4.0,
    reviews: 167,
    image: null,
    tags: ["bem-estar", "aromaterapia"],
    description:
      "Névoa fina e silenciosa que perfuma o ambiente por até 8 horas. Desliga sozinho quando a água acaba e tem luz noturna de três intensidades.",
    stock: 25,
  },
  {
    slug: "relogio-parede-minimal",
    id: "ac4faec4-a012-57f1-8c9d-49968f181b8e",
    name: "Relógio de Parede Minimal",
    category: "casa",
    merchant: "casa-lume",
    price: 9990,
    rating: 4.2,
    reviews: 143,
    image: null,
    tags: ["decoração", "silencioso"],
    description:
      "Mecanismo silencioso, ponteiros finos e fundo liso sem números para uma parede mais limpa. Diâmetro de 35 cm, aro em madeira clara.",
    stock: 25,
  },
  {
    slug: "organizador-bambu-set",
    id: "5f3dc8f1-4e71-5997-a55d-2a212a2baf07",
    name: "Organizador de Bambu Set",
    category: "casa",
    merchant: "casa-lume",
    price: 7990,
    rating: 4.3,
    reviews: 249,
    image: null,
    tags: ["organização", "bambu", "sustentável"],
    description:
      "Três peças encaixáveis em bambu tratado para gavetas, bancadas e mesa de trabalho. Resistente à umidade e fácil de limpar com um pano.",
    stock: 25,
  },
  {
    slug: "tenis-corrida-vento",
    id: "c3f4de6e-e0fd-58f6-a51d-144117b8a32d",
    name: "Tênis de Corrida Vento",
    category: "esporte",
    merchant: "trilha-sports",
    price: 45990,
    rating: 4.6,
    reviews: 874,
    image: IMG("1542291026-7eec264c27ff"),
    tags: ["corrida", "amortecimento", "respirável"],
    description:
      "Entressola com espuma responsiva e cabedal de malha que respira. Pesa 240 gramas e mantém o pé firme do primeiro ao quadragésimo quilômetro.",
    stock: 25,
  },
  {
    slug: "mochila-trilha-30l",
    id: "b84048cf-f78b-5907-83e8-0519e7ee32ad",
    name: "Mochila de Trilha 30L",
    category: "esporte",
    merchant: "trilha-sports",
    price: 31990,
    rating: 4.5,
    reviews: 326,
    image: null,
    tags: ["trilha", "impermeável", "30 litros"],
    description:
      "Costas ventiladas, cinto de quadril acolchoado e capa de chuva embutida. Compartimento para bolsa de hidratação e bolsos laterais que cabem uma garrafa inteira.",
    stock: 25,
  },
  {
    slug: "garrafa-termica-aco-750",
    id: "4b3ee522-ce80-5f10-82d6-194f99b18bff",
    name: "Garrafa Térmica Aço 750 ml",
    category: "esporte",
    merchant: "trilha-sports",
    price: 9990,
    rating: 4.8,
    reviews: 1540,
    image: null,
    tags: ["hidratação", "aço inox", "térmica"],
    description:
      "Parede dupla a vácuo que mantém a água gelada por 24 horas ou quente por 12. Tampa com trava e boca larga que aceita cubos de gelo.",
    stock: 25,
  },
  {
    slug: "tapete-yoga-grip",
    id: "9d078c2c-c647-57d8-8f68-87befa1c6d39",
    name: "Tapete de Yoga Grip",
    category: "esporte",
    merchant: "trilha-sports",
    price: 12990,
    rating: 4.4,
    reviews: 402,
    image: null,
    tags: ["yoga", "antiderrapante"],
    description:
      "Superfície antiderrapante que segura a pegada mesmo com as mãos suadas. Espessura de 6 mm para proteger joelhos e punhos, com alça para transporte.",
    stock: 25,
  },
  {
    slug: "relogio-gps-trail",
    id: "ad04c3de-979a-54e0-a00d-f7bf69940225",
    name: "Relógio GPS Trail",
    category: "esporte",
    merchant: "trilha-sports",
    price: 64990,
    rating: 4.9,
    reviews: 298,
    image: IMG("1523275335684-37898b6baf30"),
    tags: ["gps", "trilha", "bateria longa"],
    description:
      "GPS de multibanda com mapas offline, altímetro e bússola. Até 30 dias de bateria no modo relógio e 60 horas com GPS ligado, para ultras e travessias.",
    stock: 3,
  },
  {
    slug: "capacete-bike-aero",
    id: "44ccffde-ca59-50c2-8781-88eb1456820e",
    name: "Capacete de Bike Aero",
    category: "esporte",
    merchant: "trilha-sports",
    price: 27990,
    rating: 4.5,
    reviews: 187,
    image: null,
    tags: ["ciclismo", "segurança", "aerodinâmico"],
    description:
      "Casca aerodinâmica com 18 entradas de ar, ajuste por roldana e viseira removível. Certificado e leve, com forro lavável.",
    stock: 25,
  },
  {
    slug: "corda-pular-speed",
    id: "e21e5696-25c3-57f5-87b2-75c17740a913",
    name: "Corda de Pular Speed",
    category: "esporte",
    merchant: "trilha-sports",
    price: 4990,
    rating: 4.1,
    reviews: 521,
    image: null,
    tags: ["cardio", "funcional"],
    description:
      "Cabo de aço revestido com rolamento duplo para giro rápido e sem enrosco. Regulável em segundos e com cabos de espuma firme.",
    stock: 25,
  },
  {
    slug: "kit-elasticos-forca",
    id: "f72d191d-b21a-556b-bd90-605c8908b0fe",
    name: "Kit de Elásticos de Força",
    category: "esporte",
    merchant: "trilha-sports",
    price: 6990,
    rating: 4.3,
    reviews: 366,
    image: null,
    tags: ["treino em casa", "funcional"],
    description:
      "Cinco níveis de resistência em látex natural, com bolsa de transporte e guia de exercícios. Treino de corpo inteiro em qualquer cantinho da casa.",
    stock: 25,
  },
];

const DAY = 86_400_000;
const BASE = Date.now();

export const PRODUCTS: Product[] = SEEDS.map((s, i) => ({
  id: s.id,
  slug: s.slug,
  name: s.name,
  description: s.description,
  price_cents: s.price,
  currency: "BRL",
  category: s.category,
  image_url: s.image,
  rating: s.rating,
  reviews_count: s.reviews,
  tags: s.tags,
  merchant: merchantBySlug[s.merchant] ?? SEED_MERCHANTS[0]!,
  created_at: new Date(BASE - (i % 12) * 4 * DAY - i * 3_600_000).toISOString(),
}));

export const INITIAL_STOCK: Record<string, number> = Object.fromEntries(
  SEEDS.map((s) => [s.id, s.stock]),
);

export const CATEGORY_LABELS: Record<string, string> = {
  tecnologia: "Tecnologia",
  casa: "Casa e decoração",
  esporte: "Esporte e aventura",
};

export function buildCategories(): Category[] {
  return Object.entries(CATEGORY_LABELS).map(([slug, label]) => ({
    slug,
    label,
    count: PRODUCTS.filter((p) => p.category === slug).length,
  }));
}
