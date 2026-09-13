"""pycapcut를 이용한 캡컷 드래프트 생성.

함정 메모 (draft_content.json 실제 소스 확인 결과):
  - `Timerange(start, duration)`의 두 번째 인자는 **끝 시각이 아니라 길이**다.
    (pycapcut/time_util.py: trange()의 duration 인자 docstring "주의 **끝 시각이 아님**")
    끝 시각을 넣으면 클립이 실제 길이보다 훨씬 길게(혹은 짧게) 생성되는 게 가장 흔한 실수.
  - 메인(가장 아래) 비디오 트랙의 첫 세그먼트는 반드시 0s에서 시작해야 한다.
    (pycapcut/script_file.py add_track() 주석) 그렇지 않으면 CapCut이 강제로 0s로 당겨버려
    이후 모든 세그먼트의 상대 위치가 틀어진다. -> 점프컷 조립 시 첫 keep 구간을 항상 0에서 시작.
  - `ClipSettings.transform_y`는 픽셀도, 0~1 비율도 아니라 **캔버스 높이의 절반을 1로 하는 단위**다.
    자막을 화면 하단에 붙이려면 대략 -0.8 근처(자막 기본 위치), +값은 위로 올라간다.
  - CapCut 배포판/버전에 따라 드래프트 진입점 파일명이 `draft_content.json`이 아니라
    `draft_info.json`을 기대하는 경우가 보고되어 있다. pycapcut는 `draft_content.json`만 쓰므로,
    save() 이후 방어적으로 `draft_info.json`을 동일 내용으로 함께 만들어 둔다.
    (그래도 캡컷에서 드래프트가 안 보이면 이 부분부터 의심할 것 — 반드시 실제 캡컷에서 열어 확인)
  - ASR(mlx-whisper / faster-whisper 내부 numba)은 스레드 세이프하지 않다고 보고되어 있어
    동시 호출 시 세그폴트가 날 수 있다. 이 프로젝트에서는 asyncio.Lock으로 직렬화한다
    (app/pipeline/transcribe.py의 ASR_LOCK 참고, 여기 draft.py는 순수 동기 함수라 직접 관련 없음).
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pycapcut as cc

from .ranges import Range, TimelineMap, normalize

DEFAULT_TRACK_NAME_VIDEO = "video"
DEFAULT_TRACK_NAME_CAPTION = "captions"


@dataclass
class CaptionChunk:
    text: str
    start: float  # 원본 영상 기준 초
    end: float


@dataclass
class DraftBuildResult:
    draft_path: str
    new_total_duration: float
    segment_count: int
    caption_count: int
    timeline_map: TimelineMap = field(repr=False)


def _probe_dimensions(video_path: str) -> tuple[int, int, int]:
    material = cc.VideoMaterial(video_path)
    fps = 30
    return material.width, material.height, fps


def build_draft(
    video_path: str,
    keep_ranges: list[Range],
    draft_folder: str,
    draft_name: str,
    captions: list[CaptionChunk] | None = None,
    *,
    allow_replace: bool = True,
    caption_style: "cc.TextStyle | None" = None,
    caption_transform_y: float = -0.8,
) -> DraftBuildResult:
    """keep_ranges(원본 기준, 초 단위, 살릴 구간)만 남긴 점프컷 드래프트를 생성한다.

    captions가 주어지면 원본 시각 기준 자막을 새 타임라인으로 재매핑하여 자막 트랙에 추가한다.
    (컷된 구간에 걸친 자막은 살아남는 부분만 남기고 clip 됨)
    """
    keep_ranges = normalize(keep_ranges)
    if not keep_ranges:
        raise ValueError("keep_ranges가 비어 있습니다 (전부 무음/컷 처리됨)")

    width, height, fps = _probe_dimensions(video_path)
    material = cc.VideoMaterial(video_path)

    folder = cc.DraftFolder(draft_folder)
    script = folder.create_draft(draft_name, width, height, fps, allow_replace=allow_replace)
    script.add_material(material)
    script.add_track(cc.TrackType.video, DEFAULT_TRACK_NAME_VIDEO)
    if captions:
        script.add_track(cc.TrackType.text, DEFAULT_TRACK_NAME_CAPTION)

    timeline_map = TimelineMap(keep_ranges)

    cumulative_us = 0
    segment_count = 0
    for r in keep_ranges:
        src_start_us = cc.tim(f"{r.start}s")
        dur_us = cc.tim(f"{r.duration}s")
        target = cc.Timerange(cumulative_us, dur_us)
        source = cc.Timerange(src_start_us, dur_us)
        seg = cc.VideoSegment(material, target, source_timerange=source)
        script.add_segment(seg, track_name=DEFAULT_TRACK_NAME_VIDEO)
        cumulative_us += dur_us
        segment_count += 1

    caption_count = 0
    style = caption_style or cc.TextStyle(size=8.0, align=1, color=(1.0, 1.0, 1.0))
    border = cc.TextBorder(color=(0.0, 0.0, 0.0), width=40.0, alpha=1.0)
    if captions:
        for chunk in captions:
            new_ranges = timeline_map.clip_range_to_new(Range(chunk.start, chunk.end))
            for nr in new_ranges:
                if nr.duration <= 0:
                    continue
                trange = cc.Timerange(cc.tim(f"{nr.start}s"), cc.tim(f"{nr.duration}s"))
                text_seg = cc.TextSegment(
                    chunk.text,
                    trange,
                    style=style,
                    border=border,
                    clip_settings=cc.ClipSettings(transform_y=caption_transform_y),
                )
                script.add_segment(text_seg, track_name=DEFAULT_TRACK_NAME_CAPTION)
                caption_count += 1

    script.save()

    # 방어적 호환 처리: 일부 CapCut 버전은 draft_info.json을 진입점으로 기대한다는 보고가 있어
    # draft_content.json과 동일한 내용을 draft_info.json으로도 저장해 둔다.
    draft_dir = Path(draft_folder) / draft_name
    content_path = draft_dir / "draft_content.json"
    info_path = draft_dir / "draft_info.json"
    if content_path.exists():
        shutil.copyfile(content_path, info_path)

    return DraftBuildResult(
        draft_path=str(draft_dir),
        new_total_duration=cumulative_us / cc.SEC,
        segment_count=segment_count,
        caption_count=caption_count,
        timeline_map=timeline_map,
    )
