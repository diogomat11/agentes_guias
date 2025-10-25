"""
Script para importar dados das planilhas existentes para o banco Supabase
Migra dados de carteirinhas.xlsx e Pagamentos.xlsx para as tabelas criadas
"""

import pandas as pd
import psycopg2
from datetime import datetime, date
import logging
from dotenv import load_dotenv
import os
import unicodedata

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DataImporter:
    """Classe para importar dados das planilhas para o Supabase"""
    
    def __init__(self):
        load_dotenv()
        self.connection = None
        self._connect()
    
    def _connect(self):
        """Estabelece conexão com o banco de dados"""
        try:
            supabase_url = os.getenv('SUPABASE_URL')
            project_id = supabase_url.replace('https://', '').replace('.supabase.co', '')
            
            self.connection = psycopg2.connect(
                host=f'db.{project_id}.supabase.co',
                database='postgres',
                user='postgres',
                password=os.getenv('SUPABASE_PASSWORD'),
                port='5432'
            )
            logger.info("Conexão com banco de dados estabelecida")
        except Exception as e:
            logger.error(f"Erro ao conectar com banco: {e}")
            raise
    
    def import_pagamentos(self, file_path: str = "Pagamentos.xlsx"):
        """Importa dados da planilha de pagamentos"""
        try:
            if not os.path.exists(file_path):
                logger.warning(f"Arquivo {file_path} não encontrado")
                return False
            
            logger.info(f"Importando dados de pagamentos de {file_path}")
            
            # Ler planilha
            df = pd.read_excel(file_path)
            logger.info(f"Encontradas {len(df)} linhas na planilha de pagamentos")
            
            cursor = self.connection.cursor()
            
            # Limpar tabela existente (opcional)
            cursor.execute("DELETE FROM pagamentos")
            
            # Inserir dados
            for index, row in df.iterrows():
                try:
                    # Adaptar nomes das colunas conforme sua planilha
                    nome = str(row.get('nome', row.get('Nome', f'Pagamento_{index}')))
                    status = str(row.get('status', row.get('Status', 'ativo')))
                    
                    cursor.execute(
                        "INSERT INTO pagamentos (nome, status) VALUES (%s, %s)",
                        (nome, status)
                    )
                except Exception as e:
                    logger.error(f"Erro ao inserir linha {index}: {e}")
                    continue
            
            self.connection.commit()
            cursor.close()
            
            logger.info("Dados de pagamentos importados com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao importar pagamentos: {e}")
            self.connection.rollback()
            return False

    def import_agendamentos(self, file_path: str = "agendamentos.xlsx"):
        """Importa dados da planilha de agendamentos e substitui a tabela"""
        try:
            if not os.path.exists(file_path):
                logger.warning(f"Arquivo {file_path} não encontrado")
                return False

            logger.info(f"Importando dados de agendamentos de {file_path}")

            # Ler planilha sem cabeçalho e detectar linha de cabeçalhos reais
            raw = pd.read_excel(file_path, header=None)
            logger.info(f"Planilha carregada (sem header), linhas: {len(raw)}, colunas: {len(raw.columns)}")

            header_candidates = ['Carteirinha', 'Unidade', 'Id Atendimento', 'Paciente']
            header_row_idx = None
            for i in range(min(10, len(raw))):
                row_vals = [str(v) if pd.notna(v) else '' for v in list(raw.iloc[i].values)]
                if any(any(h.lower() in val.lower() for val in row_vals) for h in header_candidates):
                    header_row_idx = i
                    break

            if header_row_idx is None:
                # fallback: usar primeira linha como header
                header_row_idx = 0
                logger.warning("Cabeçalho não detectado automaticamente; usando primeira linha como header")

            df = pd.read_excel(file_path, header=header_row_idx)
            # remover linhas vazias e colunas 'Unnamed'
            df = df.dropna(how='all')
            df = df.loc[:, ~df.columns.map(lambda c: str(c).startswith('Unnamed'))]
            logger.info(f"Cabeçalho detectado na linha {header_row_idx}. Linhas úteis: {len(df)}; colunas: {len(df.columns)}")

            cursor = self.connection.cursor()

            # Limpar tabela existente
            cursor.execute("DELETE FROM agendamentos")

            def _normalize_key(k: str) -> str:
                # remover acentos e normalizar
                nk = unicodedata.normalize('NFKD', str(k)).encode('ASCII', 'ignore').decode('ASCII')
                nk = nk.lower().strip()
                for ch in [' ', '-', '/', '\\', '.', ':']:
                    nk = nk.replace(ch, '_')
                while '__' in nk:
                    nk = nk.replace('__', '_')
                return nk

            # Mapear colunas do df para nomes padronizados
            standard_cols = {
                'unidade': ['unidade'],
                'carteirinha': ['carteirinha','carteiras','carteira','n_carteirinha','num_carteirinha'],
                'cod_paciente': ['cod_paciente','codigo_paciente','codigo_do_paciente','id_paciente','codpaciente'],
                'paciente': ['paciente','nome_paciente'],
                'pagamento': ['pagamento','convenio','plano'],
                'data': ['data','data_atendimento','data_agendamento','dt_agendamento'],
                'hora_inicial': ['hora_inicial','hora','horario','hora_inicio','hr_inicial'],
                'sala': ['sala'],
                'id_profissional': ['id_profissional','profissional_id','id_do_profissional'],
                'profissional': ['profissional','nome_profissional'],
                'tipo_atend': ['tipo_atend','tipo_de_atend','tipo_de_atendimento','tipo_atendimento','tipo'],
                'qtd_sess': ['qtd_sess','quantidade_sessoes','qtd_sessoes','qtd'],
                'status': ['status','situacao'],
                'elegibilidade': ['elegibilidade'],
                'substituicao': ['substituicao'],
                'tipo_falta': ['tipo_falta','tipo_de_falta'],
                'id_pai': ['id_pai','id_agendamento_pai'],
                'codigo_faturamento': ['codigo_faturamento','cod_faturamento','codigo_de_faturamento'],
                'id_atendimento': ['id_atendimento','id_atend']
            }

            # construir mapa de colunas
            col_map = {}
            for original in df.columns:
                nk = _normalize_key(original)
                for target, synonyms in standard_cols.items():
                    if nk in synonyms:
                        col_map[target] = original
                        break

            # feedback de mapeamento
            logger.info(f"Mapa de colunas detectado: {col_map}")

            def get_val(row, keys, default=None):
                # tenta via mapa padrão
                for key in keys:
                    if key in col_map:
                        original = col_map[key]
                        val = row.get(original)
                        if pd.notna(val):
                            return val
                # fallback por nome direto
                for k in keys:
                    if k in row and pd.notna(row[k]):
                        return row[k]
                return default

            skipped_empty = 0
            skipped_invalid = 0
            inseridos = 0

            for index, row in df.iterrows():
                try:
                    # Normalização de campos com múltiplas possíveis grafias
                    unidade = str(get_val(row, ['unidade', 'Unidade'], '')) or None
                    carteirinha = str(get_val(row, ['carteirinha', 'Carteirinha'], '')) or None
                    cod_paciente = str(get_val(row, ['cod_paciente', 'Cod_Paciente', 'Codigo_Paciente'], '')) or None
                    paciente = str(get_val(row, ['paciente', 'Paciente'], '')) or None
                    pagamento = str(get_val(row, ['pagamento', 'Pagamento'], '')) or None

                    # Datas e horários
                    data_raw = get_val(row, ['data', 'Data'])
                    data_val = None
                    if data_raw is not None and pd.notna(data_raw):
                        try:
                            # tentar converter strings e datetime diretamente
                            if isinstance(data_raw, (str,)):
                                dt = pd.to_datetime(data_raw, errors='coerce')
                                data_val = dt.date() if pd.notna(dt) else None
                            elif isinstance(data_raw, (int, float)):
                                # Excel serial date
                                dt = pd.to_datetime(data_raw, unit='d', origin='1899-12-30', errors='coerce')
                                data_val = dt.date() if pd.notna(dt) else None
                            else:
                                dt = pd.to_datetime(data_raw, errors='coerce')
                                data_val = dt.date() if pd.notna(dt) else None
                        except Exception:
                            data_val = None

                    hora_raw = get_val(row, ['hora_inicial', 'Hora_Inicial', 'hora', 'Hora'])
                    hora_val = None
                    if hora_raw is not None and pd.notna(hora_raw):
                        try:
                            # Aceitar formatos "HH:MM" ou datetime/time
                            if isinstance(hora_raw, (int, float)):
                                # Excel time as fraction of day
                                total_seconds = float(hora_raw) * 24 * 3600
                                import math
                                h = int(total_seconds // 3600) % 24
                                m = int((total_seconds % 3600) // 60)
                                s = int(math.floor(total_seconds % 60))
                                from datetime import time as dt_time
                                hora_val = dt_time(h, m, s)
                            else:
                                ts = pd.to_datetime(hora_raw, errors='coerce')
                                if pd.notna(ts):
                                    hora_val = ts.time()
                                else:
                                    hora_str = str(hora_raw).strip()
                                    if ":" in hora_str:
                                        parts = hora_str.split(":")
                                        h = int(parts[0])
                                        m = int(parts[1]) if len(parts) > 1 else 0
                                        from datetime import time as dt_time
                                        hora_val = dt_time(h, m)
                        except Exception:
                            hora_val = None

                    sala = str(get_val(row, ['sala', 'Sala'], '')) or None
                    id_profissional = get_val(row, ['id_profissional', 'Id_Profissional', 'ID_Profissional'])
                    try:
                        id_profissional = int(id_profissional) if pd.notna(id_profissional) else None
                    except Exception:
                        id_profissional = None
                    profissional = str(get_val(row, ['profissional', 'Profissional'], '')) or None
                    tipo_atend = str(get_val(row, ['tipo_atend', 'Tipo_Atend', 'tipo_de_atend', 'tipo_atendimento'], '')) or None
                    qtd_sess = get_val(row, ['qtd_sess', 'Qtd_Sess', 'Quantidade_Sessoes'])
                    try:
                        qtd_sess = int(qtd_sess) if pd.notna(qtd_sess) else None
                    except Exception:
                        qtd_sess = None
                    status_ag = str(get_val(row, ['status', 'Status'], '')) or None
                    elegibilidade = str(get_val(row, ['elegibilidade', 'Elegibilidade'], '')) or None
                    substituicao = str(get_val(row, ['substituicao', 'Substituicao'], '')) or None
                    tipo_falta = str(get_val(row, ['tipo_falta', 'Tipo_Falta'], '')) or None
                    id_pai = get_val(row, ['id_pai', 'Id_Pai'])
                    try:
                        id_pai = int(id_pai) if pd.notna(id_pai) else None
                    except Exception:
                        id_pai = None
                    codigo_faturamento = str(get_val(row, ['codigo_faturamento', 'Codigo_Faturamento'], '')) or None
                    id_atendimento = get_val(row, ['id_atendimento', 'Id Atendimento', 'Id_Atendimento'])
                    try:
                        id_atendimento = int(id_atendimento) if pd.notna(id_atendimento) else None
                    except Exception:
                        id_atendimento = None

                    # Descartar linhas totalmente vazias ou sem campos essenciais
                    all_values = [unidade, carteirinha, cod_paciente, paciente, pagamento, data_val, hora_val, sala,
                                  id_profissional, profissional, tipo_atend, qtd_sess, status_ag, elegibilidade,
                                  substituicao, tipo_falta, id_pai, codigo_faturamento]
                    if all(v is None or (isinstance(v, str) and v.strip() == '') for v in all_values):
                        skipped_empty += 1
                        continue

                    if not carteirinha and not paciente and not data_val:
                        skipped_invalid += 1
                        continue

                    cursor.execute(
                        """
                        INSERT INTO agendamentos (
                            unidade, carteirinha, cod_paciente, paciente, pagamento,
                            data, hora_inicial, sala, id_profissional, profissional,
                            tipo_atend, qtd_sess, status, elegibilidade, substituicao,
                            tipo_falta, id_pai, codigo_faturamento, id_atendimento
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            unidade, carteirinha, cod_paciente, paciente, pagamento,
                            data_val, hora_val, sala, id_profissional, profissional,
                            tipo_atend, qtd_sess, status_ag, elegibilidade, substituicao,
                            tipo_falta, id_pai, codigo_faturamento, id_atendimento
                        )
                    )
                    inseridos += 1
                except Exception as e:
                    logger.error(f"Erro ao inserir linha {index}: {e}")
                    continue

            self.connection.commit()
            cursor.close()

            logger.info(f"Agendamentos importados com sucesso: {inseridos} registros")
            logger.info(f"Linhas descartadas (vazias): {skipped_empty}")
            logger.info(f"Linhas descartadas (sem campos essenciais): {skipped_invalid}")
            return True

        except Exception as e:
            logger.error(f"Erro ao importar agendamentos: {e}")
            self.connection.rollback()
            return False
    def import_carteirinhas(self, file_path: str = "carteirinhas.xlsx"):
        """Importa dados da planilha de carteirinhas"""
        try:
            if not os.path.exists(file_path):
                logger.warning(f"Arquivo {file_path} não encontrado")
                return False
            
            logger.info(f"Importando dados de carteirinhas de {file_path}")
            
            # Ler planilha
            df = pd.read_excel(file_path)
            logger.info(f"Encontradas {len(df)} linhas na planilha de carteirinhas")
            
            cursor = self.connection.cursor()
            
            # Limpar tabela existente (opcional)
            cursor.execute("DELETE FROM carteirinhas")
            
            # Inserir dados
            for index, row in df.iterrows():
                try:
                    # Adaptar nomes das colunas conforme sua planilha
                    carteiras = str(row.get('carteiras', row.get('Carteirinha', row.get('carteirinha', f'CART_{index}'))))
                    paciente = str(row.get('paciente', row.get('Paciente', row.get('PACIENTE', f'Paciente_{index}'))))
                    
                    # Buscar ID do pagamento (assumindo que existe um campo relacionado)
                    id_pagamento = None
                    pagamento_nome = row.get('pagamento', row.get('Pagamento'))
                    if pagamento_nome:
                        cursor.execute("SELECT id FROM pagamentos WHERE nome = %s LIMIT 1", (str(pagamento_nome),))
                        result = cursor.fetchone()
                        if result:
                            id_pagamento = result[0]
                    
                    # Se não encontrou pagamento, usar o primeiro disponível
                    if not id_pagamento:
                        cursor.execute("SELECT id FROM pagamentos LIMIT 1")
                        result = cursor.fetchone()
                        if result:
                            id_pagamento = result[0]
                    
                    status = str(row.get('status', row.get('Status', 'ativo')))
                    
                    cursor.execute(
                        "INSERT INTO carteirinhas (carteiras, paciente, id_pagamento, status) VALUES (%s, %s, %s, %s)",
                        (carteiras, paciente, id_pagamento, status)
                    )
                except Exception as e:
                    logger.error(f"Erro ao inserir linha {index}: {e}")
                    continue
            
            self.connection.commit()
            cursor.close()
            
            logger.info("Dados de carteirinhas importados com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao importar carteirinhas: {e}")
            self.connection.rollback()
            return False
    
    def import_base_guias(self, file_path: str = "BaseGuiasImport2.xlsx"):
        """Importa dados da planilha de guias base"""
        try:
            if not os.path.exists(file_path):
                logger.warning(f"Arquivo {file_path} não encontrado")
                return False
            
            logger.info(f"Importando dados de guias base de {file_path}")
            
            # Ler planilha
            df = pd.read_excel(file_path)
            logger.info(f"Encontradas {len(df)} linhas na planilha de guias")
            
            cursor = self.connection.cursor()
            
            # Limpar tabela existente (opcional)
            cursor.execute("DELETE FROM baseguias")
            
            # Inserir dados
            for index, row in df.iterrows():
                try:
                    carteirinha = str(row.get('carteirinha', row.get('Carteirinha', f'CART_{index}')))
                    paciente = str(row.get('paciente', row.get('Paciente', f'Paciente_{index}')))
                    guia = str(row.get('guia', row.get('Guia', f'GUIA_{index}')))
                    
                    # Buscar ID do pagamento relacionado à carteirinha
                    id_pagamento = None
                    cursor.execute("SELECT id_pagamento FROM carteirinhas WHERE carteiras = %s LIMIT 1", (carteirinha,))
                    result = cursor.fetchone()
                    if result:
                        id_pagamento = result[0]
                    
                    # Processar datas
                    data_autorizacao = None
                    validade = None
                    
                    if 'data_autorizacao' in row and pd.notna(row['data_autorizacao']):
                        data_autorizacao = pd.to_datetime(row['data_autorizacao']).date()
                    
                    if 'validade' in row and pd.notna(row['validade']):
                        validade = pd.to_datetime(row['validade']).date()
                    
                    senha = str(row.get('senha', '')) if pd.notna(row.get('senha')) else None
                    codigo_terapia = str(row.get('codigo_terapia', '')) if pd.notna(row.get('codigo_terapia')) else None
                    qtde_solicitado = int(row.get('qtde_solicitado', 0)) if pd.notna(row.get('qtde_solicitado')) else None
                    sessoes_autorizadas = int(row.get('sessoes_autorizadas', 0)) if pd.notna(row.get('sessoes_autorizadas')) else None
                    
                    cursor.execute("""
                        INSERT INTO baseguias (
                            id_pagamento, carteirinha, paciente, guia, data_autorizacao,
                            senha, validade, codigo_terapia, qtde_solicitado, sessoes_autorizadas
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        id_pagamento, carteirinha, paciente, guia, data_autorizacao,
                        senha, validade, codigo_terapia, qtde_solicitado, sessoes_autorizadas
                    ))
                    
                except Exception as e:
                    logger.error(f"Erro ao inserir linha {index}: {e}")
                    continue
            
            self.connection.commit()
            cursor.close()
            
            logger.info("Dados de guias base importados com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao importar guias base: {e}")
            self.connection.rollback()
            return False
    
    def create_sample_agendamentos(self):
        """Cria dados de exemplo para agendamentos"""
        try:
            logger.info("Criando dados de exemplo para agendamentos")
            
            cursor = self.connection.cursor()
            
            # Buscar carteirinhas existentes
            cursor.execute("SELECT carteiras, paciente FROM carteirinhas LIMIT 10")
            carteirinhas = cursor.fetchall()
            
            if not carteirinhas:
                logger.warning("Nenhuma carteirinha encontrada para criar agendamentos")
                return False
            
            # Criar agendamentos de exemplo
            from datetime import timedelta
            
            for i, (carteirinha, paciente) in enumerate(carteirinhas):
                # Criar agendamento para amanhã
                data_agendamento = date.today() + timedelta(days=1)
                
                cursor.execute("""
                    INSERT INTO agendamentos (
                        unidade, carteirinha, cod_paciente, paciente, pagamento,
                        data, hora_inicial, sala, id_profissional, profissional,
                        tipo_atend, qtd_sess, status, codigo_faturamento
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    f"Unidade {i+1}",
                    carteirinha,
                    f"PAC{i+1:03d}",
                    paciente,
                    "Unimed",
                    data_agendamento,
                    "08:00",
                    f"Sala {i+1}",
                    i+1,
                    f"Dr. Profissional {i+1}",
                    "Consulta",
                    1,
                    "agendado",
                    f"FAT{i+1:03d}"
                ))
            
            self.connection.commit()
            cursor.close()
            
            logger.info(f"Criados {len(carteirinhas)} agendamentos de exemplo")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao criar agendamentos de exemplo: {e}")
            self.connection.rollback()
            return False
    
    def verify_import(self):
        """Verifica os dados importados"""
        try:
            cursor = self.connection.cursor()
            
            tables = ['pagamentos', 'carteirinhas', 'agendamentos', 'baseguias']
            
            logger.info("Verificando dados importados:")
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                logger.info(f"  {table}: {count} registros")
            
            cursor.close()
            
        except Exception as e:
            logger.error(f"Erro ao verificar importação: {e}")
    
    def close(self):
        """Fecha a conexão com o banco"""
        if self.connection:
            self.connection.close()
            logger.info("Conexão fechada")

def main():
    """Função principal para importar todos os dados"""
    importer = DataImporter()
    
    try:
        logger.info("Iniciando importação de dados...")
        
        # Importar pagamentos
        importer.import_pagamentos()
        
        # Importar carteirinhas
        importer.import_carteirinhas()
        
        # Importar guias base
        importer.import_base_guias()

        # Importar agendamentos a partir de planilha
        importer.import_agendamentos()
        
        # Verificar importação
        importer.verify_import()
        
        logger.info("Importação concluída com sucesso!")
        
    except Exception as e:
        logger.error(f"Erro durante importação: {e}")
    finally:
        importer.close()

if __name__ == "__main__":
    main()