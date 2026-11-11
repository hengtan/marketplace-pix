# Evolução de eventos

Como mudar o formato de um evento do Kafka sem quebrar quem produz, quem consome e as mensagens que já
estão no tópico. O código está em `backend/libs/marketplace_common/src/marketplace_common/events/`.

## 1. O problema

Em um sistema com Kafka, produtor e consumidor não sobem juntos. Quando o `ordering` passa a publicar um
campo novo, existem ao mesmo tempo:

- consumidores velhos, que nunca ouviram falar do campo;
- consumidores novos, que podem receber mensagens antigas (o tópico guarda histórico, a DLQ guarda falhas,
  um reprocesso reentrega o que já passou);
- o próprio produtor, que precisa garantir que não mudou nada por acidente.

Sem disciplina, o primeiro `rename` de campo derruba o ledger em produção. A resposta aqui tem três peças:
um **envelope versionado**, **modelos e upcasters** na biblioteca e **testes de contrato** com arquivos golden.

## 2. O envelope

Toda mensagem leva a versão em dois lugares, para que dê para filtrar sem abrir o JSON e para que o payload
continue legível fora do Kafka (DLQ, replay, log):

| Onde | Campo |
|---|---|
| Header Kafka | `schema_version` (texto com o inteiro) |
| Corpo JSON | `"schema_version": 2` |

O produtor grava a versão no outbox (`marketplace_common.events.serialize_event` lê o atributo de classe
`schema_version` do evento de domínio, padrão 1). O `KafkaPublisher` copia para o header. O
`IncomingEvent` do consumidor lê o header, depois o corpo, e na falta dos dois assume `1`, que é o caso de
toda mensagem publicada antes desta mudança.

## 3. Modelos versionados e upcasters

Cada tipo de evento tem um modelo pydantic por versão (`OrderCreatedV1`, `OrderCreatedV2`, ...), registrado
em `REGISTRY`. Os modelos ignoram campos desconhecidos (`extra="ignore"`), que é o que torna a leitura
compatível para frente.

Um **upcaster** migra o payload de uma versão para a vizinha. O registro encadeia quantos forem preciso
(v1 → v2 → v3), então um consumidor novo lê qualquer mensagem do histórico como se fosse da versão mais nova.
Existe também o **downcaster**, usado quando um produtor precisa servir uma versão antiga.

```python
event.parse()                                   # IncomingEvent -> modelo da versão mais nova (upcast automático)
REGISTRY.parse_as("OrderCreated", payload, 1)   # um leitor antigo lendo dado novo
REGISTRY.downcast("OrderCreated", payload, 1)   # v2 -> v1
```

Regras de leitura:

| Situação | Comportamento |
|---|---|
| Mensagem mais velha que o consumidor | upcast até a versão mais nova que o consumidor conhece |
| Mensagem mais nova que o consumidor | lê com o modelo mais novo que conhece, ignora o resto e registra um aviso |
| Versão sem upcaster no meio da cadeia | erro explícito (`UnknownEvent`), nunca um palpite |
| Payload inválido para o modelo | `ValidationError`, e o consumidor segue o caminho normal de retry e DLQ |

## 4. Compatível ou incompatível

| Mudança | Classe | O que fazer |
|---|---|---|
| Campo novo **opcional** | compatível | nova versão do modelo, upcaster que preenche o padrão, golden novo |
| Campo novo obrigatório | incompatível | tipo novo, ou campo opcional na vez de obrigatório |
| Remover campo | incompatível | publicar as duas versões por um período (dual publish) e só então aposentar |
| Renomear campo | incompatível | adicionar o nome novo como opcional, migrar consumidores, remover o velho depois |
| Mudar tipo ou semântica (ex.: centavos para reais) | incompatível | tipo de evento novo |

Ordem de implantação para uma mudança compatível: **consumidores primeiro** (já toleram o campo por ignorarem o
que não conhecem), produtor por último. Em uma mudança incompatível, o produtor publica as duas formas até o
último consumidor migrar.

## 5. Testes de contrato (golden files)

Em `events/golden/` há um JSON por tipo e versão (`OrderCreated.v2.json`, ...), escrito à mão e revisado como
código. O helper `assert_producer_contract(tipo, payload)` compara o que o produtor realmente serializa com o
golden **e** com o modelo. Ele falha, dizendo quais campos faltam, sobram ou mudaram, quando alguém:

- remove ou renomeia um campo;
- adiciona um campo sem declarar (o teste exige que o modelo conheça tudo que sai);
- muda um tipo (data virando número, por exemplo);
- esquece de subir a versão.

