from playwright.sync_api import sync_playwright
import subprocess
import json
import time
import os
import argparse
from datetime import datetime, timezone, timedelta
import requests

TZ = timezone(timedelta(hours=-3))  # UTC-3

def carregar_cenarios(path: str) -> list:
    """
    Lê o arquivo cenarios.json e retorna uma lista de dicionários com os testes.
    """
    with open(path, 'r') as f:
        return json.load(f)

def iniciar_navegador(playwright):
    """
    Inicia o navegador com Playwright e retorna o browser.
    """
    browser = playwright.chromium.launch(headless=True)
    return browser

def acessar_aplicacao(page, url: str):
    """
    Abre a aplicação React na URL fornecida.
    """
    page.goto(url)

def criar_container(page, config: dict):
    """
    Preenche os campos de criação de container com base na configuração.
    Aguarda o botão aparecer antes de clicar.
    Seletores ajustados conforme o HTML do modal fornecido.
    """
    # Botão para abrir modal de criação
    BOTAO_CRIAR = 'button.btn.btn-primary[data-bs-target="#staticBackdrop"]'  # Botão "Add Container"
    page.wait_for_selector(BOTAO_CRIAR, timeout=60000)
    page.click(BOTAO_CRIAR)
    # Aguarda o modal abrir
    page.wait_for_selector('#staticBackdrop.show', timeout=10000)
    # Seleciona a stack (Options)
    page.select_option('#config-selection', config["backend"])  # Ex: node-postgres
    # Backend CPU e RAM
    page.fill('input.value-viewer[data-for="backend-cpu"]', str(float(config.get("backend_cpu", 0.5))))
    page.fill('input.value-viewer[data-for="backend-ram"]', str(int(config.get("backend_ram", 512))))
    # Abrir o accordion do Database antes de preencher
    db_accordion_btn = 'button.accordion-button[aria-controls="collapseTwo"]'
    page.click(db_accordion_btn)
    page.wait_for_selector('input.value-viewer[data-for="database-cpu"]', state='visible', timeout=5000)
    # Database CPU e RAM
    page.fill('input.value-viewer[data-for="database-cpu"]', str(float(config.get("db_cpu", 0.5))))
    page.fill('input.value-viewer[data-for="database-ram"]', str(int(config.get("db_ram", 512))))
    # Clica no botão Build
    page.click('#request-btn')

def aguardar_container_ativo(page) -> None:
    """
    Aguarda até que a interface indique que o container está pronto para testes.
    Agora espera pelo texto 'Container build successfully!' e clica em 'Ok'.
    """
    for _ in range(120):  # até 4 minutos
        try:
            if page.query_selector('text=Container build successfully!'):
                page.click('text=Ok')
                return
        except Exception:
            pass
        page.wait_for_timeout(2000)
    raise TimeoutError('Mensagem de sucesso do container não detectada. Ajuste o seletor se necessário.')

def executar_k6(script_path: str, output_path: str, base_url: str = None, metrics_path: str = None):
    """
    Executa o teste de carga com K6 e salva o resultado em output_path.
    Se base_url for fornecido, passa como variável de ambiente para o K6.
    Também salva as métricas finais em metrics_path, se fornecido.
    Sempre salva o summary do K6, o exit code e se os thresholds foram atingidos.
    """
    import tempfile
    import json as pyjson
    import shutil
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cmd = [
        "k6", "run", f"--out", f"json={output_path}", script_path
    ]
    if base_url:
        cmd += ["--env", f"BASE_URL={base_url}"]
    summary_data = None
    exit_code = None
    thresholds_ok = None
    if metrics_path:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            cmd += ["--summary-export", tmp.name]
            proc = subprocess.run(cmd, check=False)
            exit_code = proc.returncode
            # Copia o summary para o destino final
            try:
                with open(tmp.name, 'r') as f:
                    summary_data = pyjson.load(f)
                shutil.copy(tmp.name, metrics_path)
            except Exception:
                summary_data = None
    else:
        proc = subprocess.run(cmd, check=False)
        exit_code = proc.returncode
    # Analisa thresholds
    if summary_data and 'metrics' in summary_data:
        thresholds_ok = True
        for m in summary_data['metrics'].values():
            if 'thresholds' in m:
                for t in m['thresholds'].values():
                    if not t.get('ok', True):
                        thresholds_ok = False
                        break
    # Salva info extra no metrics_path
    if metrics_path:
        try:
            with open(metrics_path, 'r+') as f:
                try:
                    metrics_json = pyjson.load(f)
                except Exception:
                    metrics_json = {}
                metrics_json['k6_exit_code'] = exit_code
                metrics_json['k6_thresholds_ok'] = thresholds_ok
                if summary_data:
                    metrics_json['metrics'] = summary_data.get('metrics', summary_data)
                f.seek(0)
                pyjson.dump(metrics_json, f, indent=4, ensure_ascii=False)
                f.truncate()
        except Exception:
            pass

