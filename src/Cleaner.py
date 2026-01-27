from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta
import os
import threading
import time
import queue
import tempfile
import shutil
import ctypes
import ctypes.wintypes
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class DormantFile:
    path: Path
    size_bytes: int
    last_modified: datetime
    root: str  # "Downloads" | "Temp"

def _get_known_folder_path(folder_guid: str) -> Optional[Path]:
    """Windows Known Folder GUID로 경로를 가져옵니다."""
    try:
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        def guid_from_str(g: str) -> GUID:
            import uuid
            u = uuid.UUID(g)
            data4 = (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:])
            return GUID(u.time_low, u.time_mid, u.time_hi_version, data4)

        SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
        SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID),
            ctypes.wintypes.DWORD,
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        SHGetKnownFolderPath.restype = ctypes.wintypes.HRESULT

        CoTaskMemFree = ctypes.windll.ole32.CoTaskMemFree
        CoTaskMemFree.argtypes = [ctypes.c_void_p]
        CoTaskMemFree.restype = None

        fid = guid_from_str(folder_guid)
        ppszPath = ctypes.c_wchar_p()
        hr = SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(ppszPath))
        if hr != 0:
            return None

        try:
            return Path(ppszPath.value)
        finally:
            CoTaskMemFree(ppszPath)
    except Exception:
        return None


def get_downloads_dir() -> Path:
    # Downloads Known Folder GUID
    p = _get_known_folder_path("374DE290-123F-4565-9164-39C4925E467B")
    if p and p.exists():
        return p
    return Path.home() / "Downloads"


def get_temp_dir() -> Path:
    temp = os.environ.get("TEMP") or os.environ.get("TMP")
    if temp:
        return Path(temp)
    return Path(r"C:\Temp")


def human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for u in units:
        if size < 1024.0 or u == units[-1]:
            return f"{int(size)} {u}" if u == "B" else f"{size:.1f} {u}"
        size /= 1024.0
    return f"{num_bytes} B"


# -----------------------------
# Delete-safety heuristics
# -----------------------------
# "지워도 문제없을" 가능성이 높은 항목만 SAFE로 분류합니다.
# - Temp 폴더: 캐시/로그/임시파일은 대체로 안전하지만, 실행/스크립트류는 REVIEW
# - Downloads 폴더: '미완료 다운로드/임시' 성격이 강한 것만 SAFE, 그 외는 REVIEW

_SAFE_NAMES = {
    "thumbs.db",
    ".ds_store",
}

# 다운로드/임시 성격이 강해 비교적 안전하게 삭제 가능한 확장자들(보수적으로 유지)
_SAFE_EXTS = {
    ".tmp",
    ".log",
    ".dmp",
    ".bak",
    ".old",
    ".crdownload",  # Chrome 미완료 다운로드
    ".part",        # 일부 다운로드/임시
    ".download",
}

# 실행/스크립트류는 안전하다고 단정하기 어려워 REVIEW
_EXEC_EXTS = {
    ".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jar", ".com", ".scr", ".reg",
}


def classify_delete_safety(f: DormantFile) -> Tuple[str, str]:
    """(level, reason)

    level:
      - "SAFE"   : 지워도 문제 없을 가능성이 높은 항목(추천)
      - "REVIEW" : 삭제 전 확인 권장
    """
    name = f.path.name.lower()
    ext = f.path.suffix.lower()

    if name in _SAFE_NAMES or name.startswith("~$"):
        return "SAFE", "시스템/오피스 임시 파일"

    # Temp는 대체로 캐시/임시지만, 실행/스크립트는 보수적으로 REVIEW
    if f.root.lower() == "temp":
        if ext in _EXEC_EXTS:
            return "REVIEW", "Temp 내 실행/스크립트 파일"
        if ext in _SAFE_EXTS:
            return "SAFE", "Temp 내 로그/임시 파일"
        # 확장자가 없어도 Temp면 대체로 안전하지만 보수적으로 SAFE로 두되 이유 제공
        return "SAFE", "Temp 내 캐시/임시 파일"

    # Downloads는 사용자 문서/과제/자료가 섞일 가능성이 높아 매우 보수적으로 분류
    if f.root.lower() == "downloads":
        if ext in {".crdownload", ".part", ".tmp", ".download"}:
            return "SAFE", "미완료 다운로드/임시 파일"
        if ext in _EXEC_EXTS:
            return "REVIEW", "다운로드된 실행/스크립트 파일"
        return "REVIEW", "다운로드 폴더 파일(확인 권장)"

    return "REVIEW", "분류 불가(확인 권장)"


