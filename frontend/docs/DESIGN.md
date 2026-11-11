# Direção de design

## Cena de uso

Alguém no sofá, de noite ou no intervalo do almoço, decide uma compra no celular e quer pagar sem atrito.
O PIX precisa parecer rápido e confiável. O lojista confere o saldo no escritório, com tela grande.
Por isso: tema claro e escuro desde o início, alvos de toque de 44 px e um só caminho para pagar.

## Identidade: "praça de noite"

Praça é um lugar onde as coisas acontecem. A interface é uma vitrine viva: luz de aurora ao fundo, objetos flutuando
em camadas, números que rolam e um PIX que confirma diante dos olhos. O contraste vem de dois gestos:
títulos grandes e densos em Bricolage Grotesque, com uma palavra em itálico serifado (Instrument Serif) como
assinatura ("Pague em *segundos*", "Vitrine *completa*").

Cor, em OKLCH: ultramar elétrico para marca e ação, menta só para dinheiro e confirmação, sol (laranja quente) apenas
em gradientes e acentos. O claro é papel quente (`oklch(0.974 0.007 85)`); o escuro é tinta profunda
(`oklch(0.145 0.032 275)`) com superfícies em degraus de 0,04 de luminosidade.

| Papel | Claro | Escuro |
|---|---|---|
| Fundo | `oklch(0.974 0.007 85)` | `oklch(0.145 0.032 275)` |
| Superfície | `oklch(0.994 0.003 85)` | `oklch(0.19 0.035 275)` |
| Texto | `oklch(0.19 0.045 275)` | `oklch(0.96 0.01 275)` |
| Primária | `oklch(0.49 0.255 270)` | `oklch(0.72 0.17 272)` |
| PIX | `oklch(0.74 0.175 165)` | `oklch(0.82 0.165 165)` |
| Sol | `oklch(0.76 0.17 50)` | `oklch(0.8 0.15 55)` |

Todos os tokens vivem em `src/index.css` e são trocados pela classe `.dark` (sistema por padrão, persistido,
aplicado por script no `<head>`). A troca de tema usa View Transitions.

## Tipografia

- Display: Bricolage Grotesque variável, eixo de largura em 90, tracking de -0,055em, escala fluida
  (`--text-display` de 2,75 a 7,5 rem via `clamp`).
- Acento: Instrument Serif itálico, só em uma palavra por título.
- Interface: Geist variável; números com `tabular-nums`. Código PIX em Geist Mono.
- Tudo self-hosted via Fontsource, sem CDN.

## Superfícies e profundidade

- Camadas: fundo, `panel` (gradiente sutil, borda de 1 px, brilho interno no topo), `glass` (blur 18 px, saturação 1,5).
- Sombras em cinco camadas (`--shadow-lift`) tingidas com o matiz da marca; `--shadow-glow` para ação primária.
- Aurora: três manchas radiais em deriva lenta (só `transform`), grade fina com máscara e ruído fractal fixo (SVG,
  rasterizado uma vez).
- Raios: 12 px controles, 20 a 28 px cartões, pílulas em botões e filtros.

## Fotos de produto sem imagem

`ProductImage` nunca baixa imagem de terceiros. Cada produto vira uma composição SVG: gradiente OKLCH por categoria
(matiz base 272, 48 e 168) com variação por produto, grade de pontos, anéis, brilho posicionado por hash, sombra no chão e um
objeto desenhado por palavra-chave (fone, caixa, relógio, teclado, luminária, vaso, mochila, tênis, capacete e outros 6).
Só URLs do mesmo domínio (`/...`) são carregadas como `<img>`. Peso: zero bytes de imagem.

## Movimento

Biblioteca Motion, apenas `transform` e `opacity` (exceções: `stroke-dashoffset` do anel PIX e `pathLength` de traços SVG).

