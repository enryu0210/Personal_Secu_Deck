# src/secure_wiper.py
import os
import secrets

class SecureWiper:
    """
    Windows 전용 보안 삭제 엔진 (3-pass overwrite)

    - pass1: 0x00 덮어쓰기
    - pass2: 0xFF 덮어쓰기
    - pass3: 난수 덮어쓰기
    - 마지막: os.remove()

    return: (status, detail)
    status:
    "SUCCESS", "IN_USE", "PERMISSION", "SYSTEM_BLOCKED",
    "NOT_FOUND", "INVALID", "IO_ERROR", "UNKNOWN"
    """

    def __init__(self, chunk_size=1024 * 1024):
        self.chunk_size = chunk_size

    def is_system_protected_path(self, path: str) -> bool:
        """
        안전장치: 시스템 파일/경로 삭제 거부
        (팀 정책에 따라 blocked 경로는 더 추가 가능)
        """
        p = os.path.abspath(path)

        if os.name == "nt":
            blocked = [
                os.environ.get("WINDIR", r"C:\Windows"),
                r"C:\Program Files",
                r"C:\Program Files (x86)",
            ]
            p_low = p.lower()
            for b in blocked:
                if not b:
                    continue
                b_abs = os.path.abspath(b).lower()
                if p_low == b_abs or p_low.startswith(b_abs + os.sep):
                    return True

        return False

    def wipe_file(self, path: str, progress_cb=None):
        """
        progress_cb(written_bytes, total_bytes, stage)
        stage: PASS1_ZERO / PASS2_ONE / PASS3_RANDOM
        """
        try:
            if not path or not isinstance(path, str):
                return "INVALID", "경로가 올바르지 않습니다."

            if not os.path.exists(path):
                return "NOT_FOUND", "파일이 존재하지 않습니다."

            if self.is_system_protected_path(path):
                return "SYSTEM_BLOCKED", "시스템 보호 파일/경로는 삭제가 거부됩니다."

            if not os.path.isfile(path):
                return "INVALID", "일반 파일만 처리할 수 있습니다."

            total = os.path.getsize(path)

            # r+b: 바이너리 read/write. 다른 프로세스가 잡고 있거나 권한이 없으면 여기서 예외 가능
            with open(path, "r+b", buffering=0) as f:
                self._overwrite(f, total, pattern=0x00, stage="PASS1_ZERO", progress_cb=progress_cb)
                self._overwrite(f, total, pattern=0xFF, stage="PASS2_ONE", progress_cb=progress_cb)
                self._overwrite(f, total, pattern=None, stage="PASS3_RANDOM", progress_cb=progress_cb)

            os.remove(path)
            return "SUCCESS", "삭제 완료"

        except PermissionError as e:
            return "PERMISSION", str(e)
        except FileNotFoundError as e:
            return "NOT_FOUND", str(e)
        except OSError as e:
            # Windows에서 "사용 중"일 때 자주 보이는 메시지 기반 분기
            msg = str(e).lower()
            if ("being used" in msg) or ("used by another process" in msg) or ("process cannot access" in msg):
                return "IN_USE", str(e)
            return "IO_ERROR", str(e)
        except Exception as e:
            return "UNKNOWN", repr(e)

    def _overwrite(self, f, total: int, pattern, stage: str, progress_cb=None):
        """
        파일 전체를 chunk 단위로 덮어쓰기.
        pattern:
        - 0x00 또는 0xFF
        - None이면 난수
        """
        f.seek(0)
        written = 0
        remaining = total

        while remaining > 0:
            n = min(self.chunk_size, remaining)

            if pattern is None:
                buf = secrets.token_bytes(n)
            else:
                buf = bytes([pattern]) * n

            f.write(buf)
            written += n
            remaining -= n

            if progress_cb:
                progress_cb(written, total, stage)

        # 디스크 반영 최대화(실패해도 진행)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            pass
