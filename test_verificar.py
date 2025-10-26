import os
import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8002")
TOKEN = os.environ.get("API_TOKEN", "webscraping_api_token_2025")

url = f"{API_BASE_URL}/verificar_carteirinha"
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "accept": "application/json",
}
payload = {"carteirinha": "0064.8000.400948.00-5"}

try:
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    print("status:", resp.status_code)
    print("body:", resp.text)
except Exception as e:
    print("request_error:", e)