def _is_under_root(p: Path, root: Path) -> bool:
    """안전장치: 지정 루트 하위 파일만 처리."""
    try:
        pr = p.resolve()
        rr = root.resolve()
        if pr == rr:
            return True
        return str(pr).lower().startswith(str(rr).lower() + os.sep.lower())
    except Exception:
        return False


def scan_dormant_files(
    days: int = 30,
    min_size_bytes: int = 0,           # 1024면 1KB 미만 무시
    include_downloads: bool = True,
    include_temp: bool = True,
    recursive: bool = True,
    max_files: int = 20000,            # 너무 많을 때 안전장치
) -> List[DormantFile]:
    now = datetime.now()
    cutoff = now - timedelta(days=days)

    targets: List[Tuple[str, Path]] = []
    if include_downloads:
        targets.append(("Downloads", get_downloads_dir()))
    if include_temp:
        targets.append(("Temp", get_temp_dir()))

    results: List[DormantFile] = []

    for root_name, root_path in targets:
        if not root_path.exists():
            continue

        it = root_path.rglob("*") if recursive else root_path.glob("*")
        count = 0

        for p in it:
            count += 1
            if count > max_files:
                break

            try:
                if p.is_dir() or p.is_symlink():
                    continue
            except OSError:
                continue

            if not _is_under_root(p, root_path):
                continue

            try:
                st = p.stat()
            except OSError:
                continue

            if st.st_size < min_size_bytes:
                continue

            lm = datetime.fromtimestamp(st.st_mtime)
            if lm <= cutoff:
                results.append(
                    DormantFile(
                        path=p,
                        size_bytes=int(st.st_size),
                        last_modified=lm,
                        root=root_name,
                    )
                )

    results.sort(key=lambda x: x.last_modified)  # 오래된 순
    return results


def summarize(files: List[DormantFile]) -> dict:
    total = sum(f.size_bytes for f in files)
    by_root = {"Downloads": 0, "Temp": 0}
    for f in files:
        if f.root in by_root:
            by_root[f.root] += f.size_bytes

    return {
        "count": len(files),
        "total_bytes": total,
        "total_human": human_size(total),
        "downloads_human": human_size(by_root["Downloads"]),
        "temp_human": human_size(by_root["Temp"]),
    }


def delete_files(files: List[DormantFile]) -> Tuple[List[Path], List[Tuple[Path, str]]]:
    """
    일반 삭제(휴지통X, 보안삭제X). 안전하게 Downloads/Temp 하위만 삭제.
    """
    deleted: List[Path] = []
    failed: List[Tuple[Path, str]] = []

    downloads = get_downloads_dir()
    tempdir = get_temp_dir()

    for f in files:
        p = f.path

        # 안전장치: Downloads 또는 Temp 아래만 허용
        if not (_is_under_root(p, downloads) or _is_under_root(p, tempdir)):
            failed.append((p, "Blocked: not under Downloads/Temp"))
            continue

        try:
            if p.exists() and p.is_file():
                p.unlink()
            deleted.append(p)
        except PermissionError as e:
            failed.append((p, f"PermissionError: {e}"))
        except FileNotFoundError:
            deleted.append(p)
        except OSError as e:
            failed.append((p, f"OSError: {e}"))

    return deleted, failed


