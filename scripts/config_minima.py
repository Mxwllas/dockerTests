# Script para encontrar configuração mínima de CPU/RAM por stack
# Uso: python3 scripts/config_minima.py --app_url <URL_DA_APP> --stacks node-postgres,java-postgres,node-mysql --k6_script tests/consulta_intensiva.js
# Script para encontrar configuração mínima de CPU/RAM por stack
# Uso: python3 scripts/config_minima.py --app_url http://143.198.78.77/ --stacks node-postgres,java-postgres,node-mysql --k6_script tests/consulta_intensiva.js

import os
import sys
import time
import json
import argparse
from statistics import mean
from datetime import datetime, timezone, timedelta
import requests
import re

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import (
    iniciar_navegador, acessar_aplicacao, criar_container, aguardar_container_ativo,
    extrair_url_container, executar_k6, excluir_container_ate_sucesso, extrair_info_container
)

# Parâmetros globais de limites e incrementos

CPU_MIN = 0.5
RAM_MIN = 1024



CPU_INC = 0.1
RAM_INC = 128  # O incremento será dobrado a cada ciclo

CPU_MAX = 1
RAM_MAX = 1024

LIMITE_HTTP_REQ_FAILED = 0.01  # 1%

TZ = timezone(timedelta(hours=-3))  # UTC-3


def carregar_config():
    with open(os.path.join(os.path.dirname(__file__), '../config.json'), 'r') as f:
        return json.load(f)


def consultar_media_prometheus(prom_url, container_id, inicio, fim):
    from datetime import timezone
    inicio_utc = inicio.astimezone(timezone.utc)
    fim_utc = fim.astimezone(timezone.utc)
    intervalo = int((fim_utc - inicio_utc).total_seconds())
    if intervalo < 1:
        intervalo = 1
    clean_id = container_id.replace('-', '')
    prom_id = f"/system.slice/docker-{clean_id}.scope"
    query_mem = f'avg_over_time(container_memory_usage_bytes{{id="{prom_id}"}}[{intervalo}s])'
    query_cpu = f'avg_over_time(rate(container_cpu_usage_seconds_total{{id="{prom_id}"}}[1m])[{intervalo}s:1m])'
    params = {
        'query': query_mem,
        'time': fim_utc.isoformat().replace('+00:00', 'Z')
    }
    mem_resp = requests.get(f"{prom_url}/api/v1/query", params=params).json()
    params['query'] = query_cpu
    cpu_resp = requests.get(f"{prom_url}/api/v1/query", params=params).json()
    mem_val = float(mem_resp['data']['result'][0]['value'][1]) if mem_resp['data']['result'] else None
    cpu_val = float(cpu_resp['data']['result'][0]['value'][1]) if cpu_resp['data']['result'] else None
    print(f"[Prometheus] Query id: {prom_id} | Mem: {mem_val} | CPU: {cpu_val}")
    return {'mem_avg_bytes': mem_val, 'cpu_avg_cores': cpu_val, 'id_used': prom_id}


def consultar_media_prometheus_nome(prom_url, container_name, inicio, fim):
    from datetime import timezone
    inicio_utc = inicio.astimezone(timezone.utc)
    fim_utc = fim.astimezone(timezone.utc)
    intervalo = int((fim_utc - inicio_utc).total_seconds())
    if intervalo < 1:
        intervalo = 1
    # Garante um intervalo mínimo de 30s para a média
    intervalo = max(intervalo, 30)
    query_mem = f'avg_over_time(container_memory_usage_bytes{{name="{container_name}"}}[{intervalo}s])'
    # Para CPU, tenta média e valor instantâneo
    query_cpu_avg = f'avg_over_time(rate(container_cpu_usage_seconds_total{{name="{container_name}"}}[10s])[{intervalo}s:10s])'
    query_cpu_inst = f'container_cpu_usage_seconds_total{{name="{container_name}"}}'
    params = {
        'query': query_mem,
        'time': fim_utc.isoformat().replace('+00:00', 'Z')
    }
    mem_resp = requests.get(f"{prom_url}/api/v1/query", params=params).json()
    params['query'] = query_cpu_avg
    cpu_resp = requests.get(f"{prom_url}/api/v1/query", params=params).json()
    cpu_val = float(cpu_resp['data']['result'][0]['value'][1]) if cpu_resp['data']['result'] else None
    # Se não conseguir média, tenta valor instantâneo
    if cpu_val is None:
        params['query'] = query_cpu_inst
        cpu_inst_resp = requests.get(f"{prom_url}/api/v1/query", params=params).json()
        cpu_val = float(cpu_inst_resp['data']['result'][0]['value'][1]) if cpu_inst_resp['data']['result'] else None
    mem_val = float(mem_resp['data']['result'][0]['value'][1]) if mem_resp['data']['result'] else None
    print(f"[Prometheus] Query name: {container_name} | Mem: {mem_val} | CPU: {cpu_val}")
    return {'mem_avg_bytes': mem_val, 'cpu_avg_cores': cpu_val, 'name_used': container_name}


