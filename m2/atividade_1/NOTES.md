# NOTES.md — M2, atividade 1: cache de páginas, acerto e falta

Arquivos: `../cache.py` (o cache), `../minidb_cache.py` (o M1 passando pelo
cache), `teste_acerto.py` (11 testes), `medicao.py` (a medição).

## O que foi feito

`CachePaginas` guarda `capacidade` frames de 4096 bytes, uma tabela de
páginas (`dict` página → frame) e os pares `fixa`/`solta`. Toda leitura pede a
página ao cache:

1. **verifica** na tabela: se está lá, é acerto e não toca no disco;
2. senão é falta: **adiciona**, pegando um frame livre e lendo a página com o
   `le_pagina` do M1;
3. devolve o buffer do frame, a mesma `bytearray` e não uma cópia, e conta um
   pin, que só o `solta` desfaz.

## Teste 1 do slide: "ler a mesma página duas vezes faz uma leitura de disco só"

`test_ler_a_mesma_pagina_duas_vezes_faz_uma_leitura_de_disco`: `fixa(5)`,
`solta(5)`, `fixa(5)`, `solta(5)` → `leituras_disco == 1`, `faltas == 1`,
`acertos == 1`. Outros testes cobrem: mesma referência no acerto
(`assertIs`), `acertos + faltas == chamadas`, `solta` sem `fixa` levantando
erro, `usa()` soltando mesmo quando o bloco estoura, varredura de 1200
registros sem pin sobrando (inclusive com o gerador abandonado no meio) e a
falha de leitura devolvendo o frame (a capacidade não encolhe).

## Medição: 10 mil registros, duas varreduras no mesmo processo

Tabela feita pelo `insere` do M1: 10000 registros em 20 páginas de dados, mais
a página 0 = 21 páginas. Contagem de chamadas reais a `le_pagina`:

| configuração | 1ª varredura | 2ª varredura |
|---|---:|---:|
| M1, relendo a página a cada registro | 10001 | 10001 |
| M1, `varredura()` (1 leitura por página) | 21 | 21 |
| cache de 3 frames | 21 | 21 |
| cache de 32 frames | 21 | **0** |

- O slide fala em 20 e 10000; o que aparece aqui é 21 e 10001 porque a página
  0 (metadados) também é lida. Razão: 10001 / 21 ≈ 476×, o "500 vezes" do slide.
- Todas as configurações devolvem a mesma resposta (soma dos ids = 50005000).
- O cache de 3 frames não ajuda na segunda varredura: a tabela tem 21 páginas
  e cabem 3, então cada página é expulsa antes de ser pedida de novo. Só o
  cache de 32 zera as leituras da segunda varredura. É o que o slide diz:
  "nada continuou em memória" sem cache, e com cache só se a capacidade der.
- Traduzindo as contagens para as latências do slide da tabela de tempos (100 µs NVMe, 10 ms
  disco magnético): as duas varreduras ingênuas (20002 leituras) custariam
  ~2 s em NVMe e ~200 s em disco magnético; com o cache de 32 frames, 21
  leituras: ~2 ms e ~0,2 s. Os milissegundos medidos no script não servem
  para isso, porque quem responde aqui é o cache do sistema operacional e
  não o disco. A contagem de leituras é o número confiável.