| Momento | Técnica |
|---|---|
| Hero | texto por palavra com máscara, cena em camadas com parallax de mouse (spring), scroll-driven (`useScroll` e `useTransform`) |
| Cartões | tilt 3D com perspectiva e spotlight que segue o cursor, hover com elevação |
| Botões | magnéticos (`Magnetic`) em CTAs |
| Lista para detalhe | transição de elemento compartilhado via View Transitions, ligada só nos links de produto (`viewTransition`), fallback é um fade |
| Carrinho | item voa em arco até o botão do carrinho, contador com spring, linhas com `AnimatePresence` e `layout` |
| Navegação | pílula ativa com `layoutId`, barra de progresso de rolagem, página sai com fade e subida (180 ms) e entra com fade e deslocamento |
| Checkout | stepper com linha que preenche |
| PIX | QR com varredura, anel de contagem regressiva, linha do tempo que preenche em tempo real |
| Pagamento | confete (64 peças, só transform) e selo com traço desenhado |
| Painel | números que rolam, sparklines que se desenham, gráficos Recharts com entrada animada |
| Marquee | ticker de categorias em CSS puro, pausa no hover |
| Cursor | anel que cresce sobre elementos interativos e vira rótulo "Ver" nos produtos (só ponteiro fino) |

`prefers-reduced-motion`: `MotionConfig reducedMotion="user"` desliga transform e layout; componentes próprios checam
`useReducedMotion` (sem parallax, sem tilt, sem voo, sem confete, marquee estático e quebrado em linhas, shimmer removido);
CSS global zera animações. `will-change` só em camadas que animam continuamente.

## Layout

- Hero em duas colunas com cena à direita; categorias em cartões com arte; vitrine em 2, 3 e 4 colunas.
- Checkout em uma tela com resumo fixo; pedido com painel PIX e linha do tempo.
- Responsivo de 360 px a 4K (contêiner de 80 rem, tipografia fluida).

## Autenticação

`/entrar` e `/cadastro` com painel de vitrine e formulário em vidro. Contrato usado (mock MSW em `src/mocks/auth.ts`):
`POST /api/auth/register`, `POST /api/auth/login` retornam `{access_token, refresh_token, token_type, expires_in, user}`;
`POST /api/auth/refresh`; `GET /api/auth/me`. O cliente HTTP envia `Authorization: Bearer`, renova uma vez em 401
(requisição única compartilhada) e limpa a sessão se o refresh falhar. `/lojista` e `/conta` são protegidas (redirecionam
para `/entrar?redirect=...`); `/lojista` ainda exige o perfil `merchant`. A loja inteira segue navegável como convidado.
O `access_token` fica só em memória (Zustand sem persistência). O `refresh_token` é a única coisa persistida, em `sessionStorage` (chave `praca-rt`), e rotaciona a cada renovação. Ao carregar, `restoreSession` faz um refresh silencioso (compartilhado, uma vez só, pois reapresentar um refresh antigo revoga a sessão) e busca `/api/auth/me`; rotas protegidas esperam esse passo. Sair chama `POST /api/auth/logout` e apaga tudo. A chave antiga `praca-auth` do `localStorage` é removida. Recomendação para produção (cookie httpOnly via BFF) em `docs/AUTH-TOKENS.md`.

Estados de acesso: 401 que não se renova limpa a sessão e, em `/conta` e `/lojista`, redireciona para `/entrar?redirect=<destino>` com aviso; 403 mostra "Você não tem acesso a esta área" com saída para outra conta ou para a loja (`ErrorState` com `error`).

## Assistente de compras

Botão de vidro com orbe (gradiente cônico girando). O orbe acelera e pulsa enquanto o assistente pensa, e partículas
sobem no estado vazio. Mensagens entram com fade e subida, painel carregado sob demanda (lazy) e pré-carregado em
ociosidade. O chat envia o `Authorization: Bearer` quando há sessão (renova em 401). Erros amigáveis: 429 de orçamento (`budget exceeded`, escopo `session` ou `user`) sem botão de nova tentativa e com o tempo de `Retry-After`; 429 comum e 503 com contagem regressiva no botão "Tentar de novo"; resposta degradada (`warning` no SSE ou `degraded` no `done`) ganha um aviso `role=status`. Demais regras de acessibilidade e de conteúdo permanecem.

## Estados

Vazio, erro e carregamento têm ilustrações SVG próprias e animadas (`illustrations.tsx`): carrinho, busca, pedidos, erro,
página perdida e PIX. Skeletons usam shimmer por `transform`.

## Acessibilidade

Contraste AA nos dois temas (axe em loja, produto, pedido, pedidos, lojista, entrar e cadastro), foco visível de 2 px,
link de pular, landmarks, foco movido ao conteúdo a cada rota, `aria-live` para PIX e cópia, tabela com legenda,
gráficos com resumo textual, texto animado com cópia `sr-only`.

## Desempenho

Medição: build de produção em `vite preview` (proxy para o gateway real), Lighthouse 12 em modo celular (4G lento, CPU 4x, simulado), 5 execuções por página, Chromium do Playwright.

