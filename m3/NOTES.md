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
