import pycapcut as cc

from app.pipeline.draft import CaptionChunk, build_draft
from app.pipeline.ranges import Range
from app.pipeline.silence import SilenceConfig, compute_keep_ranges


def test_silence_detects_speech_bursts(tiny_clip):
    keep, duration = compute_keep_ranges(
        tiny_clip, SilenceConfig(noise_db=-30, min_silence_dur=0.5, pad=0.1, min_keep_dur=0.2),
    )
    assert duration == 8.0
    assert len(keep) == 2
    # 첫 톤은 2~3초, 둘째 톤은 5~6초 부근이어야 함(패딩 포함 약간의 오차 허용)
    assert 1.8 <= keep[0].start <= 2.1
    assert 2.9 <= keep[0].end <= 3.2
    assert 4.8 <= keep[1].start <= 5.1
    assert 5.9 <= keep[1].end <= 6.2


def test_build_draft_roundtrips_through_pycapcut(tmp_path, tiny_clip):
    keep = [Range(2.0, 3.0), Range(5.0, 6.0)]
    captions = [CaptionChunk("테스트 자막", 2.0, 3.0)]

    result = build_draft(tiny_clip, keep, str(tmp_path), "unit_test_draft", captions=captions)

    assert result.segment_count == 2
    assert result.caption_count == 1
    assert abs(result.new_total_duration - 2.0) < 1e-6

    # draft_content.json이 pycapcut 자체 로더로 예외 없이 파싱되는지 확인 (구조적 유효성)
    loaded = cc.ScriptFile.load_template(f"{result.draft_path}/draft_content.json")
    assert loaded.width > 0 and loaded.height > 0

    # 방어적 호환 파일도 함께 생성됐는지 확인 (일부 CapCut 버전 draft_info.json 요구 이슈 대응)
    import os
    assert os.path.exists(f"{result.draft_path}/draft_info.json")

    # 첫 세그먼트가 반드시 0에서 시작해야 한다 (메인 트랙 규칙)
    import json
    data = json.loads(open(f"{result.draft_path}/draft_content.json").read())
    video_track = next(t for t in data["tracks"] if t["type"] == "video")
    assert video_track["segments"][0]["target_timerange"]["start"] == 0
