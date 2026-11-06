# Atalhos para rodar os testes de cada módulo.  Uso: make test | make m3 | make clean
PY ?= python3

.PHONY: test m2 m3 m4 clean

test: m2 m3 m4

m2:
	cd m2 && $(PY) atividade_1/teste_acerto.py && $(PY) atividade_2/teste_expulsao.py && $(PY) atividade_3/teste_suja.py

m3:
	cd m3 && $(PY) teste_btree.py

m4:
	cd m4 && $(PY) teste_sql.py

clean:
	find . -name __pycache__ -not -path './.git/*' -prune -exec rm -rf {} +
	find . -name '*.db' -not -path './.git/*' -delete
