"""Настройки синтетики с одним видом контура — для тестов, которые проверяют вид отдельно."""

from genfacade.config import Config
from genfacade.schema import ContourKind


def only(cfg: Config, kind: ContourKind) -> Config:
    """Настройки, при которых все дома — вида kind."""
    weights = {k: float(k is kind) for k in ContourKind}
    syn = cfg.synthetic
    mix = syn.contours.model_copy(update={"weights": weights})
    return cfg.model_copy(update={"synthetic": syn.model_copy(update={"contours": mix})})


def only_toml(kind: ContourKind) -> str:
    """То же строкой synthetic.toml: для настроек, собираемых из папки."""
    pairs = ", ".join(f"{k.value} = {float(k is kind)}" for k in ContourKind)
    return f"[contours]\nweights = {{ {pairs} }}\n"
