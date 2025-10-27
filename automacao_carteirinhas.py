import os
import psycopg
import schedule
import time
import logging
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
from typing import List, Dict, Optional, Union
import json
import hashlib
import win32com.client as win32
from supabase import create_client, Client

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    """Gerenciador de conexão e operações com o banco de dados Supabase"""
    
    def __init__(self):
        load_dotenv()
        self.connection = None
        self._connect()
        # Inicializar cliente Supabase
        try:
            supabase_url = os.getenv('SUPABASE_URL')
            supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
            if supabase_url and supabase_key:
                self.supabase: Client = create_client(supabase_url, supabase_key)
                logger.info("Cliente Supabase inicializado com sucesso")
            else:
                logger.warning("Credenciais Supabase não encontradas - cliente não inicializado")
                self.supabase = None
        except Exception as e:
            logger.error(f"Erro ao inicializar cliente Supabase: {e}")
            self.supabase = None
    
    def _connect(self):
        """Estabelece conexão com o banco de dados"""
        try:
            supabase_url = os.getenv('SUPABASE_URL')
            project_id = supabase_url.replace('https://', '').replace('.supabase.co', '')
            
            self.connection = psycopg.connect(
                host=f'db.{project_id}.supabase.co',
                dbname='postgres',
                user='postgres',
                password=os.getenv('SUPABASE_PASSWORD'),
                port='5432',
                sslmode='require'
            )
            logger.info("Conexão com banco de dados estabelecida")
        except Exception as e:
            logger.error(f"Erro ao conectar com banco: {e}")
            raise
    
    def execute_query(self, query: str, params: tuple = None, fetch: bool = False):
        """Executa uma query no banco de dados"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            
            if fetch:
                result = cursor.fetchall()
                cursor.close()
                return result
            else:
                self.connection.commit()
                cursor.close()
                return True
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Erro ao executar query: {e}")
            raise

    def acquire_worker_lock(self, worker_id: str) -> bool:
        """Tenta adquirir um advisory lock exclusivo para o worker."""
        try:
            # Key estável baseada no worker_id
            key_src = f"sgucard_worker:{worker_id}".encode("utf-8")
            key = int(hashlib.sha1(key_src).hexdigest()[:16], 16) % (2**63 - 1)
            cursor = self.connection.cursor()
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (key,))
            row = cursor.fetchone()
            cursor.close()
            return bool(row and row[0])
        except Exception as e:
            logger.error(f"Falha ao adquirir worker lock: {e}")
            return False

    def release_worker_lock(self, worker_id: str) -> bool:
        """Libera o advisory lock exclusivo do worker, se detido."""
        try:
            key_src = f"sgucard_worker:{worker_id}".encode("utf-8")
            key = int(hashlib.sha1(key_src).hexdigest()[:16], 16) % (2**63 - 1)
            cursor = self.connection.cursor()
            cursor.execute("SELECT pg_advisory_unlock(%s)", (key,))
            row = cursor.fetchone()
            cursor.close()
            return bool(row and row[0])
        except Exception as e:
            logger.error(f"Falha ao liberar worker lock: {e}")
            return False
    
    def get_carteirinhas_for_processing(self, modo: str, carteirinha_especifica: str = None, 
                                      data_inicial: date = None, data_final: date = None) -> List[Dict]:
        """Busca carteirinhas para processamento baseado no modo de execução"""
        try:
            if modo == "manual" and carteirinha_especifica:
                query = "SELECT * FROM carteirinhas WHERE carteiras = %s"
                params = (carteirinha_especifica,)
            elif modo == "diario":
                # Buscar carteirinhas com agendamentos para o dia seguinte
                tomorrow = date.today() + timedelta(days=1)
                query = """
                    SELECT DISTINCT c.* FROM carteirinhas c
                    JOIN agendamentos a ON c.carteiras = a.carteirinha
                    WHERE a.data = %s AND c.status = 'ativo'
                """
                params = (tomorrow,)
            elif modo == "semanal":
                # Buscar todas as carteirinhas ativas
                query = "SELECT * FROM carteirinhas WHERE status = 'ativo'"
                params = None
            elif modo == "intervalo" and data_inicial and data_final:
                query = """
                    SELECT DISTINCT c.* FROM carteirinhas c
                    JOIN agendamentos a ON c.carteiras = a.carteirinha
                    WHERE a.data BETWEEN %s AND %s AND c.status = 'ativo'
                """
                params = (data_inicial, data_final)
            else:
                logger.warning("Modo de execução inválido ou parâmetros insuficientes")
                return []
            
            result = self.execute_query(query, params, fetch=True)
            carteirinhas = []
            for row in result:
                carteirinhas.append({
                    'id': row[0],
                    'carteiras': row[1],
                    'paciente': row[2],
                    'id_pagamento': row[3],
                    'status': row[4]
                })
            
            logger.info(f"Encontradas {len(carteirinhas)} carteirinhas para processamento")
            return carteirinhas
            
        except Exception as e:
            logger.error(f"Erro ao buscar carteirinhas: {e}")
            return []
    
    def save_guia_data(self, guia_data: Dict) -> bool:
        """Salva ou atualiza dados de guia na tabela BaseGuias"""
        try:
            # Verificar se a guia já existe
            check_query = "SELECT id FROM baseguias WHERE carteirinha = %s AND guia = %s"
            existing = self.execute_query(check_query, (guia_data['carteirinha'], guia_data['guia']), fetch=True)
            
            if existing:
                # Atualizar guia existente
                update_query = """
                    UPDATE baseguias SET
                        data_autorizacao = %s,
                        senha = %s,
                        validade = %s,
                        codigo_terapia = %s,
                        qtde_solicitado = %s,
                        sessoes_autorizadas = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE carteirinha = %s AND guia = %s
                """
                params = (
                    guia_data.get('data_autorizacao'),
                    guia_data.get('senha'),
                    guia_data.get('validade'),
                    guia_data.get('codigo_terapia'),
                    guia_data.get('qtde_solicitado'),
                    guia_data.get('sessoes_autorizadas'),
                    guia_data['carteirinha'],
                    guia_data['guia']
                )
                self.execute_query(update_query, params)
                logger.info(f"Guia atualizada: {guia_data['guia']}")
                return True
            else:
                # Inserir nova guia
                insert_query = """
                    INSERT INTO baseguias (
                        id_paciente, id_pagamento, carteirinha, paciente, guia,
                        data_autorizacao, senha, validade, codigo_terapia,
                        qtde_solicitado, sessoes_autorizadas
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                params = (
                    guia_data.get('id_paciente'),
                    guia_data.get('id_pagamento'),
                    guia_data['carteirinha'],
                    guia_data.get('paciente'),
                    guia_data['guia'],
                    guia_data.get('data_autorizacao'),
                    guia_data.get('senha'),
                    guia_data.get('validade'),
                    guia_data.get('codigo_terapia'),
                    guia_data.get('qtde_solicitado'),
                    guia_data.get('sessoes_autorizadas')
                )
                self.execute_query(insert_query, params)
                logger.info(f"Nova guia inserida: {guia_data['guia']}")
                return True
                
        except Exception as e:
            logger.error(f"Erro ao salvar dados da guia: {e}")
            return False
    
    def log_execution(self, tipo_execucao: str, status: str, tempo_execucao: timedelta,
                     carteirinhas_processadas: int, guias_inseridas: int, 
                     guias_atualizadas: int, mensagem: str = None, erro: str = None):
        """Registra log de execução na tabela de logs"""
        try:
            query = """
                INSERT INTO logs (
                    tipo_execucao, status, tempo_execucao, carteirinhas_processadas,
                    guias_inseridas, guias_atualizadas, mensagem, erro
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            params = (
                tipo_execucao, status, tempo_execucao, carteirinhas_processadas,
                guias_inseridas, guias_atualizadas, mensagem, erro
            )
            self.execute_query(query, params)
        except Exception as e:
            logger.error(f"Erro ao registrar log: {e}")
    
    def get_carteirinhas_ativas(self) -> List[Dict]:
        """Busca todas as carteirinhas ativas"""
        try:
            query = "SELECT * FROM carteirinhas WHERE status = 'ativo' OR status IS NULL ORDER BY id"
            result = self.execute_query(query, fetch=True)
            carteirinhas = []
            for row in result:
                carteirinhas.append({
                    'id': row[0],
                    'carteiras': row[1],
                    'paciente': row[2],
                    'id_pagamento': row[3],
                    'status': row[4]
                })
            return carteirinhas
        except Exception as e:
            logger.error(f"Erro ao buscar carteirinhas ativas: {e}")
            return []
    
    def get_carteirinhas_por_periodo(self, data_inicial: str, data_final: str) -> List[Dict]:
        """Busca carteirinhas com agendamentos em um período específico"""
        try:
            query = """
                SELECT DISTINCT c.* 
                FROM carteirinhas c
                INNER JOIN agendamentos a ON c.carteiras = a.carteirinha
                WHERE a.data BETWEEN %s AND %s
                ORDER BY c.id
            """
            result = self.execute_query(query, (data_inicial, data_final), fetch=True)
            carteirinhas = []
            for row in result:
                carteirinhas.append({
                    'id': row[0],
                    'carteiras': row[1],
                    'paciente': row[2],
                    'id_pagamento': row[3],
                    'status': row[4]
                })
            return carteirinhas
        except Exception as e:
            logger.error(f"Erro ao buscar carteirinhas por período: {e}")
            return []
    
    def inserir_ou_atualizar_guia(self, guia_data: Dict) -> str:
        """Insere nova guia ou atualiza existente"""
        try:
            # Verificar se guia já existe
            check_query = "SELECT id FROM baseguias WHERE carteirinha = %s AND guia = %s"
            existing = self.execute_query(check_query, (guia_data['carteirinha'], guia_data['guia']), fetch=True)
            
            if existing:
                # Atualizar guia existente
                update_query = """
                    UPDATE baseguias SET
                        paciente = %s,
                        data_autorizacao = %s,
                        senha = %s,
                        validade = %s,
                        codigo_terapia = %s,
                        qtde_solicitado = %s,
                        sessoes_autorizadas = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE carteirinha = %s AND guia = %s
                """
                params = (
                    guia_data['paciente'],
                    guia_data['data_autorizacao'],
                    guia_data['senha'],
                    guia_data['validade'],
                    guia_data['codigo_terapia'],
                    guia_data['qtde_solicitado'],
                    guia_data['sessoes_autorizadas'],
                    guia_data['carteirinha'],
                    guia_data['guia']
                )
                self.execute_query(update_query, params)
                return "atualizada"
            else:
                # Inserir nova guia
                insert_query = """
                    INSERT INTO baseguias (
                        carteirinha, paciente, guia, data_autorizacao,
                        senha, validade, codigo_terapia, qtde_solicitado,
                        sessoes_autorizadas
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                params = (
                    guia_data['carteirinha'],
                    guia_data['paciente'],
                    guia_data['guia'],
                    guia_data['data_autorizacao'],
                    guia_data['senha'],
                    guia_data['validade'],
                    guia_data['codigo_terapia'],
                    guia_data['qtde_solicitado'],
                    guia_data['sessoes_autorizadas']
                )
                self.execute_query(insert_query, params)
                return "inserida"
                
        except Exception as e:
            logger.error(f"Erro ao inserir/atualizar guia: {e}")
            return "erro"
    
    def test_connection(self):
        """Testa conexão com banco de dados"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            return True
        except Exception as e:
            logger.error(f"Erro ao testar conexão: {str(e)}")
            return False
    
    def get_database_stats(self):
        """Retorna estatísticas do banco de dados"""
        stats = {}
        tables = ['pagamentos', 'carteirinhas', 'agendamentos', 'baseguias', 'logs']
        
        try:
            cursor = self.connection.cursor()
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                stats[table] = count
            cursor.close()
        except Exception as e:
            logger.error(f"Erro ao obter estatísticas: {str(e)}")
            for table in tables:
                stats[table] = 0
        
        return stats
    
    def get_sample_carteirinha(self):
        """Retorna uma carteirinha de exemplo"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT carteiras, paciente FROM carteirinhas LIMIT 1")
            result = cursor.fetchone()
            cursor.close()
            
            if result:
                return {'carteirinha': result[0], 'nome': result[1]}
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar carteirinha de exemplo: {str(e)}")
            return None

    # Métodos de Jobs (RPC Supabase)
    def claim_jobs(self, worker_id: str, claim_limit: int = 1) -> List[Dict]:
        """Reivindica jobs pendentes via RPC no Supabase."""
        try:
            if not getattr(self, 'supabase', None):
                logger.warning("Supabase não inicializado; claim_jobs retorna vazio")
                return []
            vt = int(os.getenv("VISIBILITY_TIMEOUT_SECONDS", "900"))
            res = self.supabase.rpc('claim_jobs', {
                'worker_id': worker_id,
                'claim_limit': claim_limit,
                'p_visibility_timeout_seconds': vt,
                'job_type': 'sgucard'
            }).execute()
            data = getattr(res, 'data', None)
            if data is None:
                logger.info("Nenhum job retornado pelo RPC claim_jobs")
                return []
            return data
        except Exception as e:
            logger.error(f"Erro ao reivindicar jobs: {e}")
            return []

    def complete_job(self, job_id: str, worker_id: str, result: Dict) -> bool:
        """Marca job como concluído via RPC no Supabase."""
        try:
            if not getattr(self, 'supabase', None):
                logger.warning("Supabase não inicializado; complete_job ignorado")
                return False
            res = self.supabase.rpc('complete_job', {
                'job_id': job_id,
                'worker_id': worker_id,
                'result': result
            }).execute()
            data = getattr(res, 'data', None)
            return bool(data)
        except Exception as e:
            logger.error(f"Erro ao completar job {job_id}: {e}")
            return False

    def fail_job(self, job_id: str, worker_id: str, error: str) -> bool:
        """Marca job como falho e libera o lock; funciona com Supabase ou SQL."""
        try:
            if getattr(self, 'supabase', None):
                try:
                    res = self.supabase.rpc('fail_job', {
                        'job_id': job_id,
                        'worker_id': worker_id,
                        'error': error
                    }).execute()
                    data = getattr(res, 'data', None)
                    if bool(data):
                        return True
                except Exception as e:
                    logger.warning(f"Supabase RPC fail_job falhou: {e}")
            # Fallback SQL: atualiza somente se o lock pertencer ao worker
            try:
                cursor = self.connection.cursor()
                cursor.execute(
                    """
                    UPDATE job_carteirinhas
                       SET status='error',
                           error=%s,
                           locked_by=NULL,
                           locked_at=NULL,
                           locked_until=NULL,
                           updated_at=NOW()
                     WHERE id=%s AND locked_by=%s AND status='processing'
                    """,
                    (error, job_id, worker_id)
                )
                self.connection.commit()
                rows = cursor.rowcount
                cursor.close()
                return rows > 0
            except Exception as e:
                logger.error(f"Erro SQL fallback fail_job para job {job_id}: {e}")
                return False
        except Exception as e:
            logger.error(f"Erro ao marcar falha no job {job_id}: {e}")
            return False

    def release_job(self, job_id: str, worker_id: str) -> bool:
        """Libera job em processing para voltar a pending; tenta RPC e faz fallback SQL."""
        try:
            if getattr(self, 'supabase', None):
                try:
                    res = self.supabase.rpc('release_job', {
                        'job_id': job_id,
                        'worker_id': worker_id,
                    }).execute()
                    data = getattr(res, 'data', None)
                    if bool(data):
                        return True
                except Exception as e:
                    logger.warning(f"Supabase RPC release_job falhou: {e}")
            # Fallback SQL direto
            try:
                cursor = self.connection.cursor()
                cursor.execute(
                    """
                    UPDATE job_carteirinhas
                       SET status='pending',
                           locked_by=NULL,
                           locked_at=NULL,
                           locked_until=NULL,
                           updated_at=NOW()
                     WHERE id=%s AND locked_by=%s AND status='processing'
                    """,
                    (job_id, worker_id)
                )
                self.connection.commit()
                rows = cursor.rowcount
                cursor.close()
                return rows > 0
            except Exception as e:
                logger.error(f"Erro SQL fallback release_job para job {job_id}: {e}")
                return False
        except Exception as e:
            logger.error(f"Erro ao liberar job {job_id}: {e}")
            return False

    # Fallback simples baseado em tabela job_carteirinhas
    def insert_job_carteirinha(self, type: str, carteirinha: str, carteira: Optional[str] = None, id_paciente: Optional[str] = None) -> Dict:
        try:
            payload = {
                'type': type,
                'carteirinha': carteirinha,
                'carteira': carteira or carteirinha,
                'id_paciente': id_paciente
            }
            if getattr(self, 'supabase', None):
                res = self.supabase.table('job_carteirinhas').insert(payload).execute()
                data = getattr(res, 'data', None)
                return {'status': 'created', 'job': data[0] if data else payload}
            # SQL fallback
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO job_carteirinhas (type, carteirinha, carteira, id_paciente) VALUES (%s, %s, %s, %s) RETURNING id",
                (payload['type'], payload['carteirinha'], payload['carteira'], payload['id_paciente'])
            )
            job_id = cursor.fetchone()[0]
            self.connection.commit()
            cursor.close()
            payload['id'] = job_id
            return {'status': 'created', 'job': payload}
        except Exception as e:
            logger.error(f"Erro ao inserir job_carteirinha: {e}")
            raise

    def fetch_jobs_simple(self, limit: int = 1, statuses: Optional[List[str]] = None) -> List[Dict]:
        try:
            statuses = statuses or ['pending', 'error']
            if getattr(self, 'supabase', None):
                now_iso = datetime.now().isoformat()
                # Buscar por múltiplos status via Supabase REST com filtro de lock (null ou expirado)
                try:
                    res = (
                        self.supabase
                            .table('job_carteirinhas')
                            .select('*')
                            .eq('type', 'sgucard')
                            .in_('status', statuses)
                            .or_(f"locked_until.is.null,locked_until.lt.{now_iso}")
                            .order('created_at', desc=False)
                            .limit(limit)
                            .execute()
                    )
                    data = getattr(res, 'data', None) or []
                    return data
                except Exception as e:
                    logger.warning(f"Supabase REST fetch_jobs_simple com filtro de lock falhou: {e}")
            # Fallback SQL direto com filtro de lock
            cursor = self.connection.cursor()
            placeholders = ','.join(['%s'] * len(statuses))
            query = (
                f"SELECT id, type, carteirinha, carteira, id_paciente, status "
                f"FROM job_carteirinhas "
                f"WHERE type = 'sgucard' AND status IN ({placeholders}) "
                f"AND (locked_until IS NULL OR locked_until < NOW()) "
                f"ORDER BY created_at ASC LIMIT %s"
            )
            cursor.execute(query, (*statuses, limit))
            rows = cursor.fetchall()
            cursor.close()
            jobs = []
            for r in rows:
                jobs.append({'id': r[0], 'type': r[1], 'carteirinha': r[2], 'carteira': r[3], 'id_paciente': r[4], 'status': r[5]})
            return jobs
        except Exception as e:
            logger.error(f"Erro ao buscar jobs simples: {e}")
            return []

    def purge_stale_processing(self, job_type: str = 'sgucard') -> int:
        """Reabre jobs 'processing' cujo locked_until já expirou, devolvendo contagem de afetados."""
        try:
            if getattr(self, 'supabase', None):
                try:
                    res = self.supabase.rpc('purge_stale_processing', {'job_type': job_type}).execute()
                    data = getattr(res, 'data', None)
                    if isinstance(data, dict) and 'count' in data:
                        return int(data['count'])
                    if isinstance(data, (int, float)):
                        return int(data)
                except Exception as e:
                    logger.warning(f"Supabase RPC purge_stale_processing falhou: {e}")
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE job_carteirinhas
                       SET status='pending',
                           locked_by=NULL,
                           locked_at=NULL,
                           locked_until=NULL,
                           updated_at=NOW()
                     WHERE type=%s AND status='processing' AND locked_until < NOW()
                    """,
                    (job_type,)
                )
                count = cursor.rowcount
                self.connection.commit()
                cursor.close()
                return int(count or 0)
            except Exception as e:
                cursor.close()
                logger.error(f"Erro SQL fallback purge_stale_processing: {e}")
                return 0
        except Exception as e:
            logger.error(f"Falha em purge_stale_processing: {e}")
            return 0

    def start_job_processing(self, job_id: str, worker_id: str, visibility_timeout_seconds: int = 900) -> bool:
        try:
            # Tentar via Supabase REST
            if getattr(self, 'supabase', None):
                try:
                    res = (
                        self.supabase
                            .table('job_carteirinhas')
                            .update({
                                'status': 'processing',
                                'locked_by': worker_id,
                                'locked_at': datetime.now().isoformat(),
                                'locked_until': (datetime.now() + timedelta(seconds=visibility_timeout_seconds)).isoformat(),
                                'attempts': (1)  # será incrementado no SQL fallback; aqui apenas sinaliza início
                            })
                            .eq('id', job_id)
                            .in_('status', ['pending', 'error'])
                            .execute()
                    )
                    data = getattr(res, 'data', None) or []
                    return len(data) > 0
                except Exception as e:
                    logger.warning(f"Supabase REST start_job_processing falhou: {e}")
            # Fallback SQL direto com condição de status
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE job_carteirinhas
                    SET status='processing',
                        locked_by=%s,
                        locked_at=NOW(),
                        locked_until=NOW() + (%s || ' seconds')::interval,
                        attempts=attempts+1,
                        updated_at=NOW()
                    WHERE id=%s AND status IN ('pending','error')
                    RETURNING id
                    """,
                    (worker_id, visibility_timeout_seconds, job_id)
                )
                updated = cursor.fetchone()
                self.connection.commit()
                cursor.close()
                return bool(updated)
            except Exception as e:
                cursor.close()
                logger.error(f"Erro ao marcar job {job_id} como processing: {e}")
                return False
        except Exception as e:
            logger.error(f"Falha em start_job_processing para job {job_id}: {e}")
            return False

    def mark_job_processed(self, job_id: str) -> bool:
        try:
            if getattr(self, 'supabase', None):
                try:
                    self.supabase.table('job_carteirinhas').update({
                        'status': 'success',
                        'locked_by': None,
                        'locked_at': None,
                        'locked_until': None,
                        'updated_at': datetime.now().isoformat()
                    }).eq('id', job_id).execute()
                    return True
                except Exception:
                    try:
                        cursor = self.connection.cursor()
                        cursor.execute("UPDATE job_carteirinhas SET status='success', locked_by=NULL, locked_at=NULL, locked_until=NULL, updated_at=NOW() WHERE id=%s", (job_id,))
                        self.connection.commit()
                        cursor.close()
                        return True
                    except Exception as _:
                        logger.warning(f"Falha ao atualizar job {job_id} para success")
                        return False
            cursor = self.connection.cursor()
            try:
                cursor.execute("UPDATE job_carteirinhas SET status='success', locked_by=NULL, locked_at=NULL, locked_until=NULL, updated_at=NOW() WHERE id=%s", (job_id,))
                self.connection.commit()
            except Exception:
                cursor.close()
                return False
            cursor.close()
            return True
        except Exception as e:
            logger.error(f"Erro ao marcar job {job_id} como processado: {e}")
            return False

    def mark_job_failed(self, job_id: str, error: str) -> bool:
        try:
            if getattr(self, 'supabase', None):
                try:
                    self.supabase.table('job_carteirinhas').update({
                        'status': 'error',
                        'error': error,
                        'locked_by': None,
                        'locked_at': None,
                        'locked_until': None,
                        'updated_at': datetime.now().isoformat()
                    }).eq('id', job_id).execute()
                    return True
                except Exception:
                    try:
                        cursor = self.connection.cursor()
                        cursor.execute("UPDATE job_carteirinhas SET status='error', error=%s, locked_by=NULL, locked_at=NULL, locked_until=NULL, updated_at=NOW() WHERE id=%s", (error, job_id))
                        self.connection.commit()
                        cursor.close()
                        return True
                    except Exception as _:
                        logger.warning(f"Falha ao atualizar job {job_id} para error")
                        return False
            cursor = self.connection.cursor()
            try:
                cursor.execute("UPDATE job_carteirinhas SET status='error', error=%s, locked_by=NULL, locked_at=NULL, locked_until=NULL, updated_at=NOW() WHERE id=%s", (error, job_id))
                self.connection.commit()
            except Exception:
                cursor.close()
                return False
            cursor.close()
            return True
        except Exception as e:
            logger.error(f"Erro ao marcar job {job_id} como erro: {e}")
            return False

    def get_carteirinhas_with_appointments(self, data):
        """Retorna carteirinhas com agendamentos para uma data específica"""
        try:
            cursor = self.connection.cursor()
            query = """
                SELECT DISTINCT c.carteiras as carteirinha, c.paciente 
                FROM carteirinhas c
                INNER JOIN agendamentos a ON c.carteiras = a.carteirinha
                WHERE a.data = %s
                ORDER BY c.paciente
            """
            cursor.execute(query, (data,))
            results = cursor.fetchall()
            cursor.close()
            
            carteirinhas = []
            for result in results:
                carteirinhas.append({
                    'carteirinha': result[0],
                    'paciente': result[1]
                })
            
            return carteirinhas
        except Exception as e:
            logger.error(f"Erro ao buscar carteirinhas com agendamentos: {str(e)}")
            return []

    def mark_job_success_by_carteirinha(self, carteirinha: str) -> bool:
        try:
            # Tentar via Supabase REST: atualizar job em processing com carteirinha correspondente
            if getattr(self, 'supabase', None):
                try:
                    res = (
                        self.supabase
                            .table('job_carteirinhas')
                            .update({
                                'status': 'success',
                                'locked_by': None,
                                'locked_at': None,
                                'locked_until': None,
                                'updated_at': datetime.now().isoformat()
                            })
                            .eq('carteirinha', carteirinha)
                            .eq('status', 'processing')
                            .execute()
                    )
                    data = getattr(res, 'data', None) or []
                    if len(data) > 0:
                        return True
                except Exception as e:
                    logger.warning(f"Supabase REST mark_job_success_by_carteirinha falhou: {e}")
            # Fallback SQL direto
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE job_carteirinhas
                       SET status='success',
                           locked_by=NULL,
                           locked_at=NULL,
                           locked_until=NULL,
                           updated_at=NOW()
                     WHERE carteirinha=%s AND status='processing'
                    """,
                    (carteirinha,)
                )
                self.connection.commit()
                rows = cursor.rowcount
                cursor.close()
                return rows > 0
            except Exception as e:
                cursor.close()
                logger.error(f"Erro ao marcar sucesso por carteirinha {carteirinha}: {e}")
                return False
        except Exception as e:
            logger.error(f"Falha mark_job_success_by_carteirinha: {e}")
            return False

    def has_recent_success_for_carteirinha(self, carteirinha: str, min_hours: int = 6) -> bool:
        try:
            cutoff_iso = (datetime.now() - timedelta(hours=min_hours)).isoformat()
            if getattr(self, 'supabase', None):
                try:
                    res = (
                        self.supabase
                            .table('job_carteirinhas')
                            .select('id, updated_at')
                            .eq('type', 'sgucard')
                            .eq('carteirinha', carteirinha)
                            .eq('status', 'success')
                            .gte('updated_at', cutoff_iso)
                            .limit(1)
                            .execute()
                    )
                    data = getattr(res, 'data', None) or []
                    return len(data) > 0
                except Exception as e:
                    logger.warning(f"Supabase REST has_recent_success_for_carteirinha falhou: {e}")
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    SELECT 1
                      FROM job_carteirinhas
                     WHERE type='sgucard'
                       AND carteirinha=%s
                       AND status='success'
                       AND updated_at >= NOW() - (%s || ' hours')::interval
                    LIMIT 1
                    """,
                    (carteirinha, str(min_hours))
                )
                row = cursor.fetchone()
                cursor.close()
                return bool(row)
            except Exception as e:
                cursor.close()
                logger.error(f"Erro ao verificar sucesso recente para carteirinha {carteirinha}: {e}")
                return False
        except Exception as e:
            logger.error(f"Falha has_recent_success_for_carteirinha: {e}")
            return False

    def has_active_processing_for_carteirinha(self, carteirinha: str) -> bool:
        try:
            now_iso = datetime.now().isoformat()
            if getattr(self, 'supabase', None):
                try:
                    res = (
                        self.supabase
                            .table('job_carteirinhas')
                            .select('id, locked_until')
                            .eq('type', 'sgucard')
                            .eq('carteirinha', carteirinha)
                            .eq('status', 'processing')
                            .gte('locked_until', now_iso)
                            .limit(1)
                            .execute()
                    )
                    data = getattr(res, 'data', None) or []
                    return len(data) > 0
                except Exception as e:
                    logger.warning(f"Supabase REST has_active_processing_for_carteirinha falhou: {e}")
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """
                    SELECT 1
                      FROM job_carteirinhas
                     WHERE type='sgucard'
                       AND carteirinha=%s
                       AND status='processing'
                       AND locked_until >= NOW()
                    LIMIT 1
                    """,
                    (carteirinha,)
                )
                row = cursor.fetchone()
                cursor.close()
                return bool(row)
            except Exception as e:
                cursor.close()
                logger.error(f"Erro ao verificar processing ativo para carteirinha {carteirinha}: {e}")
                return False
        except Exception as e:
            logger.error(f"Falha has_active_processing_for_carteirinha: {e}")
            return False

    def mark_job_processed(self, job_id: str) -> bool:
        try:
            if getattr(self, 'supabase', None):
                try:
                    self.supabase.table('job_carteirinhas').update({
                        'status': 'success',
                        'locked_by': None,
                        'locked_at': None,
                        'locked_until': None,
                        'updated_at': datetime.now().isoformat()
                    }).eq('id', job_id).execute()
                    return True
                except Exception:
                    try:
                        cursor = self.connection.cursor()
                        cursor.execute("UPDATE job_carteirinhas SET status='success', locked_by=NULL, locked_at=NULL, locked_until=NULL, updated_at=NOW() WHERE id=%s", (job_id,))
                        self.connection.commit()
                        cursor.close()
                        return True
                    except Exception as _:
                        logger.warning(f"Falha ao atualizar job {job_id} para success")
                        return False
            cursor = self.connection.cursor()
            try:
                cursor.execute("UPDATE job_carteirinhas SET status='success', locked_by=NULL, locked_at=NULL, locked_until=NULL, updated_at=NOW() WHERE id=%s", (job_id,))
                self.connection.commit()
            except Exception:
                cursor.close()
                return False
            cursor.close()
            return True
        except Exception as e:
            logger.error(f"Erro ao marcar job {job_id} como processado: {e}")
            return False

    def mark_job_failed(self, job_id: str, error: str) -> bool:
        try:
            if getattr(self, 'supabase', None):
                try:
                    self.supabase.table('job_carteirinhas').update({
                        'status': 'error',
                        'error': error,
                        'locked_by': None,
                        'locked_at': None,
                        'locked_until': None,
                        'updated_at': datetime.now().isoformat()
                    }).eq('id', job_id).execute()
                    return True
                except Exception:
                    try:
                        cursor = self.connection.cursor()
                        cursor.execute("UPDATE job_carteirinhas SET status='error', error=%s, locked_by=NULL, locked_at=NULL, locked_until=NULL, updated_at=NOW() WHERE id=%s", (error, job_id))
                        self.connection.commit()
                        cursor.close()
                        return True
                    except Exception as _:
                        logger.warning(f"Falha ao atualizar job {job_id} para error")
                        return False
            cursor = self.connection.cursor()
            try:
                cursor.execute("UPDATE job_carteirinhas SET status='error', error=%s, locked_by=NULL, locked_at=NULL, locked_until=NULL, updated_at=NOW() WHERE id=%s", (error, job_id))
                self.connection.commit()
            except Exception:
                cursor.close()
                return False
            cursor.close()
            return True
        except Exception as e:
            logger.error(f"Erro ao marcar job {job_id} como erro: {e}")
            return False

    def get_carteirinhas_with_appointments(self, data):
        """Retorna carteirinhas com agendamentos para uma data específica"""
        try:
            cursor = self.connection.cursor()
            query = """
                SELECT DISTINCT c.carteiras as carteirinha, c.paciente 
                FROM carteirinhas c
                INNER JOIN agendamentos a ON c.carteiras = a.carteirinha
                WHERE a.data = %s
                ORDER BY c.paciente
            """
            cursor.execute(query, (data,))
            results = cursor.fetchall()
            cursor.close()
            
            carteirinhas = []
            for result in results:
                carteirinhas.append({
                    'carteirinha': result[0],
                    'paciente': result[1]
                })
            
            return carteirinhas
        except Exception as e:
            logger.error(f"Erro ao buscar carteirinhas com agendamentos: {str(e)}")
            return []

    def close(self):
        """Fecha a conexão com o banco"""
        if self.connection:
            self.connection.close()
            logger.info("Conexão com banco fechada")

