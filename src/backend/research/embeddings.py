"""本地 embedding provider（研究域向量检索的可选后端）。

设计约束（与 PRD FR-05 / FR-01 对齐）：

* **默认关闭**：只有显式配置 ``RESEARCH_EMBEDDING_MODEL`` 才启用；未配置时检索
  保持词法匹配并如实标注 ``retrieval_method="lexical"``、``degraded=True``。
* **离线优先**：默认只用本机 Hugging Face 缓存里的模型（``local_files_only``），
  不联网下载；确实允许下载时必须显式打开 ``RESEARCH_EMBEDDING_ALLOW_DOWNLOAD``。
* **失败必须可解释**：模型缺失、依赖缺失、加载失败都抛 ``EmbeddingUnavailable``
  并带机器可读 reason，由 ``retrieval_service`` 降级词法并记录原因，绝不把词法
  结果冒充向量结果。
* **不隐式加载**：模块导入不加载模型；首次 ``__call__`` 时才在后台线程加载。

对外接口是一个可调用对象（``provider(texts) -> list[list[float]]``），与
``retrieval_service.configure_embedding_provider`` 的既有约定一致。
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

__all__ = [
    "EmbeddingUnavailable",
    "SentenceTransformerEmbeddingProvider",
    "build_provider_from_settings",
    "local_model_available",
    "normalize_model_name",
]


class EmbeddingUnavailable(RuntimeError):
    """embedding 后端不可用；``reason`` 给机器可读原因。"""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


def normalize_model_name(value: object) -> str:
    """去空白；空值视为未配置。"""

    if value is None:
        return ""
    return str(value).strip()


def _hub_cache_dir() -> str:
    """Hugging Face hub 缓存目录；取不到就返回空串。"""

    try:  # sentence-transformers 会带 huggingface_hub
        from huggingface_hub.constants import HF_HUB_CACHE

        return str(HF_HUB_CACHE)
    except Exception:  # pragma: no cover - 仅作能力探测用
        return ""


def local_model_available(model_name: str) -> bool:
    """模型是否已在本机缓存（不联网、不加载模型）。"""

    name = normalize_model_name(model_name)
    if not name:
        return False
    cache = _hub_cache_dir()
    if not cache:
        return False
    folder = "models--" + name.replace("/", "--")
    try:
        from pathlib import Path

        base = Path(cache) / folder
        return base.is_dir() and any(base.rglob("*.safetensors")) or (
            base / "snapshots"
        ).is_dir()
    except Exception:  # pragma: no cover - 探测失败按不可用处理
        return False


class SentenceTransformerEmbeddingProvider:
    """sentence-transformers 后端的惰性 provider（归一化向量，余弦=点积）。"""

    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        batch_size: int = 32,
        allow_download: bool = False,
    ) -> None:
        self.model_name = normalize_model_name(model_name)
        if not self.model_name:
            raise EmbeddingUnavailable("embedding_model_not_configured")
        self.device = (device or "cpu").strip() or "cpu"
        try:
            self.batch_size = max(1, int(batch_size))
        except (TypeError, ValueError):
            self.batch_size = 32
        self.allow_download = bool(allow_download)
        self._model = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- helpers
    @property
    def dimension(self) -> int:
        model = self._ensure_model()
        getter = getattr(model, "get_sentence_embedding_dimension", None)
        if callable(getter):
            value = getter()
            if isinstance(value, int) and value > 0:
                return value
        return 0

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:  # double-check
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except Exception as exc:  # pragma: no cover - 依赖缺失分支
                raise EmbeddingUnavailable(
                    "sentence_transformers_missing", f"未能导入 sentence-transformers：{exc}"
                ) from exc
            try:
                model = SentenceTransformer(
                    self.model_name,
                    device=self.device,
                    local_files_only=not self.allow_download,
                )
            except Exception as exc:  # 模型缺失/损坏/下载被禁
                if not local_model_available(self.model_name):
                    raise EmbeddingUnavailable(
                        "embedding_model_not_cached",
                        f"本机没有 {self.model_name} 的缓存，且未允许下载：{exc}",
                    ) from exc
                raise EmbeddingUnavailable(
                    "embedding_model_load_failed",
                    f"加载 {self.model_name} 失败：{exc}",
                ) from exc
            self._model = model
            return model

    # ---------------------------------------------------------------- call
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_model()
        prepared = [str(text if text is not None else "") for text in texts]
        vectors = model.encode(
            prepared,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        try:
            return [[float(x) for x in row] for row in vectors]
        except TypeError as exc:  # pragma: no cover - 防御
            raise EmbeddingUnavailable(
                "embedding_encode_failed", f"embedding 输出不是数值矩阵：{exc}"
            ) from exc

    __call__ = encode

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"SentenceTransformerEmbeddingProvider(model={self.model_name!r}, "
            f"device={self.device!r}, allow_download={self.allow_download!r})"
        )


def build_provider_from_settings() -> Optional[SentenceTransformerEmbeddingProvider]:
    """按 settings 构造 provider；未配置模型时返回 ``None``（保持词法检索）。"""

    from ..config import settings

    model = normalize_model_name(getattr(settings, "RESEARCH_EMBEDDING_MODEL", ""))
    if not model:
        return None
    return SentenceTransformerEmbeddingProvider(
        model,
        device=str(getattr(settings, "RESEARCH_EMBEDDING_DEVICE", "cpu") or "cpu"),
        batch_size=int(getattr(settings, "RESEARCH_EMBEDDING_BATCH_SIZE", 32) or 32),
        allow_download=bool(
            getattr(settings, "RESEARCH_EMBEDDING_ALLOW_DOWNLOAD", False)
        ),
    )
