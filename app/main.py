"""캡컷 에이전트 - FastAPI 백엔드.

라우트 구성:
  GET  /                        정적 페이지
  GET  /api/env                 Step0 환경 점검 결과
  GET  /api/settings            현재 설정(드래프트 폴더 등)
  POST /api/settings            설정 변경
  POST /api/upload              영상 업로드 (drag/drop)
  GET  /api/video/{video_id}    영상 스트리밍 (Range 지원, 미리보기용)
  GET  /api/process/{video_id}/stream   SSE: silence -> asr -> filler -> draft+자막
  POST /api/mark                 사용자 보존 구간 반영 후 드래프트 재생성
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import get_env_report
from .pipeline.cache import content_hash
from .pipeline.cuts import merge_cuts
from .pipeline.draft import build_draft
from .pipeline.filler_ng import detect_filler_ng
from .pipeline.korean_chunk import Word as ChunkWord
from .pipeline.korean_chunk import chunk_words
from .pipeline.ranges import Range
from .pipeline.silence import SilenceConfig, compute_keep_ranges
from .pipeline.transcribe import Transcript, transcribe_full
from .workdir import ASR_CACHE_DIR, PIPELINE_CACHE_DIR, UPLOAD_DIR, load_settings, save_settings

app = FastAPI(title="캡컷 에이전트")

STATIC_DIR = Path(__file__).parent / "static"

STAGE_MIN_DELAY = 0.5  # 캐시 hit이어도 최소한의 지연을 둬서 스텝퍼 애니메이션이 보이게 함

# 영상 단위 파이프라인 중간 결과(같은 프로세스가 살아있는 동안만 유지되는 로컬 툴이므로 메모리 보관으로 충분)
_PIPELINE_STATE: dict[str, dict] = {}


class SettingsIn(BaseModel):
    draft_folder: Optional[str] = None
    model_size: Optional[str] = None
    language: Optional[str] = None


class MarkIn(BaseModel):
    video_id: str
    draft_name: str
    preserve_ranges: list[list[float]] = []


def _video_path_for(video_id: str) -> Path:
    matches = list(UPLOAD_DIR.glob(f"{video_id}.*"))
    if not matches:
        raise HTTPException(404, f"video_id '{video_id}'를 찾을 수 없습니다")
    return matches[0]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/env")
def api_env():
    report = get_env_report()
    return {
        "os_name": report.os_name,
        "machine": report.machine,
        "track": report.track,
        "python_version": report.python_version,
        "ready": report.ready,
        "capcut_draft_folder": report.capcut_draft_folder,
        "checks": [
            {"name": c.name, "ok": c.ok, "detail": c.detail, "install_hint": c.install_hint}
            for c in report.checks
        ],
    }


@app.get("/api/settings")
def api_get_settings():
    return load_settings()


@app.post("/api/settings")
def api_post_settings(body: SettingsIn):
    settings = load_settings()
    for k, v in body.model_dump(exclude_none=True).items():
        settings[k] = v
    save_settings(settings)
    return settings


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "video.mp4").suffix.lower()
    if suffix not in (".mp4", ".mov"):
        raise HTTPException(400, "mp4/mov 파일만 지원합니다")

    tmp_path = UPLOAD_DIR / f"_tmp_{file.filename}"
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    video_id = content_hash(tmp_path)
    final_path = UPLOAD_DIR / f"{video_id}{suffix}"
    if final_path.exists():
        tmp_path.unlink()
    else:
        tmp_path.rename(final_path)

    return {"video_id": video_id, "filename": file.filename}


_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


@app.get("/api/video/{video_id}")
def api_video(video_id: str, request: Request):
    path = _video_path_for(video_id)
    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    media_type = "video/mp4" if path.suffix == ".mp4" else "video/quicktime"

    if not range_header:
        return FileResponse(path, media_type=media_type)

    m = _RANGE_RE.match(range_header)
    if not m:
        raise HTTPException(416, "Invalid Range header")
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1
    end = min(end, file_size - 1)
    chunk_size = end - start + 1

    def iterfile():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                data = f.read(min(1024 * 1024, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
    }
    return StreamingResponse(iterfile(), status_code=206, media_type=media_type, headers=headers)


def _build_captions(transcript: Transcript, keep_ranges: list[Range]) -> list:
    captions = []
    for kr in keep_ranges:
        words_in_range = [
            ChunkWord(w.start, w.end, w.text)
            for w in transcript.words
            if w.start >= kr.start - 0.05 and w.end <= kr.end + 0.05
        ]
        captions.extend(chunk_words(words_in_range))
    return captions


def _decisions_json(decisions) -> list[dict]:
    return [
        {
            "kind": d.kind,
            "start": d.range.start,
            "end": d.range.end,
            "note": d.note,
            "segment_ids": d.segment_ids,
        }
        for d in decisions
    ]


async def _run_pipeline(video_id: str, draft_name: str, draft_folder: str, model_size: str, language: str):
    video_path = str(_video_path_for(video_id))

    # --- stage: silence ---
    yield _sse("stage", {"stage": "silence", "status": "start", "message": "무음 구간 분석 중..."})
    t0 = asyncio.get_event_loop().time()
    keep_ranges, duration = await asyncio.to_thread(compute_keep_ranges, video_path, SilenceConfig())
    await _min_delay(t0)
    yield _sse("stage", {
        "stage": "silence", "status": "done",
        "message": f"무음 {len(keep_ranges)}개 유지 구간 확보 (원본 {duration:.1f}s)",
        "data": {"duration": duration, "keep_ranges": [[r.start, r.end] for r in keep_ranges]},
    })

    # --- stage: asr ---
    yield _sse("stage", {"stage": "asr", "status": "start", "message": "전체 대본 추출 중 (Whisper)..."})
    t0 = asyncio.get_event_loop().time()
    transcript = await transcribe_full(video_path, str(ASR_CACHE_DIR), model_size=model_size, language=language)
    await _min_delay(t0)
    yield _sse("stage", {
        "stage": "asr", "status": "done",
        "message": f"대본 {len(transcript.segments)}문장 추출 완료",
        "data": {"segments": [s.__dict__ for s in transcript.segments]},
    })

    # --- stage: filler ---
    yield _sse("stage", {"stage": "filler", "status": "start", "message": "잔말/NG 판단 중 (전체 대본 기반)..."})
    t0 = asyncio.get_event_loop().time()
    decisions = await asyncio.to_thread(detect_filler_ng, transcript)
    merged = merge_cuts(keep_ranges, decisions)
    await _min_delay(t0)
    yield _sse("stage", {
        "stage": "filler", "status": "done",
        "message": f"필러/NG {len(decisions)}건 감지, 최종 유지 구간 {len(merged.keep_ranges)}개",
        "data": {"decisions": _decisions_json(decisions), "keep_ranges": [[r.start, r.end] for r in merged.keep_ranges]},
    })

    # --- stage: draft ---
    yield _sse("stage", {"stage": "draft", "status": "start", "message": "캡컷 드래프트 생성 중..."})
    t0 = asyncio.get_event_loop().time()
    captions = await asyncio.to_thread(_build_captions, transcript, merged.keep_ranges)
    result = await asyncio.to_thread(
        build_draft, video_path, merged.keep_ranges, draft_folder, draft_name, captions,
    )
    await _min_delay(t0)

    _PIPELINE_STATE[video_id] = {
        "duration": duration,
        "silence_keep_ranges": keep_ranges,
        "transcript": transcript,
        "decisions": decisions,
        "draft_name": draft_name,
        "draft_folder": draft_folder,
    }

    yield _sse("stage", {
        "stage": "draft", "status": "done",
        "message": f"드래프트 생성 완료: {result.segment_count}개 클립, 자막 {result.caption_count}개",
        "data": {
            "draft_path": result.draft_path,
            "new_total_duration": result.new_total_duration,
            "segment_count": result.segment_count,
            "caption_count": result.caption_count,
        },
    })
    yield _sse("complete", {
        "video_id": video_id,
        "draft_path": result.draft_path,
        "transcript": {"segments": [s.__dict__ for s in transcript.segments], "full_text": transcript.full_text},
        "decisions": _decisions_json(decisions),
        "keep_ranges": [[r.start, r.end] for r in merged.keep_ranges],
        "note": "빌드 성공 ≠ 검증입니다. 캡컷 앱에서 이 드래프트를 직접 열어 재생해 확인해주세요.",
    })


async def _min_delay(t0: float) -> None:
    elapsed = asyncio.get_event_loop().time() - t0
    if elapsed < STAGE_MIN_DELAY:
        await asyncio.sleep(STAGE_MIN_DELAY - elapsed)


@app.get("/api/process/{video_id}/stream")
async def api_process_stream(
    video_id: str,
    draft_name: str = "capcut_agent_draft",
    model_size: str = "small",
    language: str = "ko",
):
    settings = load_settings()
    draft_folder = settings.get("draft_folder")
    if not draft_folder or not Path(draft_folder).exists():
        raise HTTPException(400, "CapCut 드래프트 폴더가 설정되지 않았습니다. /api/settings로 먼저 설정해주세요.")

    async def gen():
        try:
            async for chunk in _run_pipeline(video_id, draft_name, draft_folder, model_size, language):
                yield chunk
        except Exception as e:  # noqa: BLE001
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/mark")
async def api_mark(body: MarkIn):
    state = _PIPELINE_STATE.get(body.video_id)
    if not state:
        raise HTTPException(400, "먼저 /api/process 스트림을 완료해야 합니다")

    video_path = str(_video_path_for(body.video_id))
    preserve_ranges = [Range(s, e) for s, e in body.preserve_ranges if e > s]

    merged = merge_cuts(state["silence_keep_ranges"], state["decisions"], preserve_ranges)
    transcript: Transcript = state["transcript"]
    captions = await asyncio.to_thread(_build_captions, transcript, merged.keep_ranges)

    result = await asyncio.to_thread(
        build_draft, video_path, merged.keep_ranges, state["draft_folder"], body.draft_name, captions,
    )

    return {
        "draft_path": result.draft_path,
        "new_total_duration": result.new_total_duration,
        "segment_count": result.segment_count,
        "caption_count": result.caption_count,
        "keep_ranges": [[r.start, r.end] for r in merged.keep_ranges],
    }


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
