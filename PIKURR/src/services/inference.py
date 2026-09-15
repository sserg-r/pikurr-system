import numpy as np
import onnxruntime as ort
from src.core.config import settings


class InferenceService:
    def __init__(self, inference_settings=None):
        self.settings = inference_settings or settings.inference

        sess_options = ort.SessionOptions()
        if self.settings.intra_op_num_threads:
            sess_options.intra_op_num_threads = self.settings.intra_op_num_threads
        if self.settings.inter_op_num_threads:
            sess_options.inter_op_num_threads = self.settings.inter_op_num_threads

        print(f"[InferenceService] Loading ONNX model: {self.settings.onnx_model_path} ...")
        self.session = ort.InferenceSession(
            self.settings.onnx_model_path,
            sess_options=sess_options,
            providers=[self.settings.provider, "CPUExecutionProvider"],
        )

        active_providers = self.session.get_providers()
        print(f"[InferenceService] Active providers: {active_providers}")
        if active_providers[0] != self.settings.provider:
            # Тихий откат на CPU — тот самый класс отказа, который закрывали
            # в предыдущих раундах (см. project_pikurr_status.md, инцидент
            # CUDA_ERROR_INVALID_HANDLE): лучше упасть сразу и явно, чем
            # молча уйти в многократно более медленный CPU-путь.
            raise RuntimeError(
                f"[InferenceService] Требуемый провайдер '{self.settings.provider}' "
                f"не активен (получили {active_providers}). "
                f"Доступные провайдеры: {ort.get_available_providers()}."
            )

        self.input_name = self.session.get_inputs()[0].name

    def predict_batch(self, images: np.ndarray) -> np.ndarray:
        if len(images) == 0:
            return np.array([])

        predictions = []
        for i in range(0, len(images), self.settings.batch_size):
            batch = images[i:i + self.settings.batch_size].astype(np.float32)
            outputs = self.session.run(None, {self.input_name: batch})
            predictions.append(outputs[0])

        return np.vstack(predictions)
