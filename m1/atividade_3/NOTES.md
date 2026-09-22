## Fechamento do M1 — páginas e varredura

Inseri 1200 registros do esquema `aluno` (id + matrícula, 8 bytes cada)
usando `insere()`. Resultado:

- **Páginas no arquivo:** 4 (1 página de metadados + 3 páginas de dados)
- **Leituras que a varredura faz:** 3

## Por que esses números

Cada página tem 4080 bytes livres para registros (4096 − 16 de
cabeçalho). Com registros de 8 bytes, cabem 510 por página. 1200
registros precisam de 3 páginas de dados (510 + 510 + 180), mais a
página 0 de metadados = 4 páginas no total.

A varredura (`varredura()`) chama `le_pagina` uma vez por página de
dados, nunca uma vez por registro — por isso 3 leituras, não 1200. Isso
vale mesmo que eu procure só 1 registro entre os 1200: sem índice, a
varredura lê as 3 páginas inteiras de qualquer jeito. É esse custo que
o índice (M3) existe para evitar.
