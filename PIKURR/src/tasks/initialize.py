# ... (импорты те же)
from pathlib import Path
import subprocess
import os
import pandas as pd
from src.services.db import DatabaseService
# from src.core.config import Settings
from src.core.config import settings

class InitializeTask:
    def __init__(self):
        self.settings = settings
        self.db_service = DatabaseService(settings)
        
    def run(self):
        # 1. Разграфка (с параметром select)
        self._run_ogr2ogr(
            source=self.settings.paths.sources / "razgrafka_SK63.zip",
            table_name=self.settings.dbtables.razgr,
            extra_args=['-select', 'm10000_id,n10000']
        )
        
        # 2. Агрополя
        self._run_ogr2ogr(
            source=self.settings.paths.sources / "agrifields.zip",
            table_name=self.settings.dbtables.afields
        )
        
        # 3. SQL запрос для создания таблицы связей
        # Читаем SQL файл
        with open(self.settings.paths.get_trapeze_agri, 'r') as sql_file:
            sql = sql_file.read()
            # Выполняем запрос через pandas (он вернет список трапеций)
            df = self.db_service.execute_query(sql)
        
        # Обработка данных
        if not df.empty:
            traps_serv = pd.DataFrame({
                'name': df['n10000'], # Было trapeze, но в SQL мы переименовали
                'serv': 'dzz'
            }).drop_duplicates()
            
            # Сохранение в таблицу trapeze_serv
            engine = self.db_service.get_engine()
            traps_serv.to_sql(
                name=self.settings.dbtables.trap,
                con=engine,
                if_exists='replace',
                index=False
            )
        else:
            print("WARNING: No intersection found between fields and trapezes.")

        print("Creating assessment schema...")
        # Путь к новому SQL файлу.
        # Можно добавить его в config.py в PathSettings, но для скорости пропишем путь тут:
        # schema_path = self.settings.paths.sqlscripts / "create_assessment_schema.sql" 

        schema_path = self.settings.paths.create_assessment_schema
        
        if schema_path.exists():
            self.db_service.execute_sql_file(schema_path)
            print("Assessment schema created successfully.")
        else:
            print(f"ERROR: Schema file not found at {schema_path}")            

    def _run_ogr2ogr(self, source: Path, table_name: str, extra_args: list[str] | None = None):
        """Вспомогательный метод для выполнения ogr2ogr"""
        env = os.environ.copy()
        env["PGPASSWORD"] = self.settings.db.password
        
        # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
        # Для zip файлов нужно добавлять префикс /vsizip/
        source_str = str(source)
        if source.suffix == '.zip':
            # Важно: путь должен быть абсолютным, но в докере он и так начинается с /data
            source_str = f"/vsizip/{source_str}"
        # -------------------------

        cmd = [
            'ogr2ogr',
            '-f', 'PostgreSQL',
            f'PG:dbname={self.settings.db.name} host={self.settings.db.host} '
            f'port={self.settings.db.port} user={self.settings.db.user}',
            source_str, # Используем модифицированную строку
            '-t_srs', 'EPSG:4326',
            '-nln', table_name,
            '-lco', 'SPATIAL_INDEX=GIST',
            '-lco', 'GEOMETRY_NAME=geom',
            '-overwrite'
        ]
        
        if extra_args:
            cmd.extend(extra_args)
        
        print(f"Executing: {' '.join(cmd)}") # Для отладки в логах
        subprocess.run(cmd, env=env, check=True)

if __name__ == "__main__":
    # settings = Settings()
    task = InitializeTask()
    task.run()