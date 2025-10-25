"""
Script para configuração inicial do banco de dados Supabase
Cria todas as tabelas necessárias para o projeto de automação de carteirinhas
"""

import os
import psycopg2
from dotenv import load_dotenv
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_environment():
    """Carrega as variáveis de ambiente do arquivo .env"""
    load_dotenv()
    
    # Extrair informações da URL do Supabase
    supabase_url = os.getenv('SUPABASE_URL')
    if not supabase_url:
        raise ValueError("SUPABASE_URL não encontrada no arquivo .env")
    
    # Extrair o projeto ID da URL (formato: https://projeto.supabase.co)
    project_id = supabase_url.replace('https://', '').replace('.supabase.co', '')
    
    return {
        'host': f'db.{project_id}.supabase.co',
        'database': 'postgres',
        'user': 'postgres',
        'password': os.getenv('SUPABASE_PASSWORD'),
        'port': '5432'
    }

def create_connection():
    """Cria conexão com o banco de dados Supabase"""
    try:
        db_config = load_environment()
        logger.info(f"Conectando ao banco: {db_config['host']}")
        
        conn = psycopg2.connect(
            host=db_config['host'],
            database=db_config['database'],
            user=db_config['user'],
            password=db_config['password'],
            port=db_config['port']
        )
        logger.info("Conexão estabelecida com sucesso!")
        return conn
    except Exception as e:
        logger.error(f"Erro ao conectar com o banco: {e}")
        raise

def create_tables(conn):
    """Cria todas as tabelas necessárias"""
    cursor = conn.cursor()
    
    try:
        # Tabela Pagamentos
        logger.info("Criando tabela Pagamentos...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Pagamentos (
                id SERIAL PRIMARY KEY,
                nome TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Tabela Carteirinhas
        logger.info("Criando tabela Carteirinhas...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Carteirinhas (
                id SERIAL PRIMARY KEY,
                carteiras TEXT,
                paciente TEXT,
                id_pagamento INTEGER REFERENCES Pagamentos(id),
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Tabela Agendamentos
        logger.info("Criando tabela Agendamentos...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Agendamentos (
                id_atendimento SERIAL PRIMARY KEY,
                unidade TEXT,
                carteirinha TEXT,
                cod_paciente TEXT,
                paciente TEXT,
                pagamento TEXT,
                data DATE,
                hora_inicial TIME,
                sala TEXT,
                id_profissional INTEGER,
                profissional TEXT,
                tipo_atend TEXT,
                qtd_sess INTEGER,
                status TEXT,
                elegibilidade TEXT,
                substituicao TEXT,
                tipo_falta TEXT,
                id_pai INTEGER,
                codigo_faturamento TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Tabela BaseGuias (conforme especificado no prompt.yaml)
        logger.info("Criando tabela BaseGuias...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS BaseGuias (
                id SERIAL PRIMARY KEY,
                id_paciente INTEGER,
                id_pagamento INTEGER REFERENCES Pagamentos(id),
                carteirinha TEXT,
                paciente TEXT,
                guia TEXT,
                data_autorizacao DATE,
                senha TEXT,
                validade DATE,
                codigo_terapia TEXT,
                qtde_solicitado INTEGER,
                sessoes_autorizadas INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Tabela de Logs para auditoria
        logger.info("Criando tabela Logs...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tipo_execucao TEXT,
                status TEXT,
                tempo_execucao INTERVAL,
                carteirinhas_processadas INTEGER,
                guias_inseridas INTEGER,
                guias_atualizadas INTEGER,
                mensagem TEXT,
                erro TEXT
            );
        """)
        
        # Criar índices para melhor performance
        logger.info("Criando índices...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_carteirinhas_carteiras ON Carteirinhas(carteiras);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_agendamentos_data ON Agendamentos(data);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_agendamentos_carteirinha ON Agendamentos(carteirinha);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_baseguias_carteirinha ON BaseGuias(carteirinha);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_baseguias_data_autorizacao ON BaseGuias(data_autorizacao);")
        
        # Criar triggers para atualizar updated_at automaticamente
        logger.info("Criando triggers para updated_at...")
        cursor.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)
        
        # Aplicar triggers nas tabelas
        tables_with_updated_at = ['Pagamentos', 'Carteirinhas', 'Agendamentos', 'BaseGuias']
        for table in tables_with_updated_at:
            cursor.execute(f"""
                DROP TRIGGER IF EXISTS update_{table.lower()}_updated_at ON {table};
                CREATE TRIGGER update_{table.lower()}_updated_at 
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
            """)
        
        conn.commit()
        logger.info("Todas as tabelas foram criadas com sucesso!")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao criar tabelas: {e}")
        raise
    finally:
        cursor.close()

def verify_tables(conn):
    """Verifica se todas as tabelas foram criadas corretamente"""
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        
        tables = cursor.fetchall()
        logger.info("Tabelas encontradas no banco:")
        for table in tables:
            logger.info(f"  - {table[0]}")
            
        # Verificar se todas as tabelas esperadas existem
        expected_tables = ['pagamentos', 'carteirinhas', 'agendamentos', 'baseguias', 'logs']
        existing_tables = [table[0].lower() for table in tables]
        
        missing_tables = [table for table in expected_tables if table not in existing_tables]
        if missing_tables:
            logger.warning(f"Tabelas faltando: {missing_tables}")
        else:
            logger.info("Todas as tabelas esperadas foram criadas!")
            
    except Exception as e:
        logger.error(f"Erro ao verificar tabelas: {e}")
    finally:
        cursor.close()

def main():
    """Função principal para configurar o banco de dados"""
    try:
        logger.info("Iniciando configuração do banco de dados...")
        
        # Criar conexão
        conn = create_connection()
        
        # Criar tabelas
        create_tables(conn)
        
        # Verificar tabelas criadas
        verify_tables(conn)
        
        logger.info("Configuração do banco de dados concluída com sucesso!")
        
    except Exception as e:
        logger.error(f"Erro na configuração do banco: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()
            logger.info("Conexão fechada.")
    
    return True

if __name__ == "__main__":
    success = main()
    if success:
        print("\n✅ Banco de dados configurado com sucesso!")
        print("Todas as tabelas foram criadas e estão prontas para uso.")
    else:
        print("\n❌ Erro na configuração do banco de dados.")
        print("Verifique os logs acima para mais detalhes.")