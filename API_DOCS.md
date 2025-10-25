# Documentação da API de Automação de Carteirinhas

Base URL: `http://127.0.0.1:8002`

Autenticação: HTTP Bearer Token
- Header: `Authorization: Bearer <API_TOKEN>`
- O token é configurado em `.env` na chave `API_TOKEN`

## Endpoints de Info

- GET `/` — Status básico da API (público)
- GET `/health` — Saúde do sistema e banco (público)
- GET `/estatisticas` — Estatísticas gerais (público)
- GET `/status` — Status detalhado e últimas execuções (requer token)

## Endpoints de Automação

- POST `/verificar_carteirinha` — Executa verificação para uma carteirinha específica
  - Body JSON: `{ "carteirinha": "<numero>" }`
  - Retorna status, timestamp e resultado agregado

- POST `/atualizar_intervalo` — Executa atualização por intervalo de datas
  - Body JSON: `{ "data_inicial": "YYYY-MM-DD", "data_final": "YYYY-MM-DD" }`
  - Retorna contagens processadas e tempos

- POST `/executar_diario` — Dispara varredura diária manual
  - Retorna `ExecutionResponse` com métricas resumidas

- POST `/executar_semanal` — Dispara varredura semanal manual
  - Retorna `ExecutionResponse` com métricas resumidas

## Endpoints SGUCARD (Web Scraping Real)

- POST `/sgucard/todos` — Executa SGUCARD para todas as carteirinhas (thread)
  - Retorna: `{ status: "accepted", message: "Execução 'todos' iniciada (thread)" }`

- POST `/sgucard/carteirinha` — Executa SGUCARD para uma carteirinha específica (thread)
  - Body JSON: `{ "carteirinha": "<numero>" }`
  - Retorna: `{ status: "accepted", message: "Execução 'carteirinha' iniciada (thread) ..." }`

- POST `/sgucard/intervalo` — Executa SGUCARD por intervalo de datas (thread)
  - Body JSON: `{ "data_inicial": "YYYY-MM-DD", "data_final": "YYYY-MM-DD" }`
  - Retorna: `{ status: "accepted", message: "Execução 'intervalo' iniciada (thread) ..." }`

- POST `/executar_webscraping_real` — Executa web scraping real via automação
  - Query opcional: `carteirinha=<numero>`
  - Body opcional: `{ "data_inicial": "YYYY-MM-DD", "data_final": "YYYY-MM-DD" }`
  - Se fornecer `carteirinha`, roda modo manual; se fornecer intervalo, roda modo intervalo
  - Retorna `ExecutionResponse`

## Endpoints de Consulta

- GET `/guias/{carteirinha}` — Lista guias de uma carteirinha
  - Retorna array de objetos com: `id`, `carteirinha`, `paciente`, `guia`, `data_autorizacao`, `validade`, `codigo_terapia`, `sessoes_autorizadas`

- GET `/logs?limit=50` — Lista logs de execução recentes
  - Retorna array com: `id`, `timestamp`, `tipo_execucao`, `status`, `carteirinhas_processadas`, `guias_inseridas`, `guias_atualizadas`, `mensagem`

## Modelos de Resposta

- `ExecutionResponse`
  - Campos: `status`, `message`, `carteirinhas_processadas`, `guias_inseridas`, `guias_atualizadas`, `tempo_execucao`

## Exemplos de Requisição

PowerShell (Invoke-RestMethod):

- SGUCARD por carteirinha
```
$headers = @{ Authorization = "Bearer $env:API_TOKEN" }
$body = @{ carteirinha = "0064.8000.090500.00-1" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8002/sgucard/carteirinha" -Headers $headers -Body $body -ContentType 'application/json'
```

- Atualizar por intervalo
```
$headers = @{ Authorization = "Bearer $env:API_TOKEN" }
$body = @{ data_inicial = "2025-10-12"; data_final = "2025-10-12" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8002/atualizar_intervalo" -Headers $headers -Body $body -ContentType 'application/json'
```

- Executar diário
```
$headers = @{ Authorization = "Bearer $env:API_TOKEN" }
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8002/executar_diario" -Headers $headers
```

curl (Windows):

- SGUCARD por carteirinha
```
curl.exe -X POST "http://127.0.0.1:8002/sgucard/carteirinha" ^
  -H "Authorization: Bearer %API_TOKEN%" ^
  -H "Content-Type: application/json" ^
  -d "{\"carteirinha\":\"1234567890\"}"
```