def extrair_thresholds_k6(k6_script_path):
    with open(k6_script_path, 'r') as f:
        content = f.read()
    thresholds = {}
    # Extrai http_req_failed: ['rate<VALOR']
    m = re.search(r"http_req_failed\s*:\s*\[\s*'rate<([0-9.]+)'", content)
    if m:
        thresholds['http_req_failed'] = float(m.group(1))
    # Extrai http_req_duration: ['p(95)<VALOR']
    m = re.search(r"http_req_duration\s*:\s*\[\s*'p\\(95\\)<([0-9.]+)'", content)
    if m:
        thresholds['http_req_duration_p95'] = float(m.group(1))
    return thresholds


def testar_configuracao(stack, cpu, ram, k6_script, page, app_url, repeticoes):
    resultados = []
    nome_teste = os.path.splitext(os.path.basename(k6_script))[0]
    for i in range(repeticoes):
        nome = f"{i+1}.{nome_teste}-{stack}-{cpu}_{ram}"
        cenario = {
            "nome": nome,
            "backend": stack,
            "backend_cpu": cpu,
            "backend_ram": ram,
            "db_cpu": cpu,
            "db_ram": ram,
            "k6_script": k6_script
        }
        inicio = datetime.now(TZ)
        container_info = None
        tentativas_id = 10
        try:
            criar_container(page, cenario)
            aguardar_container_ativo(page)
            base_url = extrair_url_container(page)
            for tentativa in range(tentativas_id):
                try:
                    container_info = extrair_info_container(page)
                    if container_info and container_info.get('id'):
                        break
                except Exception:
                    pass
                time.sleep(2)  # SLEEP: espera entre tentativas de extrair info do container
            if not container_info or not container_info.get('id'):
                fim = datetime.now(TZ)
                duracao = (fim - inicio).total_seconds()
                metrics_path = f"resultados/{nome}_metrics.json"
                metrics_data = {
                    'container_info': container_info,
                    'inicio_teste': inicio.isoformat(sep=' '),
                    'fim_teste': fim.isoformat(sep=' '),
                    'duracao_segundos': duracao,
                    'cenario': cenario,
                    'erro': 'ID do container não encontrado após múltiplas tentativas.'
                }
                with open(metrics_path, 'w') as f:
                    json.dump(metrics_data, f, indent=4, ensure_ascii=False)
                resultados.append(None)
                try:
                    excluir_container_ate_sucesso(page)
                except Exception:
                    pass
                continue
            output_path = f"resultados/{nome}.json"
            metrics_path = f"resultados/{nome}_metrics.json"
            erro_k6 = None
            k6_metrics_summary = None
            try:
                executar_k6(k6_script, output_path, base_url=base_url, metrics_path=metrics_path)
            except Exception as e:
                erro_k6 = str(e)
            # Sempre tenta carregar o summary do K6 (summary-export)
            try:
                with open(metrics_path) as f:
                    k6_metrics_summary = json.load(f)
            except Exception:
                k6_metrics_summary = None
            fim = datetime.now(TZ)
            duracao = (fim - inicio).total_seconds()
            # Sempre tenta coletar métricas do Prometheus, mesmo se o K6 falhar
            config = carregar_config()
            prom_url = config.get('prometheus_url')
            prom_metrics_backend = None
            prom_metrics_database = None
            if prom_url and container_info and container_info.get('id'):
                prefix = container_info.get('id')
                backend_name = f"{prefix}-backend-1"
                database_name = f"{prefix}-database-1"
                time.sleep(35)  # SLEEP: espera para garantir coleta de métricas do Prometheus
                prom_metrics_backend = consultar_media_prometheus_nome(prom_url, backend_name, inicio, fim)
                prom_metrics_database = consultar_media_prometheus_nome(prom_url, database_name, inicio, fim)
            # Carrega métricas do K6 se existirem
            try:
                with open(metrics_path) as f:
                    metrics = json.load(f)
            except Exception:
                metrics = {}
            # Monta o dicionário final de métricas, sem duplicidade de campos do summary do K6
            metrics = {
                "k6_summary": k6_metrics_summary,  # summary do K6 exatamente como exportado
                "container_info": container_info,
                "inicio_teste": inicio.isoformat(sep=' '),
                "fim_teste": fim.isoformat(sep=' '),
                "duracao_segundos": duracao,
                "cenario": cenario,
                "prometheus_metrics_backend": prom_metrics_backend,
                "prometheus_metrics_database": prom_metrics_database
            }
            if erro_k6:
                metrics["erro"] = erro_k6
            with open(metrics_path, 'w') as f:
                json.dump(metrics, f, indent=4, ensure_ascii=False)
            # Se o K6 rodou, pega a métrica de falha, senão None
            m = k6_metrics_summary if isinstance(k6_metrics_summary, dict) else {}
            http_req_failed = None
            if "metrics" in m and isinstance(m["metrics"], dict):
                http_req_failed = m["metrics"].get("http_req_failed", {}).get("value", None)
            resultados.append(http_req_failed)
        except Exception as e:
            fim = datetime.now(TZ)
            duracao = (fim - inicio).total_seconds()
            metrics_path = f"resultados/{nome}_metrics.json"
            metrics_data = {
                'container_info': container_info,
                'inicio_teste': inicio.isoformat(sep=' '),
                'fim_teste': fim.isoformat(sep=' '),
                'duracao_segundos': duracao,
                'cenario': cenario,
                'erro': str(e)
            }
            with open(metrics_path, 'w') as f:
                json.dump(metrics_data, f, indent=4, ensure_ascii=False)
            resultados.append(None)
        finally:
            try:
                excluir_container_ate_sucesso(page)
            except Exception:
                pass
    return resultados