Cada produtor (`ordering`, `payments`, `inventory`, `ledger`) tem `tests/unit/test_event_contract.py` com um
caso por evento. Do outro lado, cada consumidor (`ledger`, `payments`, `inventory`, `notifications`) tem
`test_consumer_compatibility.py`, que alimenta o handler com os golden de **todas** as versões publicadas.
Uma versão nova entra nos dois lados: o produtor prova que emite o combinado, o consumidor prova que entende.

## 6. A evolução real: `OrderCreated` v2

Motivação: o ordering passou a aceitar checkout de convidado e de usuário autenticado, e os consumidores
(análise, e-mails) querem saber a diferença. v2 acrescenta `customer_type`, valores `guest` ou `registered`,
**opcional**.

| | v1 | v2 |
|---|---|---|
| `customer_type` | ausente | `guest`, `registered` ou nulo |
| Upcaster v1 → v2 | | preenche `customer_type = null` (não dá para saber o passado) |
| Downcaster v2 → v1 | | remove `customer_type` |

Provas, todas automatizadas:

1. O produtor (`Order.create`) emite `schema_version = 2` com o tipo certo, e o payload é idêntico ao golden v2.
2. Um consumidor novo lê o golden v1 e recebe um `OrderCreatedV2` com `customer_type = None`.
3. Um leitor v1 lê o golden v2 sem erro (ignora o campo novo): compatibilidade para frente.
4. `downcast(upcast(v1)) == v1`: ida e volta sem perda.
5. Com Kafka real, o header `schema_version` sai do publisher e o consumer parseia mensagens v1 e v2 do
   mesmo tópico no mesmo modelo.
6. Os quatro consumidores existentes processam o golden v1 e o v2 sem alteração de código.

## 7. O que ficou de fora (e por quê)

- **Schema registry com Avro ou Protobuf**: resolve a mesma família de problemas com um serviço a mais e
  serialização binária. Para um repositório de estudo com JSON, modelos pydantic e golden files cobrem o
  raciocínio, e a migração para um registry seria trocar a fonte dos modelos, não a disciplina.
- **Validação do consumidor na entrada de todos os handlers**: só o `IncomingEvent.parse()` usa os modelos.
  Os handlers atuais continuam lendo o dicionário e ignorando o que não conhecem.
- **Evolução do envelope em si** (por exemplo mover `event_id` para dentro de um objeto): seria uma
  mudança incompatível e exigiria um tópico novo.

## 8. Roteiro de fala para entrevista

**Pergunta provável:** "Como você evolui um evento sem derrubar os consumidores?"

> Primeiro separo mudança compatível de incompatível. Campo novo opcional é compatível; remover, renomear ou
> mudar semântica não é. No projeto, toda mensagem carrega um `schema_version`, no header e no corpo, e a
> biblioteca compartilhada tem um modelo pydantic por tipo e versão, com upcasters entre versões vizinhas.
> O consumidor novo lê tudo, inclusive o histórico, como a versão mais nova. O consumidor velho ignora o que
> não conhece, e isso está em teste.
>
> O que me dá confiança são os testes de contrato: guardo um arquivo golden por versão, e o teste do produtor
> falha se o payload sair diferente, seja um campo a menos, a mais ou de outro tipo. Do lado do consumidor,
> cada serviço roda o handler contra os golden de todas as versões. Na prática eu fiz a evolução do
> `OrderCreated` para a v2 com um campo `customer_type` opcional, e provei nos dois sentidos: dado velho no
> leitor novo e dado novo no leitor velho.
>
> A ordem de implantação é consumidores primeiro, produtor depois. Para mudança incompatível eu publico as
> duas formas até o último consumidor migrar, ou crio um tipo de evento novo. Se o volume justificasse, o
> próximo passo seria um schema registry com checagem de compatibilidade no CI, mas a disciplina é a mesma.

**Perguntas de acompanhamento e respostas curtas**

- *E as mensagens que já estavam no Kafka?* Sem `schema_version` valem `1`, e o upcaster as leva à versão atual.
- *E se um consumidor receber uma versão que não conhece?* Lê com o modelo mais novo que tem, ignora o excesso e
  registra um aviso. Se faltar um upcaster no meio da cadeia, falha alto em vez de adivinhar.
- *Por que não só confiar nos testes do consumidor?* Porque quem quebra o contrato é o produtor. O golden
  transforma o contrato em um artefato versionado que o CI compara a cada mudança.
- *Qual o custo?* Código de migração para manter e golden para revisar. Vale enquanto houver mais de um
  consumidor independente, que é exatamente quando o problema aparece.
