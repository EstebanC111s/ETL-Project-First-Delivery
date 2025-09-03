from pathlib import Path
import pandas as pd

DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "data" / "Registro__nico_de_Prestadores_de_Servicios_P_blicos-RUPS.csv"

def extract(csv_path: Path = DEFAULT_INPUT) -> pd.DataFrame:
    df = pd.read_csv(csv_path, encoding="utf-8", low_memory=False)
    return df

if __name__ == "__main__":
    df = extract()
    print(df.shape)
