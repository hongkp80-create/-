from app.pipeline.korean_chunk import Word, chunk_words


def _w(text, start, end):
    return Word(start=start, end=end, text=text)


def test_dependent_noun_not_split_from_head_word():
    # "할 수 있다" 에서 청크 경계가 "할" 뒤에서 끊기지 않아야 한다(수가 의존명사이므로).
    words = [_w("정말", 0.0, 0.3), _w("열심히", 0.3, 0.6), _w("공부", 0.6, 0.9),
             _w("할", 0.9, 1.1), _w("수", 1.1, 1.2), _w("있다", 1.2, 1.5)]
    chunks = chunk_words(words)
    texts = [c.text for c in chunks]
    # "수"가 단독으로 다음 청크의 첫 단어가 되어서는 안 됨
    for t in texts:
        assert t.strip() != "수"


def test_basic_chunking_respects_gap():
    words = [_w("안녕", 0.0, 0.5), _w("하세요", 0.5, 1.0), _w("반갑습니다", 3.0, 3.5)]
    chunks = chunk_words(words)
    assert len(chunks) == 2
    assert chunks[0].text == "안녕 하세요"
    assert chunks[1].text == "반갑습니다"


def test_empty_input():
    assert chunk_words([]) == []
