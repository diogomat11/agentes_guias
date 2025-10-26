import requests
import os

API_BASE = os.getenv('CARTEIRINHA_API_BASE_URL', 'http://127.0.0.1:8002')
TOKEN = os.getenv('API_TOKEN', 'webscraping_api_token_2025')

payload = {
    "type": "sgucard",
    "carteirinha": os.getenv('TEST_CARTEIRINHA', '0064.8000.400948.00-5'),
}

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "accept": "application/json",
}

r = requests.post(f"{API_BASE}/jobs", json=payload, headers=headers, timeout=10)
print("status:", r.status_code)
print(r.text)