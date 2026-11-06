# BD_II — minidb

Projeto da disciplina de **Banco de Dados II** (ICEN/UFPA, 2026.4): construir, do zero e em Python, um
SGBD pequeno — o **minidb** — que executa um `SELECT` com `WHERE` dentro de uma transação, e que volta
ao ar consistente depois de um `kill -9` no meio do `COMMIT`.

O projeto cresce em módulos ordenados. Cada módulo vive na sua pasta, com código, testes e um
`NOTES.md` com as decisões de projeto e os números medidos.

## Módulos

| | Módulo | Tema | Pasta | Testes |
|---|---|---|---|---|
| ✅ | M1 | Página e arquivo de dados | [`m1/`](m1) | atividades (`kill.py`) |
| ✅ | M2 | Cache de páginas (buffer pool, LRU, página suja) | [`m2/`](m2) | 32 |
| ✅ | M3 | Árvore B+: busca, faixa e inserção | [`m3/`](m3) | 61 |
| ✅ | M4 | Parser, catálogo e primeira consulta | [`m4/`](m4) | 94 |
| ⬜ | M5 | Executor: `WHERE` por varredura sequencial e por índice | — | — |
| ⬜ | M6 | Transações: `BEGIN`, `COMMIT`, `ROLLBACK` | — | — |
| ⬜ | M7 | Recuperação: log de escrita antecipada (WAL) | — | — |
| ⬜ | Tópico final | Um dos 10 tópicos de aprofundamento (ver abaixo) | — | — |


## Como rodar

Requisito: Python 3.10+ (sem dependências externas).

```bash
git clone https://github.com/Emanoel-Gomes/BD_II.git
cd BD_II
make test          # roda os testes de M2, M3 e M4  (make m3, make m4, ... para um só)
make clean         # apaga __pycache__ e arquivos .db gerados
```

### O minidb no terminal (M4)

```bash
./minidb dados.db          # na raiz do repositório
CREATE TABLE aluno (id INT, matricula INT, nome CHAR(20));
OK
INSERT INTO aluno VALUES (1, 20260001, 'Ana');
OK 1
^D
./minidb dados.db          # outro processo: lê do disco o que o primeiro criou
SELECT * FROM aluno;
1|20260001|Ana
(1 linha)
```

Suportado hoje: `CREATE TABLE`, `INSERT`, `SELECT`. O `WHERE` já é analisado e conferido, mas só passa
a ser executado no M5. Ainda não há `DELETE`, `UPDATE` nem `DROP`.

### O índice B+ no terminal (M3)

```bash
cd m3
python3 indice.py aluno.db                  # cria 10000 alunos com índice e abre o prompt
python3 indice.py aluno.db busca 7500       # desce a árvore: 3 páginas lidas
python3 indice.py aluno.db varre 7500       # mesma busca sem índice: 70 páginas lidas
```

Mais comandos em [`m2/comandos_testes`](m2/comandos_testes) e [`m3/comandos_testes`](m3/comandos_testes).

## Estrutura do repositório

```text
.
├── README.md
├── Makefile                 # make test | make clean
├── .gitignore
├── minidb                   # o programa (CLI do M4): ./minidb dados.db
│
├── src/                     # o código do minidb, UMA cópia só
│   ├── minidb_m1.py         # M1  leitura/escrita de páginas
│   ├── minidb.py            # M1  cabeçalho, esquema, inserção, varredura
│   ├── cache.py             # M2  cache de páginas
│   ├── minidb_cache.py      # M2  o M1 passando pelo cache
│   ├── btree.py             # M3  árvore B+
│   ├── minidb_indice.py     # M3  índice ligado à tabela
│   ├── erros.py  sql.py     # M4  erros, tokenizador e parser
│   ├── catalogo.py          # M4  catálogo em disco
│   ├── executor.py          # M4  análise semântica e execução
│   └── apoio.py             # utilidades de teste
│
├── m1/  m2/  m3/  m4/       # um módulo por pasta: NOTES.md, testes, demos e medições
│   ├── NOTES.md             # decisões e números do módulo
│   └── atividade_N/ ...     # M1 e M2 têm uma subpasta por atividade
│
└── m5/ ...                  # próximos módulos: acrescentam arquivos em src/
```

Os módulos **evoluem o mesmo código**: o que o M3 acrescenta (`btree.py`) ou o M4 (`sql.py`...) entra em `src/`,
e cada `mN/` guarda os testes e as notas que provam aquele módulo. Os retratos de cada entrega estão nas
**tags** do git (`m1`, `m2`, `m3-m4`), com o código como ele era na época.

## Convenções

- Código compartilhado só em `src/`; nada de copiar arquivo entre pastas de módulo.
- Um `NOTES.md` por módulo (e por atividade, em M1 e M2) com decisões, números e o que o teste **não** prova.
- Testes com `unittest`, usando cache de 3 frames para forçar a expulsão.
- Arquivos `.db` e `__pycache__` não são versionados; os testes e demos recriam o que precisam.
- Commits em português, no imperativo, um assunto por commit (ex.: `M4: executor do CREATE e do INSERT`).

## Discentes

- **Emanoel Gomes** — [@Emanoel-Gomes](https://github.com/Emanoel-Gomes)
