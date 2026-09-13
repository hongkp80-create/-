"""Step 0: 실행 환경 감지 + 트랙(ASR 백엔드) 선택 + 필수 도구 점검.

트랙 분기:
  Darwin arm64        -> track "mac"      (mlx-whisper)
  Windows AMD64       -> track "windows"  (faster-whisper, CapCut 자동 export 보너스)
  그 외(Darwin x86_64 포함) -> track "fallback" (faster-whisper)
"""
from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MIN_FREE_DISK_GB = 5


@dataclass
class ToolCheck:
    name: str
    ok: bool
    detail: str
    install_hint: str = ""


@dataclass
class EnvReport:
    os_name: str
    machine: str
    track: str
    python_version: str
    checks: list[ToolCheck] = field(default_factory=list)
    capcut_draft_folder: Optional[str] = None

    @property
    def ready(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def blocking_messages(self) -> list[str]:
        return [f"{c.name}: {c.detail}\n  -> {c.install_hint}" for c in self.checks if not c.ok]


def detect_track() -> str:
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Darwin" and machine in ("arm64", "aarch64"):
        return "mac"
    if system == "Windows" and machine in ("amd64", "x86_64"):
        return "windows"
    return "fallback"


def _candidate_capcut_folders() -> list[Path]:
    home = Path.home()
    system = platform.system()
    candidates: list[Path] = []
    if system == "Darwin":
        candidates += [
            home / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
            home / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
        ]
    elif system == "Windows":
        appdata = Path(shutil.os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        localappdata = Path(shutil.os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        candidates += [
            localappdata / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
            appdata / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
            localappdata / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
        ]
    else:
        candidates += [
            home / ".capcut_agent" / "drafts",
        ]
    return candidates


def find_capcut_draft_folder() -> Optional[str]:
    for c in _candidate_capcut_folders():
        if c.exists() and c.is_dir():
            return str(c)
    return None


def check_ffmpeg() -> ToolCheck:
    ok = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
    system = platform.system()
    hint = {
        "Darwin": "brew install ffmpeg",
        "Windows": "winget install ffmpeg",
    }.get(system, "apt-get install -y ffmpeg (또는 배포판 패키지 매니저)")
    return ToolCheck(
        name="ffmpeg/ffprobe",
        ok=ok,
        detail="설치됨" if ok else "찾을 수 없음 (PATH 확인 필요)",
        install_hint="" if ok else hint,
    )


def check_python() -> ToolCheck:
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 9)
    system = platform.system()
    hint = {
        "Darwin": "brew install python@3.11",
        "Windows": "https://python.org 에서 Python 3.11 설치",
    }.get(system, "python3.11 이상 설치")
    return ToolCheck(
        name="python",
        ok=ok,
        detail=f"{platform.python_version()}",
        install_hint="" if ok else hint,
    )


def check_disk(target: Optional[Path] = None) -> ToolCheck:
    target = target or Path.home()
    try:
        free_gb = shutil.disk_usage(target).free / (1024 ** 3)
    except OSError:
        free_gb = 0.0
    ok = free_gb >= MIN_FREE_DISK_GB
    return ToolCheck(
        name="disk",
        ok=ok,
        detail=f"여유 공간 {free_gb:.1f}GB",
        install_hint="" if ok else f"최소 {MIN_FREE_DISK_GB}GB 여유 공간 필요 (ASR 모델 + 임시 파일)",
    )


def check_capcut_draft_folder() -> ToolCheck:
    folder = find_capcut_draft_folder()
    ok = folder is not None
    return ToolCheck(
        name="capcut_draft_folder",
        ok=ok,
        detail=folder or "찾을 수 없음",
        install_hint="" if ok else "CapCut을 설치하고 1회 이상 실행해 드래프트 폴더를 생성해주세요",
    )


def check_asr_backend(track: str) -> ToolCheck:
    if track == "mac":
        try:
            import mlx_whisper  # noqa: F401
            return ToolCheck("asr_backend(mlx-whisper)", True, "설치됨")
        except ImportError:
            return ToolCheck(
                "asr_backend(mlx-whisper)", False, "미설치",
                "pip install mlx-whisper",
            )
    try:
        import faster_whisper  # noqa: F401
        return ToolCheck("asr_backend(faster-whisper)", True, "설치됨")
    except ImportError:
        return ToolCheck(
            "asr_backend(faster-whisper)", False, "미설치",
            "pip install faster-whisper",
        )


def get_env_report() -> EnvReport:
    track = detect_track()
    report = EnvReport(
        os_name=platform.system(),
        machine=platform.machine(),
        track=track,
        python_version=platform.python_version(),
        capcut_draft_folder=find_capcut_draft_folder(),
    )
    report.checks = [
        check_python(),
        check_ffmpeg(),
        check_disk(),
        check_capcut_draft_folder(),
        check_asr_backend(track),
    ]
    return report


def print_report(report: EnvReport) -> None:
    track_label = {
        "mac": "트랙 A (Mac, mlx-whisper)",
        "windows": "트랙 C (Windows, faster-whisper + MP4 export 보너스)",
        "fallback": "fallback (faster-whisper)",
    }[report.track]

    print(f"[Step 0] OS={report.os_name} arch={report.machine} -> {track_label}")
    for c in report.checks:
        mark = "OK " if c.ok else "FAIL"
        print(f"  [{mark}] {c.name}: {c.detail}")
        if not c.ok and c.install_hint:
            print(f"        -> {c.install_hint}")

    if report.ready:
        print("\n환경 점검 통과. 다음 단계로 진행 가능합니다.")
    else:
        print("\n누락된 도구가 있습니다. 위 안내에 따라 설치 후 다시 실행해주세요.")


if __name__ == "__main__":
    print_report(get_env_report())
