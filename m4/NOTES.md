# NOTES.md — M4: do texto à árvore, e a primeira consulta que roda

Entrega do M4: o minidb deixa de ser uma biblioteca e passa a ser um programa.
Recebe SQL pela entrada padrão, uma instrução por linha, responde, e guarda
tudo no arquivo. A meta do slide roda palavra por palavra, **em dois
processos** (o segundo lê do disco o que o primeiro criou):

```
$ ./minidb dados.db
CREATE TABLE aluno (id INT, matricula INT, nome CHAR(20));
OK
INSERT INTO aluno VALUES (1, 20260001, 'Ana');
OK 1
INSERT INTO aluno VALUES (2, 20260002, 'Bruno');
OK 1
^D
$ ./minidb dados.db                  # outro processo
SELECT * FROM aluno;
1|20260001|Ana
2|20260002|Bruno
(2 linhas)
```

M1 e M2 **não foram alterados** (`minidb.py`, `minidb_m1.py`, `cache.py` e
`minidb_cache.py` são os do M3, byte a byte). O M4 só acrescenta arquivos e
reaproveita `Esquema`, `aloca`, `insere` e o cache. A árvore B+ do M3
(`btree.py`) não é usada no M4 e não está nesta pasta; entra de novo no M5.

| arquivo | etapa | o que é |
|---|---|---|
| `erros.py` | 1–4 | um tipo de erro por etapa: léxico, sintático, semântico, não implementado |
| `sql.py` | 1 e 2 | `tokeniza`, `Parser` (uma função por regra) e `analisa(sql)` |
| `catalogo.py` | 3 | catálogo em disco, `EsquemaSQL`, `Catalogo.insere` e `Catalogo.varre` |
| `executor.py` | 3 e 4 | `confere` (análise semântica), `roda` (um `if` por comando) e `executa` |
| `minidb` | — | o programa: abre o arquivo, laço de leitura, grava ao sair |
| `teste_sql.py` | | 94 testes |
| `exercicios_m4.py` | | os exercícios 1 e 2 rodados no código de verdade |

O caminho de uma consulta, e o que cada etapa pode recusar:

```
texto ─ tokeniza ─▶ tokens ─ Parser ─▶ árvore ─ confere ─▶ plano ─ roda ─▶ resposta
         ErroLexico          ErroSintatico        ErroSemantico        ErroNaoImplementado
        (não vira token)   (ordem errada)    (não faz sentido AQUI)
                                              precisa do catálogo
```

A mensagem sempre diz a etapa (`ERRO léxico: …`, `ERRO sintático: …`,
`ERRO semântico: …`), e um erro de etapa anterior nunca consulta o catálogo:
`SELECT * FROM naoexiste WHERE id == 1` é erro **sintático**, e não "a tabela
não existe" (testado).

## Etapas 1 e 2: o código dos slides

`tokeniza`, `Parser`, `create`, `coluna`, `insert`, `select`, `comando` e
`analisa` são os dos slides. Os tokens são pares `(tipo, valor)`, e a lista
da mão do slide (`nome CHAR(20),`) é um teste. As árvores também: o CREATE do
slide, o INSERT do gabarito e o `SELECT nome FROM aluno WHERE id = 42`.

Quatro endurecimentos pequenos em relação ao código do slide:

- **`comando` confere o tipo do token, e não só o valor.** Com `v == "CREATE"`
  o texto `'CREATE' TABLE t (a INT)` entrava em `create()` e falhava com
  "esperava CREATE, veio 'CREATE'". Agora é `comando desconhecido 'CREATE'`.
- **O dígito é ASCII.** `'²'.isdigit()` é verdadeiro e `int('²')` estoura com
  `ValueError` no meio do tokenizador. Um número com milhares de dígitos
  também (limite de conversão do Python). Os dois viram `ErroLexico`.
- **Tipo desconhecido** (`a FLOAT`) diz "esperava INT ou CHAR", e não só CHAR.
- **O FIM não aparece como `None`** na mensagem: "esperava FROM, veio o fim do comando".

A gramática é a do slide, sem acréscimos: **sem número negativo** (o `-` é
"caractere inesperado"), sem `OR`/`AND`, sem escape de aspa dentro de texto,
uma instrução por chamada.

## Etapa 3: o catálogo

A árvore traz o nome `aluno`, mas o nome sozinho não diz onde a tabela mora nem
com quais colunas. Isso fica no disco, no **catálogo**, e é o que faz o
segundo processo saber que `aluno` existe.