class CleanerScanner:
    """Background scanner that streams progress events through a Queue.

    Emits events (dict):
      - {"type":"stage","message":str}
      - {"type":"stats","scanned":int,"found":int,"total_bytes":int,"elapsed":float}
      - {"type":"batch","files":[DormantFile,...],"safety":[(level,reason),...]}
      - {"type":"done","summary":dict,"files":[DormantFile,...]}
      - {"type":"error","message":str}
    """
    def __init__(
        self,
        q: queue.Queue,
        days: int = 30,
        min_size_bytes: int = 1024,
        include_downloads: bool = True,
        include_temp: bool = True,
        max_files: int = 500_000,
        batch_size: int = 150,
        stats_every: int = 200,
    ):
        self.q = q
        self.days = int(days)
        self.min_size_bytes = int(min_size_bytes)
        self.include_downloads = bool(include_downloads)
        self.include_temp = bool(include_temp)
        self.max_files = int(max_files)
        self.batch_size = int(batch_size)
        self.stats_every = int(stats_every)

        # ✅ stop flag (기존 코드에 없어서 스캔이 바로 에러로 종료됨)
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run_scan(
        self,
        *,
        days: int | None = None,
        ignore_tiny: bool | None = None,
        include_downloads: bool | None = None,
        include_temp: bool | None = None,
        max_files: int | None = None,
    ):
        """Run scan and push events to queue."""
        try:
            if days is not None:
                self.days = int(days)
            if ignore_tiny is not None:
                self.min_size_bytes = 1024 if bool(ignore_tiny) else 0
            if include_downloads is not None:
                self.include_downloads = bool(include_downloads)
            if include_temp is not None:
                self.include_temp = bool(include_temp)
            if max_files is not None:
                self.max_files = int(max_files)

            cutoff = datetime.now() - timedelta(days=self.days)
            cutoff_ts = cutoff.timestamp()

            scanned = 0
            found = 0
            found_size = 0

            all_files: list[DormantFile] = []
            batch: list[DormantFile] = []
            safety_batch: list[tuple[str, str]] = []

            start_ts = time.time()
            self.q.put({"type": "stage", "message": f"스캔 시작 (기준: {self.days}일 이전)"})

            def push_stats(force: bool = False):
                nonlocal scanned, found, found_size
                if force or (scanned % self.stats_every == 0):
                    elapsed = max(time.time() - start_ts, 0.001)
                    self.q.put({
                        "type": "stats",
                        "scanned": scanned,
                        "found": found,
                        "total_bytes": found_size,
                        "elapsed": elapsed,
                    })

            def flush_batch():
                nonlocal batch, safety_batch
                if batch:
                    self.q.put({"type": "batch", "files": batch, "safety": safety_batch})
                    batch = []
                    safety_batch = []

            def scan_root(root_name: str, start_path: Path):
                nonlocal scanned, found, found_size, all_files, batch, safety_batch

                if self._stop_event.is_set():
                    return
                if not start_path.exists():
                    return

                self.q.put({"type": "stage", "message": f"{root_name} 검사 중..."})

                for df in self._iter_files(start_path, root_name):
                    if self._stop_event.is_set():
                        return
                    scanned += 1
                    push_stats()

                    if scanned >= self.max_files:
                        self.q.put({"type": "stage", "message": f"최대 파일 수({self.max_files}) 도달 → 스캔 중지"})
                        return

                    if df.size_bytes < self.min_size_bytes:
                        continue

                    # 오래된 파일만 후보
                    if df.last_modified.timestamp() > cutoff_ts:
                        continue

                    # 후보 채택
                    found += 1
                    found_size += df.size_bytes
                    all_files.append(df)

                    level, reason = classify_delete_safety(df)
                    batch.append(df)
                    safety_batch.append((level, reason))

                    if len(batch) >= self.batch_size:
                        flush_batch()

            # roots
            if self.include_downloads:
                scan_root("Downloads", get_downloads_dir())
            if self.include_temp:
                scan_root("Temp", get_temp_dir())
            flush_batch()
            push_stats(force=True)

            summary = summarize(all_files)
            self.q.put({"type": "done", "summary": summary, "files": all_files})

        except Exception as e:
            self.q.put({"type": "error", "message": str(e)})

    def _iter_files(self, start_path: Path, root_name: str):
        """Yield DormantFile under start_path."""
        # os.walk는 권한 오류에 비교적 강함
        for root, _, files in os.walk(str(start_path)):
            if self._stop_event.is_set():
                return
            for name in files:
                if self._stop_event.is_set():
                    return
                full_path = Path(root) / name
                try:
                    st = full_path.stat()
                except Exception:
                    continue

                yield DormantFile(
                    root=root_name,
                    path=full_path,
                    size_bytes=int(st.st_size),
                    last_modified=datetime.fromtimestamp(st.st_mtime),
                )
