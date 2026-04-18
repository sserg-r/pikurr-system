from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from src.core.config import Settings
import pandas as pd

class DatabaseService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._engine = create_engine(self.settings.db.dsn)

    def get_engine(self) -> Engine:
        return self._engine
    
    def execute_query(self, query: str, params: dict | None = None) -> pd.DataFrame:
        """Выполняет SQL запрос и возвращает DataFrame"""
        import pandas as pd
        return pd.read_sql(query, self.get_engine(), params=params)
    
    def execute_sql_file(self, path: Path) -> None:
        """Выполняет SQL-скрипт из файла"""
        with self.get_engine().connect() as conn:
            with open(path, 'r') as sql_file:
                sql = text(sql_file.read())
                conn.execute(sql)
                conn.commit()
    def execute(self, query: str, params: tuple | dict | None = None) -> None:
        """Выполняет SQL запрос без возврата результата (INSERT, UPDATE, DELETE)"""
        with self.get_engine().connect() as conn:
            conn.execute(text(query), params or {})
            conn.commit()