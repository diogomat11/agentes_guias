import pandas as pd
import unicodedata

def normalize_key(k: str) -> str:
    nk = unicodedata.normalize('NFKD', str(k)).encode('ASCII', 'ignore').decode('ASCII')
    nk = nk.lower().strip()
    for ch in [' ', '-', '/', '\\', '.', ':']:
        nk = nk.replace(ch, '_')
    while '__' in nk:
        nk = nk.replace('__', '_')
    return nk

def detect_header(fp: str):
    raw = pd.read_excel(fp, header=None)
    header_candidates = ['Carteirinha', 'Unidade', 'Id Atendimento', 'Paciente']
    header_row_idx = None
    for i in range(min(10, len(raw))):
        row_vals = [str(v) if pd.notna(v) else '' for v in list(raw.iloc[i].values)]
        if any(any(h.lower() in val.lower() for val in row_vals) for h in header_candidates):
            header_row_idx = i
            break
    if header_row_idx is None:
        header_row_idx = 0
    df = pd.read_excel(fp, header=header_row_idx)
    df = df.dropna(how='all')
    df = df.loc[:, ~df.columns.map(lambda c: str(c).startswith('Unnamed'))]
    return header_row_idx, df

def main():
    fp = 'agendamentos.xlsx'
    header_row_idx, df = detect_header(fp)
    print('Header row:', header_row_idx)
    print('Columns original:', list(df.columns))
    normalized = [normalize_key(c) for c in df.columns]
    print('Columns normalized:', normalized)
    print('Sample rows (3):')
    print(df.head(3))

if __name__ == '__main__':
    main()