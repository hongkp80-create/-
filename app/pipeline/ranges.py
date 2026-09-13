"""초 단위 구간(Range) 연산 유틸리티.

전체 파이프라인에서 시간은 이 모듈 밖으로 나가기 전까지 항상 "초(float)" 기준이다.
pycapcut의 마이크로초(Timerange.duration, **끝 시각이 아님**) 변환은 draft.py에서만 수행한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Range:
    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"end({self.end}) < start({self.start})")

    @property
    def duration(self) -> float:
        return self.end - self.start

    def overlaps(self, other: "Range") -> bool:
        return self.start < other.end and other.start < self.end


def normalize(ranges: Iterable[Range]) -> list[Range]:
    """겹치거나 붙어있는 구간을 병합하고 시작 시각 순으로 정렬."""
    items = sorted([r for r in ranges if r.end > r.start], key=lambda r: r.start)
    if not items:
        return []
    merged = [items[0]]
    for r in items[1:]:
        last = merged[-1]
        if r.start <= last.end:
            merged[-1] = Range(last.start, max(last.end, r.end))
        else:
            merged.append(r)
    return merged


def complement(ranges: Iterable[Range], total_duration: float) -> list[Range]:
    """[0, total_duration] 구간에서 주어진 구간들을 제외한 나머지."""
    merged = normalize(ranges)
    result: list[Range] = []
    cursor = 0.0
    for r in merged:
        if r.start > cursor:
            result.append(Range(cursor, r.start))
        cursor = max(cursor, r.end)
    if cursor < total_duration:
        result.append(Range(cursor, total_duration))
    return result


def subtract(base: Iterable[Range], cuts: Iterable[Range]) -> list[Range]:
    """base 구간들에서 cuts 구간들을 제외."""
    base_n = normalize(base)
    cuts_n = normalize(cuts)
    result: list[Range] = []
    for b in base_n:
        cursor = b.start
        for c in cuts_n:
            if not c.overlaps(b):
                continue
            seg_start = max(cursor, b.start)
            if c.start > cursor:
                result.append(Range(cursor, min(c.start, b.end)))
            cursor = max(cursor, c.end)
            if cursor >= b.end:
                break
        if cursor < b.end:
            result.append(Range(cursor, b.end))
    return normalize(result)


def union(a: Iterable[Range], b: Iterable[Range]) -> list[Range]:
    return normalize(list(a) + list(b))


def drop_short(ranges: Iterable[Range], min_duration: float) -> list[Range]:
    return [r for r in ranges if r.duration >= min_duration]


class TimelineMap:
    """원본 영상 시각 <-> 점프컷 후 새 타임라인 시각 매핑.

    keep_ranges는 원본 기준 "살릴 구간" 목록(정렬/병합됨)이어야 한다.
    """

    def __init__(self, keep_ranges: list[Range]):
        self.keep_ranges = normalize(keep_ranges)
        self._new_starts: list[float] = []
        cursor = 0.0
        for r in self.keep_ranges:
            self._new_starts.append(cursor)
            cursor += r.duration
        self.total_new_duration = cursor

    def to_new(self, t: float) -> float | None:
        """원본 시각 t를 새 타임라인 시각으로 변환. 컷된 구간에 속하면 None."""
        for r, new_start in zip(self.keep_ranges, self._new_starts):
            if r.start <= t <= r.end:
                return new_start + (t - r.start)
        return None

    def clip_range_to_new(self, r: Range) -> list[Range]:
        """원본 구간 r을, 컷된 부분은 버리고 새 타임라인 상의 구간(들)로 변환.

        하나의 원본 구간이 여러 keep 구간에 걸쳐 있을 수 있으므로 리스트를 반환.
        """
        out: list[Range] = []
        for kr, new_start in zip(self.keep_ranges, self._new_starts):
            inter_start = max(r.start, kr.start)
            inter_end = min(r.end, kr.end)
            if inter_end > inter_start:
                out.append(Range(new_start + (inter_start - kr.start), new_start + (inter_end - kr.start)))
        return out
