# Coleta de Métricas via SSH

## Objetivo

Descrever o procedimento para coletar métricas dos containers (backend e banco de dados) e do host durante a execução dos testes de carga com o k6, utilizando SSH. Os resultados devem ser armazenados em formato JSON.

---

## Requisitos

- As métricas devem ser coletadas tanto dos containers (backend e banco de dados) quanto do host.
- A coleta deve ocorrer durante todo o período em que o teste k6 estiver rodando.
- A coleta deve ser feita via SSH, de forma direta e eficiente.
- Os resultados da coleta devem ser armazenados em um arquivo JSON.

---

## Passos para Coleta

1. **Identificação dos Alvos de Coleta**
   - Host principal (máquina física ou VM).
   - Containers Docker: backend e banco de dados.

2. **Comandos de Coleta**
   - Para o host, utilize comandos como `top`, `vmstat`, `iostat`, `free`, `df`, etc.
   - Para containers, utilize `docker stats --no-stream <container>` ou comandos equivalentes via `docker exec`.

3. **Execução via SSH**
   - Utilize SSH para executar os comandos remotamente:
     ```bash
     ssh usuario@host "comando_de_coleta"
     ```
   - Para containers:
     ```bash
     ssh usuario@host "docker exec <container> comando_de_coleta"
     ```

4. **Sincronização com o Teste k6**
   - Inicie a coleta imediatamente antes de iniciar o teste k6.
   - Mantenha a coleta ativa durante toda a execução do teste.
   - Finalize a coleta logo após o término do teste.

5. **Armazenamento dos Resultados**
   - Capture a saída dos comandos em formato estruturado (preferencialmente JSON).
   - Exemplo de redirecionamento:
     ```bash
     ssh usuario@host "comando_de_coleta | ferramenta_para_json" > metricas_host.json
     ```
   - Para múltiplos alvos, armazene cada resultado em um campo distinto dentro de um único arquivo JSON ou em arquivos separados, conforme necessidade.

6. **Exemplo de Estrutura de JSON**
   ```json
   {
     "host": {
       "cpu": {...},
       "memoria": {...},
       "media": {
         "cpu": "...",
         "memoria": "..."
       }
     },
     "backend": {
       "cpu": {...},
       "memoria": {...},
       "media": {
         "cpu": "...",
         "memoria": "..."
       }
     },
     "banco_de_dados": {
       "cpu": {...},
       "memoria": {...},
       "media": {
         "cpu": "...",
         "memoria": "..."
       }
     }
   }
   ```
   > **Nota:** O campo `media` deve conter a média dos recursos monitorados durante todo o período do teste.

---

## Observações

- Certifique-se de que o usuário SSH tenha permissões adequadas para executar os comandos necessários.
- Automatize o processo para garantir a coleta contínua durante o teste.
- Valide a integridade dos dados coletados antes de utilizá-los para análise.
- Certifique-se de calcular e registrar a média dos recursos no JSON final, considerando todo o intervalo do teste.

