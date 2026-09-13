"""무음 컷 + 잔말/NG 컷을 하나의 최종 "살릴 구간" 목록으로 합친다."""
from __future__ import annotations

from dataclasses import dataclass

from .filler_ng import CutDecision
from .ranges import Range, drop_short, normalize, subtract, union


@dataclass
class MergedCutResult:
    keep_ranges: list[Range]
    ng_filler_ranges: list[Range]
    decisions: list[CutDecision]


def merge_cuts(
    silence_keep_ranges: list[Range],
    filler_ng_decisions: list[CutDecision],
    user_preserve_ranges: list[Range] | None = None,
    min_keep_dur: float = 0.3,
) -> MergedCutResult:
    """최종 keep = (무음 제외 구간) - (필러/NG 구간) + (사용자가 [ / ]로 강제 보존한 구간).

    사용자 보존 구간은 자동 판단(필러/NG)보다 우선한다 - Stage5에서 사람이 직접 마킹한 결과를
    자동 컷이 덮어쓰지 않도록 하기 위함.
    """
    user_preserve_ranges = user_preserve_ranges or []
    ng_filler_ranges = normalize([d.range for d in filler_ng_decisions])

    # 사용자가 보존하기로 한 구간은 필러/NG 컷 대상에서 제외
    effective_cuts = subtract(ng_filler_ranges, user_preserve_ranges)

    keep = subtract(silence_keep_ranges, effective_cuts)
    keep = union(keep, [r for r in user_preserve_ranges if r.duration > 0])
    keep = drop_short(keep, min_keep_dur)

    return MergedCutResult(keep_ranges=keep, ng_filler_ranges=ng_filler_ranges, decisions=filler_ng_decisions)
