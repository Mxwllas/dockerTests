#!/bin/bash
# Script para executar uma stack de testes Python + K6 em sequência
# Configure as variáveis abaixo conforme necessário e execute: ./run_stack_k6.sh

set -e

# === CONFIGURAÇÃO INÍCIO ===
PY_SCRIPT="scripts/config_minima.py"   # Caminho do script Python
STACK_K6=( \
    "get_users_50vus.js" \
    "post_users_50vus.js" \
    "put_users_50vus.js" \
) # Lista de scripts K6 (adicione/remova conforme necessário)
REPS=3                                 # Número de repetições da stack
PY_ARGS=""                            # Argumentos extras para o script Python (opcional)
# === CONFIGURAÇÃO FIM ===

for i in $(seq 1 $REPS); do
    echo "[STACK] Execução $i/$REPS do script Python: $PY_SCRIPT $PY_ARGS"
    python "$PY_SCRIPT" $PY_ARGS
    for k6file in "${STACK_K6[@]}"; do
        echo "[STACK] Execução do teste K6: $k6file"
        k6 run "tests k6/$k6file"
    done
    echo "[STACK] Fim da iteração $i"
done

echo "[STACK] Execução completa."
