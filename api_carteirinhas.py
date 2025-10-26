"""
API FastAPI para controle e consulta da automação de carteirinhas
Permite execução sob demanda e consulta de dados
"""

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict
import os
import json
from dotenv import load_dotenv

# Importar a classe principal da automação
from automacao_carteirinhas import AutomacaoCarteirinhas, DatabaseManager
from automacao_webscraping_real import SGUCARD
import schedule
import threading
import time

# Carregar variáveis de ambiente
load_dotenv()

# Configurar FastAPI
app = FastAPI(
    title="API de Automação de Carteirinhas",
    description="API para controle e consulta da automação de verificação de carteirinhas",
    version="1.0.0",
    swagger_ui_parameters={
        "persistAuthorization": True,
        "displayRequestDuration": True
    }
)

# Configurar autenticação
security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verifica o token de autenticação"""
    expected_token = os.getenv("API_TOKEN", "default_token_change_me")
    if credentials.credentials != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

# Modelos Pydantic para requests/responses
class CarteirinhaRequest(BaseModel):
    carteirinha: str = Field(..., description="Número da carteirinha a ser verificada")

class AtualizarIntervaloRequest(BaseModel):
    data_inicial: str = Field(..., description="Data inicial no formato YYYY-MM-DD")
    data_final: str = Field(..., description="Data final no formato YYYY-MM-DD")

class ExecutionResponse(BaseModel):
    status: str
    message: str
    carteirinhas_processadas: int
    guias_inseridas: int
    guias_atualizadas: int
    tempo_execucao: Optional[str] = None

class GuiaData(BaseModel):
    id: int
    carteirinha: str
    paciente: str
    guia: str
    data_autorizacao: Optional[date]
    validade: Optional[date]
    codigo_terapia: Optional[str]
    sessoes_autorizadas: Optional[int]

class LogEntry(BaseModel):
    id: int
    timestamp: datetime
    tipo_execucao: str
    status: str
    carteirinhas_processadas: int
    guias_inseridas: int
    guias_atualizadas: int
    mensagem: Optional[str]

# Novo modelo para criação de jobs
class JobCreateRequest(BaseModel):
    type: Optional[str] = Field(default="sgucard", description="Tipo do job")
    carteirinha: str = Field(..., description="Carteirinha alvo do job")
    carteira: Optional[str] = Field(default=None, description="Carteira (se diferente da carteirinha)")
    id_paciente: Optional[str] = Field(default=None, description="ID do paciente (opcional)")

def get_automacao():
    """Inicializa AutomacaoCarteirinhas sob demanda para evitar conexão ao DB no import."""
    global automacao
    # Evitar NameError se a variável global ainda não existir
    try:
        _ = automacao
    except NameError:
        automacao = None
    if automacao is None:
        try:
            automacao = AutomacaoCarteirinhas()
        except Exception as e:
            # Evitar derrubar o servidor por falha de banco no startup
            raise RuntimeError(f"Falha ao inicializar automação: {e}")
    return automacao

@app.get("/", tags=["Info"])
async def root():
    """Endpoint raiz com informações da API"""
    return {
        "message": "API de Automação de Carteirinhas",
        "version": "1.0.0",
        "status": "ativo",
        "endpoints": {
            "verificar_carteirinha": "POST /verificar_carteirinha",
            "atualizar_intervalo": "POST /atualizar_intervalo",
            "sgucard_todos": "POST /sgucard/todos",
            "sgucard_carteirinha": "POST /sgucard/carteirinha",
            "sgucard_intervalo": "POST /sgucard/intervalo",
            "executar_diario": "POST /executar_diario",
            "executar_semanal": "POST /executar_semanal",
            "consultar_guias": "GET /guias/{carteirinha}",
            "consultar_logs": "GET /logs"
        }
    }

@app.post("/verificar_carteirinha")
async def verificar_carteirinha_endpoint(
    request: CarteirinhaRequest,
    token: str = Depends(verify_token)
):
    """Verifica uma carteirinha específica conforme prompt.yaml"""
    try:
        # Usar função vasculhar_carteirinhas para carteirinha específica
        automacao = get_automacao()
        resultado = automacao.vasculhar_carteirinhas(
            modo_execucao="manual",
            carteirinha=request.carteirinha
        )
        # Se houve sucesso na verificação, marcar o job como success imediatamente
        try:
            if resultado.get('status') == 'sucesso' and request.carteirinha:
                automacao.db_manager.mark_job_success_by_carteirinha(request.carteirinha)
        except Exception as e:
            logger.warning(f"Falha ao marcar success por carteirinha {request.carteirinha}: {e}")
        
        return {
            "status": "sucesso" if resultado.get('status') == 'sucesso' else "erro",
            "carteirinha": request.carteirinha,
            "resultado": resultado,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno: {str(e)}"
        )

@app.post("/atualizar_intervalo")
async def atualizar_intervalo_endpoint(
    request: AtualizarIntervaloRequest,
    token: str = Depends(verify_token)
):
    """Solicita atualização de guias por intervalo de datas conforme prompt.yaml"""
    try:
        # Usar função vasculhar_carteirinhas com intervalo de datas
        resultado = get_automacao().vasculhar_carteirinhas(
            modo_execucao="manual",
            data_inicial=request.data_inicial,
            data_final=request.data_final
        )
        
        return {
            "status": "sucesso" if resultado.get('sucesso') else "erro",
            "data_inicial": request.data_inicial,
            "data_final": request.data_final,
            "carteirinhas_processadas": resultado.get('carteirinhas_processadas', 0),
            "guias_inseridas": resultado.get('guias_inseridas', 0),
            "guias_atualizadas": resultado.get('guias_atualizadas', 0),
            "tempo_execucao": resultado.get('tempo_execucao', 0),
            "resultado": resultado,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno: {str(e)}"
        )

@app.post("/executar_diario", response_model=ExecutionResponse, tags=["Automação"])
async def executar_diario(token: str = Depends(verify_token)):
    """Executa varredura diária manualmente"""
    try:
        resultado = get_automacao().executar_varredura_diaria()
        return ExecutionResponse(**resultado)
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao executar varredura diária: {str(e)}"
        )

@app.post("/executar_semanal", response_model=ExecutionResponse, tags=["Automação"])
async def executar_semanal(token: str = Depends(verify_token)):
    """Executa varredura semanal manualmente"""
    try:
        resultado = get_automacao().executar_varredura_semanal()
        return ExecutionResponse(**resultado)
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao executar varredura semanal: {str(e)}"
        )

# Endpoints para acionar SGUCARD diretamente (selenium)
@app.post("/sgucard/todos", response_model=ExecutionResponse, tags=["Automação"])
async def sgucard_todos(token: str = Depends(verify_token)):
    print("[API] Disparando SGUCARD modo 'todos' em thread dedicada...")
    threading.Thread(target=SGUCARD, args=('todos',), daemon=True).start()
    return ExecutionResponse(status="accepted", message="Execução 'todos' iniciada (thread)", carteirinhas_processadas=0, guias_inseridas=0, guias_atualizadas=0)

@app.post("/sgucard/carteirinha", response_model=ExecutionResponse, tags=["Automação"])
async def sgucard_carteirinha(request: CarteirinhaRequest, token: str = Depends(verify_token)):
    print(f"[API] Disparando SGUCARD modo 'unico' para carteirinha {request.carteirinha} em thread dedicada...")
    threading.Thread(target=SGUCARD, args=('unico', request.carteirinha), daemon=True).start()
    return ExecutionResponse(status="accepted", message=f"Execução 'carteirinha' iniciada (thread) para {request.carteirinha}", carteirinhas_processadas=0, guias_inseridas=0, guias_atualizadas=0)

@app.post("/sgucard/intervalo", response_model=ExecutionResponse, tags=["Automação"])
async def sgucard_intervalo(request: AtualizarIntervaloRequest, token: str = Depends(verify_token)):
    print(f"[API] Disparando SGUCARD modo 'intervalo' ({request.data_inicial} a {request.data_final}) em thread dedicada...")
    threading.Thread(target=SGUCARD, args=('intervalo', None, request.data_inicial, request.data_final), daemon=True).start()
    return ExecutionResponse(status="accepted", message=f"Execução 'intervalo' iniciada (thread) ({request.data_inicial} a {request.data_final})", carteirinhas_processadas=0, guias_inseridas=0, guias_atualizadas=0)

# Agendamentos usando 'schedule' em thread de background
def _job_intervalo_amanha():
    amanha = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        SGUCARD('intervalo', None, amanha, amanha)
    except Exception as e:
        print(f"Erro no job diário intervalo (amanhã): {e}")

def _job_todos():
    try:
        SGUCARD('todos')
    except Exception as e:
        print(f"Erro no job semanal todos: {e}")

def _schedule_loop():
    while True:
        schedule.run_pending()
        time.sleep(30)

@app.on_event("startup")
async def _startup_schedule():
    # Diário 19:00 - intervalo do dia seguinte
    schedule.every().day.at("19:00").do(_job_intervalo_amanha)
    # Semanal sábado 19:00 - todos
    schedule.every().saturday.at("19:00").do(_job_todos)
    threading.Thread(target=_schedule_loop, daemon=True).start()

@app.post("/executar_webscraping_real", response_model=ExecutionResponse, tags=["Automação"])
async def executar_webscraping_real(
    request: AtualizarIntervaloRequest = None,
    carteirinha: Optional[str] = None,
    token: str = Depends(verify_token)
):
    """Executa web scraping real com automação Excel/macros"""
    try:
        # Preparar parâmetros
        data_inicial = None
        data_final = None
        
        if request:
            data_inicial = request.data_inicial
            data_final = request.data_final
        
        # Executar automação real
        resultado = get_automacao().vasculhar_carteirinhas(
            modo_execucao="manual" if carteirinha else "intervalo",
            carteirinha=carteirinha,
            data_inicial=data_inicial,
            data_final=data_final,
            usar_webscraping_real=True
        )
        
        return ExecutionResponse(**resultado)
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro na execução do web scraping real: {str(e)}"
        )

@app.get("/guias/{carteirinha}", response_model=List[GuiaData], tags=["Consultas"])
async def consultar_guias(
    carteirinha: str,
    token: str = Depends(verify_token)
):
    """Consulta guias de uma carteirinha específica"""
    try:
        db_manager = DatabaseManager()
        
        query = """
            SELECT id, carteirinha, paciente, guia, data_autorizacao, 
                   validade, codigo_terapia, sessoes_autorizadas
            FROM baseguias 
            WHERE carteirinha = %s
            ORDER BY data_autorizacao DESC
        """
        
        result = db_manager.execute_query(query, (carteirinha,), fetch=True)
        
        guias = []
        for row in result:
            guias.append(GuiaData(
                id=row[0],
                carteirinha=row[1],
                paciente=row[2],
                guia=row[3],
                data_autorizacao=row[4],
                validade=row[5],
                codigo_terapia=row[6],
                sessoes_autorizadas=row[7]
            ))
        
        db_manager.close()
        return guias
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao consultar guias: {str(e)}"
        )

@app.get("/logs", response_model=List[LogEntry], tags=["Consultas"])
async def consultar_logs(
    limit: int = 50,
    token: str = Depends(verify_token)
):
    """Consulta logs de execução"""
    try:
        db_manager = DatabaseManager()
        
        query = """
            SELECT id, timestamp, tipo_execucao, status, carteirinhas_processadas,
                   guias_inseridas, guias_atualizadas, mensagem
            FROM logs 
            ORDER BY timestamp DESC
            LIMIT %s
        """
        
        result = db_manager.execute_query(query, (limit,), fetch=True)
        
        logs = []
        for row in result:
            logs.append(LogEntry(
                id=row[0],
                timestamp=row[1],
                tipo_execucao=row[2],
                status=row[3],
                carteirinhas_processadas=row[4],
                guias_inseridas=row[5],
                guias_atualizadas=row[6],
                mensagem=row[7]
            ))
        
        db_manager.close()
        return logs
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao consultar logs: {str(e)}"
        )

@app.get("/status", tags=["Info"])
async def status_sistema(token: str = Depends(verify_token)):
    """Retorna status do sistema"""
    try:
        db_manager = DatabaseManager()
        
        # Contar registros nas tabelas principais
        stats = {}
        
        tables = ['carteirinhas', 'agendamentos', 'baseguias', 'logs']
        for table in tables:
            query = f"SELECT COUNT(*) FROM {table}"
            result = db_manager.execute_query(query, fetch=True)
            stats[table] = result[0][0] if result else 0
        
        # Último log de execução
        query = """
            SELECT timestamp, tipo_execucao, status, carteirinhas_processadas
            FROM logs 
            ORDER BY timestamp DESC 
            LIMIT 1
        """
        result = db_manager.execute_query(query, fetch=True)
        
        ultima_execucao = None
        if result:
            ultima_execucao = {
                'timestamp': result[0][0].isoformat(),
                'tipo_execucao': result[0][1],
                'status': result[0][2],
                'carteirinhas_processadas': result[0][3]
            }
        
        db_manager.close()
        
        return {
            'status': 'ativo',
            'timestamp': datetime.now().isoformat(),
            'estatisticas': stats,
            'ultima_execucao': ultima_execucao
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter status: {str(e)}"
        )

@app.get("/estatisticas", tags=["Info"])
async def estatisticas_sistema():
    """Retorna estatísticas gerais do sistema (sem autenticação)"""
    try:
        db_manager = DatabaseManager()
        
        # Buscar estatísticas básicas
        stats = {
            "total_carteirinhas": 0,
            "total_pagamentos": 0,
            "total_agendamentos": 0,
            "total_guias": 0,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            # Contar carteirinhas
            result = db_manager.supabase.table("carteirinhas").select("id", count="exact").execute()
            stats["total_carteirinhas"] = result.count or 0
        except:
            pass
            
        try:
            # Contar pagamentos
            result = db_manager.supabase.table("pagamentos").select("id", count="exact").execute()
            stats["total_pagamentos"] = result.count or 0
        except:
            pass
            
        try:
            # Contar agendamentos
            # Usar coluna correta da chave primária
            result = db_manager.supabase.table("agendamentos").select("id_atendimento", count="exact").execute()
            stats["total_agendamentos"] = result.count or 0
        except:
            pass
            
        try:
            # Contar guias
            result = db_manager.supabase.table("baseguias").select("id", count="exact").execute()
            stats["total_guias"] = result.count or 0
        except:
            pass
        
        return stats
        
    except Exception as e:
        return {
            "error": f"Erro ao obter estatísticas: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }

@app.get("/health", tags=["Info"])
async def health_check():
    """Verifica a saúde do sistema"""
    try:
        # Testar conexão com banco
        db_manager = DatabaseManager()
        test_result = db_manager.get_sample_carteirinha()
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "database": "connected",
            "message": "Sistema funcionando normalmente"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "database": "error",
            "message": f"Erro: {str(e)}"
        }

if __name__ == "__main__":
    import uvicorn
    
    # Configurações do servidor
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    
    print(f"Iniciando API na porta {port}")
    print(f"Documentação disponível em: http://{host}:{port}/docs")
    
    uvicorn.run(
        "api_carteirinhas:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )

# Endpoint para criar job de carteirinha
@app.post("/jobs", tags=["Jobs"])
async def criar_job(request: JobCreateRequest, token: str = Depends(verify_token)):
    try:
        db_manager = DatabaseManager()
        result = db_manager.insert_job_carteirinha(
            type=request.type,
            carteirinha=request.carteirinha,
            carteira=request.carteira or request.carteirinha,
            id_paciente=request.id_paciente
        )
        return {
            "status": "created",
            "job": result.get("job", result),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar job: {str(e)}"
        )