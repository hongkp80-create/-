"""ffmpeg silencedetect 기반 무음 구간 탐지 -> "살릴 구간(keep ranges)" 산출.

함정: ffmpeg silencedetect는 stderr로 결과를 출력한다 (stdout 아님).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from .ranges import Range, complement, drop_short, normalize

_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")


@dataclass
class SilenceConfig:
    noise_db: float = -30.0
    min_silence_dur: float = 0.6      # 이보다 짧은 무음은 컷하지 않고 그대로 둠(자연스러운 호흡)
    pad: float = 0.15                 # 컷 경계에서 발화 쪽으로 남겨둘 여유(말 잘림 방지)
    min_keep_dur: float = 0.3         # 이보다 짧게 남는 "살릴 구간"은 버림(마이크로 슬리버)


def probe_duration(video_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def _run_silencedetect(video_path: str, cfg: SilenceConfig) -> str:
    cmd = [
        "ffmpeg", "-i", video_path,
        "-af", f"silencedetect=noise={cfg.noise_db}dB:d={cfg.min_silence_dur}",
        "-f", "null", "-",
    ]
    # silencedetect는 stderr에 출력하며, 정상 동작해도 ffmpeg는 exit code 0을 반환하지 않을 수 있어
    # returncode는 확인하지 않고 stderr 파싱 결과 유무로 성공을 판단한다.
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stderr


def detect_silence_ranges(video_path: str, cfg: SilenceConfig | None = None) -> list[Range]:
    """무음 구간 목록(초 단위)을 반환."""
    cfg = cfg or SilenceConfig()
    stderr = _run_silencedetect(video_path, cfg)

    starts = [float(m.group(1)) for m in _SILENCE_START_RE.finditer(stderr)]
    ends = [float(m.group(1)) for m in _SILENCE_END_RE.finditer(stderr)]

    duration = probe_duration(video_path)

    # silence_end가 silence_start보다 하나 적게 잡히는 경우: 영상이 무음으로 끝남
    if len(ends) < len(starts):
        ends.append(duration)

    ranges = [Range(s, e) for s, e in zip(starts, ends) if e > s]
    return normalize(ranges)


def compute_keep_ranges(video_path: str, cfg: SilenceConfig | None = None) -> tuple[list[Range], float]:
    """무음 제거 후 "살릴 구간" 목록과 원본 총 길이를 반환.

    각 keep 구간 경계에 cfg.pad만큼 무음 쪽에서 여유를 남겨 말이 잘리지 않게 한다.
    """
    cfg = cfg or SilenceConfig()
    duration = probe_duration(video_path)
    silences = detect_silence_ranges(video_path, cfg)

    padded_silences = [
        Range(min(s.start + cfg.pad, s.end), max(s.end - cfg.pad, s.start))
        for s in silences
    ]
    padded_silences = [r for r in padded_silences if r.duration > 0]

    keep = complement(padded_silences, duration)
    keep = drop_short(keep, cfg.min_keep_dur)
    return keep, duration
