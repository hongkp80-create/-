from app.pipeline.filler_ng import (
    detect_duplicate_segments,
    detect_filler_only_segments,
    detect_retake_segments,
)
from app.pipeline.transcribe import SegmentTs


def test_retake_trigger_cuts_self_and_previous():
    segments = [
        SegmentTs(0, 0.0, 1.0, "안녕하세요 반갑습니다"),
        SegmentTs(1, 1.1, 1.8, "음 다시 할게요"),
        SegmentTs(2, 2.0, 3.0, "안녕하세요 반갑습니다"),
    ]
    decisions = detect_retake_segments(segments)
    assert len(decisions) == 1
    d = decisions[0]
    assert d.kind == "ng_retake"
    assert d.range.start == 0.0  # 직전 문장까지 포함해서 컷
    assert d.range.end == 1.8


def test_duplicate_segment_keeps_last_occurrence():
    segments = [
        SegmentTs(0, 0.0, 1.0, "오늘은 날씨가 정말 좋습니다"),
        SegmentTs(1, 2.0, 3.0, "오늘은 날씨가 정말 좋네요"),
    ]
    decisions = detect_duplicate_segments(segments)
    assert len(decisions) == 1
    assert decisions[0].kind == "ng_duplicate"
    assert decisions[0].range.start == 0.0  # 앞선(첫) 발화만 컷, 뒤는 유지


def test_filler_only_segment_detected():
    segments = [SegmentTs(0, 0.0, 0.5, "음 어")]
    decisions = detect_filler_only_segments(segments)
    assert len(decisions) == 1
    assert decisions[0].kind == "filler"


def test_meaningful_segment_not_flagged_as_filler():
    segments = [SegmentTs(0, 0.0, 1.0, "저기 산에 가면 정말 좋은 풍경이 있어요")]
    decisions = detect_filler_only_segments(segments)
    assert decisions == []
