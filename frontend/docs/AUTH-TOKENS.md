# Tokens de autenticação no navegador

## Como está hoje

- `access_token` (JWT, 10 min): só em memória, no store Zustand sem persistência. Some ao recarregar.
- `refresh_token` (opaco, rotativo): `sessionStorage`, chave `praca-rt`, e nada mais. Ao carregar, uma renovação silenciosa e compartilhada devolve um access novo e `GET /api/auth/me` devolve o perfil.
- Cada renovação troca o refresh (o antigo morre). Por isso só existe uma renovação em voo por vez e ela nunca roda dentro de um efeito do React.
- Sair chama `POST /api/auth/logout` (revoga a sessão) e apaga o storage. O antigo `localStorage["praca-auth"]` é removido no boot.
- `sessionStorage` vale por aba: outra aba pede login de novo. É a menor superfície possível sem backend novo. `localStorage` daria sessão entre abas, mas expõe o refresh a qualquer XSS por mais tempo.

Limite desta abordagem: um XSS ainda lê o refresh enquanto a aba estiver aberta.

## Recomendação para produção: cookie httpOnly via BFF

1. Um BFF na mesma origem do SPA (por exemplo o próprio nginx com um serviço fino) recebe `login` e `refresh`, guarda o refresh em cookie `HttpOnly; Secure; SameSite=Strict; Path=/api/auth`, e devolve ao navegador só o access.
2. O SPA chama `POST /api/auth/refresh` sem corpo; o cookie vai sozinho. O JS nunca vê o refresh.
3. CSRF: `SameSite=Strict` mais um cabeçalho customizado obrigatório (`X-Requested-With`) nas rotas de sessão.
4. Rotação com detecção de reuso continua no identity (reapresentar refresh usado revoga a sessão).
5. No frontend a mudança é pequena: `refreshSession` deixa de ler e gravar token e `store/auth.ts` perde o `writeRefresh`.
