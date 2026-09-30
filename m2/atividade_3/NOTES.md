# NOTES.md — M2, atividade 3: página suja, e o que acontece se o cache morrer

Arquivos: `teste_suja.py` (10 testes), `morte.py` (kill -9 com o cache),
`integracao.py` (M1 com e sem cache, escrita).

## Página suja

Cada frame tem um bit `sujo`. Quem altera o buffer (que é o do frame, não uma
cópia) avisa em `solta(n, sujo=True)`, ou usa `with cache.usa(n, escreve=True)`.
O bit só sobe: uma leitura depois não o limpa, e só a gravação em disco o
limpa. A vítima suja é **gravada antes** de sair do cache (`_expulsa`), e
`grava_tudo()` grava todas as sujas quando alguém mandar.

## Teste 3 do slide: "alterar, expulsar, reabrir em outro processo"

`test_alterar_expulsar_reabrir_em_outro_processo`: altera a página 1 (suja),
toca 3 páginas novas (cache de 3 frames), a 1 é expulsa e gravada; um
`python -c` novo lê o arquivo direto do disco e vê o byte alterado.

Junto vem o **controle negativo**, que importa tanto quanto o teste:
`test_controle_negativo_...` altera, não expulsa e não grava. O outro processo
ainda vê o valor antigo, enquanto o próprio cache já devolve o novo. É a
diferença entre "está em memória" e "está no disco".

Outros testes: expulsar página limpa não escreve nada; 500 alterações na
mesma página viram **1** gravação (`no-force`: nada foi ao disco até a
expulsão); alterar sem avisar perde a alteração (o contrato explícito); e,
da armadilha "expulsar suja sem gravar", se a gravação na expulsão falha
(`OSError`), a página suja **continua no cache com o conteúdo intacto**, e
uma nova tentativa, com o disco de volta, grava certo.

## E se o cache morrer? Os dados são perdidos?

`morte.py` faz o mesmo que o `kill.py` do M1: o filho se mata com `kill -9`
sem fechar nada, e o pai confere o arquivo. Cache de 3 frames:

| caso | o que o filho fez antes do kill -9 | o que o pai achou no disco |
|---|---|---|
| A | alterou a página 1, nenhuma gravação | valor antigo. **Perdida** |
| B | alterou a página 1 e chamou `grava_tudo()` | valor novo. Sobreviveu |
| C | alterou a página 1 e 3 leituras a expulsaram, sem `grava_tudo()` | valor novo. Sobreviveu |
| D | só leituras, nenhuma alteração | arquivo idêntico ao original. Nada a perder |

Resposta curta: o cache é só memória, então o que **só** existe nele morre com
ele. O que morre é a diferença entre o cache e o disco:

- **Páginas limpas:** nada se perde, são cópias do que está no disco. O cache
  volta frio e as primeiras leituras viram falta. Custo de desempenho, não de dados.
- **Páginas sujas ainda não gravadas:** perdidas. O disco tem a versão antiga.
  Se a alteração era de uma transação que já tinha feito COMMIT, é
  exatamente o problema do `no-force`: o COMMIT não forçou a gravação, então
  a página só estava em memória. É o caso A.
- **Páginas sujas já expulsas ou gravadas:** ficam. É o caso C, e sobreviveu
  porque a expulsão gravou, não por causa de nenhuma decisão de durabilidade.
  Se a página fosse de uma transação **sem** COMMIT, o disco guardaria dado de
  uma transação que não existiu (o `steal` do slide).

**Perder é o menos grave; ficar inconsistente é pior.** O caso E monta a
tabela do M1 (1200 registros) pelo cache de 3 frames e mata sem `grava_tudo()`:

```
página 0 diz 1 página (o certo seriam 4); o arquivo tem 4 páginas
página 1 no disco: cabeçalho diz 510 registros
página 2 no disco: cabeçalho diz 0 registros
página 3 no disco: cabeçalho diz 0 registros
varredura do M1 encontrou 0 registros de 1200
```

A expulsão escolhe vítimas por LRU, sem saber nada sobre relações entre
páginas. A página 1 (cheia, 510 registros) chegou ao disco, mas a página 0,
que conta quantas páginas de dados existem, ficou suja na memória. O disco
passou a ter um estado que nunca existiu em nenhum instante. Nenhum registro
foi corrompido, mas há 510 registros no disco que ninguém enxerga, e 690
que nunca chegaram.

**Por isso existe o log.** O cache não tem que ser durável e não deve ser: a
graça dele é ficar em memória. A durabilidade vem do log de escrita
antecipada (WAL), que é gravado e sincronizado no disco **antes** da página que ele
descreve. Com `steal` e `no-force`, depois de uma queda:

- **REFAZER** (redo): repõe o que um COMMIT já confirmado deixou só em memória (caso A);
- **DESFAZER** (undo): tira do disco o que uma transação sem COMMIT deixou lá por expulsão (caso C).

O M2 não tem log. Então o que garante durabilidade aqui é o `grava_tudo()`
explícito, que é uma política *force* feita à mão, e a decisão de quando
chamá-lo é do chamador. Quem fecha sem chamá-lo perde as sujas.

Um aviso sobre o teste: `kill -9` mata o processo, não a máquina. O cache do
sistema operacional sobrevive, então o que passou por `write()` sobrevive
(como no NOTES do M1). Queda de energia é outro teste: só o que passou por
`fsync` chega. O `escreve_pagina` do M1 já faz `flush()` + `fsync()` em cada
página, então tudo que o cache grava é durável no sentido forte, com o custo de
um `fsync` por página expulsa.

## Integração com o M1, antes e depois (inserção)

Mesmos N registros do esquema `aluno`. Leituras e escritas são chamadas a
`le_pagina` / `escreve_pagina`. Os três arquivos resultantes são **idênticos
byte a byte** (o formato em disco não mudou).

| N | configuração | leituras | escritas |
|---:|---|---:|---:|
| 1200 | M1 sem cache | 1208 | 1207 |
| 1200 | cache de 3 frames | 4 | 5 |
| 1200 | cache de 32 frames | 4 | 5 |
| 10000 | M1 sem cache | 10059 | 10041 |
| 10000 | cache de 3 frames | 21 | 22 |
| 10000 | cache de 32 frames | 21 | 22 |

O M1 lê e reescreve (com `fsync`) a página inteira a cada registro. O cache
absorve as alterações no frame: 10000 inserções viram 22 escritas, uma por
página mais a página 0 e o bootstrap (`inicializa_pagina0`, que ainda é do M1).
Com 3 frames, 18 delas acontecem por expulsão e 3 no `grava_tudo()` final;
com 32, nenhuma expulsão, tudo no final. Isso vale só se o `grava_tudo()`
chegar a rodar; é o mesmo ganho do caso A, visto pelo lado bom.

O tempo medido (cerca de 120 ms → 6 ms para 1200; ~1 s → ~50 ms para 10000) vem de uma
máquina em que o `fsync` é barato. Em disco de verdade a diferença seria bem
maior, mas esse número não foi medido aqui.