def encontrar_configuracao_minima(stack, k6_script, page, app_url, repeticoes):
    thresholds = extrair_thresholds_k6(k6_script)
    # Defaults caso não encontre
    limite_falha = thresholds.get('http_req_failed', 0.01)
    limite_p95 = thresholds.get('http_req_duration_p95', 500)
    cpu = CPU_MIN
    ram = RAM_MIN
    nome_teste = os.path.splitext(os.path.basename(k6_script))[0]
    while True:
        if cpu > CPU_MAX or ram > RAM_MAX:
            break
        cpu_atual = cpu
        ram_atual = ram
        resultados = testar_configuracao(stack, cpu_atual, ram_atual, k6_script, page, app_url, repeticoes)
        validos = [r for r in resultados if r is not None]
        media_falha = mean(validos) if validos else 1.0
        # Coletar médias separadas para backend e database
        prom_cpu_backend_vals = []
        prom_mem_backend_vals = []
        prom_cpu_database_vals = []
        prom_mem_database_vals = []
        k6_p95_vals = []
        for i in range(repeticoes):
            nome = f"{i+1}.{nome_teste}-{stack}-{cpu_atual}_{ram_atual}"
            metrics_path = f"resultados/{nome}_metrics.json"
            if os.path.exists(metrics_path):
                with open(metrics_path) as f:
                    metrics = json.load(f)
                prom_backend = metrics.get('prometheus_metrics_backend', {})
                prom_database = metrics.get('prometheus_metrics_database', {})
                if prom_backend.get('cpu_avg_cores') is not None:
                    prom_cpu_backend_vals.append(prom_backend['cpu_avg_cores'])
                if prom_backend.get('mem_avg_bytes') is not None:
                    prom_mem_backend_vals.append(prom_backend['mem_avg_bytes'])
                if prom_database.get('cpu_avg_cores') is not None:
                    prom_cpu_database_vals.append(prom_database['cpu_avg_cores'])
                if prom_database.get('mem_avg_bytes') is not None:
                    prom_mem_database_vals.append(prom_database['mem_avg_bytes'])
                # Extrai p(95) do tempo de resposta do K6
                k6_summary = metrics.get('k6_summary', {})
                k6_metrics = k6_summary.get('metrics', {}) if isinstance(k6_summary, dict) else {}
                http_req_duration = k6_metrics.get('http_req_duration', {})
                p95 = None
                if 'values' in http_req_duration:
                    # K6 v0.43+ salva percentis em 'values'
                    p95 = http_req_duration['values'].get('p(95)')
                elif 'p(95)' in http_req_duration:
                    # K6 versões antigas
                    p95 = http_req_duration.get('p(95)')
                if p95 is not None:
                    try:
                        k6_p95_vals.append(float(p95))
                    except Exception:
                        pass
        avg_cpu_backend = mean(prom_cpu_backend_vals) if prom_cpu_backend_vals else 0
        avg_mem_backend = mean(prom_mem_backend_vals) if prom_mem_backend_vals else 0
        avg_cpu_database = mean(prom_cpu_database_vals) if prom_cpu_database_vals else 0
        avg_mem_database = mean(prom_mem_database_vals) if prom_mem_database_vals else 0
        avg_p95 = mean(k6_p95_vals) if k6_p95_vals else None
        # Gargalo: uso médio > 85% do limite configurado
        cpu_gargalo_backend = avg_cpu_backend > 0.85 * (cpu_atual * 100)
        mem_gargalo_backend = avg_mem_backend > 0.8 * (ram_atual * 1024 * 1024)
        cpu_gargalo_database = avg_cpu_database > 0.85 * (cpu_atual * 100)
        mem_gargalo_database = avg_mem_database > 0.8 * (ram_atual * 1024 * 1024)
        # --- Lógica dinâmica para thresholds do K6 ---
        # Extrai todos os thresholds definidos no script K6
        thresholds = extrair_thresholds_k6(k6_script)
        # Dicionários para médias e avaliação
        medias_thresholds = {}
        atingiu_thresholds = {}
        # Para cada threshold definido, calcula a média e avalia se foi atingido
        for nome, valor in thresholds.items():
            if nome == 'http_req_failed':
                # Já temos a média de http_req_failed
                medias_thresholds[nome] = media_falha
                atingiu_thresholds[nome] = media_falha < valor if media_falha is not None else False
            elif nome == 'http_req_duration_p95':
                medias_thresholds[nome] = avg_p95
                atingiu_thresholds[nome] = avg_p95 < valor if avg_p95 is not None else False
            # Adicione aqui outros thresholds conforme forem extraídos
        # Salvar médias e avaliação dos thresholds no log (apenas bloco dinâmico)
        with open(f"resultados/minimo_{nome_teste}_{stack}.log", "a") as f:
            f.write(f"CPU={cpu_atual}, RAM={ram_atual}, ")
            for nome in thresholds:
                f.write(f"media_{nome}={medias_thresholds.get(nome)}, threshold_{nome}={thresholds[nome]}, atingiu_{nome}={atingiu_thresholds.get(nome)}, ")
            f.write(f"avg_cpu_backend={avg_cpu_backend}, avg_mem_backend={avg_mem_backend}, "
                    f"avg_cpu_database={avg_cpu_database}, avg_mem_database={avg_mem_database}, "
                    f"resultados={resultados}\n")
        # Critérios de parada automáticos:
        if (media_falha < limite_falha and avg_p95 < limite_p95 and avg_cpu_backend < 0.85 * (cpu_atual * 100)):
            break
        # Lógica de incremento: prioriza backend, depois database, depois RAM
        if cpu_gargalo_backend and cpu < CPU_MAX:
            cpu = round(min(cpu + CPU_INC, CPU_MAX), 2)
        elif mem_gargalo_backend and ram < RAM_MAX:
            ram = min(ram * 2, RAM_MAX)
        elif cpu_gargalo_database and cpu < CPU_MAX:
            cpu = round(min(cpu + CPU_INC, CPU_MAX), 2)
        elif mem_gargalo_database and ram < RAM_MAX:
            ram = min(ram * 2, RAM_MAX)
        else:
            if ram < RAM_MAX:
                ram = min(ram * 2, RAM_MAX)
            elif cpu < CPU_MAX:
                cpu = round(min(cpu + CPU_INC, CPU_MAX), 2)
        # Garante saída do loop se não for mais possível aumentar CPU ou RAM
        if cpu >= CPU_MAX and ram >= RAM_MAX:
            print(f"[PARADA] CPU e RAM atingiram ou ultrapassaram o limite máximo: CPU={cpu}, RAM={ram}. Encerrando busca.")
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app_url', required=True, help='URL pública da aplicação React')
    parser.add_argument('--stacks', required=True, help='Lista de stacks separadas por vírgula')
    parser.add_argument('--k6_script', required=True, help='Caminho do script K6')
    parser.add_argument('--repeticoes', type=int, default=5, help='Quantidade de repetições por configuração')
    args = parser.parse_args()
    stacks = [s.strip() for s in args.stacks.split(',')]

    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = iniciar_navegador(playwright)
        context = browser.new_context()
        page = context.new_page()
        acessar_aplicacao(page, args.app_url)
        for stack in stacks:
            encontrar_configuracao_minima(stack, args.k6_script, page, args.app_url, args.repeticoes)
        browser.close()

if __name__ == "__main__":
    # Como executar no terminal:
    # python3 scripts/config_minima.py --app_url http://143.198.78.77:80 --stacks node-postgres,java-postgres,node-mysql --k6_script tests/consulta_intensiva.js
    main()
