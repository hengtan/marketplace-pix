# Avaliação do RAG: baseline contra cada melhoria

Este documento registra, com números medidos, o que cada técnica do pipeline de recuperação do `assistant` muda na qualidade. Tudo roda com o embedder lexical (`HashingEmbedder`) e o LLM simulado (`MockLlm`), sem chave de API. Por isso os números valem como **comparação relativa entre variantes** e como rede de segurança contra regressão, não como promessa de qualidade com um modelo real (veja as limitações no fim).

## Como reproduzir

```bash
cd backend/services/assistant
uv run python -m assistant.rageval --write-docs ../../../docs/RAG-AVALIACAO.md   # tabela comparativa abaixo
uv run python -m assistant.evals --offline                                       # avaliação ponta a ponta (agente, geração, juiz)
uv run python -m assistant.evals --offline --gate                                # portão de regressão usado no CI
uv run python -m assistant.cachebench                                            # hit rate e economia do cache semântico
```

O `rageval` cria o banco `assistant_rageval`, reindexa o snapshot do catálogo (24 produtos) uma vez por configuração de chunk e roda cada variante sobre os mesmos casos. Ele recusa apagar qualquer banco cujo nome não termine em `_rageval`.

## O conjunto dourado

`evals/cases.yaml` tem **111 casos** (eram 36). Cada caso tem categoria e uma marca `split`:

| categoria | casos | o que testa |
|---|---|---|
| direct | 24 | pergunta com as palavras do catálogo |
| paraphrase | 19 | mesma ideia com outras palavras (sinônimos, uso, contexto) |
| adversarial | 16 | injeção de prompt, fora de escopo, ruído, SQL, emoji, preço falso |
| typo | 10 | erros de digitação |
| multi_hop | 8 | duas necessidades na mesma pergunta; pergunta que exige busca e depois estoque |
| negation | 6 | "exceto", "não quero", "menos o"; o produto proibido não pode aparecer |
| price, rating, sorting, category | 4, 2, 3, 1 | filtros e ordenação extraídos do texto |
| stock, order, policy, memory, comparison | 4, 4, 4, 4, 2 | ferramentas, política da loja, referência a mensagens anteriores |

- **dev** (76 casos): usados enquanto as técnicas eram construídas e ajustadas.
- **holdout** (35 casos): escritos **depois** de congelar o léxico de sinônimos e as regras de consulta, sem ajustes posteriores nas regras para fazê-los passar. É a leitura mais honesta de generalização que este conjunto permite. A mesma pessoa escreveu as duas partes e conhece o catálogo, então o holdout é otimista: um holdout de verdade viria de perguntas reais de usuários.

Nos casos da harness de recuperação entram os que não dependem de histórico e esperam `search_products` ou nenhuma ferramenta (95 de 111). `negação` mede se o produto proibido ficou de fora; `abstenção` mede se perguntas sem resposta no catálogo devolveram contexto vazio.

## Métricas

- **hit@k**: pelo menos um produto esperado entre os k primeiros (todos, nos casos `require_all`). **MRR**: média de 1/posição do primeiro produto esperado. **nDCG@5**: ganho descontado pela posição, com relevância binária.
- **precisão de contexto**: precisão média (AP) sobre os trechos entregues ao modelo; premia relevantes no topo. **revocação de contexto**: fração dos esperados presentes no contexto (limitada ao tamanho do contexto, 4).
- **ctx com preço**: fração dos trechos entregues que contêm o preço do produto, fato de que respostas de compra dependem. É a métrica que mostra o ganho do parent-document.
- **faithfulness**: fração das afirmações verificáveis da resposta (frases com número ou nome de produto) cujos números existem na evidência. **answer relevancy**: sobreposição lexical e semântica com a pergunta; recusas só valem nas perguntas sem resposta. Ambas vêm de um juiz heurístico determinístico atrás da interface `JudgeLlm`; um juiz LLM entra sem mudar o harness.

## Tabela comparativa

