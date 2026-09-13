"""단어 단위 ASR 결과를 자막 청크(2~4 어절)로 묶는다.

함정 (의존명사 청크): 한국어 띄어쓰기 규범상 의존명사("것", "수", "때", "만큼", "뿐"...)는
앞말과 띄어 쓰기 때문에 whisper의 단어 단위 타임스탬프에서 별도 단어로 분리되는 경우가 많다.
"할 수 있다" -> ["할", "수", "있다"]. 청크 경계를 글자 수/시간으로만 자르면
"~할 | 수 있다"처럼 관형어와 의존명사 사이가 끊어져 가독성이 크게 떨어진다.
그래서 청크 경계를 정할 때 "다음 단어가 의존명사이면 경계를 넘긴다"는 보정을 한 번 거친다.
"""
from __future__ import annotations

from dataclasses import dataclass

# 완전한 목록이 아닌, 자막 줄바꿈에서 특히 어색해지는 대표적인 의존명사만 실용적으로 선정
DEPENDENT_NOUNS = {
    "것", "거", "수", "때", "등", "바", "데", "지", "만큼", "뿐",
    "채", "듯", "터", "리", "나름", "적", "김", "중", "노릇", "셈",
    "만", "게", "분", "번",
}

MAX_CHUNK_CHARS = 16
MAX_CHUNK_WORDS = 4
MAX_CHUNK_DUR = 3.0  # 초
MAX_GAP_WITHIN_CHUNK = 0.6  # 초, 이보다 크게 벌어지면 새 청크로 분리(다른 호흡 단위로 간주)


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class CaptionChunk:
    text: str
    start: float
    end: float
    words: list[Word]


def _should_extend_for_dependent_noun(next_word: Word) -> bool:
    return next_word.text.strip() in DEPENDENT_NOUNS


def chunk_words(words: list[Word]) -> list[CaptionChunk]:
    """단어 리스트(같은 keep 구간 안, 시간순)를 자막 청크로 묶는다.

    호출 시 이미 "살릴 구간" 단위로 잘려 들어온다고 가정 -> 컷 경계를 넘어 묶지 않음.
    """
    if not words:
        return []

    chunks: list[list[Word]] = []
    current: list[Word] = []

    for w in words:
        text = w.text.strip()
        if not text:
            continue

        if current:
            gap = w.start - current[-1].end
            cur_text = "".join(x.text for x in current)
            cur_dur = current[-1].end - current[0].start
            would_break = (
                gap > MAX_GAP_WITHIN_CHUNK
                or len(cur_text) + len(text) > MAX_CHUNK_CHARS
                or len(current) >= MAX_CHUNK_WORDS
                or (w.end - current[0].start) > MAX_CHUNK_DUR
            )
            if would_break:
                # 의존명사가 다음 단어라면 경계를 넘겨 현재 청크에 포함시킨다
                if _should_extend_for_dependent_noun(w) and len(current) < MAX_CHUNK_WORDS + 1:
                    current.append(w)
                    continue
                chunks.append(current)
                current = [w]
                continue
        current.append(w)

    if current:
        chunks.append(current)

    # 후처리: 청크가 의존명사 하나만으로 시작하면(이전 청크 분리 시점이 좋지 않았던 경우)
    # 바로 이전 청크의 마지막 단어를 끌어와 합친다.
    fixed: list[list[Word]] = []
    for c in chunks:
        if (
            fixed
            and len(c) >= 1
            and c[0].text.strip() in DEPENDENT_NOUNS
        ):
            fixed[-1].append(c[0])
            rest = c[1:]
            if rest:
                fixed.append(rest)
        else:
            fixed.append(c)

    result = []
    for c in fixed:
        if not c:
            continue
        text = " ".join(w.text.strip() for w in c).strip()
        text = text.replace("  ", " ")
        result.append(CaptionChunk(text=text, start=c[0].start, end=c[-1].end, words=c))
    return result