| Página | Antes (desempenho) | Depois (desempenho) |
|---|---|---|
| Home | 84 a 85 (LCP 3,7 s, FCP 2,6 s, TBT 80 ms) | 88 a 91, mediana 89 (LCP 3,0 a 3,2 s, FCP 2,6 s, TBT 50 a 160 ms, CLS 0) |
| Produto | 82 a 83 (LCP 4,0 s, FCP 2,7 s, TBT 100 a 140 ms) | 87 a 88 (LCP 3,3 s, FCP 2,7 s, TBT 30 a 50 ms, CLS 0,003) |

A meta de 90 não fechou de forma estável no laboratório simulado: o piso é o JS para renderizar (React, roteador, Query, Motion, ~199 kB gzip contra ~275 kB antes). Medindo com throttling real do Chromium (CDP), o LCP da home caiu de 4,1 s para 1,1 s por causa do shell estático.

O que mudou, em ordem de ganho:

- JS inicial de ~275 para ~199 kB gzip: Motion em `LazyMotion` com `m` e recursos (`domMax`) carregados à parte; `zod/mini`; Sonner, menu do usuário (Radix), sino, cursor, painel do assistente, carrinho e paleta fora do caminho crítico, carregados na primeira interação ou após 6 s; sino só para quem está logado.
- Entrada da página não esconde mais o conteúdo no primeiro carregamento (`AnimatePresence initial={false}`): com os recursos do Motion assíncronos, o `opacity: 0` inicial atrasava o LCP em ~1,2 s.
- Shell estático da home no `index.html` (pílula, título e texto do hero com as mesmas classes). O app só monta depois do primeiro paint (`afterFirstPaint`) e pula a animação de entrada do que já está na tela. Uma checagem em `src/lib/shell.test.ts` mantém o texto igual ao do `Hero`.
- Produto: busca do produto iniciada por script inline no `<head>` e reaproveitada pelo cliente (`window.__early`); página de produto carregada junto do bundle principal (2,5 kB); produtos relacionados só após 900 ms.
- A view transition inicial do TanStack Router (`defaultViewTransition`) foi desligada: ela envolvia o primeiro render. Agora só os links de produto usam `viewTransition`.
- Fontes: Bricolage Grotesque reexportada com `wdth` fixo em 90 e só latim (41 kB, antes 78 kB, mesmo desenho), preload só na home (Geist, Bricolage e Instrument Serif; o serif evita o CLS de 0,17), nenhum preload nas outras rotas.
- Animações infinitas (marca, chips e orbe) passaram de JS por quadro para keyframes CSS no compositor.
- Paleta ⌘K não busca pedidos até abrir.
- Testado e descartado: `manualChunks`/`codeSplitting` por grupos (pior), `build.target` mais novo (sem ganho), `HomePage` lazy (-2,5 kB, mais um round trip na home).

### Transição de saída entre páginas

`AnimatePresence mode="wait"` envolve o conteúdo da rota em `AppShell`. Congelar o `Outlet` durante a saída não é possível nesta versão do TanStack Router (as matches vêm de stores e a saída da rota antiga zera o store dela). Por isso a navegação é retida: o `beforeLoad` da raiz abre a saída (`src/lib/route-transition.ts`), o conteúdo antigo faz fade e sobe 10 px em 180 ms, `onExitComplete` libera a navegação e a página nova entra. Não dispara em preload, em mudança só de query, com `prefers-reduced-motion` nem entre lista e produto. Foco vai para `#conteudo` e o scroll volta ao topo ao resolver, como antes; há fallback de 700 ms. Coberto por e2e (opacidade mínima, foco, scroll, axe, movimento reduzido).

### Elemento compartilhado lista para produto

Mantida a View Transitions. `layoutId` do Motion precisa que o elemento antigo e o novo existam ao mesmo tempo sob um `AnimatePresence`, e pelo motivo acima a rota antiga não fica montada. A View Transitions captura o DOM antes e depois da troca, funciona sem tirar a rota antiga da árvore, roda no compositor e custa 0 kB de JS. Sem medição regressiva: o JS inicial caiu e o Lighthouse não depende dela (ela só roda em navegação).

## Copy

pt-BR, sem travessão, frases curtas, verbos diretos. Rodapé: "Engineering by MocktStudio" com link para
https://mocktstudio.com.
