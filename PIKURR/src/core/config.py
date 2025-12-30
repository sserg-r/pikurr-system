from pathlib import Path
from pydantic import BaseModel, PostgresDsn, computed_field, Json
from pydantic_settings import BaseSettings, SettingsConfigDict

class DBSettings(BaseModel):
    host: str
    port: int
    user: str
    password: str
    name: str

    @computed_field
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

class GEESettings(BaseModel):
    # Pydantic автоматически распарсит JSON-строку из .env в словарь
    service_account: Json | dict
    project: str # = "pikurr-project" # Опционально

class TileServices(BaseModel):
    esri: str
    google: str
    dzz: str

class DBTables(BaseModel):
    trap: str
    afields: str
    razgr: str

# class Models(BaseModel):
#     deep_lab_forest: str

class TelegramSettings(BaseModel):
    token: str | None = None
    chat_id: str | None = None

class PathConfig(BaseModel):
    """Настройки путей (читаются из PATHS__...)"""
    # data_dir: Path
    data_input: Path  # /data_input
    data_output: Path # /data_output

    @property
    def sources(self) -> Path:
        # return self.data_dir / "sources"
        return self.data_input / "sources"

    @property
    def predictions(self) -> Path:
        # return self.data_dir / "predictions"
        return self.data_output / "predictions"

    # @property
    # def temp(self) -> Path:
    #     return self.data_dir / "temp"

    # @property
    # def sample_tile_dir(self) -> Path:
    #     return self.temp / "images"

    # @property
    # def sample_tiles_pred_dir(self) -> Path:
    #     return self.temp / "images_pred"

    # @property
    # def smplhansenpnts(self) -> Path:
    #     return self.temp / "sample_points.geojson"

    @property
    def predictions_veget(self) -> Path:
        return self.predictions / "predictions_veget"

    @property
    def predictions_usab(self) -> Path:
        return self.predictions / "predictions_usab"

    @property
    def predictions_final(self) -> Path:
        return self.predictions / "predictions_final"

    @property
    def public_root(self) -> Path:
        return self.predictions / "geoserver_public"
    
    @property
    def tiles_dir(self) -> Path:
        """Специальная папка для сырых тайлов"""
        # return self.data_dir / "tiles" 
        return self.data_output / "tiles"
    
        
    @property
    def dist_dir(self) -> Path:
        """Папка для готовых пакетов обновлений"""
        return self.data_output / "dist"

  

    @property
    def sqlscripts(self) -> Path:
        # return Path(__file__).resolve().parent.parent.parent / "sqlscripts"
        return Path(__file__).resolve().parent.parent / "sqlscripts"

    @property
    def get_trapeze_agri(self) -> Path:
        return self.sqlscripts / "get_trapeze_on_agrifields.sql"

    @property
    def create_class_schema(self) -> Path:
        return self.sqlscripts / "create_classified_schema.sql" 
    
    @property
    def create_assessment_schema(self) -> Path:
        return self.sqlscripts / "create_assessment_schema.sql" 

    # @property
    # def models(self) -> Path:
    #     return Path(__file__).resolve().parent.parent.parent / "models"

    # @property
    # def deeplabforest(self) -> Path:
    #     return self.models / "deeplab_model_dump.h5"


class InferenceSettings(BaseModel):
    host: str #= "192.168.251.190"
    port: int #= 8500
    model_name: str #= "two"
    model_version: int #= 1
    batch_size: int #= 8

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # env_file=".env.docker",
        # env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore"
    )

    
    # base_dir: Path = Path(__file__).resolve().parent.parent.parent
    # data_dir: Path | None = None

    # data_input: Path  | None = None
    # data_output: Path | None = None

    db: DBSettings
    gee: GEESettings
    tileservices: TileServices
    dbtables: DBTables
    # models: Models
    inference: InferenceSettings
    telegram: TelegramSettings = TelegramSettings()
    paths: PathConfig

    # @computed_field
    # def paths(self) -> PathConfig:
    #     root_path = self.data_dir if self.data_dir else (self.base_dir / "data")
    #     return PathConfig(data_dir=root_path)

# Создаем экземпляр настроек, который будет использоваться во всем приложении
settings = Settings()