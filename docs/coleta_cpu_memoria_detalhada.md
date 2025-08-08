# Documentação detalhada: Coleta de CPU e Memória via SSH (host)

## Resumo
Este documento descreve, em detalhes técnicos e práticos, como é realizada a coleta de métricas de CPU e memória do host durante os testes de carga, garantindo alinhamento com o que é exibido no htop e robustez contra erros de parsing.

---

## Coleta de CPU (host)

- **Comando utilizado:**
  ```bash
  LANG=C top -bn1 | grep 'Cpu(s)'
  ```
- **Racional:**
  - O comando `top` com `LANG=C` garante saída em inglês, padronizando o formato.
  - A linha capturada contém algo como:
    ```
    %Cpu(s):  2.0 us,  1.0 sy,  0.0 ni, 97.0 id,  0.0 wa, ...
    ```
  - O valor de interesse é o campo `id` (idle), pois o uso real de CPU é `100 - idle`.
- **Parsing:**
  - Utiliza regex robusto para capturar apenas números válidos antes de `id`.
  - Exemplo de regex: `(\d+[\.,]?\d*)\s*id`
  - O valor capturado é convertido para float após substituir vírgula por ponto.
  - Se o valor não for um número válido, a amostra é descartada e um aviso é logado.
- **Exemplo de saída e cálculo:**
  - Saída: `%Cpu(s):  2.0 us,  1.0 sy,  0.0 ni, 97.0 id, ...`
  - Captura: `idle = 97.0`
  - Uso real: `cpu_val = 100.0 - idle = 3.0%`

---

## Coleta de Memória (host)

- **Comando utilizado:**
  ```bash
  free -m | grep Mem
  ```

- **Racional:**
  - O comando `free -m` retorna uma linha como:
    ```
    Mem:  7977  7890   87   123   456   6789
    ```
    (total, used, free, shared, buff/cache, available)
  - O valor exibido como "usado" no htop corresponde a `total - free - buff/cache` do free.

- **Parsing e cálculo:**
  - O script extrai as colunas:
    - `total = parts[1]`
    - `free = parts[3]`
    - `buff/cache = parts[5]`
    - `mem_val = total - free - buff/cache`
  - Isso garante que a métrica de memória coletada reflete o valor real de uso, igual ao htop.

- **Exemplo de saída e cálculo:**
  - Saída: `Mem:  7977  7890   87   123   456   6789`
  - Cálculo: `mem_val = 7977 - 87 - 456 = 7434 MB`

---

## Robustez e Tratamento de Erros
- Se o parsing de CPU ou memória falhar, a amostra é descartada e um aviso é logado.
- O script só registra amostras válidas, evitando distorções nas médias.
- Logs de erro incluem a saída original do comando para facilitar diagnóstico.

---

## Alinhamento com htop
- O valor de CPU reportado é o uso real (100 - idle), igual ao campo superior do htop.
- O valor de memória reportado é o "usado real" (used - buff/cache), igual ao campo "used" do htop.

---

## Limitações
- Pequenas diferenças podem ocorrer devido ao tempo de amostragem e atualização dos comandos.
- O script depende do formato padrão dos comandos Linux; distribuições muito customizadas podem exigir ajustes.

---

## Exemplo de JSON gerado

## Unidades e formatos dos campos no JSON de métricas

- **host.cpu**: lista de valores em porcentagem de uso da CPU do host (float, 0–100). Exemplo: `[3.0, 2.5, 4.1, ...]`
- **host.memoria**: lista de valores em megabytes (MB) de memória usada real do host (float). Exemplo: `[7434, 7432, 7435, ...]`
- **backend.cpu**: lista de valores em porcentagem de uso da CPU do container backend (float, 0–100). Exemplo: `[2.1, 3.5, ...]`
- **backend.memoria**: lista de valores em megabytes (MB) de memória usada pelo container backend (float). Exemplo: `[35.3, 36.1, ...]`
- **banco_de_dados.cpu**: lista de valores em porcentagem de uso da CPU do container de banco de dados (float, 0–100). Exemplo: `[1.2, 1.5, ...]`
- **banco_de_dados.memoria**: lista de valores em megabytes (MB) de memória usada pelo container de banco de dados (float). Exemplo: `[25.9, 26.0, ...]`
- **media**: cada subcampo traz a média dos valores acima, na mesma unidade.

> Todos os valores de memória são sempre em MB (megabytes), mesmo que a coleta original venha em MiB (1 MiB ≈ 1.0486 MB, mas o script armazena o valor numérico como float para facilitar comparação e análise).

## Exemplo de JSON gerado
```json
{
  "host": {
    "cpu": [3.0, 2.5, 4.1, ...],
    "memoria": [7434, 7432, 7435, ...],
    "media": {
      "cpu": 3.2,
      "memoria": 7433.7
    }
  },
  "backend": {
    "cpu": [2.1, 3.5, ...],
    "memoria": [35.3, 36.1, ...],
    "media": {
      "cpu": 2.8,
      "memoria": 35.7
    }
  },
  "banco_de_dados": {
    "cpu": [1.2, 1.5, ...],
    "memoria": [25.9, 26.0, ...],
    "media": {
      "cpu": 1.35,
      "memoria": 25.95
    }
  }
}
```

---

## Referências
- [htop documentation](https://htop.dev/)
- [man top](https://man7.org/linux/man-pages/man1/top.1.html)
- [man free](https://man7.org/linux/man-pages/man1/free.1.html)
