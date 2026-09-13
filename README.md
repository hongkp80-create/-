# 캡컷 에이전트

한국어 토킹 영상을 업로드하면 무음·잔말·NG 컷을 자동으로 판단하고, 단어별(어절 단위) 자막이
붙은 캡컷(CapCut) 드래프트를 만들어주는 로컬 웹 도구입니다.

```
입력: mp4 / mov
출력: CapCut 드래프트 (draft_content.json) - CapCut 앱에서 열어 바로 확인/편집
```

## 핵심 원칙

- **전체 대본(script) 먼저**: Whisper로 영상 전체의 대본을 문장 단위로 뽑아낸 뒤, 그 대본을 보고
  "이 문장을 통째로 자를지"를 판단합니다. 단어 하나하나를 필러 사전과 대조해서 지우는 방식이 아닙니다.
- **빌드 성공 ≠ 검증**: 이 도구는 드래프트 파일(JSON)을 구조적으로 올바르게 만들 뿐입니다.
  실제로 의도한 대로 잘렸는지, 자막 위치/타이밍이 맞는지는 **반드시 CapCut 앱에서 직접 열어 재생**해서
  확인해야 합니다.

## 아키텍처

```
app/
  config.py            Step0: OS/트랙 감지 + 필수 도구 점검
  workdir.py            업로드/캐시 디렉터리, 설정 저장
  main.py                FastAPI 앱 (업로드, SSE 파이프라인, 미리보기, 보존구간 재생성)
  static/index.html      단일 정적 페이지 (드래그드롭 + SSE 스텝퍼 + 미리보기)
  pipeline/
    ranges.py            초 단위 구간 연산 (병합/차집합/타임라인 리매핑)
    silence.py           ffmpeg silencedetect 기반 무음 컷
    transcribe.py         Whisper 전체 대본 추출 (ASR Lock + 컨텐츠 해시 캐시)
    korean_chunk.py       단어 -> 자막 청크 (의존명사 청크 보정)
    filler_ng.py           전체 대본 기반 잔말/NG(재촬영/중복) 판단
    cuts.py                무음컷 ∩ ¬(필러/NG) ∪ 사용자 보존구간 = 최종 컷
    draft.py               pycapcut으로 실제 CapCut 드래프트(JSON) 생성
```

## Step 0 - 환경 점검

```bash
python3 -m app.config
```

OS/CPU 아키텍처에 따라 자동으로 트랙이 갈립니다.

| 환경 | 트랙 | ASR 백엔드 | 비고 |
|---|---|---|---|
| macOS Apple Silicon (Darwin arm64) | 트랙 A | mlx-whisper | |
| Windows AMD64 | 트랙 C | faster-whisper | CapCut 자동 export 보너스(uiautomation) |
| 그 외 (Intel Mac, Linux 등) | fallback | faster-whisper | |

필요 도구가 없으면 설치 명령을 안내하고 대기합니다:

