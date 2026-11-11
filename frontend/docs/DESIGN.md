# Direção de design

## Cena de uso

Alguém no sofá, de noite ou no intervalo do almoço, decide uma compra no celular e quer pagar sem atrito.
O PIX precisa parecer rápido e confiável. O lojista confere o saldo no escritório, com tela grande.
Por isso: tema claro e escuro desde o início, alvos de toque de 44 px e um só caminho para pagar.

## Identidade

Nome: Praça. O símbolo é um "P" de traço contínuo com um ponto verde, o ponto do PIX.
O azul ultramar carrega a marca e as ações; o verde menta é reservado para dinheiro e confirmação
(PIX pago, saldo, linha do tempo). Nada mais usa menta, então o verde sempre significa "dinheiro entrou".

Estratégia de cor: comprometida. Neutros azulados (nunca preto ou branco puros), ultramar em botões e foco,
menta só para confirmação.

| Papel | Claro | Escuro |
|---|---|---|
| Fundo | `oklch(0.972 0.008 268)` | `oklch(0.17 0.03 268)` |
| Superfície | `oklch(0.994 0.004 268)` | `oklch(0.215 0.035 268)` |
| Texto | `oklch(0.2 0.045 268)` | `oklch(0.96 0.01 268)` |
| Primária | `oklch(0.47 0.25 268)` | `oklch(0.7 0.17 272)` |
| PIX | `oklch(0.72 0.17 165)` | `oklch(0.8 0.16 165)` |
| Alerta | `oklch(0.45 0.13 55)` | `oklch(0.82 0.13 80)` |
| Perigo | `oklch(0.52 0.2 25)` | `oklch(0.74 0.15 25)` |

Todos os tokens vivem em `src/index.css` e são trocados por classe `.dark` (padrão do sistema, persistido, aplicado
por script no `<head>` para evitar flash).

## Tipografia

- Títulos: Bricolage Grotesque variável, eixo de largura reduzido (`wdth 92`), tracking negativo. Tem personalidade
  própria e comprime bem em títulos longos em português.
- Texto e interface: Geist variável. Números com `tabular-nums` em preços, contagem e tabelas.
- Código PIX: Geist Mono.
- Escala com razão mínima de 1,25 entre degraus; o título do hero usa `clamp` de 2,9 a 6,5 rem.
- Fontes self-hosted via `@fontsource-variable`, sem CDN.

## Forma e profundidade

Raios: 12 px em controles, 20 px em cartões e 28 px em painéis grandes. Pílulas para filtros e navegação.
Sombras em dois níveis (`shadow-soft` em repouso, `shadow-lift` em destaque), tingidas com o matiz da marca.
Bordas de 1 px carregam a estrutura; cartões só aparecem onde há conteúdo agrupado de verdade (produto, painel PIX, resumo).

## Movimento

Um momento orquestrado: a entrada do hero (linhas emergindo de uma máscara). O resto responde a ações:
botão de adicionar vira confirmação, gaveta desliza, selo de sucesso desenha o check com um pequeno estouro de pontos,
contagem do PIX avança uma barra por `transform`. Curvas ease-out exponenciais, nunca bounce.
Troca de tema usa View Transitions. `prefers-reduced-motion` desliga tudo.

## Layout

- Hero tipográfico à esquerda, com um recibo PIX inclinado à direita para contar o produto sem imagem de banco.
- Categorias como faixas de ação (filtro), não como cartões decorativos.
- Grade de produtos 2, 3 e 4 colunas; imagem quadrada com dimensões fixas para evitar deslocamento.
- Checkout em uma tela: dados à esquerda, resumo fixo à direita. O botão já mostra o total.
- Pedido: painel PIX com QR e contagem à esquerda, linha do tempo à direita; no sucesso o painel vira confirmação.

## Imagens

`image_url` nulo ou com falha vira um gradiente em OKLCH, com matiz por categoria e variação por produto, mais um glifo
da categoria. Nunca aparece imagem quebrada.

## Acessibilidade

Contraste AA nos dois temas (verificado com axe em loja, produto, pedido, pedidos e lojista), foco visível de 2 px,
link de pular para o conteúdo, landmarks (`header`, `nav`, `main`, `footer`), foco movido ao conteúdo a cada troca de rota,
título de página por rota, regiões `aria-live` para status do PIX e cópia, tabela com legenda e cabeçalhos no extrato,
gráfico com resumo textual.

## Copy

pt-BR, sem travessão, frases curtas, verbos diretos. Erros explicam o que houve e o que fazer. O mesmo verbo vale no botão
e no aviso (por exemplo "Adicionar ao carrinho" e "Adicionado ao carrinho").
