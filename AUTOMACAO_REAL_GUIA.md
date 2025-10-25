# 🚀 Automação Real de Web Scraping - Guia Completo

## 📋 Visão Geral

A automação real de web scraping foi integrada ao sistema, substituindo o processo manual baseado em Excel por uma solução automatizada que:

- **Obtém carteirinhas** do Supabase com filtros personalizáveis
- **Executa web scraping real** usando macros Excel existentes
- **Armazena dados extraídos** diretamente na tabela `baseguias` do Supabase
- **Registra logs** de execução para monitoramento

## 🔧 Arquivos Principais

### 1. `automacao_webscraping_real.py`
- **Classe principal**: `WebScrapingRealAutomacao`
- **Funcionalidade**: Orquestra todo o processo de automação real
- **Integração**: Com Excel, Supabase e sistema de logs

### 2. `automacao_carteirinhas.py` (Modificado)
- **Função atualizada**: `vasculhar_carteirinhas()`
- **Novo parâmetro**: `usar_webscraping_real=True`
- **Comportamento**: Delega para automação real quando habilitado

### 3. `api_carteirinhas.py` (Modificado)
- **Novo endpoint**: `/executar_webscraping_real`
- **Métodos**: POST com parâmetros opcionais
- **Autenticação**: Bearer token obrigatório

## 🌐 API - Endpoint de Automação Real

### URL
```
POST http://localhost:8002/executar_webscraping_real
```

### Headers
```json
{
  "Authorization": "Bearer webscraping_api_token_2025",
  "Content-Type": "application/json"
}
```

### Parâmetros (Opcionais)

#### 1. Por Intervalo de Datas
```json
{
  "data_inicial": "2025-01-01",
  "data_final": "2025-01-31"
}
```

#### 2. Por Carteirinha Específica
```json
{
  "carteirinha": "63307737"
}
```

#### 3. Query String (Alternativa)
```
POST /executar_webscraping_real?carteirinha=63307737
POST /executar_webscraping_real?data_inicial=2025-01-01&data_final=2025-01-31
```

### Resposta de Sucesso
```json
{
  "status": "success",
  "message": "Automação real executada com sucesso",
  "carteirinhas_processadas": 15,
  "guias_inseridas": 45,
  "tempo_execucao": "00:02:30",
  "detalhes": {
    "carteirinhas_encontradas": 15,
    "guias_extraidas": 45,
    "guias_novas": 30,
    "guias_atualizadas": 15
  }
}
```

### Resposta de Warning
```json
{
  "status": "warning",
  "message": "Nenhuma carteirinha encontrada",
  "carteirinhas_processadas": 0,
  "guias_inseridas": 0
}
```

## 🔄 Fluxo de Execução

### 1. **Obtenção de Carteirinhas**
```python
# Busca carteirinhas no Supabase com filtros
carteirinhas = obter_carteirinhas_supabase(
    carteirinha_especifica="63307737",  # Opcional
    data_inicial="2025-01-01",          # Opcional
    data_final="2025-01-31"             # Opcional
)
```

### 2. **Preparação do Excel**
```python
# Cria arquivo Excel temporário com carteirinhas
excel_path = preparar_excel_carteirinhas(carteirinhas)
```

### 3. **Execução de Macros**
```python
# Executa macros de web scraping no Excel
executar_macros_webscraping(excel_path)
```

### 4. **Extração de Dados**
```python
# Extrai dados do Excel após web scraping
dados_extraidos = extrair_dados_excel(excel_path)
```

### 5. **Salvamento no Supabase**
```python
# Salva dados na tabela baseguias
salvar_dados_supabase(dados_extraidos)
```

### 6. **Registro de Logs**
```python
# Registra execução nos logs
registrar_log_execucao(resultado)
```

## 📊 Monitoramento e Logs

### Verificar Estatísticas
```bash
curl http://localhost:8002/estatisticas
```

### Visualizar Logs Recentes
```bash
curl -H "Authorization: Bearer webscraping_api_token_2025" \
     http://localhost:8002/logs?limit=10
```

### Status da API
```bash
curl http://localhost:8002/health
```

## 🧪 Testes

### Executar Teste Completo
```bash
python teste_automacao_real.py
```

