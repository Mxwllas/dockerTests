# Script para testar todas as combinações de CPU/RAM sem alterar o backend e sem parar nos thresholds
# Uso: python3 scripts/config_minima_fixed_backend.py --app_url <URL_DA_APP> --stacks node-postgres,java-postgres,node-mysql --k6_script tests/consulta_intensiva.js

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
RAM_INC = 128
CPU_MAX = 1
RAM_MAX = 1024
TZ = timezone(timedelta(hours=-3))  # UTC-3

def carregar_config():
    with open(os.path.join(os.path.dirname(__file__), '../config.json'), 'r') as f:
        return json.load(f)

def consultar_media_prometheus_nome(prom_url, container_name, inicio, fim):
    from datetime import timezone
    inicio_utc = inicio.astimezone(timezone.utc)
    fim_utc = fim.astimezone(timezone.utc)
    intervalo = int((fim_utc - inicio_utc).total_seconds())
    if intervalo < 1:
        intervalo = 1
    intervalo = max(intervalo, 30)
    query_mem = f'avg_over_time(container_memory_usage_bytes{{name="{container_name}"}}[{intervalo}s])'
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
    m = re.search(r"http_req_failed\s*:\s*\[\s*'rate<([0-9.]+)'", content)
    if m:
        thresholds['http_req_failed'] = float(m.group(1))
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
            "backend_cpu": CPU_MIN,  # Mantém fixo
            "backend_ram": RAM_MIN,  # Mantém fixo
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
                time.sleep(2)
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
            try:
                with open(metrics_path) as f:
                    k6_metrics_summary = json.load(f)
            except Exception:
                k6_metrics_summary = None
            fim = datetime.now(TZ)
            duracao = (fim - inicio).total_seconds()
            config = carregar_config()
            prom_url = config.get('prometheus_url')
            prom_metrics_backend = None
            prom_metrics_database = None
            if prom_url and container_info and container_info.get('id'):
                prefix = container_info.get('id')
                backend_name = f"{prefix}-backend-1"
                database_name = f"{prefix}-database-1"
                time.sleep(35)
                prom_metrics_backend = consultar_media_prometheus_nome(prom_url, backend_name, inicio, fim)
                prom_metrics_database = consultar_media_prometheus_nome(prom_url, database_name, inicio, fim)
            try:
                with open(metrics_path) as f:
                    metrics = json.load(f)
            except Exception:
                metrics = {}
            metrics = {
                "k6_summary": k6_metrics_summary,
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

def testar_todas_combinacoes(stack, k6_script, page, app_url, repeticoes):
    nome_teste = os.path.splitext(os.path.basename(k6_script))[0]
    cpu = CPU_MIN
    while cpu <= CPU_MAX + 1e-6:
        ram = RAM_MIN
        while ram <= RAM_MAX + 1e-6:
            testar_configuracao(stack, cpu, ram, k6_script, page, app_url, repeticoes)
            ram += RAM_INC
        cpu = round(cpu + CPU_INC, 2)

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
            testar_todas_combinacoes(stack, args.k6_script, page, args.app_url, args.repeticoes)
        browser.close()

if __name__ == "__main__":
    main()
