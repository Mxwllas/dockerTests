# Versão do config_minima que coleta métricas via SSH sem criar arquivos no host
# Requer: paramiko (pip install paramiko)
# Uso: python3 scripts/config_minima_ssh_inline.py --app_url <URL_DA_APP> --stacks node-postgres,java-postgres,node-mysql --k6_script tests/consulta_intensiva.js --ssh_host 143.198.78.77 --ssh_user <usuario> --ssh_key <caminho_chave>

import os
import sys
import time
import json
import argparse
from statistics import mean
from datetime import datetime, timezone, timedelta
import paramiko
import threading

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import (
    iniciar_navegador, acessar_aplicacao, criar_container, aguardar_container_ativo,
    extrair_url_container, executar_k6, excluir_container_ate_sucesso, extrair_info_container
)

CPU_MIN = 0.5
RAM_MIN = 1024
CPU_INC = 0.1
RAM_INC = 128
CPU_MAX = 1
RAM_MAX = 1024
TZ = timezone(timedelta(hours=-3))  # UTC-3

class SSHMetrics:
    def __init__(self, host, user, key_path):
        self.host = host
        self.user = user
        self.key_path = key_path
        self.ssh = None

    def connect(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(self.host, username=self.user, key_filename=self.key_path)

    def close(self):
        if self.ssh:
            self.ssh.close()

    def start_parallel_collection(self, backend_name, db_name, interval=2):
        self._collecting = True
        self._samples = []
        def collect():
            while self._collecting:
                # Host CPU
                stdin, stdout, stderr = self.ssh.exec_command("top -bn1 | grep 'Cpu(s)'")
                cpu_info = stdout.read().decode()
                cpu_val = None
                if cpu_info:
                    try:
                        cpu_val = float(cpu_info.split()[1].replace(',', '.'))
                    except Exception:
                        pass
                # Host MEM
                stdin, stdout, stderr = self.ssh.exec_command("free -m | grep Mem")
                mem_info = stdout.read().decode()
                mem_val = None
                if mem_info:
                    try:
                        mem_val = int(mem_info.split()[2])
                    except Exception:
                        pass
                # Containers
                stdin, stdout, stderr = self.ssh.exec_command(f"docker stats --no-stream --format '{{{{.Name}}}},{{{{.CPUPerc}}}},{{{{.MemUsage}}}}' | grep '{backend_name}\\|{db_name}'")
                docker_stats = stdout.read().decode().strip().split('\n')
                backend_cpu = backend_mem = db_cpu = db_mem = None
                for line in docker_stats:
                    parts = line.split(',')
                    if len(parts) >= 3:
                        name = parts[0]
                        cpu = parts[1].replace('%','').replace(',','.')
                        mem = parts[2].split()[0].replace(',','.')
                        try:
                            cpu = float(cpu)
                            mem = float(mem)
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
        # Calcula médias
        def avg(lst):
            vals = [v for v in lst if v is not None]
            return sum(vals)/len(vals) if vals else None
        host_cpu_avg = avg([s['host_cpu'] for s in self._samples])
        host_mem_avg = avg([s['host_mem'] for s in self._samples])
        backend_cpu_avg = avg([s['backend_cpu'] for s in self._samples])
        backend_mem_avg = avg([s['backend_mem'] for s in self._samples])
        db_cpu_avg = avg([s['db_cpu'] for s in self._samples])
        db_mem_avg = avg([s['db_mem'] for s in self._samples])
        return {
            'samples': self._samples,
            'host_cpu_avg': host_cpu_avg,
            'host_mem_avg': host_mem_avg,
            'backend_cpu_avg': backend_cpu_avg,
            'backend_mem_avg': backend_mem_avg,
            'db_cpu_avg': db_cpu_avg,
            'db_mem_avg': db_mem_avg
        }

def testar_configuracao(stack, cpu, ram, k6_script, page, app_url, repeticoes, ssh_metrics):
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
            # Coleta métricas via SSH em paralelo ao teste
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
            # Para coleta paralela e obtém métricas do período do teste
            metrics_during = ssh_metrics.stop_parallel_collection()
            fim = datetime.now(TZ)
            duracao = (fim - inicio).total_seconds()
            # Carrega métricas do K6 se existirem
            try:
                with open(metrics_path) as f:
                    k6_metrics_summary = json.load(f)
            except Exception:
                k6_metrics_summary = None
            # Monta o dicionário final de métricas
            metrics = {
                "k6_summary": k6_metrics_summary,
                "container_info": container_info,
                "inicio_teste": inicio.isoformat(sep=' '),
                "fim_teste": fim.isoformat(sep=' '),
                "duracao_segundos": duracao,
                "cenario": cenario,
                "ssh_metrics_during": metrics_during
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--app_url', required=True, help='URL pública da aplicação React')
    parser.add_argument('--stacks', required=True, help='Lista de stacks separadas por vírgula')
    parser.add_argument('--k6_script', required=True, help='Caminho do script K6')
    parser.add_argument('--repeticoes', type=int, default=5, help='Quantidade de repetições por configuração')
    parser.add_argument('--ssh_host', required=True, help='Host SSH para monitoramento')
    parser.add_argument('--ssh_user', required=True, help='Usuário SSH')
    parser.add_argument('--ssh_key', required=True, help='Caminho da chave SSH privada')
    args = parser.parse_args()
    stacks = [s.strip() for s in args.stacks.split(',')]

    from playwright.sync_api import sync_playwright
    ssh_metrics = SSHMetrics(args.ssh_host, args.ssh_user, args.ssh_key)
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
