# NOTES.md — M3: árvore B+

Entrega do M3: um índice B+ sobre o cache do M2, que leva de um `id` ao RID
`(página, slot)` do M1. Achar um registro desce a árvore e lê **uma** página
da tabela, sem varrê-la. Busca por chave, busca por faixa e inserção com
divisão de folha, de nó interno e de raiz. **Sem remoção** (fora do M3).

| arquivo | o que é |
|---|---|
| `btree.py` | a árvore: formato do nó na página, `busca`, `faixa`, `insere`, `confere` |
| `minidb_indice.py` | a ligação com a tabela: `insere_indexado`, `busca_registro`, `faixa_registros`, `indexa_tabela` |
| `teste_btree.py` | 61 testes, com cache de 3 frames |
| `indice.py` | o M3 no terminal: criar a tabela, `busca`, `faixa`, `insere`, `arvore` (ver abaixo) |
| `exercicios.py` | os exercícios 1 e 2 rodados na árvore de verdade, passo a passo |
| `demo_indice.py` | páginas lidas com e sem índice, e altura do índice conforme a tabela cresce |

## Usar no terminal

```
python indice.py aluno.db            # cria 10000 alunos com índice (se não existir) e abre o prompt
indice> busca 7500                   # mostra a descida, página por página
indice> varre 7500                   # o mesmo sem índice, para comparar
indice> faixa 5000 5010
indice> insere 10001 777             # tabela e índice; recusa id repetido
indice> arvore | info | ajuda | sair
python indice.py aluno.db busca 7500 # ou um comando só, sem prompt
```

`busca 7500` numa tabela de 10 mil alunos: nó interno (página 23) → folha (página 58) →
página 15 da tabela, **3 páginas lidas do disco** com cache frio. `varre 7500` lê 70.
Cada comando começa com cache frio. `insere` grava no disco ao terminar (`grava_tudo`).

M1 e M2 ficaram como estavam, com uma única mudança: `varredura` (M1) e `varre`
(M2) pulam páginas cujo `tam_registro` é 0, que são nós do índice (2 linhas
cada). Ver a decisão 4.

## Como um nó é representado dentro da página

Cada nó ocupa **exatamente uma página de 4096 bytes**, e o cabeçalho tem os
mesmos 16 bytes do M1, para uma página de nó e uma de dados começarem do mesmo jeito.

| bytes | campo | folha | nó interno |
|---|---|---|---|
| 0–1 | `n_chaves` (u16) | quantas chaves | quantas chaves |
| 2–3 | marca (u16) | **sempre 0** | **sempre 0** |
| 4–7 | `num_pagina` (u32) | a própria página | a própria página |
| 8 | tipo (u8) | 1 | 2 |
| 9–11 | reservado | 0 | 0 |
| 12–15 | `extra` (u32) | **próxima folha** (0 = última) | **filho 0**, o mais à esquerda |
| 16… | entradas | `n` × (chave i32, página u32, slot u16) = 10 bytes | `n` × (chave i32, filho u32) = 8 bytes |

- **Capacidade:** `(4096 − 16) // 10` = **408 chaves** na folha e
  `(4096 − 16) // 8` = **510** no nó interno. O nó interno é mais denso porque
  não carrega o RID, que é o argumento do slide para tirar o dado dos nós internos.
- **No nó interno** a entrada `i` guarda a chave `k_i` e o filho `i+1`; o filho 0
  fica no `extra`. Com `n` chaves são `n+1` filhos. À esquerda de `k_i` ficam
  chaves menores que `k_i`; `k_i` e as maiores vão para a direita.
- **Como o M1 distingue um nó de uma página de dados:** nos dados, os bytes 2–3
  são o `tam_registro`, que nunca é 0. Nos nós são sempre 0. É a marca que
  `varre`/`varredura` testam para pular o nó, e `decodifica_no` testa ao
  contrário (marca 0, tipo 1 ou 2, e `num_pagina` igual à página pedida): se a
  página não é um nó, **falha alto** em vez de decodificar lixo.
- **Onde fica a raiz:** na página 0, depois do que o M1 já usa (que termina no
  byte 17): bytes 18–21 = página da raiz (0 = a tabela ainda não tem índice;
  serve de "nulo" porque a página 0 nunca é nó) e 22–23 = `max_chaves` (0 = o que
  cabe na página). Quando a raiz divide, só esse campo muda.
