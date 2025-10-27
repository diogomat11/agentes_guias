-- RPCs de gestão de fila de jobs para job_carteirinhas
-- claim_jobs, complete_job, fail_job, heartbeat_job, release_job, purge_stale_processing

-- Drops para permitir renomear parâmetros de funções
DROP FUNCTION IF EXISTS public.claim_jobs(text, integer, integer, text);
DROP FUNCTION IF EXISTS public.heartbeat_job(uuid, text, integer);

-- Função: claim_jobs
CREATE OR REPLACE FUNCTION public.claim_jobs(
  worker_id text,
  claim_limit integer DEFAULT 1,
  p_visibility_timeout_seconds integer DEFAULT 900,
  job_type text DEFAULT 'sgucard'
)
RETURNS SETOF public.job_carteirinhas
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_limit integer := GREATEST(claim_limit, 1);
BEGIN
  RETURN QUERY
  WITH available AS (
    SELECT j.id
      FROM public.job_carteirinhas j
     WHERE j.type = job_type
       AND j.status IN ('pending','error')
       AND (j.locked_until IS NULL OR j.locked_until < NOW())
     ORDER BY j.created_at ASC
     LIMIT v_limit
     FOR UPDATE SKIP LOCKED
  ),
  updated AS (
    UPDATE public.job_carteirinhas j
       SET status = 'processing',
           locked_by = worker_id,
           locked_at = NOW(),
           locked_until = NOW() + (p_visibility_timeout_seconds || ' seconds')::interval,
           attempts = COALESCE(j.attempts, 0) + 1,
           updated_at = NOW()
     WHERE j.id IN (SELECT id FROM available)
     RETURNING j.*
  )
  SELECT * FROM updated;
END;
$$;

-- Função: complete_job
CREATE OR REPLACE FUNCTION public.complete_job(
  job_id uuid,
  worker_id text,
  result jsonb DEFAULT NULL
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  updated_count integer;
BEGIN
  UPDATE public.job_carteirinhas j
     SET status = 'success',
         locked_by = NULL,
         locked_at = NULL,
         locked_until = NULL,
         updated_at = NOW()
   WHERE j.id = job_id
     AND j.locked_by = worker_id;
  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RETURN updated_count > 0;
END;
$$;

-- Função: fail_job
CREATE OR REPLACE FUNCTION public.fail_job(
  job_id uuid,
  worker_id text,
  p_error text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  updated_count integer;
BEGIN
  UPDATE public.job_carteirinhas j
     SET status = 'error',
         error = p_error,
         locked_by = NULL,
         locked_at = NULL,
         locked_until = NULL,
         updated_at = NOW()
   WHERE j.id = job_id
     AND j.locked_by = worker_id;
  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RETURN updated_count > 0;
END;
$$;

-- Função: heartbeat_job (renova visibilidade)
CREATE OR REPLACE FUNCTION public.heartbeat_job(
  job_id uuid,
  worker_id text,
  p_visibility_timeout_seconds integer DEFAULT 900
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  updated_count integer;
BEGIN
  UPDATE public.job_carteirinhas j
     SET locked_until = NOW() + (p_visibility_timeout_seconds || ' seconds')::interval,
         updated_at = NOW()
   WHERE j.id = job_id
     AND j.locked_by = worker_id
     AND j.status = 'processing';
  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RETURN updated_count > 0;
END;
$$;

-- Função: release_job (libera job para outro worker)
CREATE OR REPLACE FUNCTION public.release_job(
  job_id uuid,
  worker_id text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  updated_count integer;
BEGIN
  UPDATE public.job_carteirinhas j
     SET status = 'pending',
         locked_by = NULL,
         locked_at = NULL,
         locked_until = NULL,
         updated_at = NOW()
   WHERE j.id = job_id
     AND j.locked_by = worker_id
     AND j.status = 'processing';
  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RETURN updated_count > 0;
END;
$$;

-- Função: purge_stale_processing (reabre jobs expirados)
CREATE OR REPLACE FUNCTION public.purge_stale_processing(
  job_type text DEFAULT 'sgucard'
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  updated_count integer;
BEGIN
  UPDATE public.job_carteirinhas j
     SET status = 'pending',
         locked_by = NULL,
         locked_at = NULL,
         locked_until = NULL,
         updated_at = NOW()
   WHERE j.type = job_type
     AND j.status = 'processing'
     AND j.locked_until IS NOT NULL
     AND j.locked_until < NOW();
  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RETURN updated_count;
END;
$$;

-- Permissões de execução das funções RPC
GRANT EXECUTE ON FUNCTION public.claim_jobs(text, integer, integer, text) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.complete_job(uuid, text, jsonb) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.fail_job(uuid, text, text) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.heartbeat_job(uuid, text, integer) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.release_job(uuid, text) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.purge_stale_processing(text) TO authenticated, service_role;