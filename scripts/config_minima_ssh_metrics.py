def main():
    import argparse
    from playwright.sync_api import sync_playwright
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
    ssh_metrics = SSHMetricsCollector(args.ssh_host, args.ssh_user, args.ssh_key)
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

# Versão do config_minima que coleta métricas via SSH na máquina host
# Requer: paramiko (pip install paramiko)
# Uso: python3 scripts/config_minima_ssh_metrics.py --app_url <URL_DA_APP> --stacks node-postgres,java-postgres,node-mysql --k6_script tests/consulta_intensiva.js --ssh_host 143.198.78.77 --ssh_user <usuario> --ssh_key <caminho_chave>

import os
import sys
import time
import json
import argparse
from statistics import mean
from datetime import datetime, timezone, timedelta
import paramiko

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


# Nova classe para coleta inline via SSH, aderente à documentação
import threading
class SSHMetricsCollector:
    def __init__(self, host, user, key_path):
        self.host = host
        self.user = user
        self.key_path = key_path
        self.ssh = None
        self._collecting = False
        self._samples = []

    def connect(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(self.host, username=self.user, key_filename=self.key_path)

    def close(self):
        if self.ssh:
            self.ssh.close()

    def start_collection(self, backend_name, db_name, interval=2):
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
                    match = re.search(r'([0-9.,]+)\s*id', cpu_info)
                    if match:
                        idle = float(match.group(1).replace(',', '.'))
                        cpu_val = 100.0 - idle
                # Só registra amostra se parsing foi bem-sucedido
                if cpu_val is None:
                    time.sleep(interval)
                    continue
                # Coleta memória do host (alinhado ao htop: total - free - buff/cache)
                stdin, stdout, stderr = self.ssh.exec_command("free -m | grep Mem")
                mem_info = stdout.read().decode()
                mem_val = None
                if mem_info:
                    try:
                        parts = mem_info.split()
                        total = int(parts[1])
                        free = int(parts[3])
                        buff_cache = int(parts[5])
                        mem_val = total - free - buff_cache
                    except Exception:
                        pass
                # Coleta docker stats
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

    def stop_collection(self):
        self._collecting = False
        self._thread.join()
        return self._samples

    def get_metrics_json(self):
        # Calcula médias e estrutura conforme documentação
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
            "backend_cpu": CPU_MIN,  # Mantém fixo
            "backend_ram": RAM_MIN,  # Mantém fixo
            "db_cpu": cpu,
            "db_ram": ram,
            "k6_script": k6_script
        }
        inicio = datetime.now(TZ)
        container_info = None
        tentativas_id = 10
    # Bloco de execução principal do teste
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
            # Inicia coleta de métricas via SSH inline
            prefix = container_info.get('id')
            backend_name = f"{prefix}-backend-1"
            database_name = f"{prefix}-database-1"
            ssh_metrics.start_collection(backend_name, database_name, interval=2)
            output_path = f"resultados/{nome}.json"
            metrics_path = f"resultados/{nome}_metrics.json"
            erro_k6 = None
            k6_metrics_summary = None
            try:
                executar_k6(k6_script, output_path, base_url=base_url, metrics_path=metrics_path)
            except Exception as e:
                erro_k6 = str(e)
            # Para monitoramento: para coleta e gera JSON estruturado
            ssh_metrics.stop_collection()
            metrics_json = ssh_metrics.get_metrics_json()
            fim = datetime.now(TZ)
            duracao = (fim - inicio).total_seconds()
            # Carrega métricas do K6 se existirem
            try:
                with open(metrics_path) as f:
                    k6_metrics_summary = json.load(f)
            except Exception:
                k6_metrics_summary = None
            # Monta o dicionário final de métricas conforme documentação
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

if __name__ == "__main__":
    main()

# Adiciona função ausente para varrer combinações de CPU/RAM
def testar_todas_combinacoes(stack, k6_script, page, app_url, repeticoes, ssh_metrics):
    cpu = CPU_MIN
    while cpu <= CPU_MAX + 1e-6:
        ram = RAM_MIN
        while ram <= RAM_MAX + 1e-6:
            testar_configuracao(stack, cpu, ram, k6_script, page, app_url, repeticoes, ssh_metrics)
            ram += RAM_INC
        cpu = round(cpu + CPU_INC, 2)
