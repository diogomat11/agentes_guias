import requests

if __name__ == "__main__":
    print("Trying GET /health ...")
    try:
        r = requests.get('http://127.0.0.1:8002/health', timeout=5)
        print('status', r.status_code)
        print(r.text)
    except Exception as e:
        print('error', e)