**Onde fica.** Tudo pelo cache do M2, no mesmo arquivo, com o formato de
página do M1:

| onde | o quê |
|---|---|
| página 0, bytes 24–27 | página do 1º catálogo (0 = o arquivo ainda não tem). Os bytes 18–23 são a raiz do índice do M3, sem choque |
| página de catálogo | cabeçalho de 16 bytes: `n_entradas`, **marca 0** (o mesmo "não é página de dados" do M3, então `varre` do M1/M2 a pula), `num_pagina`, tipo 3, e `extra` = próxima página de catálogo |
| uma entrada | nome, `n_colunas`, **primeira** e **última** página de dados, e por coluna: nome, tipo (1 INT, 2 CHAR), tamanho |
| página de dados | cabeçalho do M1 e, **nos bytes 8–11, a próxima página da mesma tabela** (0 = última) |

Os bytes 8–15 do cabeçalho do M1 eram reservados e zerados, então o formato
dos dados é o mesmo e um arquivo antigo continua abrindo. Um arquivo do M1–M3
(sem catálogo) ganha um catálogo vazio na primeira abertura e as páginas
antigas não são alteradas (testado), mas **não são adotadas por nenhuma tabela**.

**Por que a corrente de páginas.** Com uma tabela só (M1–M3), a tabela era "as
páginas de 1 a N". Com duas, as páginas se misturam no arquivo (aluno, curso,
aluno…), e a varredura do M1 não sabe de quem é cada uma. Um teste mostra isso:
duas tabelas com **o mesmo esquema**, e o `varre` do M2 devolve as linhas das
duas misturadas, enquanto `Catalogo.varre` devolve só as da tabela pedida. O
catálogo guarda `primeira` (por onde a varredura começa) e `ultima` (onde o
INSERT grava), e `ultima` é atualizada no disco quando a corrente cresce.
Inserir não percorre a corrente.

**`EsquemaSQL`** estende o `Esquema` do M1: `INT` vira `i` (4 bytes) e `CHAR(n)`
vira `ns`, sempre `n` bytes completados com zeros, então o registro segue de
tamanho fixo e `tamanho` continua derivado das colunas. `n` é em **bytes**: 10
letras `ã` (2 bytes cada) cabem em `CHAR(20)`, 11 não.

**O que a análise semântica confere** (nada é gravado antes de ela terminar):

| comando | confere |
|---|---|
| `CREATE` | nome de tabela novo (sem diferenciar caixa), colunas sem repetição, `CHAR(n)` com n ≥ 1, nomes de até 32 bytes, registro de até 4080 bytes (cabe numa página), até 255 colunas e entrada que caiba numa página de catálogo |
| `INSERT` | a tabela existe, o número de valores é o de colunas, o tipo de cada um bate, `INT` em 32 bits, texto sem byte nulo e dentro de `CHAR(n)` |
| `SELECT` | a tabela existe, cada coluna existe, e o valor do `WHERE` tem o tipo da coluna |

Nomes de tabela e de coluna **não diferenciam maiúsculas**, mas o catálogo
guarda a caixa em que foram criados. As palavras reservadas também não diferenciam: já
saem maiúsculas do tokenizador.

## Etapa 4: a execução, "um `if` por comando"

`roda` é um `if` por `op`, direto sobre o plano, chamando o que já existia:
`aloca` e `insere` do M2 (pelo cache) e `Catalogo.varre`.

- **`SELECT *` e `SELECT a, b`** rodam de verdade, na ordem de inserção (a
  ordem da corrente). `(1 linha)` no singular, `(0 linhas)` na tabela vazia.