def excluir_container(page):
    """
    Realiza a exclusão do container pela interface.
    Aguarda o botão 'Remove' aparecer, clica nele e espera 3 segundos para garantir remoção.
    """
    BOTAO_REMOVE = 'a:has-text("Remove")'
    try:
        page.wait_for_selector(BOTAO_REMOVE, timeout=60000)
        page.click(BOTAO_REMOVE)
        page.wait_for_timeout(3000)  # Aguarda 3 segundos para o popup sumir e o container ser removido
    except Exception:
        print('Botão Remove não encontrado. Ajuste o seletor se necessário.')

def extrair_url_container(page):
    """
    Após o container ser criado, extrai o href do botão/link 'Run' correspondente ao container recém-criado.
    Se o href for '#', aguarda até que seja atualizado para a URL real do container.
    Retorna a URL encontrada ou lança erro se não encontrar.
    """
    page.wait_for_selector('a:has-text("Run"), button:has-text("Run")', timeout=90000)
    tentativas = 90  # até 2 minutos
    for _ in range(tentativas):
        run_links = page.query_selector_all('a:has-text("Run")')
        if run_links:
            href = run_links[0].get_attribute('href')
            if href and href != "#":
                return href
        # Caso seja botão, pode ser necessário extrair de outro atributo
        run_btns = page.query_selector_all('button:has-text("Run")')
        if run_btns:
            href = run_btns[0].get_attribute('data-href')
            if href and href != "#":
                return href
        page.wait_for_timeout(5000)
    raise Exception('Nenhum link ou botão Run válido encontrado para extrair URL do container.')

def extrair_url_container_debug(page):
    print('[DEBUG] Iniciando extração da URL do container (Run)')
    tentativas = 60  # até 2 minutos
    for i in range(tentativas):
        print(f'[DEBUG] Tentativa {i+1}/{tentativas}')
        run_links = page.query_selector_all('a:has-text("Run")')
        if run_links:
            for idx, link in enumerate(run_links):
                href = link.get_attribute('href')
                print(f'[DEBUG] Link {idx}: href={href}')
                if href and href != "#":
                    print(f'[DEBUG] Encontrado href válido: {href}')
                    return href
        run_btns = page.query_selector_all('button:has-text("Run")')
        if run_btns:
            for idx, btn in enumerate(run_btns):
                href = btn.get_attribute('data-href')
                print(f'[DEBUG] Botão {idx}: data-href={href}')
                if href and href != "#":
                    print(f'[DEBUG] Encontrado data-href válido: {href}')
                    return href
        if (i+1) % 5 == 0:
            print('[DEBUG] Dando reload na página para tentar atualizar o estado do Run')
            page.reload()
        page.wait_for_timeout(5000)
    raise Exception('Nenhum link ou botão Run válido encontrado para extrair URL do container.')

def extrair_info_container(page):
    """
    Extrai informações do container criado na interface:
    - id (h5.card-title)
    - stack (div.card-header)
    - backend_cpu, backend_ram, db_cpu, db_ram (parágrafos na card-body)
    Retorna um dicionário com esses dados.
    """
    info = {}
    # Extrai o id do container
    id_elem = page.query_selector('h5.card-title')
    info['id'] = id_elem.inner_text().strip() if id_elem else None
    # Extrai a stack
    stack_elem = page.query_selector('div.card-header')
    info['stack'] = stack_elem.inner_text().strip() if stack_elem else None
    # Extrai CPU/RAM Backend e Database
    backend_div = page.query_selector('div.card-body .d-flex .bg-primary-subtle:nth-child(1)')
    db_div = page.query_selector('div.card-body .d-flex .bg-primary-subtle:nth-child(2)')
    if backend_div:
        backend_texts = backend_div.inner_text().split('\n')
        for t in backend_texts:
            if 'Cpus:' in t:
                info['backend_cpu'] = t.split(':',1)[1].strip()
            if 'Memória Ram:' in t:
                info['backend_ram'] = t.split(':',1)[1].strip()
    if db_div:
        db_texts = db_div.inner_text().split('\n')
        for t in db_texts:
            if 'Cpus:' in t:
                info['db_cpu'] = t.split(':',1)[1].strip()
            if 'Memória Ram:' in t:
                info['db_ram'] = t.split(':',1)[1].strip()
    return info

def comparar_info_container(container_info, cenario):
    """
    Compara as informações extraídas da interface com o cenário atual.
    Lança exceção se houver incompatibilidade.
    """
    erros = []
    # Stack
    stack_cenario = str(cenario.get('backend', '')).strip().lower()
    stack_html = str(container_info.get('stack', '')).strip().lower()
    if stack_cenario not in stack_html:
        erros.append(f"Stack incompatível: esperado '{stack_cenario}', encontrado '{stack_html}'")
    # Backend CPU/RAM
    if str(cenario.get('backend_cpu')) not in str(container_info.get('backend_cpu', '')):
        erros.append(f"Backend CPU incompatível: esperado '{cenario.get('backend_cpu')}', encontrado '{container_info.get('backend_cpu')}'")
    if str(cenario.get('backend_ram')) not in str(container_info.get('backend_ram', '')):
        erros.append(f"Backend RAM incompatível: esperado '{cenario.get('backend_ram')}', encontrado '{container_info.get('backend_ram')}'")
    # DB CPU/RAM
    if str(cenario.get('db_cpu')) not in str(container_info.get('db_cpu', '')):
        erros.append(f"DB CPU incompatível: esperado '{cenario.get('db_cpu')}', encontrado '{container_info.get('db_cpu')}'")
    if str(cenario.get('db_ram')) not in str(container_info.get('db_ram', '')):
        erros.append(f"DB RAM incompatível: esperado '{cenario.get('db_ram')}', encontrado '{container_info.get('db_ram')}'")
    if erros:
        raise Exception('Incompatibilidade entre cenário e container extraído: ' + '; '.join(erros))