Cada linha liga uma técnica ao baseline (hybrid + RRF + reranker lexical, o pipeline original). Entre parênteses, a diferença para o baseline. A latência é de recuperação, em máquina compartilhada com outros containers: só serve como ordem de grandeza.

<!-- rageval:start -->
Casos de recuperação avaliados: 95.

| variante | hit@1 | hit@3 | MRR | nDCG@5 | prec. ctx | rev. ctx | negação | abstenção | ctx com preço | hit@3 dev | hit@3 holdout | MRR holdout | p50 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline (hybrid + RRF + reranker) | 0,756 | 0,923 | 0,870 | 0,861 | 0,870 | 0,892 | 0,000 | 0,765 | 0,771 | 0,933 | 0,909 | 0,783 | 7 |
| pós-filtro em vez de pré-filtro | 0,756 | 0,923 | 0,870 | 0,861 | 0,870 | 0,892 | 0,000 | 0,765 | 0,771 | 0,933 | 0,909 | 0,783 | 65 |
| pré-filtro, ramos de 5 candidatos | 0,756 | 0,897 (-0,026) | 0,862 (-0,008) | 0,853 (-0,008) | 0,861 (-0,009) | 0,883 (-0,009) | 0,000 | 0,765 | 0,763 (-0,007) | 0,933 | 0,849 | 0,765 | 12 |
| pós-filtro, ramos de 5 candidatos | 0,756 | 0,897 (-0,026) | 0,862 (-0,008) | 0,853 (-0,008) | 0,861 (-0,009) | 0,883 (-0,009) | 0,000 | 0,765 | 0,763 (-0,007) | 0,933 | 0,849 | 0,765 | 52 |
| pesos RRF 0,5 vetor / 1,5 texto | 0,756 | 0,910 (-0,013) | 0,869 (-0,001) | 0,858 (-0,003) | 0,870 | 0,888 (-0,004) | 0,000 | 0,765 | 0,802 (+0,031) | 0,933 | 0,879 | 0,780 | 18 |
| pesos RRF 1,5 vetor / 0,5 texto | 0,756 | 0,910 (-0,013) | 0,863 (-0,007) | 0,853 (-0,008) | 0,863 (-0,007) | 0,879 (-0,013) | 0,000 | 0,882 (+0,118) | 0,763 (-0,008) | 0,911 | 0,909 | 0,798 | 20 |
| + correção de digitação | 0,769 (+0,013) | 0,923 | 0,876 (+0,006) | 0,866 (+0,005) | 0,876 (+0,006) | 0,892 | 0,000 | 0,765 | 0,771 | 0,933 | 0,909 | 0,798 | 27 |
| + expansão de sinônimos (sempre) | 0,808 (+0,051) | 0,936 (+0,013) | 0,913 (+0,044) | 0,903 (+0,042) | 0,911 (+0,041) | 0,926 (+0,034) | 0,000 | 0,765 | 0,690 (-0,081) | 0,978 | 0,879 | 0,826 | 34 |
| + expansão de sinônimos (adaptativa) | 0,782 (+0,026) | 0,936 (+0,013) | 0,901 (+0,031) | 0,890 (+0,030) | 0,902 (+0,032) | 0,918 (+0,026) | 0,000 | 0,765 | 0,742 (-0,029) | 0,978 | 0,879 | 0,795 | 26 |
| + HyDE (documento hipotético) | 0,782 (+0,026) | 0,923 | 0,885 (+0,015) | 0,872 (+0,011) | 0,885 (+0,015) | 0,892 | 0,000 | 0,882 (+0,118) | 0,733 (-0,038) | 0,933 | 0,909 | 0,818 | 15 |
| + negação | 0,808 (+0,051) | 0,949 (+0,026) | 0,908 (+0,038) | 0,897 (+0,037) | 0,908 (+0,038) | 0,923 (+0,031) | 1,000 (+1,000) | 0,765 | 0,794 (+0,023) | 0,933 | 0,970 | 0,874 | 11 |
| + decomposição | 0,756 | 0,923 | 0,876 (+0,006) | 0,864 (+0,003) | 0,873 (+0,003) | 0,892 | 0,000 | 0,765 | 0,771 | 0,933 | 0,909 | 0,798 | 28 |
| + MMR lambda 0,7 | 0,756 | 0,910 (-0,013) | 0,872 (+0,002) | 0,862 (+0,001) | 0,871 (+0,001) | 0,892 | 0,000 | 0,765 | 0,768 (-0,003) | 0,933 | 0,879 | 0,788 | 16 |
| + MMR lambda 0,4 | 0,756 | 0,923 | 0,870 | 0,860 (-0,001) | 0,868 (-0,002) | 0,892 | 0,000 | 0,765 | 0,768 (-0,003) | 0,933 | 0,909 | 0,783 | 15 |
| + roteamento de intenção | 0,756 | 0,923 | 0,870 | 0,861 | 0,870 | 0,892 | 0,000 | 0,882 (+0,118) | 0,765 (-0,006) | 0,933 | 0,909 | 0,783 | 6 |
| chunks pequenos (150/30) | 0,769 (+0,013) | 0,923 | 0,882 (+0,013) | 0,871 (+0,010) | 0,883 (+0,014) | 0,892 | 0,000 | 0,765 | 0,243 (-0,528) | 0,933 | 0,909 | 0,813 | 19 |
| parent-document (chunks 300/60) | 0,756 | 0,923 | 0,870 | 0,861 | 0,870 | 0,892 | 0,000 | 0,765 | 1,000 (+0,229) | 0,933 | 0,909 | 0,783 | 11 |
| chunks pequenos + parent-document | 0,769 (+0,013) | 0,923 | 0,882 (+0,013) | 0,871 (+0,010) | 0,883 (+0,014) | 0,892 | 0,000 | 0,765 | 1,000 (+0,229) | 0,933 | 0,909 | 0,813 | 7 |
| combo: adaptativa + digitação + negação + decomposição | 0,846 (+0,090) | 0,962 (+0,038) | 0,946 (+0,076) | 0,931 (+0,070) | 0,944 (+0,075) | 0,949 (+0,057) | 1,000 (+1,000) | 0,882 (+0,118) | 0,752 (-0,019) | 0,978 | 0,939 | 0,901 | 28 |
| combo: sempre + digitação + negação + decomposição | 0,859 (+0,103) | 0,962 (+0,038) | 0,952 (+0,082) | 0,942 (+0,081) | 0,951 (+0,081) | 0,957 (+0,065) | 1,000 (+1,000) | 0,882 (+0,118) | 0,698 (-0,073) | 0,978 | 0,939 | 0,917 | 19 |
| combo anterior + HyDE | 0,846 (+0,090) | 0,962 (+0,038) | 0,942 (+0,073) | 0,931 (+0,071) | 0,941 (+0,072) | 0,944 (+0,052) | 1,000 (+1,000) | 0,941 (+0,176) | 0,685 (-0,086) | 0,978 | 0,939 | 0,894 | 14 |
| combo anterior + MMR 0,7 | 0,859 (+0,103) | 0,962 (+0,038) | 0,952 (+0,082) | 0,941 (+0,080) | 0,950 (+0,080) | 0,957 (+0,065) | 1,000 (+1,000) | 0,882 (+0,118) | 0,698 (-0,073) | 0,978 | 0,939 | 0,917 | 15 |
| produção (configuração padrão do serviço) | 0,859 (+0,103) | 0,962 (+0,038) | 0,952 (+0,082) | 0,942 (+0,081) | 0,951 (+0,081) | 0,957 (+0,065) | 1,000 (+1,000) | 0,882 (+0,118) | 1,000 (+0,229) | 0,978 | 0,939 | 0,917 | 16 |