- **O `WHERE` é conferido mas não executado**, como pede o slide ("fica para o
  M5"): `ERRO não implementado: o WHERE é conferido, mas só passa a ser executado
  no M5`. Coluna inexistente ou tipo errado no `WHERE` já dá erro **semântico**
  agora. Como a árvore B+ do M3 é por tabela e guarda a raiz na página 0, ligar
  um índice por tabela fica para o M5, junto com os operadores.
- **Gravação:** `CREATE` e `INSERT` chamam `cache.grava_tudo()` **antes** de
  responder `OK`. O slide só grava ao fim do laço (`cache.descarrega()`), e
  isso faz o `OK 1` mentir se o processo morrer antes. Um teste mata o processo
  com `kill -9` logo depois do `OK 1` e o dado está lá. O fim do laço também
  grava, como no slide. Custa uma página (e um `fsync`) por comando: 5500
  INSERTs em duas tabelas levaram 1,5 s aqui. Num disco lento seria mais, e a
  saída seria um modo em lote, que não existe. O cache continua servindo às
  leituras e ao que estiver sujo no meio de um comando.

## O programa

`./minidb dados.db` (ou `python3 minidb dados.db`). Sem arquivo, cria. Com
terminal na entrada mostra o prompt `minidb> `; com pipe ou redirecionamento
só as respostas. Linha em branco é ignorada, e **um erro não derruba o
programa**.

Uma proteção que não está no slide: antes de usar `le_pagina`, o programa lê os
8 primeiros bytes com um `open` comum e confere o número mágico. O motivo é
que o `le_pagina` do M1 **completa com zeros** o que passa do fim do arquivo,
escrevendo. Abrir um `notas.txt` pelo minidb o encheria de zeros até 4096 bytes. Agora
recusa (`não é um arquivo do minidb`, código de saída 1) e **não toca no arquivo**
(testado). Arquivo de 0 bytes é tratado como novo.

## Respostas aos exercícios (`python exercicios_m4.py` mostra tudo rodando)

**Exercício 1** — `INSERT INTO aluno VALUES (3, 20260003, 'Carla');`

1. 13 tokens: `INSERT` `INTO` (palavras), `aluno` (nome), `VALUES` (palavra), `(`,
   `3` e `20260003` (números), `'Carla'` (texto, já sem as aspas), `)`, `;`
   (símbolos, com as vírgulas) e `FIM`.
2. Árvore: `{"op": "INSERT", "tabela": "aluno", "valores": [3, 20260003, "Carla"]}`.
3. Sem as aspas, `Carla` vira `NOME`: o **tokenizador passa** (13 tokens, nenhum
   erro, ele olha um token de cada vez), e o erro vem do **parser**,
   `esperava valor, veio 'Carla'`, **etapa 2**. No minidb 0.0 tudo era texto, e
   por isso nada era errado.

**Exercício 2, item 1** — em que etapa cada um falha, medido:

| comando | etapa | mensagem |
|---|---|---|
| `SELECT nome FROM aluno WHERE id == 42` | 2, sintático | `esperava valor, veio '='` (o tokenizador aceita dois `=`) |
| `SELECT * FROM WHERE id = 42` | 2, sintático | `esperava NOME, veio 'WHERE'` |
| `SELECT idade FROM aluno` | **3, semântico** | `a tabela aluno não tem a coluna idade` (a ordem está certa; só o catálogo sabe) |
| `SELECT * FROM aluno WHERE nome = 'O'Brien'` | **1, léxico** | `aspas sem fechamento na posição 41`: `'O'` fecha, `Brien` é nome, e a última aspa nunca fecha. O tokenizador falha antes de o parser ver qualquer coisa |

O quarto é o que mais engana: parece erro de sintaxe, e é léxico.

**Exercício 2, item 2** — `"SELECT * FROM aluno WHERE nome = '" + nome + "'"` com `nome = x' OR '1'='1`:

- O texto montado é `SELECT * FROM aluno WHERE nome = 'x' OR '1'='1'`. Tokens:
  `SELECT` `*` `FROM` `aluno` `WHERE` `nome` `=` **`'x'`** (texto) **`OR`** (nome)
  **`'1'`** (texto) `=` **`'1'`** (texto) `FIM`.
- O minidb responde `ERRO sintático: esperava FIM, veio 'OR'`, na **etapa 2**: o
  `WHERE` aceita uma só comparação, e sobra o `OR`.
- **Ele não está protegido.** O argumento:
  1. O ataque já funcionou na etapa 1: o texto do usuário **mudou o que é
     dado e o que é comando**. A aspa dele fechou o texto, e `OR` virou token de
     fora de qualquer texto. O que barrou foi o parser, porque a gramática não tem `OR`.
     É falta de alvo, não proteção.
  2. A mesma técnica funciona onde a gramática dá espaço. Num `INSERT` com
     `nome = Zé', 'extra`, o texto montado tem **quatro valores**; o parser
     aceita, e numa tabela de quatro colunas o catálogo também. Grava `1|a|Zé|extra`:
     um valor que o programa não previu (`exercicios_m4.py` e
     `Injecao.test_nao_e_protecao…`). Numa tabela de três colunas só a contagem
     da etapa 3 derruba o comando, por acaso.
  3. Quando o M5 trouxer `AND`/`OR`, o primeiro payload passa a funcionar.
  4. **Escapar não é saída aqui:** o tokenizador não tem escape (`''`), então
     o minidb nem consegue guardar `O'Brien`. A defesa é o que o slide mostra
     em Python: o valor **nunca** passa pelo tokenizador. A consulta é
     analisada antes (`... WHERE nome = ?`) e o valor entra depois, já como
     dado. O minidb não tem `?` nem `executa(sql, parametros)`; é a extensão
     natural, e fica fora do M4.

## Como sei que está certo

`teste_sql.py` (94 testes, `python teste_sql.py -v`), com **cache de 3 frames**
nos de banco, como no M2/M3, e `fixadas() == 0` conferido depois de **cada**
comando, inclusive os que dão erro:

- **Tokenizador**: os exemplos dos slides (a tabela da mão, o CREATE de 18
  tokens, o SELECT de 9, o gabarito do exercício 1), caixa, texto com símbolos
  por dentro, cada erro léxico com a posição.
- **Parser**: as três árvores dos slides, os 4 comandos do exercício 2.1, a
  palavra reservada na posição errada, sobra de token, comando incompleto,
  `OR`/`AND`/`>` (fora da gramática).
- **Semântica**: cada linha da tabela acima, e que um erro semântico **não
  grava nada** (a contagem de páginas do arquivo não muda).
- **Catálogo**: reabrir com outro cache, 300 tabelas que forçam um catálogo de
  várias páginas encadeadas, acentos, página de catálogo corrompida e arquivo
  que não é minidb falham alto, arquivo do M3 ganha catálogo.
- **Tabelas**: 3 páginas e meia de registros de 28 bytes, duas tabelas
  intercaladas (e com o mesmo esquema), cache de 3 e de **2** frames com
  expulsão de verdade, corrente que dá voltas.
- **Programa**: a meta do slide em dois processos, `kill -9`, arquivo alheio
  intocado, três processos em sequência.

Para ter certeza de que os testes pegam defeitos, quebrei o código de 12
jeitos, um por vez: o parser sem `espera("FIM")`, texto que guarda as aspas,
`comando` olhando só o valor, `espera` ignorando o valor, varredura que para na
primeira página, página nova sem encadear, `ultima` sem ir ao catálogo, catálogo
sem encadear, INSERT sem conferir tipo, INSERT sem contar valores, INSERT sem
gravar, `existe` diferenciando caixa. **Os 12 foram pegos.** Na primeira rodada dois
escaparam, e eram lacunas minhas: nada testava `CREATE FROM t (...)` (palavra
reservada trocada de lugar) nem o texto `'CREATE'` como comando. Escrevi os testes que faltavam.

A escrita dos testes achou um defeito real: uma tabela com mais de 255 colunas
estourava um `struct.error` dentro do catálogo (o contador de colunas é 1
byte), em vez de um erro semântico. Agora é `ERRO semântico: 400 colunas: …`.

## O que fica de fora

- **`WHERE`** (M5) e, com ele, usar o índice B+ nas consultas e um índice por tabela.
- **Sem `DROP`, `DELETE` e `UPDATE`**, e sem remoção de tabela do catálogo.
- **Uma instrução por linha.** Como o `;` é opcional, uma linha incompleta
  não se distingue de uma instrução inteira, então um `CREATE` quebrado em
  várias linhas dá erro sintático em cada pedaço.
- **Sem parâmetros `?`**, que são a defesa contra injeção (ver acima).
- **Sem número negativo, sem escape de aspa** (gramática dos slides).
- **Log e recuperação.** Gravar a cada comando não é uma transação: um `INSERT`
  que enche uma página grava várias (a de dados, a nova, a 0 e o catálogo), e
  se o processo morrer **no meio** disso o arquivo pode ficar com a corrente
  pela metade. É o problema do M2/M3, e quem resolve é o log.
- **Concorrência.** Dois processos escrevendo no mesmo arquivo ao mesmo tempo
  se corrompem, sem trava nenhuma. Um depois do outro funciona (testado).
- **A saída é montada inteira em memória** antes de imprimir. Para uma tabela
  de milhões de linhas o certo seria imprimir linha a linha.
