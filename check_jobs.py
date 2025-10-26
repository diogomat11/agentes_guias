import os
from dotenv import load_dotenv
from supabase import create_client

if __name__ == "__main__":
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        raise SystemExit(1)
    client = create_client(url, key)
    res = client.table("job_carteirinhas").select("*").execute()
    print({"count": len(res.data or []), "rows": res.data})