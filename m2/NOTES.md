# NOTES.md — M2: cache de páginas (buffer pool)

Entrega do M2: um cache de páginas entre o resto do minidb e o arquivo do M1,
com `fixa`/`solta`, LRU, contadores de acerto e falta, bit de sujeira e
gravação na expulsão. Cada atividade tem o seu `NOTES.md` com os números;
este arquivo tem as decisões e as respostas ao tema.

| atividade | tema | teste do slide "Como saber que está certo" |
|---|---|---|
| `atividade_1` | estrutura, acerto e falta, fixar e soltar | 1. Acerto |
| `atividade_2` | política de expulsão (LRU vs FIFO) | 2. Expulsão |
| `atividade_3` | página suja, kill -9, integração com o M1 | 3. Suja |

## Capacidade escolhida: 32 frames (128 KiB), e 3 nos testes

O padrão do `CachePaginas` é **32 frames**. Motivos, medidos:

- A tabela de 10 mil registros ocupa 21 páginas (20 de dados + página 0). Com
  LRU e varreduras repetidas o cache tem um **degrau**: de 1 a 20 frames o LRU
  acerta **0%** (cada página é expulsa exatamente antes de ser pedida de
  novo); com 21, acerta 90%. Um cache "quase do tamanho da tabela" não
  ajuda em nada nesse padrão de acesso, e por isso a capacidade tem que
  cobrir a tabela inteira, e não uma fração dela. Na medição da atividade 1, a
  segunda varredura faz 21 leituras com 3 frames e **0** com 32.
- Os 11 frames de sobra deixam a tabela crescer até cerca de 15 mil
  registros sem perder o degrau, e reservam lugar para as páginas do índice
  do M3, que vão disputar o mesmo cache.
- Custa 128 KiB de memória, o que não pesa.
- Em cargas com páginas quentes (atividade 2) o ganho de acerto tem retorno
  decrescente: 8 frames dão 85,5%, 12 dão 91,4%, 21 dão 99,9%. Mais do que a
  tabela inteira não compra nada.

Nos **testes uso 3 frames**, como o slide manda: com capacidade grande a
expulsão nunca acontece e os testes de expulsão e de página suja passariam
sem provar nada.

Isso é ajustado a uma tabela de brinquedo; a regra de fundo é que a capacidade
tem que cobrir o conjunto de trabalho. Bancos reais têm padrões na casa dos
128 MB (PostgreSQL `shared_buffers`, InnoDB `innodb_buffer_pool_size`), e
isso é dimensionado da mesma forma, pelo tamanho do que precisa ficar quente.

## Decisão de projeto mais difícil: a ordem das operações quando a expulsão falha

A parte que mais exigiu pensar não foi o LRU (uma lista ordenada e um
`move_to_end`), foi o que acontece **no meio** da expulsão quando alguma
coisa dá errado. Quando a vítima está suja, existem duas ordens possíveis:

1. tirar a página da tabela e depois gravá-la: é a mais natural de escrever,
   mas se a gravação falhar (`OSError`), a única cópia atualizada da página
   já saiu do cache e ainda não chegou ao disco. É a armadilha "expulsar suja
   sem gravar" do slide, só que agora acontecendo por erro, e não por
   esquecimento.
2. gravar e só depois tirar da tabela: se a gravação falhar, a exceção sobe e
   o cache fica **exatamente como estava**, com a página suja e intacta.

Fiquei com a 2 e escrevi o teste que a exercita
(`test_se_a_gravacao_na_expulsao_falha_a_pagina_suja_continua_no_cache`: a
gravação falha, a página continua lá, e com o disco de volta a próxima expulsão
grava certo). O mesmo raciocínio vale do lado da leitura: quando uma falta já
pegou um frame (livre ou de uma vítima) e o `le_pagina` falha, o frame volta
para a lista de livres. Sem isso, cada leitura que falhasse encolheria a
capacidade do cache em silêncio.

