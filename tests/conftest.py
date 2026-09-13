import shutil
import subprocess

import pytest


@pytest.fixture(scope="session")
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture(scope="session")
def tiny_clip(tmp_path_factory, ffmpeg_available):
    """무음 2s - 톤 1s - 무음 2s - 톤 1s - 무음 2s (총 8s) 짜리 합성 테스트 클립."""
    if not ffmpeg_available:
        pytest.skip("ffmpeg가 설치되어 있지 않습니다")

    d = tmp_path_factory.mktemp("clip")
    parts = [
        ("anullsrc=r=44100:cl=mono:d=2", d / "s1.wav"),
        ("sine=frequency=440:sample_rate=44100:duration=1", d / "s2.wav"),
        ("anullsrc=r=44100:cl=mono:d=2", d / "s3.wav"),
        ("sine=frequency=660:sample_rate=44100:duration=1", d / "s4.wav"),
        ("anullsrc=r=44100:cl=mono:d=2", d / "s5.wav"),
    ]
    for src, out in parts:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", src, str(out)],
            capture_output=True, check=True,
        )
    listfile = d / "list.txt"
    listfile.write_text("".join(f"file '{p.name}'\n" for _, p in parts))
    audio = d / "audio.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(audio)],
        capture_output=True, check=True, cwd=d,
    )
    video = d / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=8:r=30",
         "-i", str(audio), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(video)],
        capture_output=True, check=True,
    )
    return str(video)
