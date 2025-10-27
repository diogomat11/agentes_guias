import os
import psycopg2
from dotenv import load_dotenv

"""
Aplica o arquivo SQL de RPCs (sql_jobs_rpcs.sql) no banco do Supabase.
Também valida a criação listando as funções instaladas.
"""

def get_connection():
    load_dotenv()
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_password = os.getenv('SUPABASE_PASSWORD')
    if not supabase_url or not supabase_password:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_PASSWORD não definidos no .env")
    project_id = supabase_url.replace('https://', '').replace('.supabase.co', '')
    conn = psycopg2.connect(
        host=f'db.{project_id}.supabase.co',
        database='postgres',
        user='postgres',
        password=supabase_password,
        port='5432'
    )
    return conn


def apply_sql(conn, sql_path: str):
    with open(sql_path, 'r', encoding='utf-8') as f:
        sql = f.read()
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    cur.close()


def list_installed_rpcs(conn):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT routine_name
          FROM information_schema.routines
         WHERE routine_schema = 'public'
           AND routine_name IN (
                'claim_jobs',
                'complete_job',
                'fail_job',
                'heartbeat_job',
                'release_job',
                'purge_stale_processing'
           )
         ORDER BY routine_name;
        """
    )
    rows = cur.fetchall()
    cur.close()
    names = [r[0] for r in rows]
    return names


def main():
    sql_path = os.path.join(os.path.dirname(__file__), 'sql_jobs_rpcs.sql')
    print({"sql_path": sql_path})
    conn = get_connection()
    try:
        apply_sql(conn, sql_path)
        rpcs = list_installed_rpcs(conn)
        print("RPCs instaladas:", rpcs)
    finally:
        conn.close()
        print("Conexão encerrada.")


if __name__ == '__main__':
    main()