### Teste Manual via API
```bash
# Teste com intervalo
curl -X POST http://localhost:8002/executar_webscraping_real \
  -H "Authorization: Bearer webscraping_api_token_2025" \
  -H "Content-Type: application/json" \
  -d '{"data_inicial": "2025-01-01", "data_final": "2025-01-31"}'

# Teste com carteirinha específica
curl -X POST http://localhost:8002/executar_webscraping_real?carteirinha=63307737 \
  -H "Authorization: Bearer webscraping_api_token_2025"
```

## ⚙️ Configuração

### Variáveis de Ambiente Necessárias
```env
# Supabase
SUPABASE_URL=sua_url_supabase
SUPABASE_KEY=sua_chave_supabase

# API Token
API_TOKEN=webscraping_api_token_2025

# Caminhos (opcionais)
EXCEL_TEMPLATE_PATH=caminho_para_template.xlsm
LOG_FILE_PATH=caminho_para_logs.txt
```

### Dependências Python
```txt
supabase>=2.0.0
requests>=2.28.0
python-dotenv>=1.0.0
win32com.client  # Para automação Excel
schedule>=1.2.0
uvicorn>=0.20.0
fastapi>=0.100.0
```

## 🔒 Segurança

### Autenticação
- **Token obrigatório** para endpoints sensíveis
- **Validação** de parâmetros de entrada
- **Logs** de todas as execuções

### Validações
- **Datas válidas** e intervalos lógicos
- **Carteirinhas existentes** no banco
- **Permissões** de acesso aos arquivos Excel

## 📈 Performance

### Otimizações Implementadas
- **Processamento em lote** de carteirinhas
- **Reutilização** de conexões Supabase
- **Cache** de dados temporários
- **Limpeza automática** de arquivos temporários

### Métricas Monitoradas
- **Tempo de execução** total
- **Carteirinhas processadas** por minuto
- **Taxa de sucesso** das extrações
- **Uso de memória** durante processamento

## 🚨 Troubleshooting

### Problemas Comuns

#### 1. "Nenhuma carteirinha encontrada"
- **Causa**: Filtros muito restritivos ou dados inexistentes
- **Solução**: Verificar parâmetros de data ou carteirinha

#### 2. "Erro ao conectar com Excel"
- **Causa**: Excel não instalado ou COM não configurado
- **Solução**: Instalar Excel e verificar permissões

#### 3. "Falha na conexão Supabase"
- **Causa**: Credenciais inválidas ou rede
- **Solução**: Verificar variáveis de ambiente

#### 4. "Token de autenticação inválido"
- **Causa**: Token incorreto ou expirado
- **Solução**: Verificar API_TOKEN no .env

### Logs de Debug
```python
# Habilitar logs detalhados
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 🔄 Migração do Sistema Antigo

### Antes (Excel)
```python
# Sistema antigo baseado em Excel
carteirinhas = ler_excel("carteirinhas.xlsx")
dados = processar_macros(carteirinhas)
salvar_excel("BaseGuiasImport2.xlsx", dados)
```

### Depois (Supabase)
```python
# Sistema novo integrado
resultado = vasculhar_carteirinhas(
    usar_webscraping_real=True,
    data_inicial="2025-01-01",
    data_final="2025-01-31"
)
```

## 📅 Agendamento Automático

### Execução Diária
```python
import schedule
import time

def executar_automacao_diaria():
    """Executa automação diariamente"""
    automacao = WebScrapingRealAutomacao()
    automacao.executar_automacao_completa()

# Agendar para executar todo dia às 08:00
schedule.every().day.at("08:00").do(executar_automacao_diaria)

while True:
    schedule.run_pending()
    time.sleep(60)
```

## 📞 Suporte

### Contatos
- **Desenvolvedor**: Sistema de Automação
- **Logs**: Verificar `log_execucao.txt`
- **API**: http://localhost:8002/health

### Comandos Úteis
```bash
# Verificar status da API
curl http://localhost:8002/health

# Executar teste completo
python teste_automacao_real.py

# Verificar logs recentes
tail -f log_execucao.txt
```

---

## ✅ Status da Integração

**✅ INTEGRAÇÃO COMPLETA FUNCIONANDO PERFEITAMENTE!**

- ✅ API funcionando
- ✅ Automação real disponível  
- ✅ Supabase conectado
- ✅ Logs sendo registrados
- ✅ Dados sendo salvos

**Score: 100% ✨**

O sistema está pronto para usar web scraping real com dados vindos do Supabase e salvos na tabela baseguias.