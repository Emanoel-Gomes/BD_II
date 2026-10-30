"""
erros.py - M4: um tipo de erro por etapa do caminho de uma consulta.

    1 tokenizador         ErroLexico      "o texto não vira token"
    2 parser              ErroSintatico   "os tokens estão na ordem errada"
    3 análise semântica   ErroSemantico   "a ordem está certa, mas não faz sentido
                                           para ESTE banco" (precisa do catálogo)
    4 execução            ErroNaoImplementado (o que o M4 ainda não executa)

Misturar as três primeiras é o defeito mais comum do módulo. Por isso cada
uma tem a sua classe e a sua etiqueta na mensagem: quem lê "ERRO sintático"
sabe em que etapa olhar.
"""


class ErroSQL(Exception):
    etapa = "sql"


class ErroLexico(ErroSQL):
    etapa = "léxico"


class ErroSintatico(ErroSQL):
    etapa = "sintático"


class ErroSemantico(ErroSQL):
    etapa = "semântico"


class ErroNaoImplementado(ErroSQL):
    etapa = "não implementado"