- SGUCARD por intervalo
```
curl.exe -X POST "http://127.0.0.1:8002/sgucard/intervalo" ^
  -H "Authorization: Bearer %API_TOKEN%" ^
  -H "Content-Type: application/json" ^
  -d "{\"data_inicial\":\"2025-10-12\",\"data_final\":\"2025-10-12\"}"
```

## Agendamentos via API

- `POST /executar_diario` — dispara a rotina das carteirinhas com agendamentos do dia seguinte
- `POST /executar_semanal` — dispara a rotina semanal para todas as carteirinhas
- A API também agenda automaticamente no startup:
  - Diário: todos os dias às `19:00` (intervalo de amanhã)
  - Semanal: sábados às `19:00` (todas as carteirinhas)

## Erros Comuns

- 401 Unauthorized — Token inválido ou ausente
- 422 Unprocessable Entity — JSON malformado ou campos ausentes
- 500 Internal Server Error — Erro interno ao processar a execução

## Observações

- Configure `.env` com `API_TOKEN`, credenciais Supabase e variáveis necessárias.
- Em produção, prefira `http://localhost:8002` e um reverse proxy conforme necessidade.

## Exemplos por Linguagem

Node.js (axios):
```
import axios from 'axios';

const API_TOKEN = process.env.API_TOKEN;
const client = axios.create({
  baseURL: 'http://127.0.0.1:8002',
  headers: { Authorization: `Bearer ${API_TOKEN}` }
});

async function executarCarteirinha() {
  const resp = await client.post('/sgucard/carteirinha', { carteirinha: '1234567890' });
  console.log(resp.data);
}

async function consultarGuias() {
  const resp = await client.get('/guias/1234567890');
  console.log(resp.data);
}

executarCarteirinha();
```

Node.js (fetch nativo):
```
const API_TOKEN = process.env.API_TOKEN;
await fetch('http://127.0.0.1:8002/sgucard/intervalo', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${API_TOKEN}`,
  },
  body: JSON.stringify({ data_inicial: '2025-10-12', data_final: '2025-10-12' }),
});
```

Java (OkHttp):
```
import okhttp3.*;

OkHttpClient client = new OkHttpClient();
MediaType JSON = MediaType.get("application/json; charset=utf-8");
String token = System.getenv("API_TOKEN");

RequestBody body = RequestBody.create("{\"carteirinha\":\"1234567890\"}", JSON);
Request request = new Request.Builder()
    .url("http://127.0.0.1:8002/sgucard/carteirinha")
    .addHeader("Authorization", "Bearer " + token)
    .post(body)
    .build();

try (Response response = client.newCall(request).execute()) {
    System.out.println(response.body().string());
}
```

Java (HttpClient Java 11+):
```
var token = System.getenv("API_TOKEN");
var client = java.net.http.HttpClient.newHttpClient();
var req = java.net.http.HttpRequest.newBuilder()
    .uri(java.net.URI.create("http://127.0.0.1:8002/logs?limit=10"))
    .header("Authorization", "Bearer " + token)
    .build();
var resp = client.send(req, java.net.http.HttpResponse.BodyHandlers.ofString());
System.out.println(resp.body());
```

Python (requests):
```
import os
import requests

API_TOKEN = os.getenv('API_TOKEN')
headers = { 'Authorization': f'Bearer {API_TOKEN}' }

# SGUCARD por carteirinha
r = requests.post('http://127.0.0.1:8002/sgucard/carteirinha',
                  json={'carteirinha':'1234567890'}, headers=headers)
print(r.json())

# Consultar logs
r = requests.get('http://127.0.0.1:8002/logs', headers=headers)
print(r.json())
```

## Geração de Clientes (OpenAPI)

- A especificação OpenAPI está disponível em: `http://127.0.0.1:8002/openapi.json`.
- Baixar o arquivo (PowerShell):
  - `Invoke-WebRequest -Uri http://127.0.0.1:8002/openapi.json -OutFile openapi.json`
- Baixar com `curl.exe`:
  - `curl.exe -o openapi.json http://127.0.0.1:8002/openapi.json`

Gerar clientes com OpenAPI Generator (sem instalar globalmente):
- TypeScript Axios:
  - `npx @openapitools/openapi-generator-cli generate -i openapi.json -g typescript-axios -o clients/typescript-axios`
- Java:
  - `npx @openapitools/openapi-generator-cli generate -i openapi.json -g java -o clients/java`
- Python:
  - `npx @openapitools/openapi-generator-cli generate -i openapi.json -g python -o clients/python`

Opções úteis:
- Adicionar propriedades:
  - `--additional-properties=useSingleRequestParameter=true,supportsES6=true`
- Templates específicos podem ser configurados conforme a linguagem.