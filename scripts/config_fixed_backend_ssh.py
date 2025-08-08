# Script para testar todas as combinações de CPU/RAM do backend (mantendo o banco fixo) coletando métricas via SSH inline
# Requer: paramiko (pip install paramiko)
# Uso: python3 scripts/config_fixed_backend_ssh.py --app_url <URL_DA_APP> --stacks node-postgres,java-postgres --k6_script tests/consulta_intensiva.js --repeticoes 3 --ssh_config ssh_config.json

import os
import sys
import time
import json
import argparse
from statistics import mean
from datetime import datetime, timezone, timedelta
import paramiko
import threading
import re

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import (
    iniciar_navegador, acessar_aplicacao, criar_container, aguardar_container_ativo,
    extrair_url_container, executar_k6, excluir_container_ate_sucesso, extrair_info_container
)

CPU_MIN = 1
RAM_MIN = 1024
CPU_INC = 1
RAM_INC = 1024
CPU_MAX = 2
RAM_MAX = 2048
TZ = timezone(timedelta(hours=-3))  # UTC-3

class SSHMetrics:
    def __init__(self, host, user, key_path=None, password=None):
        self.host = host
        self.user = user
        self.key_path = key_path
        self.password = password
        self.ssh = None

    def connect(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if self.password:
            self.ssh.connect(self.host, username=self.user, password=self.password)
        else:
            self.ssh.connect(self.host, username=self.user, key_filename=self.key_path)

    def close(self):
        if self.ssh:
            self.ssh.close()

    def start_parallel_collection(self, backend_name, db_name, interval=2):
        self._collecting = True
        self._samples = []
        import re
        def collect():
            while self._collecting:
                # Coleta CPU do host (robusto, uso real = 100 - idle)
                stdin, stdout, stderr = self.ssh.exec_command("LANG=C top -bn1 | grep 'Cpu(s)'")
                cpu_info = stdout.read().decode()
                cpu_val = None
                if cpu_info:
                    # Regex robusto: captura apenas números válidos (ex: 99.0, 99, 99,0)
                    match = re.search(r'(\d+[\.,]?\d*)\s*id', cpu_info)
                    if match:
                        idle_str = match.group(1).replace(',', '.')
                        try:
                            # Garante que só converte se for número válido
                            if re.fullmatch(r'\d+(\.\d+)?', idle_str):
                                idle = float(idle_str)
                                cpu_val = 100.0 - idle
                            else:
                                print(f"[WARN] Valor de idle inválido capturado: '{idle_str}' na saída: {cpu_info.strip()}")
                        except Exception as e:
                            print(f"[ERROR] Falha ao converter idle para float: '{idle_str}' na saída: {cpu_info.strip()} - {e}")
                # Só registra amostra se parsing foi bem-sucedido
                if cpu_val is None:
                    time.sleep(interval)
                    continue
                # Coleta memória do host (alinhado ao htop: total - available)
                stdin, stdout, stderr = self.ssh.exec_command("free -m | grep Mem")
                mem_info = stdout.read().decode()
                mem_val = None
                if mem_info:
                    try:
                        parts = mem_info.split()
                        # free -m: total used free shared buff/cache available
                        total = int(parts[1])
                        available = int(parts[6])
                        mem_val = total - available
                    except Exception:
                        pass
                # Coleta docker stats
                stdin, stdout, stderr = self.ssh.exec_command(f"docker stats --no-stream --format '{{{{.Name}}}},{{{{.CPUPerc}}}},{{{{.MemUsage}}}}' | grep '{backend_name}\\|{db_name}'")
                docker_stats_raw = stdout.read().decode().strip()
                print(f"[DEBUG] docker stats output: {docker_stats_raw}")
                docker_stats = docker_stats_raw.split('\n')
                backend_cpu = backend_mem = db_cpu = db_mem = None
                for line in docker_stats:
                    parts = line.split(',')
                    if len(parts) >= 3:
                        name = parts[0]
                        cpu = parts[1].replace('%','').replace(',','.')
                        # Extrai apenas o valor numérico em MiB da string "35.33MiB / 1GiB"
                        mem_match = re.match(r'([0-9.]+)MiB', parts[2])
                        mem = None
                        if mem_match:
                            mem = float(mem_match.group(1))
                        try:
                            cpu = float(cpu)
                        except Exception:
                            continue
                        if backend_name in name:
                            backend_cpu = cpu
                            backend_mem = mem
                        elif db_name in name:
                            db_cpu = cpu
                            db_mem = mem
                self._samples.append({
                    'host_cpu': cpu_val,
                    'host_mem': mem_val,
                    'backend_cpu': backend_cpu,
                    'backend_mem': backend_mem,
                    'db_cpu': db_cpu,
                    'db_mem': db_mem
                })
                time.sleep(interval)
        self._thread = threading.Thread(target=collect)
        self._thread.start()

    def stop_parallel_collection(self):
        self._collecting = False
        self._thread.join()
        def avg(lst):
            vals = [v for v in lst if v is not None]
            return sum(vals)/len(vals) if vals else None
        samples = self._samples
        host_cpu = [s['host_cpu'] for s in samples]
        host_mem = [s['host_mem'] for s in samples]
        backend_cpu = [s['backend_cpu'] for s in samples]
        backend_mem = [s['backend_mem'] for s in samples]
        db_cpu = [s['db_cpu'] for s in samples]
        db_mem = [s['db_mem'] for s in samples]
        return {
            "host": {
                "cpu": host_cpu,
                "memoria": host_mem,
                "media": {
                    "cpu": avg(host_cpu),
                    "memoria": avg(host_mem)
                }
            },
            "backend": {
                "cpu": backend_cpu,
                "memoria": backend_mem,
                "media": {
                    "cpu": avg(backend_cpu),
                    "memoria": avg(backend_mem)
                }
            },
            "banco_de_dados": {
                "cpu": db_cpu,
                "memoria": db_mem,
                "media": {
                    "cpu": avg(db_cpu),
                    "memoria": avg(db_mem)
                }
            }
        }

def testar_configuracao(stack, cpu, ram, k6_script, page, app_url, repeticoes, ssh_metrics):
    resultados = []
    nome_teste = os.path.splitext(os.path.basename(k6_script))[0]
    for i in range(repeticoes):
        nome = f"{i+1}.{nome_teste}-{stack}-{cpu}_{ram}"
        cenario = {
            "nome": nome,
            "backend": stack,
            "backend_cpu": cpu,
            "backend_ram": ram,
            "db_cpu": CPU_MIN,  # Mantém fixo
            "db_ram": RAM_MIN,  # Mantém fixo
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
            prefix = container_info.get('id')
            backend_name = f"{prefix}-backend-1"
            database_name = f"{prefix}-database-1"
            ssh_metrics.start_parallel_collection(backend_name, database_name, interval=2)
            output_path = f"resultados/{nome}.json"
            metrics_path = f"resultados/{nome}_metrics.json"
            erro_k6 = None
            k6_metrics_summary = None
            try:
                executar_k6(k6_script, output_path, base_url=base_url, metrics_path=metrics_path)
            except Exception as e:
                erro_k6 = str(e)
            metrics_json = ssh_metrics.stop_parallel_collection()
            fim = datetime.now(TZ)
            duracao = (fim - inicio).total_seconds()
            try:
                with open(metrics_path) as f:
                    k6_metrics_summary = json.load(f)
            except Exception:
                k6_metrics_summary = None
            metrics = {
                "host": metrics_json.get("host", {}),
                "backend": metrics_json.get("backend", {}),
                "banco_de_dados": metrics_json.get("banco_de_dados", {}),
                "media": {
                    "host": metrics_json.get("host", {}).get("media", {}),
                    "backend": metrics_json.get("backend", {}).get("media", {}),
                    "banco_de_dados": metrics_json.get("banco_de_dados", {}).get("media", {})
                },
                "k6_summary": k6_metrics_summary,
                "container_info": container_info,
                "inicio_teste": inicio.isoformat(sep=' '),
                "fim_teste": fim.isoformat(sep=' '),
                "duracao_segundos": duracao,
                "cenario": cenario
            }
            if erro_k6:
                metrics["erro"] = erro_k6
            with open(metrics_path, 'w') as f:
                json.dump(metrics, f, indent=4, ensure_ascii=False)
            resultados.append(None)
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

def testar_todas_combinacoes(stack, k6_script, page, app_url, repeticoes, ssh_metrics):
    cpu = CPU_MIN
    while cpu <= CPU_MAX + 1e-6:
        ram = RAM_MIN
        while ram <= RAM_MAX + 1e-6:
            testar_configuracao(stack, cpu, ram, k6_script, page, app_url, repeticoes, ssh_metrics)
            ram += RAM_INC
        cpu = round(cpu + CPU_INC, 2)

def main():
    import json as jsonlib
    parser = argparse.ArgumentParser()
    parser.add_argument('--app_url', required=True, help='URL pública da aplicação React')
    parser.add_argument('--stacks', required=True, help='Lista de stacks separadas por vírgula')
    parser.add_argument('--k6_script', required=True, help='Caminho do script K6')
    parser.add_argument('--repeticoes', type=int, default=5, help='Quantidade de repetições por configuração')
    parser.add_argument('--ssh_config', default='ssh_config.json', help='Arquivo JSON com dados de conexão SSH')
    args = parser.parse_args()
    stacks = [s.strip() for s in args.stacks.split(',')]

    # Lê config SSH do arquivo
    with open(args.ssh_config, 'r') as f:
        ssh_conf = jsonlib.load(f)
    ssh_host = ssh_conf.get('ssh_host')
    ssh_user = ssh_conf.get('ssh_user')
    ssh_key = ssh_conf.get('ssh_key')
    ssh_password = ssh_conf.get('ssh_password')

    from playwright.sync_api import sync_playwright
    ssh_metrics = SSHMetrics(ssh_host, ssh_user, key_path=ssh_key, password=ssh_password)
    ssh_metrics.connect()
    with sync_playwright() as playwright:
        browser = iniciar_navegador(playwright)
        context = browser.new_context()
        page = context.new_page()
        acessar_aplicacao(page, args.app_url)
        for stack in stacks:
            testar_todas_combinacoes(stack, args.k6_script, page, args.app_url, args.repeticoes, ssh_metrics)
        browser.close()
    ssh_metrics.close()

if __name__ == "__main__":
    main()