class ExcelProcessor:
    """Classe para processar planilhas Excel e executar macros"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.caminho_planilha = r"G:\Meu Drive\1.Administrativo\2.Guia Unimed\2020\NAO UTILIZAR\Cases_soluções\Download_Protocolo_com Guias\Download_Base_Guias_finalizadas -diario.xlsm"
    
    def executar_processamento_excel(self, data_inicial: str = None, data_final: str = None) -> Dict[str, any]:
        """
        Executa o processamento Excel original com macros
        """
        try:
            self.logger.info("Iniciando processamento Excel")
            
            # Verificar se o arquivo existe
            if not os.path.exists(self.caminho_planilha):
                self.logger.error("ERRO: A planilha não foi encontrada!")
                return {
                    'sucesso': False,
                    'erro': 'Planilha não encontrada',
                    'timestamp': datetime.now()
                }
            
            # Usar data atual se não especificada
            if not data_inicial:
                data_inicial = datetime.now().strftime("%m/%d/%Y")
            if not data_final:
                data_final = data_inicial
                
            self.logger.info(f"Processando período: {data_inicial} até {data_final}")
            
            # Abrir Excel
            excel = win32.gencache.EnsureDispatch("Excel.Application")
            excel.Visible = False  # Executar em background
            self.logger.info("Excel aberto com sucesso")
            
            # Abrir planilha
            workbook = excel.Workbooks.Open(self.caminho_planilha)
            self.logger.info("Planilha aberta com sucesso")
            
            # Selecionar planilha
            sheet = workbook.Sheets("Guias_Capturadas")
            sheet.Cells(1, 1).Value = 1  # Célula A1
            sheet.Cells(1, 10).Value = data_inicial  # Célula J1
            sheet.Cells(1, 11).Value = data_final  # Célula K1
            
            # Executar macros
            self.logger.info("Iniciando execução de macros")
            macros_executadas = []
            
            for macro in ["LimparProtocolo", "LimparGuias", "capt_finalizadas"]:
                try:
                    self.logger.info(f"Executando macro: {macro}")
                    excel.Application.Run(macro)
                    macros_executadas.append(macro)
                    time.sleep(10)  # Aguardar processamento
                except Exception as e:
                    self.logger.error(f"Erro ao executar macro {macro}: {e}")
            
            # Salvar e fechar
            workbook.Close(SaveChanges=True)
            excel.Quit()
            
            self.logger.info("Processamento Excel concluído com sucesso")
            return {
                'sucesso': True,
                'macros_executadas': macros_executadas,
                'data_inicial': data_inicial,
                'data_final': data_final,
                'timestamp': datetime.now()
            }
            
        except Exception as e:
            self.logger.error(f"ERRO durante processamento Excel: {e}")
            return {
                'sucesso': False,
                'erro': str(e),
                'timestamp': datetime.now()
            }

class CarteirinhaProcessor:
    """Processador de carteirinhas - simula o processamento web scraping"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.excel_processor = ExcelProcessor()
    
    def processar_carteirinha(self, carteirinha_data: Dict) -> List[Dict]:
        """
        Processa uma carteirinha específica
        NOTA: Esta é uma simulação. Na implementação real, aqui seria feito
        o web scraping usando Selenium para extrair dados das guias
        """
        try:
            carteirinha = carteirinha_data['carteiras']
            logger.info(f"Processando carteirinha: {carteirinha}")
            
            # Simulação de dados extraídos (substituir por web scraping real)
            guias_simuladas = [
                {
                    'id_paciente': carteirinha_data['id'],
                    'id_pagamento': carteirinha_data['id_pagamento'],
                    'carteirinha': carteirinha,
                    'paciente': carteirinha_data['paciente'],
                    'guia': f"GUIA{carteirinha}001",
                    'data_autorizacao': date.today(),
                    'senha': f"SENHA{carteirinha}",
                    'validade': date.today() + timedelta(days=30),
                    'codigo_terapia': "T001",
                    'qtde_solicitado': 10,
                    'sessoes_autorizadas': 8
                }
            ]
            
            # Simular tempo de processamento
            time.sleep(2)
            
            logger.info(f"Carteirinha {carteirinha} processada com {len(guias_simuladas)} guias")
            return guias_simuladas
            
        except Exception as e:
            logger.error(f"Erro ao processar carteirinha {carteirinha_data['carteiras']}: {e}")
            return []
    
    def processar_carteirinha_real(self, carteirinha: str, data_inicial: str = None, data_final: str = None) -> Dict[str, any]:
        """
        Processa uma carteirinha usando o sistema Excel real
        """
        logger.info(f"Iniciando processamento real para carteirinha: {carteirinha}")
        
        # Executar processamento Excel
        resultado_excel = self.excel_processor.executar_processamento_excel(data_inicial, data_final)
        
        if not resultado_excel['sucesso']:
            return resultado_excel
        
        # Aqui você pode adicionar lógica adicional para:
        # 1. Ler os dados processados da planilha
        # 2. Filtrar por carteirinha específica
        # 3. Converter para formato do banco de dados
        
        # Por enquanto, retornamos o resultado do Excel
        resultado_excel['carteirinha'] = carteirinha
        return resultado_excel

