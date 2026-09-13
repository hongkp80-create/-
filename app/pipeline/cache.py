"""컨텐츠 해시 기반 캐시.

함정: 파일 mtime/경로 기반 캐시 키는 업로드할 때마다(파일이 복사/재생성되어 mtime이 바뀌므로)
매번 캐시 miss가 난다. 반드시 파일 내용 자체의 해시를 키로 써야 재업로드/재처리 시 캐시가 맞는다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

_CHUNK = 8 * 1024 * 1024


def content_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()[:24]


class JsonCache:
    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str) -> Optional[Any]:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value: Any) -> None:
        self._path(key).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def has(self, key: str) -> bool:
        return self._path(key).exists()
