# Documentação do Script `run_stack_k6.sh`

## Objetivo
Automatizar a execução de experimentos completos, rodando um script Python de preparação/configuração e, em seguida, uma sequência de scripts K6 para testes de carga, repetindo o ciclo conforme necessário.

## Funcionamento
- O script executa, em cada ciclo:
  1. O script Python definido na variável `PY_SCRIPT`.
  2. Todos os scripts K6 listados em `STACK_K6`, na ordem definida.
- O ciclo é repetido conforme o valor de `REPS`.
- Não é necessário passar argumentos na linha de comando. Toda configuração é feita editando as variáveis no início do arquivo.

## Como configurar
Abra o arquivo `run_stack_k6.sh` e edite as variáveis:
- `PY_SCRIPT`: Caminho do script Python a ser executado (ex: `scripts/config_minima.py`)
- `STACK_K6`: Lista dos scripts K6 a serem executados (ex: `"get_users_50vus.js" "post_users_50vus.js"`)
- `REPS`: Número de repetições do ciclo completo
- `PY_ARGS`: Argumentos extras para o Python (opcional)

## Exemplo de configuração
```bash
PY_SCRIPT="scripts/config_minima.py"
STACK_K6=( "get_users_50vus.js" "post_users_50vus.js" )
REPS=3
PY_ARGS=""
```

## Execução
No terminal, execute:
```sh
./run_stack_k6.sh
```

## O que esperar
- O script irá mostrar no terminal o início e fim de cada ciclo, além de qual script está sendo executado.
- Os resultados dos testes K6 e do Python serão salvos conforme a lógica dos próprios scripts.

## Boas práticas
- Sempre revise as variáveis antes de rodar para garantir que está testando o cenário desejado.
- Mantenha o script versionado junto do projeto para rastreabilidade.
- Documente no README principal o objetivo de cada stack de teste criada.

## Observações
- O script foi pensado para uso em ambientes Linux/Mac. Para Windows, use WSL ou adapte para `.bat`.
- Certifique-se de que `python` e `k6` estejam disponíveis no PATH.

---

Dúvidas ou sugestões? Edite este arquivo ou abra uma issue no repositório.