Duas decisões menores, na mesma linha de "quem responde pelo quê":

- **Cache todo fixado:** `fixa` levanta `CacheCheio` em vez de esperar ou de
  crescer além da capacidade. Esperar precisaria de outra thread para soltar
  (não há), e crescer desmancha o que "capacidade" quer dizer.
- **Como o cache sabe que está suja:** devolvo a **mesma** `bytearray` do
  frame (uma cópia faria a alteração morrer ali) e quem altera avisa em
  `solta(n, sujo=True)`. O custo é que esquecer de avisar perde a alteração
  em silêncio, o que virou um teste (`test_alterar_sem_avisar_perde_a_alteracao`).
  `usa(n, escreve=True)` reduz o risco: marca suja mesmo se o bloco estourar.

## Respostas ao tema

**O que o cache guarda e onde.** Cópias em memória das páginas mais usadas
("quentes") do arquivo. Uma estrutura separada do arquivo: `frames` (o
espaço), `tabela` (página → frame) e `ordem` (quem sai primeiro). O arquivo
continua sendo a fonte da verdade.

**Verificar, adicionar, resolver.** Os três passos do `fixa`:
*verificar* se a página está na tabela (acerto: devolve o frame, nenhum acesso a
disco); senão *adicionar*: pegar um frame livre e ler a página do disco (falta);
e, se não há frame livre, *resolver* a falta de espaço expulsando uma página.

**Política de inserção e de remoção.** Inserção por demanda: só entra a
página que foi pedida, no fim da fila (a mais recente). Remoção LRU: sai a
mais antiga da fila que não esteja fixada, e se estiver suja é gravada antes.
Alternativas com o mesmo esqueleto e regras diferentes: FIFO (implementado,
pior com páginas quentes: 8 frames, 77,0% contra 85,5% do LRU), Clock, LRU-K,
2Q e LRU com inserção no meio da lista, feitos para o caso em que o LRU puro falha (uma
varredura grande que expulsa as páginas quentes).

**Acerto e falta.** Acerto: a página estava em memória, 0 leituras de disco.
Falta: 1 leitura. Contadores no cache; `acertos + faltas == chamadas` sempre
(testado inclusive quando a falta termina em erro).

**Se o cache morrer, os dados são perdidos?** Só o que existia apenas nele:
páginas sujas ainda não gravadas. Páginas limpas não perdem nada (o cache
volta frio, é só desempenho) e páginas já gravadas ou expulsas ficam no disco.
Pior que a perda é a **inconsistência**: no caso E de `atividade_3/morte.py`,
1200 inserções pelo cache e `kill -9` sem `grava_tudo()` deixam a página 1
com 510 registros no disco enquanto a página 0 ainda diz que só existe 1 página, e o
M1 não acha nenhum registro. Quem resolve isso é o log (WAL, com REFAZER para o
`no-force` e DESFAZER para o `steal`), que o M2 não tem. Aqui a durabilidade é
o `grava_tudo()` explícito. Detalhes e tabela em `atividade_3/NOTES.md`.

## O que fica de fora (e aparece nas próximas aulas)

- **Log e recuperação:** ver acima. É a razão de o `steal`/`no-force` ser seguro.
- **Concorrência:** uma thread só, sem trava nas páginas.
- **A dúvida deixada no NOTES do M1** (ler página nunca escrita e ler página
  zerada de propósito são indistinguíveis) **não foi resolvida**. O cache
  guarda o que o `le_pagina` devolve. Vi o efeito colateral no caso E: como o
  `le_pagina` estende o arquivo com zeros quando pedem uma página além do
  fim, o arquivo ficou com 4 páginas enquanto a página 0 dizia 1. Uma
  `nova_pagina()` que instale um frame zerado sem ler o disco, e uma
  checagem contra o `total_paginas` da página 0, resolveriam.
- **LRU puro:** vulnerável à varredura grande, como mostrado na atividade 2.

```
