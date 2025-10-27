import os
from dotenv import load_dotenv
from supabase import create_client

if __name__ == '__main__':
    load_dotenv()
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        raise SystemExit('Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY')
    client = create_client(url, key)
    res = client.rpc('purge_stale_processing', {'job_type': 'sgucard'}).execute()
    print('purged_count:', getattr(res, 'data', None))