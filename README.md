# Sistema de Automação de Carteirinhas

Descrição: sistema backend para atualização de base de guias; roda localmente após requisição via API.

Sistema automatizado para verificação e atualização de carteirinhas de pacientes, baseado na especificação do arquivo `prompt.yaml`.

## 📋 Descrição

Este projeto migra dados de planilhas Excel para um banco Supabase e automatiza a verificação de carteirinhas através de web scraping, oferecendo:

- **Migração de dados**: Excel → Supabase
- **Automação programada**: Verificações diárias e semanais
- **API REST**: Controle remoto e consultas
- **Processamento paralelo**: Via Docker/Selenoid
- **Logs detalhados**: Rastreamento completo

## 🗄️ Estrutura do Banco de Dados

### Tabelas Criadas

1. **pagamentos** - Dados de pagamentos dos pacientes
2. **carteirinhas** - Informações das carteirinhas
3. **agendamentos** - Agendamentos de consultas
4. **baseguias** - Base de guias autorizadas
5. **logs** - Logs de execução do sistema

## 🚀 Instalação e Configuração

### 1. Dependências

```bash
pip install -r requirements.txt
```

### 2. Configuração do Ambiente

Certifique-se de que o arquivo `.env` contém:

```env
SUPABASE_URL=sua_url_supabase
SUPABASE_PASSWORD=sua_senha
SUPABASE_SERVICE_ROLE_KEY=sua_service_key
API_TOKEN=seu_token_api
SELENOID_URL=http://localhost:4444/wd/hub
```

### 3. Configuração do Banco

```bash
python setup_database.py
```

### 4. Importação de Dados

```bash
python import_data.py
```

## 📁 Arquivos do Projeto

### Scripts Principais

- `setup_database.py` - Configuração inicial do banco
- `import_data.py` - Importação dos dados das planilhas
- `automacao_carteirinhas.py` - Lógica principal de automação
- `automacao_webscraping_real.py` - Web scraping real (SGUCARD)
- `api_carteirinhas.py` - API REST para controle

### Arquivos de Configuração

- **`prompt.yaml`** - Especificação do projeto
- **`.env`** - Variáveis de ambiente
- **`requirements.txt`** - Dependências Python

### Dados

- Dados operacionais são mantidos no banco (Supabase/Postgres)

## 🔧 Uso do Sistema

### Execução

### Iniciar API REST

```bash
python -m uvicorn api_carteirinhas:app --host 0.0.0.0 --port 8002 --reload
```

### Endpoints da API

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/` | Status da API |
| POST | `/verificar_carteirinha` | Verificar carteirinha específica |
| POST | `/atualizar_intervalo` | Atualizar por intervalo de datas |
| POST | `/scan_diario` | Executar scan diário manual |
| POST | `/scan_semanal` | Executar scan semanal manual |
| GET | `/guias` | Listar guias |
| GET | `/logs` | Visualizar logs |

Documentação completa de integração: ver `API_DOCS.md`.

## ⚙️ Funcionalidades

### 1. Função Principal: `vasculhar_carteirinhas`

```python
# Modo manual - carteirinha específica
await automacao.processar_carteirinha_especifica("123456789")

# Modo diário - carteirinhas com agendamentos amanhã
await automacao.executar_scan_diario()

# Modo semanal - todas as carteirinhas
await automacao.executar_scan_semanal()

# Modo intervalo - período específico
await automacao.processar_intervalo_datas("2024-01-01", "2024-01-31")
```

### 2. Agendamentos Automáticos

- **Diário**: 19:00 - Carteirinhas com agendamentos do dia seguinte
- **Semanal**: Sábados às 19:00 - Todas as carteirinhas

### 3. Processamento Paralelo

O sistema suporta processamento paralelo via Docker/Selenoid para otimizar a verificação de múltiplas carteirinhas.

## 📊 Monitoramento

### Logs

- Logs são armazenados na tabela `logs` do banco e expostos via API
  (`GET /logs`).

### Estatísticas

O sistema fornece estatísticas em tempo real:

- Total de carteirinhas processadas
- Guias encontradas/atualizadas
- Erros e sucessos
- Tempo de processamento

## 🔒 Segurança

- Autenticação via token API
- Conexões seguras com Supabase
- Logs sem exposição de dados sensíveis
- Validação de entrada em todos os endpoints

## 🐛 Troubleshooting

### Problemas Comuns

1. **Erro de conexão com Supabase**
   - Verifique as credenciais no `.env`
   - Confirme se o Supabase está acessível

2. **Falha na importação de dados**
   - Verifique se as planilhas Excel existem
   - Confirme o formato das colunas

3. **Erro no processamento de carteirinhas**
   - Verifique a configuração do Selenoid
   - Confirme se o Docker está rodando

## 📈 Próximos Passos

- [ ] Implementar interface web
- [ ] Adicionar notificações por email
- [ ] Melhorar tratamento de erros
- [ ] Adicionar testes automatizados
- [ ] Implementar cache para otimização

## 📞 Suporte

Para dúvidas ou problemas, consulte os logs do sistema ou verifique a documentação da API em `/docs` quando o servidor estiver rodando.