def excluir_container_ate_sucesso(page):
    """
    Tenta excluir o container até ter certeza que foi removido.
    Só retorna quando o botão Remove não estiver mais disponível.
    """
    BOTAO_REMOVE = 'a:has-text("Remove")'
    tentativas = 0
    while True:
        try:
            page.wait_for_selector(BOTAO_REMOVE, timeout=5000)
            page.click(BOTAO_REMOVE)
            page.wait_for_timeout(3000)
            tentativas += 1
        except Exception:
            # Se não encontrar mais o botão, consideramos removido
            break
        # Pequena pausa para garantir atualização da interface
        page.wait_for_timeout(1000)
        # Se já tentou muitas vezes, pode ser um erro
        if tentativas > 20:
            raise Exception('Não foi possível remover o container após várias tentativas.')

def executar_fluxo_de_teste(cenario: dict, page, app_url=None):
    """
    Executa todas as etapas para um cenário de teste.
    Agora extrai a URL do container criado e usa como BASE_URL no K6.
    Também salva informações do container no metrics.json.
    Valida se as informações extraídas batem com o cenário.
    Salva início, fim e duração do teste no metrics.json.
    """
    criar_container(page, cenario)
    aguardar_container_ativo(page)
    inicio = datetime.now(TZ)
    # Extrai a URL do container para usar no teste
    base_url = extrair_url_container(page)
    # Extrai informações do container
    container_info = extrair_info_container(page)
    # Valida compatibilidade
    comparar_info_container(container_info, cenario)
    script_path = cenario['k6_script']
    output_path = f"resultados/{cenario['nome']}.json"
    metrics_path = f"resultados/{cenario['nome']}_metrics.json"
    executar_k6(script_path, output_path, base_url=base_url, metrics_path=metrics_path)
    fim = datetime.now(TZ)
    duracao = (fim - inicio).total_seconds()
    # Adiciona as informações do container e do teste ao metrics.json
    try:
        with open(metrics_path, 'r') as f:
            metrics_data = json.load(f)
    except Exception:
        metrics_data = {}
    metrics_data['container_info'] = container_info
    metrics_data['inicio_teste'] = inicio.isoformat()
    metrics_data['fim_teste'] = fim.isoformat()
    metrics_data['duracao_segundos'] = duracao
    metrics_data['cenario'] = cenario
    # --- INTEGRAÇÃO PROMETHEUS ANTES DE EXCLUIR O CONTAINER ---
    time.sleep(5)  # Aguarda para garantir que o Prometheus colete as métricas
    config = carregar_config()
    prom_url = config.get('prometheus_url')
    container_id = container_info.get('id')
    if prom_url and container_id:
        prom_metrics = consultar_media_prometheus(prom_url, container_id, inicio, fim)
        metrics_data['prometheus_metrics'] = prom_metrics
    # --- FIM INTEGRAÇÃO PROMETHEUS ---
    with open(metrics_path, 'w') as f:
        json.dump(metrics_data, f, indent=4, ensure_ascii=False)
    excluir_container_ate_sucesso(page)

def carregar_config():
    with open('config.json', 'r') as f:
        return json.load(f)

def consultar_media_prometheus(prom_url, container_id, inicio, fim):
    from datetime import timezone
    inicio_utc = inicio.astimezone(timezone.utc)
    fim_utc = fim.astimezone(timezone.utc)
    intervalo = int((fim_utc - inicio_utc).total_seconds())
    if intervalo < 1:
        intervalo = 1
    # Remove traços do ID, se houver
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cenarios", default="cenarios.json", help="Arquivo JSON de cenários")
    parser.add_argument("--app_url", required=True, help="URL pública da aplicação React")
    args = parser.parse_args()

    cenarios = carregar_cenarios(args.cenarios)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = iniciar_navegador(playwright)
        context = browser.new_context()
        page = context.new_page()
        acessar_aplicacao(page, args.app_url)
        for cenario in cenarios:
            executar_fluxo_de_teste(cenario, page, app_url=args.app_url)
            # time.sleep(5)  # Espera 5 segundos entre os testes
        browser.close()

if __name__ == "__main__":
    # Como executar no terminal:
    # python main.py --cenarios cenarios.json --app_url http://localhost:3000
    main()
