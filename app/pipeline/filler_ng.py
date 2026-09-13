"""잔말(filler)/NG(재촬영) 컷 판단.

★ 핵심 원칙: 반드시 전체 대본(문장/세그먼트 단위)을 먼저 보고 판단한다.
   단어 하나하나를 필러 사전과 대조해서 그 단어만 지우는 방식이 아니다 - 그렇게 하면
   "저기 산에 가면"의 "저"처럼 실제 의미가 있는 단어를 필러로 오인해 잘라내는 사고가 난다.
   대신 "이 문장/구간을 통째로 버릴지"를 문맥(앞뒤 문장, 재촬영 신호어, 중복 여부)으로 결정한다.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .ranges import Range
from .transcribe import SegmentTs, Transcript

FILLER_TOKENS = [
    "음", "어", "그", "저", "이제", "약간", "인제", "자", "막", "뭐랄까", "그니까",
    "어어", "음음", "그그", "저저", "네네",
]

RETAKE_TRIGGER_PATTERNS = [
    r"다시\s*(할게요|갈게요|찍을게요|갈까요|해볼게요)",
    r"(죄송|미안).{0,4}다시",
    r"\bcut\b",
    r"컷\s*(할게요|해주세요|주세요)?",
    r"엔지\b|NG\b",
    r"잠깐만요.{0,6}다시",
]

DUPLICATE_SIMILARITY_THRESHOLD = 0.72
DUPLICATE_LOOKAHEAD = 3


@dataclass
class CutDecision:
    range: Range
    kind: str  # "filler" | "ng_retake" | "ng_duplicate"
    note: str
    segment_ids: list[int]


def _normalize(text: str) -> str:
    text = re.sub(r"[^\w가-힣]", "", text)
    return text.strip()


def _strip_fillers(text: str) -> str:
    result = text
    for tok in FILLER_TOKENS:
        result = re.sub(rf"(?<![가-힣]){re.escape(tok)}(?![가-힣])", "", result)
    return re.sub(r"\s+", " ", result).strip()


def _is_retake_trigger(text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in RETAKE_TRIGGER_PATTERNS)


def detect_filler_only_segments(segments: list[SegmentTs]) -> list[CutDecision]:
    """세그먼트 전체가 필러로만 구성된 경우(실질적 내용이 거의 없음) 통째로 컷."""
    decisions = []
    for seg in segments:
        stripped = _strip_fillers(seg.text)
        if len(stripped) <= 1 and len(seg.text.strip()) > 0:
            decisions.append(CutDecision(
                range=Range(seg.start, seg.end),
                kind="filler",
                note=f"필러만 존재: \"{seg.text.strip()}\"",
                segment_ids=[seg.id],
            ))
    return decisions


def detect_retake_segments(segments: list[SegmentTs], lookback_prev: bool = True) -> list[CutDecision]:
    """"다시 할게요" 같은 재촬영 신호 문장을 찾아 그 문장(+직전 문장)을 NG로 컷."""
    decisions = []
    for i, seg in enumerate(segments):
        if not _is_retake_trigger(seg.text):
            continue
        ids = [seg.id]
        start = seg.start
        if lookback_prev and i > 0:
            prev = segments[i - 1]
            ids.append(prev.id)
            start = prev.start
        decisions.append(CutDecision(
            range=Range(start, seg.end),
            kind="ng_retake",
            note=f"재촬영 신호어 감지: \"{seg.text.strip()}\"",
            segment_ids=ids,
        ))
    return decisions


def detect_duplicate_segments(segments: list[SegmentTs]) -> list[CutDecision]:
    """비슷한 문장이 반복되면(재도전) 마지막 것만 남기고 앞의 것들을 컷."""
    decisions = []
    n = len(segments)
    for i in range(n):
        norm_i = _normalize(segments[i].text)
        if len(norm_i) < 4:
            continue
        for j in range(i + 1, min(i + 1 + DUPLICATE_LOOKAHEAD, n)):
            norm_j = _normalize(segments[j].text)
            if len(norm_j) < 4:
                continue
            ratio = difflib.SequenceMatcher(None, norm_i, norm_j).ratio()
            if ratio >= DUPLICATE_SIMILARITY_THRESHOLD:
                decisions.append(CutDecision(
                    range=Range(segments[i].start, segments[i].end),
                    kind="ng_duplicate",
                    note=f"중복 문장(마지막 발화 유지): \"{segments[i].text.strip()}\"",
                    segment_ids=[segments[i].id],
                ))
                break  # i는 한 번만 컷 판정하면 충분
    return decisions


def detect_filler_ng(transcript: Transcript, lookback_prev: bool = True) -> list[CutDecision]:
    decisions: list[CutDecision] = []
    decisions += detect_retake_segments(transcript.segments, lookback_prev=lookback_prev)
    decisions += detect_duplicate_segments(transcript.segments)
    decisions += detect_filler_only_segments(transcript.segments)
    return decisions
