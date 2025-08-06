#!/bin/bash
# Script para executar múltiplos scripts Python variando o teste K6 passado como argumento
# Configure a variável TESTES_K6 para definir quais scripts de teste executar

set -e

# === CONFIGURAÇÃO INÍCIO ===
PY_SCRIPT="scripts/config_minima.py"   # Script Python a ser executado
APP_URL="http://localhost:3000"        # URL da aplicação
STACKS="node-postgres"                 # Stacks a testar
PASTA_K6="tests k6"                    # Pasta correta dos scripts K6
# Lista de scripts de teste K6 a serem usados
TESTES_K6=(
    "get_users_50vus.js"
    "post_users_50vus.js"
    "put_users_50vus.js"
)
# === CONFIGURAÇÃO FIM ===

for TESTE_K6 in "${TESTES_K6[@]}"; do
    CMD="python $PY_SCRIPT --app_url $APP_URL --stacks $STACKS --k6_script \"$PASTA_K6/$TESTE_K6\" --repeticoes 5"
    echo "[STACK] Executando: $CMD"
    eval $CMD
    echo "[STACK] Fim do comando: $CMD"
done

echo "[STACK] Execução completa."
