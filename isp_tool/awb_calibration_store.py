"""Durable user-device calibration; never overwrite a failed/corrupt load."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .awb_ccm_table import CalibrationTable
from .i18n import preferences_path


class CalibrationStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else preferences_path().with_name('awb_ccm_calibration.json')

    def load(self):
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return CalibrationTable.default()
        if size > 1024 * 1024:
            raise ValueError('标定表超过 1 MiB')
        return CalibrationTable.from_payload(json.loads(self.path.read_text(encoding='utf-8-sig')))

    def save(self, table):
        # Validate before touching disk. Replace on the same filesystem so a
        # failed write cannot truncate the previously accepted calibration.
        validated = CalibrationTable.from_payload(table.to_payload())
        content = json.dumps(validated.to_payload(), ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             dir=self.path.parent, prefix=self.path.name+'.',
                                             suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
