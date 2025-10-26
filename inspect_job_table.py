import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_PASSWORD = os.getenv("SUPABASE_PASSWORD")

if not SUPABASE_URL or not SUPABASE_PASSWORD:
    raise RuntimeError("SUPABASE_URL and SUPABASE_PASSWORD must be set in environment")

project_id = SUPABASE_URL.replace('https://', '').replace('.supabase.co', '')

conn = psycopg2.connect(
    host=f'db.{project_id}.supabase.co',
    database='postgres',
    user='postgres',
    password=SUPABASE_PASSWORD,
    port='5432'
)
cur = conn.cursor()

print("-- Columns of job_carteirinhas --")
cur.execute("""
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema='public' AND table_name='job_carteirinhas'
ORDER BY ordinal_position;
""")
for row in cur.fetchall():
    print(row)

print("\n-- Check constraints of job_carteirinhas --")
cur.execute("""
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'public.job_carteirinhas'::regclass AND contype = 'c';
""")
for row in cur.fetchall():
    print(row)

print("\n-- Sample rows (limit 5) --")
cur.execute("SELECT id, type, status, error FROM public.job_carteirinhas ORDER BY created_at DESC LIMIT 5;")
for row in cur.fetchall():
    print(row)

cur.close()
conn.close()
print("\nDone.")