hit@3 por categoria, baseline contra produção:

| categoria | baseline | produção |
|---|---|---|
| adversarial | 1,000 | 1,000 |
| category | 1,000 | 1,000 |
| comparison | 1,000 | 1,000 |
| direct | 1,000 | 1,000 |
| multi_hop | 1,000 | 1,000 |
| negation | 0,667 | 1,000 |
| paraphrase | 0,789 | 0,842 |
| price | 1,000 | 1,000 |
| rating | 1,000 | 1,000 |
| sorting | 1,000 | 1,000 |
| typo | 1,000 | 1,000 |
<!-- rageval:end -->

## Leitura dos resultados

**O que ajudou de verdade**

- **Expansão de sinônimos** é a maior alavanca de recuperação isolada: MRR 0,870 para 0,913 e hit@1 de 0,756 para 0,808. Resolve as paráfrases em que consulta e documento não dividem palavra ("algo para ouvir música" para o fone). Rodar sempre ficou melhor que rodar só quando a primeira busca é fraca (modo adaptativo, MRR 0,901), sem custo extra de abstenção; o modo "sempre" ainda faz uma única busca em vez de duas.
- **Negação** fecha uma classe inteira de erro: o baseline devolve o produto que o usuário pediu para excluir em todos os casos de negação (negação 0,000), a variante com negação nunca devolve (1,000).
- **Roteamento de intenção** não mexe no ranking, mas faz perguntas fora do escopo terminarem sem ferramenta e sem contexto: abstenção de 0,765 para 0,882.
- **Correção de digitação** rende pouco aqui (+0,013 em hit@1) porque o catálogo é pequeno e quase todo erro de digitação cai em uma frase com outras palavras corretas. Em catálogos maiores a conta muda, mas isso não foi medido.
- **Parent-document** não muda o ranking por construção: ele troca o trecho recuperado pelo documento inteiro do produto. O efeito aparece em "ctx com preço": com chunks de 150 caracteres só 24% dos trechos entregues trazem o preço; com parent-document, 100%. É a combinação clássica: chunk pequeno para achar, contexto grande para responder.

