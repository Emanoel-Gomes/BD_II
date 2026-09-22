# NOTES.md — Exercício de saída (kill -9 e sync())

## O teste

Duas páginas (2 e 3) escritas com `f.write()`, processo morto com
`kill -9` antes de `close()`, sem e com `flush()+fsync()` antes do kill.

```
--- SEM sync() antes do kill -9 ---
página 2: toda 'A' (a escrita chegou inteira)
página 3: vazia/zero (a escrita não chegou)

--- COM sync() antes do kill -9 ---
página 2: toda 'A' (a escrita chegou inteira)
página 3: toda 'B' (a escrita chegou inteira)
```

## Por que mudou

`f.write()` não escreve no disco: só empilha bytes num buffer interno do
processo Python (~8192 bytes, o tamanho de duas páginas). `kill -9` mata
o processo na hora, sem chance de terminar nada — então tudo que ainda
estava só nesse buffer morre junto.

- **Sem sync():** a página 2 coube no buffer e foi parcialmente
  descarregada quando o buffer estourou ao escrever a página 3; a página
  3 ainda estava no buffer quando o processo morreu. A página 2 sobrou
  por acaso, não por garantia.
- **Com `flush()+fsync()`:** as duas páginas foram forçadas a sair do
  processo antes do kill. Como já não dependiam mais da memória do
  processo, sobreviveram as duas.

## A lição

`kill -9` só apaga o que ainda está dentro da memória do processo. Sem
`flush()`/`fsync()`, o programa não controla o que sobra — depende do
tamanho do buffer e da sorte do timing. `sync()` existe para tirar essa
sorte da equação.

## O que esse teste não prova

`kill -9` mata o processo, não a máquina — o cache do sistema
operacional continua de pé. Isso testa se o dado saiu do processo, não
se ele chegou fisicamente no disco (isso só apareceria com queda de
energia/reboot, que é o problema que `fsync()` resolve de verdade).
