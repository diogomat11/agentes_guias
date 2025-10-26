import os
import time
import logging
import requests
import json
from typing import Dict, List
from dotenv import load_dotenv
import threading

from automacao_carteirinhas import AutomacaoCarteirinhas, DatabaseManager

load_dotenv()

logger = logging.getLogger("worker_carteirinhas")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


def _build_verificar_url() -> str:
    """Resolve a URL do endpoint de verificar carteirinha."""
    url = os.getenv("VERIFICAR_CARTEIRINHA_URL")
    base = os.getenv("CARTEIRINHA_API_BASE_URL")
    if not url:
        if base:
            url = f"{base.rstrip('/')}/verificar_carteirinha"
        else:
            url = "http://127.0.0.1:8002/verificar_carteirinha"
    return url


def _build_real_url() -> str:
    """Resolve a URL do endpoint de automação real."""
    url = os.getenv("EXECUTAR_WEBSCRAPING_REAL_URL")
    base = os.getenv("CARTEIRINHA_API_BASE_URL")
    if not url:
        if base:
            url = f"{base.rstrip('/')}/executar_webscraping_real"
        else:
            url = "http://127.0.0.1:8002/executar_webscraping_real"
    return url


def trigger_webscraping_real(carteirinha: str) -> Dict:
    """Chama POST /executar_webscraping_real com query param carteirinha."""
    url = _build_real_url()
    token = os.getenv("API_TOKEN", "")
    headers = {
        "Authorization": f"Bearer {token}",
    }
    params = {"carteirinha": carteirinha}
    # Logar comando curl equivalente
    curl_cmd = (
        f"curl -X 'POST' '{url}?carteirinha={carteirinha}' "
        f"-H 'accept: application/json' "
        f"-H 'Authorization: Bearer {token}'"
    )
    logger.info(f"[worker] Enviando requisição (real): {curl_cmd}")
    resp = requests.post(url, params=params, headers=headers, timeout=int(os.getenv("CARTEIRINHA_API_TIMEOUT", "60")))
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code}


def trigger_verificar_carteirinha(carteirinha: str, base_url: str = None) -> Dict:
    """Chama POST /verificar_carteirinha na API, opcionalmente usando base_url específica."""
    url = (f"{base_url.rstrip('/')}" + "/verificar_carteirinha") if base_url else _build_verificar_url()
    token = os.getenv("API_TOKEN", "")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"carteirinha": carteirinha}
    # Logar comando curl equivalente
    curl_cmd = (
        f"curl -X 'POST' '{url}' "
        f"-H 'accept: application/json' "
        f"-H 'Authorization: Bearer {token}' "
        f"-H 'Content-Type: application/json' "
        f"-d '{json.dumps(payload)}'"
    )
    logger.info(f"[worker] Enviando requisição: {curl_cmd}")
    resp = requests.post(url, json=payload, headers=headers, timeout=int(os.getenv("CARTEIRINHA_API_TIMEOUT", "30")))
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code}


def _extract_error_from_result(result: Dict) -> str:
    """Extrai mensagem de erro amigável do payload da API."""
    if not isinstance(result, dict):
        return "Resposta inválida da API"
    # Estrutura esperada: { status, carteirinha, resultado: { status, message?, erro? } }
    msg = None
    inner = result.get("resultado") or {}
    msg = inner.get("message") or inner.get("erro") or result.get("detail")
    if not msg:
        msg = f"Status da API: {result.get('status')}"
    return str(msg)