**O que não ajudou (e fica desligado ou como opção)**

- **HyDE** (documento hipotético): com o gerador por template, MRR 0,870 para 0,885 isolado, mas em combinação com a expansão perde (0,942 contra 0,952) e custa uma geração a mais com um LLM real. A abstenção sobe (0,941) porque o documento hipotético afasta consultas sem relação. Fica implementado e desligado por padrão (`RETRIEVAL_HYDE=false`).
- **MMR**: neutro (MRR 0,872 com lambda 0,7; 0,870 com 0,4). A recuperação já devolve um chunk por produto, então não há redundância para reduzir neste catálogo. Em um catálogo com muitos produtos quase iguais ele deve valer a pena; aqui não.
- **Pesos da fusão**: 1,0/1,0 foi o melhor. Pesar o vetor (1,5/0,5) piora hit@3 e MRR; pesar o texto (0,5/1,5) piora um pouco. Com o embedder lexical os dois ramos já concordam muito.
- **Decomposição** quase não aparece em hit@k (MRR +0,006) porque a busca com OU já traz os dois produtos de uma pergunta composta. Ela existe por causa de perguntas com filtros diferentes em cada metade ("fone até R$ 400 e mochila até R$ 350"), que o baseline não separa.

**Pré-filtro contra pós-filtro.** No catálogo de 24 produtos os dois empatam, porque cada ramo da busca já devolve quase tudo. O teste `test_prefilter_returns_full_results_where_postfilter_starves` cria 200 clones do fone com preços espalhados e pergunta "fone bluetooth até 100 reais" com ramos de 20 candidatos: o pré-filtro devolve 4 produtos dentro do preço; o pós-filtro devolve **0**, porque os 20 melhores candidatos de cada ramo quase nunca estão dentro do teto. Filtrar antes da busca vetorial é o que mantém a revocação quando o catálogo cresce.

