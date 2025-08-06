# Documentação do Projeto dockerTests

## Visão Geral
Este projeto automatiza testes de performance em stacks Docker, coletando métricas de uso de CPU e memória do host e dos containers durante a execução dos testes.

## Estrutura de Pastas
```
├── scripts/                # Scripts Python e utilitários
├── tests k6/               # Scripts de teste K6
├── docs/                   # Documentação do projeto
├── config.json             # Configurações gerais
├── ssh_config_example.json # Exemplo de configuração SSH
├── README.md               # Instruções rápidas
```


## Principais Scripts

## Principais Scripts
- `main.py`: Funções utilitárias para orquestração dos testes, criação/remoção de containers, execução do K6, extração de métricas e controle do fluxo dos experimentos. Usado como módulo auxiliar.
- `config_minima.py`: ÚNICO script que pode variar recursos do banco e backend. Usa Prometheus para coletar métricas detalhadas dos containers.
- `config_fixed_backend_prometheus.py`: Varia apenas recursos do backend, mantendo o banco fixo. Coleta métricas via Prometheus.
- `config_fixed_backend_ssh.py`: Varia apenas recursos do backend, mantendo o banco fixo. Coleta métricas via SSH inline, lendo credenciais do arquivo JSON.


## Como configurar o acesso SSH
  "ssh_password": "sua_senha"
}
Exemplo:
```
python scripts/config_minima_ssh_inline.py \
  --app_url http://143.198.78.77/ \
  --stacks node-postgres,java-postgres \
  --k6_script "tests k6/consulta_intensiva.js" \
  --repeticoes 3
```

## Saída dos Resultados
- Os resultados de cada teste são salvos em arquivos JSON na pasta `resultados/`.
- Cada arquivo contém:
  - Métricas do K6
  - Informações do container
  - Métricas de CPU/RAM do host e containers durante o teste (amostras e médias)

## Requisitos
- Python 3.8+
- Bibliotecas: `paramiko`, `playwright`, `requests`
- Docker instalado no host remoto

## Segurança
- Nunca compartilhe sua senha ou chave privada SSH publicamente.
- O arquivo `ssh_config.json` deve ser mantido seguro e fora do controle de versão.

## Dúvidas
Abra uma issue ou consulte este diretório para mais detalhes.
