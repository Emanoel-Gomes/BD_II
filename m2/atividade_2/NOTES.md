# NOTES.md — M2, atividade 2: política de expulsão (LRU)

Arquivos: `teste_expulsao.py` (11 testes), `comparacao.py` (números abaixo).

## Como a expulsão funciona

Além da tabela de páginas, o cache mantém um `OrderedDict` com as páginas
residentes, da mais antiga para a mais nova. Na falta com o cache cheio:

- LRU: o acerto faz `move_to_end`, e a vítima é a primeira da fila.
- **A vítima é a primeira da fila sem pin**, não simplesmente a primeira.
  Página fixada é pulada. Se todas estiverem fixadas, `CacheCheio` é
  levantada e nada é expulso.
- Frame novo → política de **inserção**: a página entra no fim da fila
  (é a mais recente).

`fifo` existe só para comparar: o acerto não mexe na fila.

## Teste 2 do slide: "com 3 frames, tocar 4 páginas expulsa a menos usada"

- `test_4_paginas_em_3_frames_expulsa_a_menos_usada`: tocar 0, 1, 2, 3 expulsa
  a 0, e `expulsoes == 1`.
- `test_trace_do_slide_1_2_3_1_4`: o mesmo trace do slide "Quando o cache enche". Depois do 4º
  acesso a fila é `[2, 3, 1]` (o acerto levou a 1 para o fim) e depois do 5º
  `[3, 1, 4]`: saiu a 2, não a 1. Com 1 acerto e 4 faltas, igual à tabela.
- `test_fifo_expulsaria_a_pagina_que_acabou_de_ser_lida`: mesmo trace, FIFO
  termina em `[2, 3, 4]`, e a 1 volta a ser falta.
- `test_capacidade_grande_nunca_expulsa`: o aviso do slide, com 64 frames.

Do "Para saber mais": `test_todas_fixadas_levanta_erro_em_vez_de_expulsar`
(o cache não perde nenhuma página no caminho, e a chamada que falhou não
deixa pin), e `acertos + faltas == chamadas`, conferido em 6 capacidades por
`test_lru_bate_com_o_modelo`, que compara o cache real com um LRU de 8 linhas
em traces aleatórios.

O cenário do slide "Fixar e soltar" também é um teste: a varredura para na página 2 (entre o
`fixa` e o `solta`), outra "consulta" toca páginas novas com o cache cheio, e a
página da varredura continua lá e o iterador segue certo. A resposta ao "quem
sai?" do slide é: qualquer uma, menos a fixada.

## O que a política e a capacidade mudam (`comparacao.py`, tabela de 21 páginas)

Trace do slide "Quando o cache enche" estendido (1, 2, 3, 1, 4, 1), 3 frames: FIFO 1 acerto e
5 faltas, LRU 2 acertos e 4 faltas.

Carga com páginas quentes (20000 acessos, 80% em 5 páginas):

| frames | FIFO | LRU |
|---:|---:|---:|
| 3 | 41,2% | 42,4% |
| 4 | 52,3% | 55,2% |
| 6 | 67,8% | 75,5% |
| 8 | 77,0% | 85,5% |
| 12 | 87,0% | 91,4% |
| 21 | 99,9% | 99,9% |

O LRU ganha quando há páginas quentes, e o ganho é maior nas capacidades
intermediárias (8 frames: 8,5 pontos). Com 21 frames os dois empatam, porque a
tabela inteira cabe e nada é expulso.

**Onde o LRU não acerta nenhuma vez.** Varredura completa da tabela (21
páginas) repetida 10 vezes:

| frames | 1–20 | 21 ou mais |
|---|---:|---:|
| acertos (LRU) | **0,0%** | 90,0% |

Com um frame a menos que a tabela, cada página é expulsa exatamente antes de
ser pedida de novo. Não é gradual: é um degrau. Isso é o problema que o
slide "Quando o cache enche" aponta (`O'Neil et al.`, LRU-K), e é o motivo de bancos reais não
usarem LRU puro: uma varredura grande varre embora as páginas quentes. No
brinquedo o efeito é pequeno, mas mensurável: com uma varredura completa a
cada 400 acessos, o LRU de 8 frames cai de 85,5% para 81,4%, e o de 12 de 91,4%
para 87,4%. Com tabelas bem maiores que o cache o efeito cresce.

## Alternativas de estrutura consideradas

- `OrderedDict` (usado): `dict` + lista duplamente ligada, tudo O(1) para
  acertar, mover para o fim e tirar do começo. A rigor é o LRU "de livro".
- Clock / second chance: um bit de referência por frame e um ponteiro. O
  acerto só liga um bit, sem mexer numa lista. Aproxima o LRU com custo menor
  no caminho de acerto (o PostgreSQL usa uma variante).
- LRU-K, 2Q, ou LRU com inserção no meio da lista (o InnoDB faz algo assim):
  a página que entrou por causa de uma varredura não vai para o "topo", e não
  expulsa as quentes.

Ficou o `OrderedDict` por ser o mais direto de provar certo (o teste contra o
modelo de referência).
