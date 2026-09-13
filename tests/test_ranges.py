from app.pipeline.ranges import Range, TimelineMap, complement, normalize, subtract, union


def test_normalize_merges_overlapping():
    result = normalize([Range(0, 2), Range(1, 3), Range(5, 6)])
    assert result == [Range(0, 3), Range(5, 6)]


def test_complement():
    result = complement([Range(1, 2), Range(4, 5)], total_duration=10)
    assert result == [Range(0, 1), Range(2, 4), Range(5, 10)]


def test_subtract_partial_overlap():
    base = [Range(0, 10)]
    cuts = [Range(2, 4), Range(7, 8)]
    result = subtract(base, cuts)
    assert result == [Range(0, 2), Range(4, 7), Range(8, 10)]


def test_subtract_full_cover():
    assert subtract([Range(0, 5)], [Range(-1, 6)]) == []


def test_union():
    result = union([Range(0, 1)], [Range(0.5, 2)])
    assert result == [Range(0, 2)]


def test_timeline_map_basic():
    keep = [Range(5, 7), Range(10, 12)]
    tmap = TimelineMap(keep)
    assert tmap.to_new(5) == 0
    assert tmap.to_new(6) == 1
    assert tmap.to_new(10) == 2
    assert tmap.to_new(11.5) == 3.5
    assert tmap.to_new(8) is None  # 컷된 구간
    assert tmap.total_new_duration == 4


def test_timeline_map_clip_range_spanning_cut():
    keep = [Range(0, 2), Range(5, 7)]
    tmap = TimelineMap(keep)
    # 자막이 keep 구간 하나에 걸쳐 있으면 그대로 매핑
    clipped = tmap.clip_range_to_new(Range(0.5, 1.5))
    assert clipped == [Range(0.5, 1.5)]
    # 컷된 3~5초를 걸치는 구간은 살아남는 부분만 조각으로 반환
    clipped2 = tmap.clip_range_to_new(Range(1.5, 6))
    assert clipped2 == [Range(1.5, 2), Range(2, 3)]
