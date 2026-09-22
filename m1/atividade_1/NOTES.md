# NOTES.md — M1: Página e arquivo de dados

## Onde o registro foi parar

O registro gravado no slot 0 da página 2 (`id=1`, `matricula=20260001`) foi
escrito no **byte 8208** do arquivo `dados.db`.

Cálculo do offset:

- a página 2 começa no byte `2 * 4096 = 8192`;
- o cabeçalho da página ocupa os primeiros 16 bytes;
- o slot 0 vem logo depois do cabeçalho: `8192 + 16 = 8208`.

Conferido no disco com:

```
od -A d -t x1z -j 8208 -N 8 dados.db
```

que devolve `01 00 00 00 a1 24 35 01` — `1` e `20260001` em little-endian,
batendo com o que `le_registro_pagina2()` leu de volta depois de fechar e
reabrir o arquivo.

## Decisão de projeto mais difícil

A parte que mais exigiu pensar não foi escrever bytes no arquivo — foi
decidir **o que fazer quando a escrita falha**. A tentação inicial era só
deixar o `f.write()` estourar e propagar a exceção sem mais nada. Isso
funciona, mas esconde em qual página e em qual arquivo o problema
aconteceu, o que é exatamente a informação que falta quando alguém precisa
depurar um SGBD de verdade.

A solução foi separar dois tipos de falha:

1. **Falha do sistema operacional** (`OSError`): capturada em
   `escreve_pagina` e `le_pagina`, onde ela é reportada com uma mensagem
   `[erro]` dizendo a página e o arquivo envolvidos, e só depois
   relançada com `raise` — ou seja, o chamador ainda fica sabendo que a
   operação falhou, mas com mais contexto no caminho.
2. **Escrita parcial**, quando `f.write()` devolve menos bytes do que
   `PAGE_SIZE`: isso não levanta exceção nenhuma em Python, então sem uma
   checagem explícita (`if escritos != PAGE_SIZE`) esse tipo de corrupção
   passaria batido silenciosamente.

Para provar que esse caminho de erro realmente funciona (e não só existe
no código, sem nunca ser exercitado), adicionei `demonstra_falha()`: ela
abre `dados.db` em modo somente-leitura (`"rb"`) e tenta escrever nele.
O SO recusa a escrita, `escreve_pagina` pega o `OSError`, imprime a
mensagem de erro com página e arquivo, e relança — exatamente o
comportamento que o try/except foi desenhado para ter.

Outra decisão menor, mas relacionada: `_garante_tamanho()` preenche o
arquivo com zeros até a página pedida existir, em vez de simplesmente
falhar quando alguém pede uma página que ainda não foi escrita (como a
página 2 num arquivo novo, vazio). Isso evita um `seek` além do fim do
arquivo virar um estado inconsistente, mas significa que "ler uma página
que nunca foi escrita" e "ler uma página zerada de propósito" ficam
indistinguíveis por enquanto — um problema que o M2 (cache de páginas)
provavelmente vai precisar resolver de verdade.
