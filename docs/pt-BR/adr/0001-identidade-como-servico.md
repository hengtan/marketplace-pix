# ADR 0001: identidade como serviço próprio (`identity`, porta 8008)

Status: aceita.

## Contexto

O sistema não tinha autenticação nem autorização: qualquer cliente lia qualquer pedido, alterava estoque e
via o ledger de qualquer lojista. Precisamos de cadastro, login, tokens, papéis e isolamento entre lojistas.
A decisão é onde colocar a responsabilidade de identidade: dentro do gateway (módulo) ou em um serviço novo.

## Decisão

Um serviço `identity` separado, com banco próprio (`identity`), que cuida de credenciais, tokens e chaves.
O gateway fica sem estado de identidade: só **valida** o JWT (assinatura, `iss`, `aud`, `exp`) com a chave
pública do `identity` (JWKS) e injeta nos upstreams uma identidade **assinada** (HMAC) que os serviços
confiam. O código do gateway que lida com isso fica em módulos novos (`gateway/auth/`).

Escolhas de segurança:

- Access token JWT curto (10 minutos), assinado com **EdDSA (Ed25519)**, `kid` no cabeçalho e JWKS público.
  O algoritmo é fixado na verificação (nada de `none`, nada de HS256 com a chave pública).
- Refresh token **opaco**, rotativo, guardado só como SHA-256. Cada uso emite um novo; reapresentar um token
  já usado revoga a família inteira (detecção de roubo). A sessão tem prazo absoluto de 30 dias.
- Senha com **argon2id**. Login com tempo equalizado para e-mail inexistente e bloqueio temporário por conta.
- Papéis (`customer`, `merchant`, `admin`) viram **escopos** (`orders:create`, `ledger:read:own`, ...). O
  lojista carrega `merchant_id` no token: é a fonte do tenant, nunca um parâmetro do cliente.
- Defesa em profundidade: o gateway aplica uma política por rota (anônimo, opcional, obrigatório + escopo), e
  cada serviço **reaplica** a autorização por objeto (pedido do dono, ledger do lojista, estoque do lojista),
  porque as portas dos serviços também ficam publicadas no host.

## Por que não um módulo dentro do gateway

| Critério | Módulo no gateway | Serviço `identity` |
|---|---|---|
| Superfície de ataque | O proxy de borda passa a guardar hash de senha e chave privada | O proxy só tem a chave pública |
| Estado | O gateway deixa de ser stateless (banco, migrações) | O gateway escala horizontalmente sem estado |
| Raio de explosão | Falha no proxy afeta credenciais | Credenciais isoladas, com banco e deploy próprios |
| Rotação de chaves | Acoplada ao deploy do gateway | O JWKS publica a chave nova e a antiga ao mesmo tempo |
| Custo | Menor (um processo a menos) | Um serviço a mais, uma chamada de JWKS cacheada |

O custo extra é pequeno (um serviço no padrão que o repositório já usa) e o ganho é separar quem **emite**
confiança de quem **repassa** requisições.

## Consequências

- As portas dos serviços continuam publicadas, então a identidade vinda do gateway é **assinada** e presa ao
  `X-Request-Id` e a um carimbo de tempo (60 s). Cabeçalhos `X-User-*` forjados não valem nada, e o gateway
  remove os que o cliente enviar.
- Se o JWKS estiver indisponível, requisições com token falham fechado (503); as anônimas seguem.
- O token de acesso não é revogável antes de expirar (10 minutos). É o preço de validar sem consultar o banco.
- O refresh token trafega no corpo da resposta. Um front de produção deveria guardá-lo em cookie `HttpOnly`.
- Checkout de convidado continua existindo (pedido sem dono, acessível por quem tem o id). Pode ser desligado
  com `ALLOW_GUEST_CHECKOUT=false` no gateway.
