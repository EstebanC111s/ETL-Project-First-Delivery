import pandas as pd
from sqlalchemy import create_engine

def load(df: pd.DataFrame, db_path="database/rups.db"):
    engine = create_engine(f"sqlite:///{db_path}")
    df.to_sql("prestadores", engine, index=False, if_exists="replace")

if __name__ == "__main__":
    from extract import extract
    from transform import transform
    df = transform(extract())
    load(df)
