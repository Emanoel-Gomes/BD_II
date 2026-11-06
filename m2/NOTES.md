# NOTES.md — M2: cache de páginas (buffer pool)

> **Layout do repositório (atualizado).** O código que os módulos compartilham mora em
> [`../src/`](../src) (uma única cópia: `minidb_m1.py`, `minidb.py`, `cache.py`, `minidb_cache.py`, `apoio.py`,
> `btree.py`, `minidb_indice.py`, `sql.py`, `catalogo.py`, `executor.py`, `erros.py`). Esta pasta guarda só o que é
> deste módulo: testes, demos e notas. Onde o texto abaixo diz "esta pasta" para um desses arquivos, leia `src/`.
> O retrato original, com as cópias por pasta, está nas tags `m1`, `m2` e `m3-m4` do git.

Entrega do M2: um cache de páginas entre o resto do minidb e o arquivo do M1,
com `fixa`/`solta`, LRU, contadores de acerto e falta, bit de sujeira e
gravação na expulsão.

| atividade | tema | teste do slide "Como saber que está certo" |
|---|---|---|
| `atividade_1` | estrutura, acerto e falta, fixar e soltar | 1. Acerto |
| `atividade_2` | política de expulsão (LRU vs FIFO) | 2. Expulsão |
| `atividade_3` | página suja, kill -9, integração com o M1 | 3. Suja |

```
