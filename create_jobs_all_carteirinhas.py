import os
import sys
import time
import requests
from typing import List, Dict
from dotenv import load_dotenv

from automacao_carteirinhas import DatabaseManager

"""
Script: create_jobs_all_carteirinhas.py

Cria jobs para todas as carteirinhas da tabela 'carteirinhas'.
- Usa o endpoint POST /jobs da API (api_carteirinhas.py)
- Evita duplicidade opcionalmente (pendente/processing e sucesso recente)

Variáveis de ambiente:
- CARTEIRINHA_API_BASE_URL: Base URL da API (default: http://127.0.0.1:8002)
- API_TOKEN: Token Bearer (default: webscraping_api_token_2025)
- LIMIT: Limite máximo de carteirinhas a processar (default: sem limite)
- ONLY_ATIVAS: "true" para apenas carteirinhas ativas (default: false)
- SKIP_EXISTING: "true" para pular carteirinhas com job pendente/processing (default: true)
- SKIP_ACTIVE_PROCESSING: "true" para pular carteirinhas com processing ativo (default: true)
- SKIP_RECENT_SUCCESS_HOURS: horas para considerar sucesso recente e pular (default: 6)
- RATE_LIMIT_MS: atraso em ms entre requisições (default: 0)
"""

load_dotenv()

API_BASE = os.getenv("CARTEIRINHA_API_BASE_URL", "http://127.0.0.1:8002")
API_TOKEN = os.getenv("API_TOKEN", "webscraping_api_token_2025")

LIMIT = int(os.getenv("LIMIT", "0") or "0")
ONLY_ATIVAS = str(os.getenv("ONLY_ATIVAS", "false")).lower() == "true"
SKIP_EXISTING = str(os.getenv("SKIP_EXISTING", "true")).lower() == "true"
SKIP_ACTIVE_PROCESSING = str(os.getenv("SKIP_ACTIVE_PROCESSING", "true")).lower() == "true"
SKIP_RECENT_SUCCESS_HOURS = int(os.getenv("SKIP_RECENT_SUCCESS_HOURS", "6") or "6")
RATE_LIMIT_MS = int(os.getenv("RATE_LIMIT_MS", "0") or "0")

headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "accept": "application/json",
    "Content-Type": "application/json",
}


def fetch_carteirinhas(db: DatabaseManager) -> List[Dict]:
    if ONLY_ATIVAS:
        try:
            return db.get_carteirinhas_ativas()
        except Exception:
            pass
    # Fallback: buscar todas
    query = "SELECT id, carteiras, paciente, id_pagamento, status FROM carteirinhas ORDER BY id"
    rows = db.execute_query(query, fetch=True)
    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "carteiras": r[1],
            "paciente": r[2],
            "id_pagamento": r[3],
            "status": r[4],
        })
    return result


def has_pending_job(db: DatabaseManager, carteirinha: str) -> bool:
    try:
        rows = db.execute_query(
            """
            SELECT 1
              FROM job_carteirinhas
             WHERE type='sgucard'
               AND carteirinha=%s
               AND status IN ('pending','processing')
             LIMIT 1
            """,
            params=(carteirinha,),
            fetch=True,
        )
        return bool(rows)
    except Exception:
        return False


def should_skip(db: DatabaseManager, carteirinha: str) -> (bool, str):
    if not SKIP_EXISTING:
        return False, ""
    # processing ativo
    if SKIP_ACTIVE_PROCESSING:
        try:
            if db.has_active_processing_for_carteirinha(carteirinha):
                return True, "processing_active"
        except Exception:
            pass
    # sucesso recente
    try:
        if db.has_recent_success_for_carteirinha(carteirinha, min_hours=SKIP_RECENT_SUCCESS_HOURS):
            return True, "recent_success"
    except Exception:
        pass
    # pendente/processing existente
    try:
        if has_pending_job(db, carteirinha):
            return True, "pending_or_processing_exists"
    except Exception:
        pass
    return False, ""


def create_job(carteirinha: str) -> Dict:
    payload = {
        "type": "sgucard",
        "carteirinha": carteirinha,
        "carteira": carteirinha,
    }
    url = f"{API_BASE.rstrip('/')}/jobs"
    r = requests.post(url, json=payload, headers=headers, timeout=15)
    try:
        data = r.json()
    except Exception:
        data = {"status_code": r.status_code, "text": r.text[:200]}
    return {"http_status": r.status_code, "data": data}


def main():
    print("-- Iniciando criação de jobs para carteirinhas --")
    print({
        "API_BASE": API_BASE,
        "LIMIT": LIMIT,
        "ONLY_ATIVAS": ONLY_ATIVAS,
        "SKIP_EXISTING": SKIP_EXISTING,
        "SKIP_ACTIVE_PROCESSING": SKIP_ACTIVE_PROCESSING,
        "SKIP_RECENT_SUCCESS_HOURS": SKIP_RECENT_SUCCESS_HOURS,
        "RATE_LIMIT_MS": RATE_LIMIT_MS,
    })

    db = DatabaseManager()
    try:
        cards = fetch_carteirinhas(db)
        # deduplicar carteirinhas
        seen = set()
        items = []
        for c in cards:
            num = (c.get("carteiras") or c.get("carteirinha") or "").strip()
            if not num:
                continue
            if num in seen:
                continue
            seen.add(num)
            items.append({"carteirinha": num, "paciente": c.get("paciente")})

        total = len(items)
        print(f"Encontradas {total} carteirinhas únicas.")

        created = 0
        skipped = 0
        errors = 0

        limit = LIMIT if LIMIT and LIMIT > 0 else total
        for idx, item in enumerate(items[:limit], start=1):
            cart = item["carteirinha"]
            skip, reason = should_skip(db, cart)
            if skip:
                skipped += 1
                print(f"[{idx}/{limit}] SKIP {cart} ({reason})")
            else:
                try:
                    resp = create_job(cart)
                    if 200 <= resp["http_status"] < 300:
                        created += 1
                        print(f"[{idx}/{limit}] CREATED {cart} -> {resp['data'].get('status','')} ")
                    else:
                        errors += 1
                        print(f"[{idx}/{limit}] ERROR {cart} -> {resp['http_status']} {resp['data']}")
                except Exception as e:
                    errors += 1
                    print(f"[{idx}/{limit}] EXCEPTION {cart} -> {e}")
            if RATE_LIMIT_MS > 0:
                time.sleep(RATE_LIMIT_MS / 1000.0)

        print("-- Resumo --")
        print({
            "total": total,
            "processed": limit,
            "created": created,
            "skipped": skipped,
            "errors": errors,
        })
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()