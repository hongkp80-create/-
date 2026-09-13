"""전체 대본(script) 추출 - ASR.

핵심 원칙: 여기서 나온 segments(문장 단위 전체 대본)가 NG/필러 판단의 입력이 된다.
단어 단위(words)는 자막 표시용으로만 쓰고, 잘라낼지 말지의 "판단"에는 쓰지 않는다.

함정 (ASR Lock): mlx-whisper/faster-whisper 내부(numba, mlx 커널)는 스레드 세이프하지 않다고
보고되어 있어, 여러 요청이 동시에 모델을 호출하면 세그폴트가 날 수 있다. asyncio.Lock으로
전역 직렬화한다 - 이벤트 루프를 막지 않도록 실제 추론은 asyncio.to_thread로 스레드에 위임하되,
그 앞뒤를 Lock으로 감싸 "동시에 두 추론이 진행되는 상황"만 막는다.

함정 (캐시 키): mtime이 아니라 파일 컨텐츠 해시를 키로 쓴다 (cache.py 참고). 그래야 같은 영상을
다시 업로드하거나 Stage5에서 사용자가 보존 구간만 조정해 재실행할 때 ASR을 다시 돌리지 않는다.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field

from ..config import detect_track
from .cache import JsonCache, content_hash

ASR_LOCK = asyncio.Lock()

_MODEL_CACHE: dict[str, object] = {}


@dataclass
class WordTs:
    start: float
    end: float
    text: str
    segment_id: int


@dataclass
class SegmentTs:
    id: int
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    segments: list[SegmentTs] = field(default_factory=list)
    words: list[WordTs] = field(default_factory=list)
    language: str = "ko"
    full_text: str = ""

    def to_json(self) -> dict:
        return {
            "segments": [asdict(s) for s in self.segments],
            "words": [asdict(w) for w in self.words],
            "language": self.language,
            "full_text": self.full_text,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Transcript":
        return cls(
            segments=[SegmentTs(**s) for s in data["segments"]],
            words=[WordTs(**w) for w in data["words"]],
            language=data.get("language", "ko"),
            full_text=data.get("full_text", ""),
        )


def _get_faster_whisper_model(model_size: str):
    key = f"fw:{model_size}"
    if key not in _MODEL_CACHE:
        from faster_whisper import WhisperModel
        _MODEL_CACHE[key] = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _MODEL_CACHE[key]


def _transcribe_faster_whisper(video_path: str, model_size: str, language: str) -> Transcript:
    model = _get_faster_whisper_model(model_size)
    segments_iter, _info = model.transcribe(
        video_path, language=language, word_timestamps=True, vad_filter=True,
    )

    transcript = Transcript(language=language)
    full_text_parts = []
    for seg_id, seg in enumerate(segments_iter):
        text = seg.text.strip()
        transcript.segments.append(SegmentTs(id=seg_id, start=seg.start, end=seg.end, text=text))
        full_text_parts.append(text)
        for w in (seg.words or []):
            wtext = w.word.strip()
            if not wtext:
                continue
            transcript.words.append(WordTs(start=w.start, end=w.end, text=wtext, segment_id=seg_id))
    transcript.full_text = " ".join(full_text_parts)
    return transcript


def _transcribe_mlx_whisper(video_path: str, model_size: str, language: str) -> Transcript:
    import mlx_whisper

    repo_map = {
        "tiny": "mlx-community/whisper-tiny-mlx",
        "base": "mlx-community/whisper-base-mlx",
        "small": "mlx-community/whisper-small-mlx",
        "medium": "mlx-community/whisper-medium-mlx",
        "large-v3": "mlx-community/whisper-large-v3-mlx",
    }
    repo = repo_map.get(model_size, repo_map["small"])
    result = mlx_whisper.transcribe(
        video_path, path_or_hf_repo=repo, language=language, word_timestamps=True,
    )

    transcript = Transcript(language=language)
    full_text_parts = []
    for seg_id, seg in enumerate(result.get("segments", [])):
        text = seg["text"].strip()
        transcript.segments.append(SegmentTs(id=seg_id, start=seg["start"], end=seg["end"], text=text))
        full_text_parts.append(text)
        for w in seg.get("words", []) or []:
            wtext = w["word"].strip()
            if not wtext:
                continue
            transcript.words.append(WordTs(start=w["start"], end=w["end"], text=wtext, segment_id=seg_id))
    transcript.full_text = " ".join(full_text_parts)
    return transcript


def _transcribe_sync(video_path: str, model_size: str, language: str) -> Transcript:
    track = detect_track()
    if track == "mac":
        try:
            return _transcribe_mlx_whisper(video_path, model_size, language)
        except ImportError:
            pass  # mlx-whisper 미설치 시 faster-whisper로 폴백
    return _transcribe_faster_whisper(video_path, model_size, language)


async def transcribe_full(
    video_path: str,
    cache_dir: str,
    model_size: str = "small",
    language: str = "ko",
) -> Transcript:
    """전체 대본을 추출한다. 동일 영상(내용 기준) 재요청 시 캐시를 사용한다."""
    cache = JsonCache(cache_dir)
    key = f"{content_hash(video_path)}-{model_size}-{language}"

    cached = cache.get(key)
    if cached is not None:
        return Transcript.from_json(cached)

    async with ASR_LOCK:
        # Lock을 잡은 뒤 다시 확인: 대기 중 다른 요청이 이미 캐시를 채웠을 수 있음
        cached = cache.get(key)
        if cached is not None:
            return Transcript.from_json(cached)
        transcript = await asyncio.to_thread(_transcribe_sync, video_path, model_size, language)

    cache.set(key, transcript.to_json())
    return transcript
