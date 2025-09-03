from etl.extract import extract
from etl.transform import transform
from etl.load import load

if __name__ == "__main__":
    df = extract()
    print("[EXTRACT]", df.shape)
    df_clean = transform(df)
    print("[TRANSFORM]", df_clean.shape)
    load(df_clean)
    print("[LOAD] Data loaded into database/rups.db")