**Produção.** O padrão do serviço é o que sobrou da medição: expansão "sempre", correção de digitação, negação, decomposição, parent-document e roteamento de intenção; HyDE e MMR desligados. Contra o baseline, no conjunto de recuperação: hit@1 0,756 para 0,859, hit@3 0,923 para 0,962, MRR 0,870 para 0,952, nDCG@5 0,861 para 0,942, precisão de contexto 0,870 para 0,951, revocação de contexto 0,892 para 0,957. No holdout: hit@3 0,909 para 0,939 e MRR 0,783 para 0,917.

## Avaliação ponta a ponta

Pipeline completo (agente, geração, guarda de embasamento, juiz heurístico), 111 casos, `python -m assistant.evals --offline`:

| métrica | original (36 casos) | atual (111 casos) |
|---|---|---|
| hit@3 | 0,893 | 0,965 |
| MRR | 0,893 | 0,956 |
| nDCG@5 | n/d | 0,946 |
| precisão de contexto | n/d | 0,955 |
| revocação de contexto | n/d | 0,961 |
| negação | n/d | 1,000 |
| faithfulness (juiz) | n/d | 1,000 |
| answer relevancy (juiz) | n/d | 0,686 |
| groundedness | 1,000 | 1,000 |
| tool accuracy | 1,000 | 1,000 |
| answer pass | 1,000 | 0,991 |

Por split: dev hit@3 0,980; holdout hit@3 0,943. Na coluna "original" os 36 casos antigos rodaram no pipeline antigo; sobre esses mesmos 36 casos o pipeline atual tem hit@3 e MRR de 0,964. As métricas "n/d" não existiam. O `answer relevancy` de 0,686 reflete um juiz heurístico lexical: ele subestima respostas corretas que recomendam o produto sem repetir as palavras da pergunta. Use-o para detectar queda, não como nota absoluta.

Casos que ainda falham (todos conhecidos): `parafrase-exercitar-em-casa`, `p-chuva` e `p-cheiro` (paráfrases sem sobreposição que nem o léxico cobre; exigem embedding semântico) e `a-produto-inexistente` (um produto que o catálogo não vende, mas cuja palavra vizinha dispara a expansão).

## Cache semântico

`python -m assistant.cachebench` repete as 107 perguntas sem histórico do conjunto dourado em quatro passadas, com o cache ligado (limiar de similaridade 0,92). Perguntas de estoque e de pedido nunca entram no cache (dado vivo), por isso 22 ficam "ignoradas".

| passada | consultas | hits | misses | ignoradas | hit rate | tokens economizados |
|---|---|---|---|---|---|---|
| 1. primeira vez | 107 | 0 | 85 | 22 | 0.000 | 0 |
| 2. mesma pergunta | 107 | 85 | 0 | 22 | 1.000 | 45852 |
| 3. caixa alta e pontuação | 107 | 85 | 0 | 22 | 1.000 | 45852 |
| 4. com cortesia | 107 | 85 | 0 | 22 | 1.000 | 45852 |

Total: hit rate 0,750, 137556 tokens e US$ 0,0688 economizados (preço de referência).

A passada 4 (com "por favor" e "obrigado") só acerta porque essas palavras entram na lista de palavras vazias: sem isso o hit rate dela era 1,2%, uma lição de que o cache depende da mesma limpeza de texto do embedder. Os tokens economizados usam a estimativa de quatro caracteres por token e o preço de referência (US$ 0,0005 por mil tokens de entrada), porque o modelo simulado não é cobrado.

## Limitações

- O embedder é lexical. Paráfrases sem palavra em comum só são resolvidas pelo léxico de sinônimos, que é escrito à mão e conhece o catálogo. Com embeddings semânticos reais (Ollama, `nomic-embed-text`) os números das técnicas de reescrita mudam, e o HyDE tende a valer mais.
- 24 produtos é pouco: MMR, pré-filtro e correção de digitação são as técnicas mais penalizadas por isso.
- O holdout foi escrito pelo mesmo autor do léxico. O juiz é heurístico. Nenhum número aqui foi medido com um LLM real.
