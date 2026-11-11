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
  features/   painel PIX, linha do tempo, hero
  pages/      rotas (carregadas sob demanda)
docs/         DESIGN.md e screenshots
e2e/          Playwright
```

## Decisões

- `customer_id` é um uuid salvo em `localStorage`. A `Idempotency-Key` é gerada por tentativa de checkout
  (assinatura de itens e e-mail) e mantida até o sucesso, então reenvios por falha de rede não duplicam o pedido.
- A pré-visualização de e-mail busca `/api/notifications/{id}/preview` e renderiza em um `iframe` com `sandbox` vazio.
- `GET /products/by-ids` é lido como envelope paginado, conforme a versão atual do contrato.
