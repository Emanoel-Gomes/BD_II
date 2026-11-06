# NOTES.md — M4: do texto à árvore, e a primeira consulta que roda

<<<<<<< HEAD
> **Layout do repositório (atualizado).** O código que os módulos compartilham mora em
> [`../src/`](../src) (uma única cópia: `minidb_m1.py`, `minidb.py`, `cache.py`, `minidb_cache.py`, `apoio.py`,
> `btree.py`, `minidb_indice.py`, `sql.py`, `catalogo.py`, `executor.py`, `erros.py`). Esta pasta guarda só o que é
> deste módulo: testes, demos e notas. Onde o texto abaixo diz "esta pasta" para um desses arquivos, leia `src/`.
> O programa `minidb` fica na raiz do repositório (`./minidb dados.db`), e a árvore B+ (`btree.py`) já está em `src/`, ainda sem uso no M4.
> O retrato original, com as cópias por pasta, está nas tags `m1`, `m2` e `m3-m4` do git.

Entrega do M4: o minidb deixa de ser uma biblioteca e passa a ser um programa.
Recebe SQL pela entrada padrão, uma instrução por linha, responde, e guarda
tudo no arquivo. A meta do slide roda palavra por palavra, **em dois
processos** (o segundo lê do disco o que o primeiro criou):

=======
Entrega do M4
>>>>>>> f0e0ea7df3d6976882a14939eff8a775a76e0131
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
