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

# Função para rodar script de monitoramento via SSH
class SSHMonitor:
    def __init__(self, host, user, key_path):
        self.host = host
        self.user = user
        self.key_path = key_path
        self.ssh = None
        self.sftp = None
        self.monitor_pid = None
        self.metrics_file = None

    def connect(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(self.host, username=self.user, key_filename=self.key_path)
        self.sftp = self.ssh.open_sftp()

    def start_monitor(self, backend_name, db_name, interval, remote_metrics_file):
        self.metrics_file = remote_metrics_file
        # Garante que não há monitor antigo rodando
        self.ssh.exec_command(f"pkill -f monitor_metrics.sh || true")
        # Inicia monitor em background
        cmd = f"nohup ./monitor_metrics.sh {backend_name} {db_name} {interval} {remote_metrics_file} > /dev/null 2>&1 & echo $!"
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        self.monitor_pid = stdout.read().decode().strip()

    def stop_monitor(self):
        if self.monitor_pid:
            self.ssh.exec_command(f"kill {self.monitor_pid}")
            time.sleep(1)

    def fetch_metrics(self, local_path):
        if self.metrics_file:
            self.sftp.get(self.metrics_file, local_path)

    def close(self):
        if self.sftp:
            self.sftp.close()
        if self.ssh:
            self.ssh.close()


def testar_configuracao(stack, cpu, ram, k6_script, page, app_url, repeticoes, ssh_monitor):
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
            # Inicia monitoramento via SSH
            prefix = container_info.get('id')
            backend_name = f"{prefix}-backend-1"
            database_name = f"{prefix}-database-1"
            remote_metrics_file = f"/tmp/{nome}_metrics.log"
            ssh_monitor.start_monitor(backend_name, database_name, 2, remote_metrics_file)
            output_path = f"resultados/{nome}.json"
            metrics_path = f"resultados/{nome}_metrics.json"
            erro_k6 = None
            k6_metrics_summary = None
            try:
                executar_k6(k6_script, output_path, base_url=base_url, metrics_path=metrics_path)
            except Exception as e:
                erro_k6 = str(e)
            fim = datetime.now(TZ)
            duracao = (fim - inicio).total_seconds()
            # Para monitoramento e baixa arquivo
            ssh_monitor.stop_monitor()
            local_metrics_file = f"resultados/{nome}_host_metrics.log"
            try:
                ssh_monitor.fetch_metrics(local_metrics_file)
            except Exception as e:
                print(f"Falha ao baixar métricas via SSH: {e}")
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
                "host_metrics_file": local_metrics_file
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

def testar_todas_combinacoes(stack, k6_script, page, app_url, repeticoes, ssh_monitor):
    cpu = CPU_MIN
    while cpu <= CPU_MAX + 1e-6:
        ram = RAM_MIN
        while ram <= RAM_MAX + 1e-6:
            testar_configuracao(stack, cpu, ram, k6_script, page, app_url, repeticoes, ssh_monitor)
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
    ssh_monitor = SSHMonitor(args.ssh_host, args.ssh_user, args.ssh_key)
    ssh_monitor.connect()
    with sync_playwright() as playwright:
        browser = iniciar_navegador(playwright)
        context = browser.new_context()
        page = context.new_page()
        acessar_aplicacao(page, args.app_url)
        for stack in stacks:
            testar_todas_combinacoes(stack, args.k6_script, page, args.app_url, args.repeticoes, ssh_monitor)
        browser.close()
    ssh_monitor.close()

if __name__ == "__main__":
    main()
