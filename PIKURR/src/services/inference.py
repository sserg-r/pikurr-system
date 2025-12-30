import numpy as np
import ovmsclient
from src.core.config import settings
from tqdm import tqdm

class InferenceService:
    def __init__(self, inference_settings=None):
        self.settings = inference_settings or settings.inference
        
        address = f"{self.settings.host}:{self.settings.port}"
        print(f"[InferenceService] Connecting to: {address} ...") # <--- Отладка
        
        self.client = ovmsclient.make_grpc_client(address)
        
        # Добавляем timeout=10, так как это помогло в debug-скрипте
        print(f"[InferenceService] Loading metadata for model: {self.settings.model_name}...")
        try:
            self.model_metadata = self.client.get_model_metadata(
                model_name=self.settings.model_name,
                model_version=self.settings.model_version,
                timeout=10 
            )
            print("[InferenceService] Metadata loaded successfully.")
        except Exception as e:
            print(f"[InferenceService] ERROR: Could not load metadata from {address}")
            raise e
            
        self.input_name = next(iter(self.model_metadata["inputs"]))

    def predict_batch(self, images: np.ndarray) -> np.ndarray:
        predictions = []
        # Если изображений нет или размер батча 0 - защита от деления на ноль
        if len(images) == 0:
            return np.array([])
            
        total_batches = (len(images) + self.settings.batch_size - 1) // self.settings.batch_size
        
        # Убираем tqdm, если батчей мало, чтобы не засорять логи, или оставляем
        iterator = range(0, len(images), self.settings.batch_size)
        if total_batches > 1:
            iterator = tqdm(iterator, desc="Inferencing", total=total_batches, leave=False)

        for i in iterator:
            batch = images[i:i+self.settings.batch_size].astype(np.float32)
            inputs = {self.input_name: batch}
            result = self.client.predict(
                inputs=inputs,
                model_name=self.settings.model_name,
                model_version=self.settings.model_version,
                timeout=30 # Таймаут на само предсказание (может быть долгим)
            )
            predictions.append(result)

        return np.vstack(predictions)