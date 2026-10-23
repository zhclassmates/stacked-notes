"""处理状态跟踪：增量跳过、失败重试、错误日志。

状态文件：output/.manifest.json
键为源文件绝对路径，值记录内容哈希、状态、产物、错误信息。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

STATUS_OK = "ok"
STATUS_FAILED = "failed"


def file_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {"version": 1, "files": {}}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # 状态文件损坏时备份重建，不阻塞流程
                backup = path.with_suffix(f".corrupt-{int(time.time())}.json")
                path.replace(backup)

    @property
    def files(self) -> dict:
        return self.data.setdefault("files", {})

    def is_done(self, src: Path, digest: str) -> bool:
        rec = self.files.get(str(src))
        return bool(rec and rec.get("sha256") == digest and rec.get("status") == STATUS_OK)

    def mark(self, src: Path, digest: str, status: str, outputs: list[str] | None = None,
             error: str | None = None, extra: dict | None = None):
        rec = {
            "sha256": digest,
            "status": status,
            "outputs": outputs or [],
            "error": error,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        if extra:
            rec["extra"] = extra
        self.files[str(src)] = rec

    def failed_sources(self) -> list[str]:
        return [k for k, v in self.files.items() if v.get("status") == STATUS_FAILED]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
