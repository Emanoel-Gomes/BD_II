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

```
