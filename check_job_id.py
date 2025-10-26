import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
job_id = os.getenv("JOB_ID", "b0fc7ccb-d21c-48d1-8a94-18a7d5316e42")

if not url or not key:
    print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    raise SystemExit(1)

client = create_client(url, key)
res = client.table("job_carteirinhas").select("*").eq("id", job_id).execute()
print(res.data)