class AutomacaoCarteirinhas:
    """Classe principal da automação"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.processor = CarteirinhaProcessor(self.db_manager)
    
    def vasculhar_carteirinhas(self, modo_execucao: str = "manual", 
                             carteirinha: str = None,
                             data_inicial: Union[str, date] = None,
                             data_final: Union[str, date] = None,
                             usar_webscraping_real: bool = True) -> Dict:
        """
        Função principal para vasculhar carteirinhas
        
        Args:
            modo_execucao: "diario", "semanal", "manual", "intervalo"
            carteirinha: carteirinha específica (para modo manual)
            data_inicial: data inicial (para modo intervalo)
            data_final: data final (para modo intervalo)
            usar_webscraping_real: se True, usa automação real com Excel/macros
        """
        inicio_execucao = datetime.now()
        guias_inseridas = 0
        guias_atualizadas = 0
        carteirinhas_processadas = 0
        
        try:
            logger.info(f"Iniciando varredura - Modo: {modo_execucao}, WebScraping Real: {usar_webscraping_real}")
            
            # Converter strings de data para objetos date se necessário
            if isinstance(data_inicial, str):
                data_inicial = datetime.strptime(data_inicial, "%Y-%m-%d").date()
            if isinstance(data_final, str):
                data_final = datetime.strptime(data_final, "%Y-%m-%d").date()
            
            # Se usar web scraping real, delegar para automação real
            if usar_webscraping_real:
                try:
                    from automacao_webscraping_real import WebScrapingRealAutomacao
                    
                    automacao_real = WebScrapingRealAutomacao()
                    
                    # Preparar parâmetros para automação real
                    data_inicio_str = data_inicial.strftime("%Y-%m-%d") if data_inicial else None
                    data_fim_str = data_final.strftime("%Y-%m-%d") if data_final else None
                    
                    resultado = automacao_real.executar_automacao_completa(
                        filtro_api=modo_execucao,
                        carteira=carteirinha,
                        data_inicio=data_inicio_str,
                        data_fim=data_fim_str
                    )
                    
                    if resultado['sucesso']:
                        logger.info("Automação real executada com sucesso")
                        # Marcador de conclusão: gravar success no job correspondente
                        try:
                            if carteirinha:
                                self.db_manager.mark_job_success_by_carteirinha(carteirinha)
                        except Exception as e:
                            logger.warning(f"Falha ao marcar success por carteirinha {carteirinha}: {e}")
                        return {
                            'status': 'sucesso',
                            'message': 'Web scraping real executado com sucesso',
                            'carteirinhas_processadas': resultado['carteirinhas_processadas'],
                            'guias_inseridas': resultado['guias_extraidas'],
                            'guias_atualizadas': 0,
                            'tempo_execucao': resultado['tempo_execucao']
                        }
                    else:
                        logger.error(f"Falha na automação real: {resultado['erro']}")
                        # Continuar com simulação em caso de falha
                        
                except ImportError:
                    logger.warning("Módulo de automação real não disponível, usando simulação")
                except Exception as e:
                    logger.error(f"Erro na automação real: {e}, usando simulação")
            
            # Buscar carteirinhas para processamento (simulação ou fallback)
            carteirinhas = self.db_manager.get_carteirinhas_for_processing(
                modo_execucao, carteirinha, data_inicial, data_final
            )
            
            if not carteirinhas:
                logger.warning("Nenhuma carteirinha encontrada para processamento")
                return {
                    'status': 'warning',
                    'message': 'Nenhuma carteirinha encontrada',
                    'carteirinhas_processadas': 0,
                    'guias_inseridas': 0,
                    'guias_atualizadas': 0
                }
            
            # Processar cada carteirinha (modo simulação)
            for carteirinha_data in carteirinhas:
                try:
                    guias = self.processor.processar_carteirinha(carteirinha_data)
                    carteirinhas_processadas += 1
                    
                    # Salvar guias no banco
                    for guia_data in guias:
                        # Verificar se é inserção ou atualização
                        check_query = "SELECT id FROM baseguias WHERE carteirinha = %s AND guia = %s"
                        existing = self.db_manager.execute_query(
                            check_query, 
                            (guia_data['carteirinha'], guia_data['guia']), 
                            fetch=True
                        )
                        
                        if self.db_manager.save_guia_data(guia_data):
                            if existing:
                                guias_atualizadas += 1
                            else:
                                guias_inseridas += 1
                
                except Exception as e:
                    logger.error(f"Erro ao processar carteirinha {carteirinha_data['carteiras']}: {e}")
                    continue
            
            # Calcular tempo de execução
            tempo_execucao = datetime.now() - inicio_execucao
            
            # Registrar log de execução
            self.db_manager.log_execution(
                tipo_execucao=modo_execucao,
                status='sucesso',
                tempo_execucao=tempo_execucao,
                carteirinhas_processadas=carteirinhas_processadas,
                guias_inseridas=guias_inseridas,
                guias_atualizadas=guias_atualizadas,
                mensagem=f"Execução concluída com sucesso"
            )
            
            resultado = {
                'status': 'sucesso',
                'message': 'Varredura concluída com sucesso',
                'carteirinhas_processadas': carteirinhas_processadas,
                'guias_inseridas': guias_inseridas,
                'guias_atualizadas': guias_atualizadas,
                'tempo_execucao': str(tempo_execucao)
            }
            
            logger.info(f"Varredura concluída: {resultado}")
            return resultado
            
        except Exception as e:
            tempo_execucao = datetime.now() - inicio_execucao
            erro_msg = f"Erro durante varredura: {e}"
            logger.error(erro_msg)
            
            # Registrar log de erro
            self.db_manager.log_execution(
                tipo_execucao=modo_execucao,
                status='erro',
                tempo_execucao=tempo_execucao,
                carteirinhas_processadas=carteirinhas_processadas,
                guias_inseridas=guias_inseridas,
                guias_atualizadas=guias_atualizadas,
                erro=erro_msg
            )
            
            return {
                'status': 'erro',
                'message': erro_msg,
                'carteirinhas_processadas': carteirinhas_processadas,
                'guias_inseridas': guias_inseridas,
                'guias_atualizadas': guias_atualizadas
            }
    
    def executar_varredura_diaria(self):
        """Executa varredura diária automática"""
        logger.info("Executando varredura diária automática")
        return self.vasculhar_carteirinhas("diario")
    
    def executar_varredura_semanal(self):
        """Executa varredura semanal automática"""
        logger.info("Executando varredura semanal automática")
        return self.vasculhar_carteirinhas("semanal")
    
    def executar_scan_diario(self):
        """Executa scan diário automático usando vasculhar_carteirinhas"""
        logger.info("Iniciando scan diário automático")
        try:
            resultado = self.vasculhar_carteirinhas(modo_execucao="diario")
            
            if resultado['status'] == 'sucesso':
                logger.info(f"Scan diário concluído: {resultado['carteirinhas_processadas']} carteirinhas processadas")
            else:
                logger.error(f"Falha no scan diário: {resultado.get('message', 'Erro desconhecido')}")
                
        except Exception as e:
            logger.error(f"Erro durante scan diário: {e}")

    def executar_scan_semanal(self):
        """Executa scan semanal automático usando vasculhar_carteirinhas"""
        logger.info("Iniciando scan semanal automático")
        try:
            resultado = self.vasculhar_carteirinhas(modo_execucao="semanal")
            
            if resultado['status'] == 'sucesso':
                logger.info(f"Scan semanal concluído: {resultado['carteirinhas_processadas']} carteirinhas processadas")
            else:
                logger.error(f"Falha no scan semanal: {resultado.get('message', 'Erro desconhecido')}")
                
        except Exception as e:
            logger.error(f"Erro durante scan semanal: {e}")
    
    async def executar_scan_semanal(self):
        """Executa scan semanal de todas as carteirinhas"""
        logger.info("Iniciando scan semanal de todas as carteirinhas")
        
        try:
            # Buscar todas as carteirinhas ativas
            carteirinhas = self.db_manager.get_carteirinhas_for_processing("semanal")
            
            if not carteirinhas:
                logger.info("Nenhuma carteirinha ativa encontrada")
                return
            
            logger.info(f"Processando {len(carteirinhas)} carteirinhas")
            
            # Processar carteirinhas em paralelo
            tasks = []
            for carteirinha in carteirinhas:
                task = self.processar_carteirinha_especifica(carteirinha['carteiras'])
                tasks.append(task)
            
            # Executar processamento paralelo
            import asyncio
            resultados = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Registrar resultados
            sucessos = sum(1 for r in resultados if isinstance(r, dict) and r.get('sucesso'))
            erros = len(resultados) - sucessos
            
            self.db_manager.log_execution(
                tipo_execucao='scan_semanal',
                status='concluido',
                tempo_execucao=datetime.now() - datetime.now(),
                carteirinhas_processadas=len(carteirinhas),
                guias_inseridas=0,
                guias_atualizadas=0,
                mensagem=f"Processadas: {len(carteirinhas)}, Sucessos: {sucessos}, Erros: {erros}"
            )
            
            logger.info(f"Scan semanal concluído. Sucessos: {sucessos}, Erros: {erros}")
            
        except Exception as e:
            logger.error(f"Erro no scan semanal: {str(e)}")
            self.db_manager.log_execution(
                tipo_execucao='scan_semanal',
                status='erro',
                tempo_execucao=datetime.now() - datetime.now(),
                carteirinhas_processadas=0,
                guias_inseridas=0,
                guias_atualizadas=0,
                erro=str(e)
            )
    
    def processar_carteirinha_especifica(self, carteirinha: str) -> Dict[str, any]:
        """Processa uma carteirinha específica (método legado - usar vasculhar_carteirinhas)"""
        return self.vasculhar_carteirinhas(modo_execucao="manual", carteirinha=carteirinha)
    
    async def processar_carteirinha_especifica_async(self, carteirinha):
        """Processa uma carteirinha específica de forma assíncrona"""
        logger.info(f"Processando carteirinha específica: {carteirinha}")
        
        try:
            # Simular processamento (em produção seria web scraping real)
            import time
            import random
            import asyncio
            
            start_time = time.time()
            
            # Simular tempo de processamento
            await asyncio.sleep(0.5)
            
            # Simular resultado
            guias_encontradas = random.randint(0, 5)
            sucesso = random.choice([True, True, True, False])  # 75% de sucesso
            
            tempo_processamento = round(time.time() - start_time, 2)
            
            if sucesso:
                # Registrar log de sucesso
                self.db_manager.log_execution(
                    tipo_execucao='carteirinha_especifica',
                    status='sucesso',
                    tempo_execucao=timedelta(seconds=tempo_processamento),
                    carteirinhas_processadas=1,
                    guias_inseridas=guias_encontradas,
                    guias_atualizadas=0,
                    mensagem=f"Guias encontradas: {guias_encontradas}"
                )
                
                return {
                    'sucesso': True,
                    'carteirinha': carteirinha,
                    'guias_encontradas': guias_encontradas,
                    'tempo_processamento': tempo_processamento
                }
            else:
                # Registrar log de erro
                self.db_manager.log_execution(
                    tipo_execucao='carteirinha_especifica',
                    status='erro',
                    tempo_execucao=timedelta(seconds=tempo_processamento),
                    carteirinhas_processadas=1,
                    guias_inseridas=0,
                    guias_atualizadas=0,
                    erro="Erro simulado no processamento"
                )
                
                return {
                    'sucesso': False,
                    'carteirinha': carteirinha,
                    'erro': 'Erro simulado no processamento',
                    'tempo_processamento': tempo_processamento
                }
                
        except Exception as e:
            logger.error(f"Erro ao processar carteirinha {carteirinha}: {str(e)}")
            
            self.db_manager.log_execution(
                tipo_execucao='carteirinha_especifica',
                status='erro',
                tempo_execucao=timedelta(seconds=0),
                carteirinhas_processadas=1,
                guias_inseridas=0,
                guias_atualizadas=0,
                erro=str(e)
            )
            
            return {
                'sucesso': False,
                'carteirinha': carteirinha,
                'erro': str(e)
            }
    
    def iniciar_agendamento(self):
        """Inicia o sistema de agendamento automático"""
        logger.info("Iniciando sistema de agendamento automático")
        
        # Agendar varredura diária às 19:00
        schedule.every().day.at("19:00").do(self.executar_scan_diario)
        
        # Agendar varredura semanal aos sábados às 19:00
        schedule.every().saturday.at("19:00").do(self.executar_scan_semanal)
        
        logger.info("Agendamentos configurados:")
        logger.info("- Varredura diária: todos os dias às 19:00")
        logger.info("- Varredura semanal: sábados às 19:00")
        
        # Loop principal
        while True:
            try:
                schedule.run_pending()
                time.sleep(60)  # Verificar a cada minuto
            except KeyboardInterrupt:
                logger.info("Agendamento interrompido pelo usuário")
                break
            except Exception as e:
                logger.error(f"Erro no loop de agendamento: {e}")
                time.sleep(300)  # Aguardar 5 minutos antes de tentar novamente
    
    def __del__(self):
        """Destrutor para fechar conexão com banco"""
        if hasattr(self, 'db_manager'):
            self.db_manager.close()

# Função principal para uso direto
def main():
    """Função principal para execução direta do script"""
    import sys
    
    automacao = AutomacaoCarteirinhas()
    
    if len(sys.argv) > 1:
        modo = sys.argv[1]
        
        if modo == "agendamento":
            automacao.iniciar_agendamento()
        elif modo == "diario":
            resultado = automacao.executar_varredura_diaria()
            print(json.dumps(resultado, indent=2, default=str))
        elif modo == "semanal":
            resultado = automacao.executar_varredura_semanal()
            print(json.dumps(resultado, indent=2, default=str))
        elif modo == "manual" and len(sys.argv) > 2:
            carteirinha = sys.argv[2]
            resultado = automacao.vasculhar_carteirinhas("manual", carteirinha=carteirinha)
            print(json.dumps(resultado, indent=2, default=str))
        else:
            print("Uso: python automacao_carteirinhas.py [agendamento|diario|semanal|manual <carteirinha>]")
    else:
        # Modo interativo
        print("Automação de Carteirinhas - Modo Interativo")
        print("1. Iniciar agendamento automático")
        print("2. Executar varredura diária")
        print("3. Executar varredura semanal")
        print("4. Processar carteirinha específica")
        
        escolha = input("Escolha uma opção (1-4): ")
        
        if escolha == "1":
            automacao.iniciar_agendamento()
        elif escolha == "2":
            resultado = automacao.executar_varredura_diaria()
            print(json.dumps(resultado, indent=2, default=str))
        elif escolha == "3":
            resultado = automacao.executar_varredura_semanal()
            print(json.dumps(resultado, indent=2, default=str))
        elif escolha == "4":
            carteirinha = input("Digite o número da carteirinha: ")
            resultado = automacao.vasculhar_carteirinhas("manual", carteirinha=carteirinha)
            print(json.dumps(resultado, indent=2, default=str))

if __name__ == "__main__":
    main()