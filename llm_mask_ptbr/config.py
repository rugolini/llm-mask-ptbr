import os
import re
from dataclasses import dataclass, field, fields

import yaml

from .detectors import BUILTIN, dictionary
from .engine import Masker
from .vault import Vault

MODES = ("mask", "shadow")
KIND = re.compile(r"[A-Z][A-Z_]*")


@dataclass
class Settings:
    upstream: str = ""
    mode: str = "mask"
    vault: str = ":memory:"
    unmasked_models: list = field(default_factory=list)
    detectors: list = field(default_factory=lambda: list(BUILTIN))
    dictionary: dict = field(default_factory=dict)
    allow: list = field(default_factory=list)
    ner: dict | None = None
    host: str = "0.0.0.0"
    port: int = 8400


def _read(path):
    with open(path) as file:
        return yaml.safe_load(file) or {}


def load(path=None, env=os.environ):
    data = _read(path) if path else {}
    terms = dict(data.pop("dictionary", None) or {})
    if extra := data.pop("dictionary_file", None):
        for kind, values in _read(os.path.join(os.path.dirname(path), extra)).items():
            terms[kind] = [*terms.get(kind, []), *values]
    known = {f.name for f in fields(Settings)}
    if unknown := set(data) - known:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    settings = Settings(**data, dictionary=terms)
    for name in ("upstream", "mode", "vault", "host", "port"):
        if value := env.get(f"LLM_MASK_{name.upper()}"):
            setattr(settings, name, int(value) if name == "port" else value)
    if not settings.upstream:
        raise ValueError("upstream is required (settings file or LLM_MASK_UPSTREAM)")
    if settings.mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {settings.mode!r}")
    if unknown := set(settings.detectors) - set(BUILTIN):
        raise ValueError(f"unknown detectors: {sorted(unknown)}; available: {sorted(BUILTIN)}")
    if bad := [kind for kind in settings.dictionary if not KIND.fullmatch(kind)]:
        raise ValueError(f"dictionary kinds must be upper case letters and underscores, got {bad}")
    return settings


def build_masker(settings):
    detectors = [dictionary(settings.dictionary), *(BUILTIN[name] for name in settings.detectors)]
    if settings.ner is not None:
        from .ner import presidio
        detectors.append(presidio(**settings.ner))
    return Masker(detectors, Vault(settings.vault), settings.allow)
