# Praça, frontend do marketplace PIX

Loja, checkout com PIX e painel do lojista. React 19, Vite, TypeScript estrito, Tailwind CSS v4,
TanStack Router e Query, Zustand, React Hook Form com Zod, Motion, cmdk, Recharts.
A SPA fala apenas com o gateway (`/api/...`), conforme `docs/CONTRATOS.md`.

## Como rodar

Requisitos: Node 22+ e pnpm.

```bash
pnpm install

# 1) Sozinho, com mocks (MSW) fiéis ao contrato, estado persistido no localStorage
pnpm dev:mock            # http://localhost:5173

# 2) Com o backend real (gateway em http://localhost:8000)
cp .env.example .env     # ajuste VITE_API_URL se preciso
pnpm dev                 # http://localhost:5173
```

Para testar a ferramenta de simulação com o backend real, use `VITE_ENABLE_DEV_TOOLS=true pnpm dev`.

## Variáveis de ambiente

| Variável | Padrão | Efeito |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Base do gateway. Vazia no Docker (usa o proxy do nginx, mesma origem) |
| `VITE_USE_MOCKS` | `false` | `true` liga o MSW e todos os endpoints do contrato com estado em memória |
| `VITE_ENABLE_DEV_TOOLS` | `false` | `true` mostra o botão "Simular pagamento" no painel PIX |
| `VITE_PROXY_TARGET` | vazia | Só no `pnpm dev`: encaminha `/api` do Vite para o gateway (use com `VITE_API_URL=` vazia para evitar CORS em outra porta) |

## Scripts

| Script | O que faz |
|---|---|
| `pnpm dev` / `pnpm dev:mock` | Servidor de desenvolvimento (real / mocks) |
| `pnpm build` | Typecheck e build de produção em `dist/` |
| `pnpm typecheck` | `tsc` estrito |
| `pnpm lint` / `pnpm format` | Biome |
| `pnpm test` | Vitest (unitários e de componentes) |
| `pnpm e2e` | Playwright com mocks (fluxo de compra, paleta, tema, axe) |
| `pnpm screenshots` | Regera `docs/screenshots/` |

Na primeira execução do Playwright: `pnpm exec playwright install chromium`.

## Cenários demonstráveis com os mocks

- Compra completa: carrinho, checkout, QR Code, "Simular pagamento", sucesso.
- PIX expirado: use um e-mail ou nome contendo `expira` (o PIX vence em 25 s e o pedido é cancelado com `payment expired`).
- Estoque insuficiente: `relogio-gps-trail` tem 3 unidades e `smartwatch-orbit` tem 5. Peça mais do que o disponível
  (por exemplo reduzindo o estoque pelo `PUT /api/inventory/stock/{id}` ou comprando duas vezes) e o pedido é cancelado com `out of stock`.
- Erro de listagem: buscar por `__erro` devolve 500.
- Para zerar o estado dos mocks, limpe o `localStorage` do site.

## Assistente de compras

O botão flutuante (canto inferior direito), a paleta ⌘K ("Perguntar ao assistente" ou "Perguntar: seu texto") e o
atalho `Ctrl /` (`⌘ /` no Mac) abrem o chat. Esc fecha e o foco volta ao botão.

- Streaming: `POST /api/assistant/chat/stream` lido com `fetch` e um parser de SSE tolerante a chunks quebrados
  (`src/features/assistant/sse.ts`). Eventos `tool_call` viram estados vivos, `token` monta o texto e `done` traz sessão,
  citações e rastro. O botão de parar usa `AbortController` e há timeout de 45 s sem eventos.
- Respostas: renderizador próprio e seguro (negrito, listas, quebras de linha, chips `[1]` para `/produto/:slug`), sem
  `dangerouslySetInnerHTML`. Os produtos citados aparecem como cartões com preço e "Adicionar".
- "Como cheguei nessa resposta": ferramentas chamadas (argumentos, resumo, duração), trechos recuperados com pontuação e
  latência, em linha do tempo.
- Sessão em `localStorage` (`praca-assistant-session`), recarregada por `GET /api/assistant/sessions/{id}`.
  "Nova conversa" limpa tudo.
- Mocks (`src/mocks/assistant.ts`) simulam SSE com `tool_call`, citações e rastro. Frases de teste: `simular erro`
  (evento `error`) e `resposta lenta` (tokens devagar, bom para testar o botão de parar).
- Contra o backend real em outra porta: `VITE_PROXY_TARGET=http://localhost:8000 VITE_API_URL= pnpm exec vite --port 5174`.
- No nginx, `/api/assistant/chat/stream` tem `proxy_buffering off` para o texto chegar token a token.

Captura em `docs/screenshots/07-assistente-escuro.png`.

## Conta e rotas protegidas

`/entrar` e `/cadastro` falam com `POST /api/auth/login`, `POST /api/auth/register`, `POST /api/auth/refresh` e
`GET /api/auth/me` (mock MSW com as contas `lojista@praca.dev` e `cliente@praca.dev`, senha `praca1234`). `/lojista` e `/conta`
exigem sessão; a loja segue aberta para convidados. O cliente HTTP renova o token uma vez em 401.

## Desempenho

Build de produção servido por `vite preview` contra o backend real, Lighthouse 13 na home: desktop 98 de desempenho
(LCP 1,1 s, TBT 0 ms, CLS 0); celular com a simulação padrão (4G lento, CPU 4x) de 84 a 88 (LCP 3,9 s, CLS 0).
Recharts (~111 kB gzip) só carrega no painel; o assistente, o carrinho e a paleta carregam sob demanda.

## Docker

```bash
docker build -t marketplace-pix-frontend .
docker run --rm -p 8080:80 -e API_UPSTREAM=http://host.docker.internal:8000 marketplace-pix-frontend
```

Build multi-stage: Node compila e o nginx serve a SPA com fallback para `index.html` e proxy de `/api/` para
`API_UPSTREAM` (padrão `http://gateway:8000`). `GET /healthz` responde `ok`.

## Estrutura

```
src/
  api/        cliente tipado, schemas Zod e endpoints do contrato
  mocks/      dados de seed, banco em memória (idempotência, saga, ledger) e handlers MSW
  hooks/      queries do TanStack Query e useOrderStatus (polling de 2 s, trocável por SSE)
  store/      carrinho (persistido), cliente, tema, UI
  components/ componentes reutilizáveis e base de UI (Radix)
  features/   painel PIX, linha do tempo, hero, assistant (chat, SSE, rastro)
  pages/      rotas (carregadas sob demanda)
docs/         DESIGN.md e screenshots
e2e/          Playwright
```

## Decisões

- `customer_id` é um uuid salvo em `localStorage`. A `Idempotency-Key` é gerada por tentativa de checkout
  (assinatura de itens e e-mail) e mantida até o sucesso, então reenvios por falha de rede não duplicam o pedido.
- A pré-visualização de e-mail busca `/api/notifications/{id}/preview` e renderiza em um `iframe` com `sandbox` vazio.
- `GET /products/by-ids` é lido como envelope paginado, conforme a versão atual do contrato.
