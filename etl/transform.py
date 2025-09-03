import pandas as pd

def transform(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df[df["DEPARTAMENTO_PRESTACION"].notna() & df["MUNICIPIO_PRESTACION"].notna()]
    return df

if __name__ == "__main__":
    from extract import extract
    df = extract()
    df_clean = transform(df)
    print(df_clean.shape)