- **A sobra da página é zerada** a cada gravação, então o mesmo nó sempre dá os
  mesmos bytes (testado), e nada de um nó antigo vaza no seguinte.
- **Na memória** a página vira um objeto `No` (listas de chaves, RIDs e filhos)
  em `decodifica_no`, e volta em `codifica_no`, no mesmo buffer do frame do cache.

## Decisões

**1. Decodificar o nó inteiro em vez de mexer nos bytes no lugar.** `_le` fixa a
página, copia para um `No`, e solta. Isso deixa `busca` e `insere` iguais ao
pseudocódigo do slide (`bisect`, `insert`, fatias), e só uma página fica
fixada por vez. O custo é decodificar até 408 entradas a cada nó visitado.
Em Python: 100 mil inserções em ordem levam ~9 s. Para um banco de verdade seria
ler o campo direto do buffer, mas aqui o gargalo desejado são as páginas, e
não os microssegundos.

**2. Folha copia o separador, nó interno o move.** Ao dividir uma folha
`[a b | c d]`, o `c` **continua** na folha da direita e uma cópia sobe para
o pai (os dados só existem nas folhas). Ao dividir um nó interno, a chave do meio
**sobe e sai** dos dois filhos. É a regra que o exercício 2 testa. A busca usa
`bisect_right`, então chave igual ao separador desce pela direita, que é onde a
folha a guarda. Um `bisect_left` aqui faria a árvore errar em toda chave que é
separador (um dos mutantes testados).

**3. Divisão ao meio, e o que isso custa.** Com 4 chaves em nó de 3 a divisão dá
2 e 2. Com 409 numa folha dá 204 e 205. Inserir em ordem crescente (o caso
dos ids de um aluno novo) deixa as folhas **pela metade**: medi 588 folhas
para 120 mil chaves, ~204 por folha de 408. A altura passa de 2 para 3
entre 100 mil e 120 mil chaves (medido); a conta é 511 folhas × ~204 chaves ≈ 104 mil,
em vez das ~208 mil (511 × 408) que caberiam com folhas cheias. Dividir
assimetricamente quando a inserção é sempre no fim (como bancos fazem) ocuparia
melhor, e ficou fora.

**4. Índice e tabela no mesmo arquivo.** Os nós usam `_aloca` sobre o contador de
páginas da página 0, o mesmo do `aloca` do M1, então cresce o mesmo arquivo e
nenhum número de página colide. A consequência é que uma varredura da
tabela passa pelas páginas do índice (as fixa só para ver que a marca é 0 e
pular). Medido com 10 mil alunos: a tabela tem 21 páginas, **o arquivo com índice tem 71**
(50 de índice), e com 32 frames a varredura lê **71 páginas toda vez**. O dimensionamento do M2
("o cache tem que cobrir a tabela inteira") agora tem que cobrir tabela + índice, ou
o índice ir para um arquivo separado. Para as buscas isso não pesa: 800 buscas
aleatórias com 32 frames, já aquecido, fizeram **0,96 leitura de disco por busca**
(67,8% de acertos), porque a raiz e as folhas quentes ficam no cache.

**5. Chave única, int32.** É o `id`. A duplicata é recusada **antes de qualquer
alteração**: em `insere`, a folha é conferida antes de mexer, e `insere_indexado`
chama `busca` **antes** de gravar o registro na tabela. Se fosse depois, o
registro ficaria gravado e invisível ao índice (testado: a tabela não ganha
nada). Chaves fora de 32 bits e RID fora de `(u32, u16)` também são recusados
antes, em vez de estourar no `struct.pack` no meio de uma divisão, com a
árvore pela metade.

**6. No máximo 2 páginas fixadas ao mesmo tempo**, em qualquer altura. Por isso
a árvore roda com um cache de 3 frames (e até de 2, testado), e nenhuma operação
deixa página fixada, nem quando dá erro (`cache.fixadas()` volta a 0, também testado).
Uso `with cache.usa(...)` em todo lugar, como o M2 pede.

**7. `max_chaves`.** `ArvoreBMais.cria(cache, max_chaves=3)` limita as chaves por
nó, para reproduzir os exercícios ("no máximo 3 chaves por nó") e testar divisões
com 20 chaves em vez de 20 mil. Fica gravado na página 0, então ao reabrir a
árvore continua com o mesmo limite. Sem ele, vale o que cabe na página (408/510).

## Respostas ao tema

