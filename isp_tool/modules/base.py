from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Iterable, Sequence, Tuple

import numpy as np

from ..models import ParameterSpec, RawMetadata


class ISPModule:
    module_id = "base"
    name = "Base"
    input_domains: Sequence[str] = ("bayer", "rgb")

    def __init__(self, specs: Iterable[ParameterSpec], enabled: bool = True):
        self.enabled = enabled
        self.specs = OrderedDict((spec.key, spec) for spec in specs)
        self.parameters: Dict[str, Any] = {
            spec.key: spec.default for spec in self.specs.values()
        }

    def process(
        self, image: np.ndarray, domain: str, metadata: RawMetadata
    ) -> Tuple[np.ndarray, str, Dict[str, Any]]:
        raise NotImplementedError

    def reset(self) -> None:
        self.parameters = {
            spec.key: spec.default for spec in self.specs.values()
        }

    def get_default_parameters(self) -> Dict[str, Any]:
        return {spec.key: spec.default for spec in self.specs.values()}

    def set_parameters(self, values: Dict[str, Any]) -> None:
        for key, value in values.items():
            if key in self.specs:
                spec = self.specs[key]
                if spec.kind == "float":
                    value = float(value)
                    if not np.isfinite(value):
                        raise ValueError(f"{spec.label} 不能是 NaN 或 Infinity")
                elif spec.kind == "int":
                    value = int(value)
                elif spec.kind == "bool":
                    value = bool(value)
                self.parameters[key] = value

    def config(self) -> Dict[str, Any]:
        config = {
            "id": self.module_id,
            "name": self.name,
            "enabled": self.enabled,
            "parameters": dict(self.parameters),
        }
        state = self.export_state()
        if state:
            config["state"] = state
        return config

    def export_state(self) -> Dict[str, Any]:
        return {}

    def load_state(self, state: Dict[str, Any]) -> None:
        del state