- **macOS**: `brew install python@3.11 ffmpeg`
- **Windows**: [python.org](https://python.org)에서 Python 설치, `winget install ffmpeg`
- **CapCut 드래프트 폴더**: CapCut을 설치하고 1회 이상 실행해야 생성됩니다. 자동으로 못 찾으면
  웹 UI 상단의 "드래프트 폴더" 입력란에 직접 경로를 넣어주세요.
- 디스크 여유공간 5GB 이상 (Whisper 모델 다운로드/캐시용)

## 실행

```bash
# macOS (Apple Silicon)
./run_mac.sh

# Windows
run_win.bat

# 그 외 (Intel Mac / Linux)
./run_fallback.sh
```

브라우저에서 `http://127.0.0.1:8000` 접속.

## 빌드 적층 - 단계별 실제 검증 방법

이 프로젝트는 아래 순서로 쌓아 올렸고, **각 단계는 실제로 CapCut에서 열어 재생해봐야 다음 단계로
넘어간 것**입니다. 코드가 예외 없이 돌았다는 것과 캡컷에서 정상 재생되는 것은 별개입니다.

1. **점프컷만** (`app/pipeline/silence.py` + `draft.py`): 무음 구간만 잘라낸 드래프트.
   → CapCut에서 열어 "말 잘림 없이 자연스럽게 붙는지" 확인.
2. **웹 UI**: 드래그드롭 업로드 + SSE 스텝퍼가 4단계(무음→대본→필러/NG→드래프트)를 순서대로 보여주는지 확인.
3. **자막**: Whisper 전체 대본 + 어절 단위 자막이 붙은 드래프트. → 자막 타이밍/위치(화면 하단) 확인.
4. **필러/NG 통합 컷**: "다시 할게요" 같은 재촬영 신호, 중복 문장, 잔말만 있는 구간이 실제로 빠졌는지,
   결과 카드의 대본 하이라이트(NG/중복/필러 태그)가 실제 컷과 일치하는지 확인.
5. **미리보기 + 수동 보존**: 영상 미리보기에서 `[`/`]`로 구간을 표시해 자동 컷을 덮어쓴 뒤 재생성한
   드래프트가 그 구간을 실제로 살렸는지 확인.

## 알려진 함정 (pycapcut 실제 소스 확인 기준)

- **`Timerange(start, duration)`의 두 번째 인자는 끝 시각이 아니라 길이**입니다. 끝 시각을 넣는 실수를
  하면 클립이 원본보다 훨씬 길거나 짧게 생성됩니다. (`app/pipeline/draft.py` 참고)
- **메인(최하단) 비디오 트랙의 첫 세그먼트는 반드시 0초에서 시작**해야 합니다. 아니면 CapCut이 강제로
  0초로 당겨서 이후 모든 세그먼트 위치가 틀어집니다.
- **`ClipSettings.transform_y`는 픽셀도 0~1 비율도 아니라 "캔버스 높이의 절반"을 1로 하는 단위**입니다.
  자막 기본 위치(화면 하단)는 대략 `-0.8` 부근입니다.
- **드래프트 진입점 파일명 이슈**: pycapcut은 `draft_content.json`만 생성하지만, CapCut 버전에 따라
  `draft_info.json`을 기대한다는 보고가 있어 방어적으로 동일 내용을 `draft_info.json`으로도 함께
  저장합니다. 그래도 CapCut에 드래프트가 안 보이면 이 부분부터 의심하고 실제 확인이 필요합니다.
- **ASR은 스레드 세이프하지 않습니다** (mlx/numba 내부 이슈로 동시 호출 시 세그폴트 가능). 전역
  `asyncio.Lock`으로 직렬화합니다 (`app/pipeline/transcribe.py`의 `ASR_LOCK`).
- **캐시 키는 파일 내용 해시**를 씁니다. mtime/경로 기반이면 재업로드할 때마다 캐시가 miss 납니다.
- **의존명사 청크**: "할 수 있다"처럼 관형어+의존명사("수")가 자막 줄에서 갈라지지 않도록
  청크 경계를 보정합니다 (`app/pipeline/korean_chunk.py`).

## 이 세션(빌드 환경)에서 검증하지 못한 부분

이 코드는 클라우드 리눅스 샌드박스에서 작성되었고, 다음은 **이 환경의 제약으로 직접 검증하지
못했으니 실제 사용 환경(Mac/Windows + CapCut 설치됨)에서 꼭 확인해주세요**:

- **CapCut 실제 재생**: 이 샌드박스에는 CapCut 앱 자체가 없어 GUI로 드래프트를 열어볼 수 없습니다.
  대신 `pycapcut.ScriptFile.load_template()`으로 생성된 `draft_content.json`을 다시 로드해
  구조적으로 유효한지(예외 없이 파싱, 세그먼트 개수/타이밍 일치)만 확인했습니다 (`tests/` 참고).
- **실제 Whisper 모델 다운로드/추론**: 샌드박스의 아웃바운드 네트워크 정책상 `huggingface.co`
  접근이 막혀 있어(조직 egress 정책), 실제 모델 가중치를 받아 진짜 한국어 음성을 전사해보지
  못했습니다. 대신 가짜(mock) 대본으로 업로드→SSE 파이프라인→필러/NG 판단→드래프트 생성→
  보존구간 재생성까지 전체 배관(plumbing)을 end-to-end로 검증했습니다. 실제 환경에서는 첫 실행 시
  Whisper 모델이 자동 다운로드됩니다(인터넷 필요, 수 분 소요될 수 있음).
- **Mac(mlx-whisper) 트랙**: Apple Silicon 하드웨어가 없어 `mlx_whisper` 경로는 코드만 작성했고
  실행 검증은 못 했습니다. 미설치 시 자동으로 faster-whisper로 폴백합니다.
- **Windows CapCut 자동 export 보너스**: `uiautomation` 기반 자동 export는 Windows 전용이라
  이 세션에서 실행할 수 없었습니다 (미구현 상태 - 필요하면 `pycapcut.jianying_controller`를
  참고해 추가해주세요).

## 테스트

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -v
```

ffmpeg로 합성한 무음/톤 테스트 클립에 대해 무음 탐지, 잔말/NG 판단, 드래프트 생성 및
pycapcut 자체 로더를 통한 구조적 유효성 검증(round-trip)을 수행합니다.
