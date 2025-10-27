import os
from dotenv import load_dotenv
from supabase import create_client

"""
Libera jobs em status 'processing' bloqueados pelo worker atual,
redefinindo status para 'pending' via RPC release_job.
"""

if __name__ == "__main__":
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    worker_id = os.getenv("WORKER_ID", "worker-carteirinhas")
    if not url or not key:
        raise SystemExit("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")

    client = create_client(url, key)

    # Buscar jobs processing do próprio worker
    res = (
        client.table("job_carteirinhas")
        .select("id,status,locked_by,carteirinha")
        .eq("status", "processing")
        .eq("locked_by", worker_id)
        .order("created_at", desc=False)
        .limit(50)
        .execute()
    )
    rows = res.data or []
    print(f"Encontrados {len(rows)} jobs em processing para {worker_id}")

    released = 0
    for r in rows:
        job_id = r.get("id")
        try:
            out = (
                client.table("job_carteirinhas").update({
                    "status": "pending",
                    "locked_by": None,
                    "locked_at": None,
                    "locked_until": None,
                    "updated_at": None,
                })
                .eq("id", job_id)
                .eq("locked_by", worker_id)
                .eq("status", "processing")
                .execute()
            )
            ok = bool(out.data)
            print({"job_id": job_id, "released": ok})
            if ok:
                released += 1
        except Exception as e:
            print({"job_id": job_id, "error": str(e)})

    print(f"Liberados: {released}/{len(rows)}")

    # Corrigir pendentes com lock ativo do mesmo worker
    fix_res = (
        client.table("job_carteirinhas")
        .select("id,status,locked_by")
        .eq("status", "pending")
        .eq("locked_by", worker_id)
        .limit(50)
        .execute()
    )
    fix_rows = fix_res.data or []
    fixed = 0
    for r in fix_rows:
        job_id = r.get("id")
        try:
            out = (
                client.table("job_carteirinhas").update({
                    "locked_by": None,
                    "locked_at": None,
                    "locked_until": None,
                    "updated_at": None,
                })
                .eq("id", job_id)
                .eq("locked_by", worker_id)
                .eq("status", "pending")
                .execute()
            )
            ok = bool(out.data)
            print({"job_id": job_id, "fixed_lock": ok})
            if ok:
                fixed += 1
        except Exception as e:
            print({"job_id": job_id, "error_fix": str(e)})
    print(f"Locks limpos em pendentes: {fixed}/{len(fix_rows)}")