def worker_loop(worker_id: str, claim_batch: int = 1, poll_interval: int = 5):
    """Loop principal do worker: consome jobs e distribui entre múltiplos servidores."""
    # Configurar lista de servidores de API
    servers_env = os.getenv("API_SERVER_URLS", "").strip()
    servers: List[str] = [u.strip().rstrip('/') for u in servers_env.split(',') if u.strip()]
    if not servers:
        # fallback para um único servidor
        base = os.getenv("CARTEIRINHA_API_BASE_URL", "http://127.0.0.1:8002").rstrip('/')
        servers = [base]

    server_busy = {srv: False for srv in servers}
    busy_lock = threading.Lock()

    logger.info(f"Worker iniciado: {worker_id}, poll_interval={poll_interval}s, servidores={servers}")

    automacao = AutomacaoCarteirinhas()
    db: DatabaseManager = automacao.db_manager

    def process_job_on_server(job: Dict, server_url: str, slot_id: str):
        job_id = job.get("id")
        carteirinha = job.get("carteirinha") or job.get("carteira")
        try:
            logger.info(f"[slot {slot_id}] Processando job={job_id} carteirinha={carteirinha} no servidor {server_url}")
            result = trigger_verificar_carteirinha(carteirinha, base_url=server_url)
            status_api = str(result.get("status", "")).lower()
            if status_api == "erro":
                err_msg = _extract_error_from_result(result)
                logger.warning(f"[slot {slot_id}] API retornou erro para job={job_id}: {err_msg}")
                ok = db.fail_job(job_id, slot_id, err_msg)
                if not ok:
                    logger.warning(f"[slot {slot_id}] Falha ao marcar erro para job {job_id}")
            else:
                logger.info(f"[slot {slot_id}] API aceitou requisição para job={job_id}; automação marcará sucesso.")
            # Cooldown pós-job opcional
            try:
                cooldown = int(os.getenv("POST_JOB_COOLDOWN_SECONDS", "0"))
                if cooldown > 0:
                    logger.info(f"[slot {slot_id}] Cooldown pós-job {cooldown}s para carteirinha={carteirinha}")
                    time.sleep(cooldown)
            except Exception:
                pass
        except Exception as call_err:
            logger.warning(f"[slot {slot_id}] Falha ao chamar API para job={job_id}: {call_err}")
            ok = db.fail_job(job_id, slot_id, f"API call failed: {call_err}")
            if not ok:
                logger.warning(f"[slot {slot_id}] Falha ao marcar erro para job {job_id}")
        finally:
            with busy_lock:
                server_busy[server_url] = False

    while True:
        try:
            # Determinar quantos servidores estão livres
            with busy_lock:
                free_servers = [srv for srv in servers if not server_busy[srv]]
            if not free_servers:
                time.sleep(poll_interval)
                continue

            # Buscar até N jobs (N = servidores livres)
            jobs: List[Dict] = []
            try:
                jobs = db.claim_jobs(worker_id, claim_limit=len(free_servers))
            except Exception as e:
                logger.error(f"Erro ao reivindicar jobs: {e}")
            if not jobs:
                jobs = db.fetch_jobs_simple(limit=len(free_servers))
            if not jobs:
                time.sleep(poll_interval)
                continue

            # Distribuir jobs em servidores livres
            ji = 0
            for server_url in free_servers:
                if ji >= len(jobs):
                    break
                job = jobs[ji]
                ji += 1
                job_id = job.get("id")
                carteirinha = job.get("carteirinha") or job.get("carteira")
                if not carteirinha:
                    logger.warning(f"Job {job_id} sem carteirinha; marcando como falho")
                    ok = db.fail_job(job_id, worker_id, "Job sem carteirinha")
                    if not ok:
                        logger.warning(f"Falha ao marcar erro para job {job_id}")
                    continue
                status_job = str(job.get("status", "")).lower()
                if status_job in ("success", "processing"):
                    logger.info(f"Pulando job {job_id} status={status_job} (success/processing).")
                    continue

                slot_id = f"{worker_id}:{servers.index(server_url)+1}"
                vt = int(os.getenv("VISIBILITY_TIMEOUT_SECONDS", "900"))
                started = db.start_job_processing(job_id, slot_id, visibility_timeout_seconds=vt)
                if not started:
                    logger.info(f"Job {job_id} não pôde ser iniciado (status mudou ou em processamento). Pulando.")
                    continue

                # Alocar servidor e iniciar thread
                with busy_lock:
                    server_busy[server_url] = True
                t = threading.Thread(target=process_job_on_server, args=(job, server_url, slot_id), daemon=True)
                t.start()

            # Aguardar até próximo ciclo de verificação
            time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("Worker interrompido pelo usuário")
            break
        except Exception as e:
            logger.error(f"Erro no loop do worker: {e}")
            time.sleep(poll_interval)


if __name__ == "__main__":
    worker_id = os.getenv("WORKER_ID", "worker-carteirinhas")
    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
    worker_loop(worker_id, poll_interval=poll_interval)