**Achar um registro sem ler a tabela.** Medido com a tabela do M1 de 10 mil
alunos (`demo_indice.py`, cache frio, 4096 bytes por página):

| consulta | sem índice | com índice |
|---|---|---|
| `id = 7500` | **21** leituras de disco (a tabela inteira) | **3** (2 do índice + 1 da tabela) |
| `id = 10001` (não existe) | 21 | 2 (nem chega à tabela) |
| `id` entre 5000 e 5099 | 21 | **3** (2 do índice + 1 da tabela, os 100 caem na mesma página) |

A altura do índice é o que uma busca custa. Medida com nó de página inteira e
inserção em ordem: 1 nível até 408 chaves, 2 níveis com 5 mil e com 100 mil,
**3 níveis com 120 mil**. A conta para os 10 milhões do slide (estimativa, não medida,
com folhas pela metade): ~49 mil folhas, ~190 nós internos, uma raiz, ou seja,
**3 níveis, 3 leituras**, contra as 24 de uma árvore binária e as ~20 mil de uma varredura.

**Árvore B e B+.** Na B cada chave aparece uma vez, com o dado, em qualquer
nível. Na B+ o dado só está nas folhas, e os nós internos só têm chaves para guiar,
o que dá mais filhos por página (510 contra 408) e deixa as folhas encadeadas
para ler faixas em ordem. É isso que `faixa` faz: desce **uma vez** até a folha do
mínimo e segue o encadeamento, sem voltar à raiz, e para na primeira chave
acima do máximo.

**Busca e inserção sem divisão (aula de 08/10) e com divisão (13/10).** `insere`
desce guardando o caminho (nó interno, filho escolhido); se a folha cabe,
grava e acabou. Se estoura, divide, e sobe pelo caminho colocando `(separador, filho novo)`
em cada pai, dividindo o pai também se estourar. Se a divisão passar da raiz, uma raiz nova
com 1 chave e 2 filhos, e a altura sobe em 1. **Todas as folhas continuam na mesma
profundidade** porque a árvore só cresce por cima.

## Exercícios 1 e 2 (`python exercicios.py` mostra isto rodando)

Máximo de 3 chaves por nó.

**Exercício 1** — inserir 10, 20, 5, 30, 25, 40, 15:

```
10, 20, 5        [5 10 20]                     cabe numa folha, que é a raiz
30 (divisão 1)   [20]                          o 20 sobe como cópia
                 [5 10] -> [20 30]
25               [20]
                 [5 10] -> [20 25 30]          cabe
40 (divisão 2)   [20 30]                       o 30 sobe como cópia, a raiz tem espaço
                 [5 10] -> [20 25] -> [30 40]
15               [20 30]
                 [5 10 15] -> [20 25] -> [30 40]   cabe, sem divisão
```

Altura ao fim: **2**. A busca por 25 lê **2 páginas** (raiz e a folha `[20 25]`).

**Exercício 2** — a partir dessa árvore, 35, 45, 50, 55:

```
35               [20 30]     [5 10 15] -> [20 25] -> [30 35 40]             cabe
45 (divisão 1)   [20 30 40]  [5 10 15] -> [20 25] -> [30 35] -> [40 45]     o 40 sobe (cópia)
50               [20 30 40]  [5 10 15] -> [20 25] -> [30 35] -> [40 45 50]  cabe
55 (divisões 2 e 3), a folha [40 45 50 55] divide e o 50 sobe; a raiz ficaria [20 30 40 50],
                 não cabe, divide, e o 40 SOBE (sai dos filhos) para uma raiz nova:

                                  [40]
                          [20 30]      [50]
        [5 10 15] -> [20 25] -> [30 35] -> [40 45] -> [50 55]
```

Altura ao fim: **3**. A divisão que chega à raiz é a do 55. `WHERE id BETWEEN 12
AND 33` lê **5 páginas**: raiz, nó interno `[20 30]`, e as folhas `[5 10 15]`,
`[20 25]` e `[30 35]` (a última mostra que o 35 passou do 33). Se o máximo
fosse 24, leria 4; se fosse 25, o último valor da folha `[20 25]`,
leria 5 (só a folha seguinte prova que acabou). Os dois estão nos testes.

Ao dividir `[20 30 40 50]` subir o 30 em vez do 40 também seria uma árvore B+
válida (`[20]` e `[40 50]`). O código sobe o 40 (`len // 2`), o mesmo critério
das folhas, que deixa o lado direito com a chave que sobe.
