import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
password = os.getenv('SUPABASE_PASSWORD')
job_id = os.getenv('JOB_ID', 'b0fc7ccb-d21c-48d1-8a94-18a7d5316e42')

if not supabase_url or not password:
    print('Missing SUPABASE_URL or SUPABASE_PASSWORD')
    raise SystemExit(1)

project_id = supabase_url.replace('https://','').replace('.supabase.co','')
conn = psycopg2.connect(
    host=f'db.{project_id}.supabase.co',
    database='postgres',
    user='postgres',
    password=password,
    port='5432'
)

try:
    cur = conn.cursor()
    try:
        cur.execute("UPDATE job_carteirinhas SET type='sgucard_error' WHERE id=%s", (job_id,))
        conn.commit()
        print('Updated job type via SQL successfully')
    except Exception as e:
        conn.rollback()
        print('SQL update failed:', str(e))
    finally:
        cur.close()
finally:
    conn.close()