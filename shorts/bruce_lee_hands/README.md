# 이소룡의 손 — 30초 유튜브 쇼츠

`make_short.py`가 1080x1920 / 30fps / 30초 쇼츠를 만듭니다.

```bash
pip install pillow numpy espeakng-loader koreanize-matplotlib   # 폰트(나눔고딕, OFL)는 koreanize-matplotlib 에 포함
python make_short.py --photo hands.jpg --font NanumGothicExtraBold.ttf --out output/short.mp4
python make_short.py --photo hands.jpg --font NanumGothicExtraBold.ttf --no-voice --out output/short_novoice.mp4
```

- `--photo`: 좌(손 클로즈업) / 우(전신) 2분할 콜라주 이미지
- `--layout single --photo <인물사진> [--face-y 0.3]`: 퍼블릭 도메인 인물 사진 1장용. 첫 장면과 마지막 장면에 사진을 쓰고,
  손 클로즈업 장면은 굳은살 재연 그래픽으로 대체합니다. 후보: Wikimedia Commons
  `File:Bruce-Lee-as-Kato-1967-retouched.jpg` (1967 ABC 홍보 사진. 저작권 표기 없이 발행돼 미국 퍼블릭 도메인이지만, 캐나다·중국·독일 등에서는 아직 보호될 수 있음)
- 기본 출력에는 **가이드 나레이션**(오프라인 espeak-ng, 기계음)이 들어갑니다. 타이밍 확인용이니
  최종본은 `--no-voice` 버전을 CapCut에 올리고 아래 대본을 **CapCut 텍스트 읽기(TTS)** 로 입히세요.

## 콘티 & 나레이션 대본

| 시간 | 화면 | 나레이션 (자막) |
|---|---|---|
| 0.0–3.6 | 실제 사진: 손 클로즈업, 천천히 줌인 + 타이틀 "이소룡의 손" | 이게… 이소룡의 손입니다 |
| 3.6–7.6 | 실제 사진: 손가락 마디 확대 + 하이라이트 링 | 마디마다 혹처럼 솟은 굳은살 |
| 7.6–11.8 | 재연 그래픽: 목인장 타격, 횟수 카운터 | 나무인형과 샌드백을 수없이 두드린 흔적 |
| 11.8–15.6 | 재연 그래픽: 두 손가락 팔굽혀펴기 | 엄지와 검지, 두 손가락 팔굽혀펴기 |
| 15.6–20.4 | 재연 그래픽: 1964 롱비치 → 원 인치 펀치 | 1964년, 단 1인치 거리의 펀치 |
| 20.4–24.8 | 재연 그래픽: 손바닥 위 동전 바꿔치기 | 손을 쥐기 전에 동전을 바꿔치기했다죠 |
| 24.8–30.0 | 실제 사진: 손 → 얼굴로 틸트업, 줌아웃 | 재능이 아니라, 반복이 만든 손 |

사실 관계: 목인장(영춘권 수련 도구), 두 손가락 팔굽혀펴기, 1964년 롱비치 국제 가라테 대회의
원 인치 펀치 시연은 기록이 남아 있는 내용입니다. 동전 바꿔치기는 주변인의 증언으로 **전해지는 일화**라
화면에도 그렇게 표기했습니다.

## 재연 구간을 AI 영상으로 바꾸고 싶다면

재연 그래픽 구간(7.6–24.8초)은 코드로 그린 모션그래픽입니다. Kling / Runway / Veo / Sora 같은 영상 생성 AI로
교체하려면 아래 프롬프트를 9:16, 4초로 쓰세요. **실존 인물 얼굴을 흉내 내지 않도록** 손·실루엣 위주로 구성했습니다.

1. `Close-up of a man's knuckles striking a wooden Wing Chun training dummy, 1970s film grain, sepia, dramatic side light, slow motion dust, no face visible`
2. `Low angle silhouette of a martial artist doing push-ups on only thumb and index finger, 1960s gym, sepia film grain, no face visible`
3. `Extreme slow motion of a fist travelling one inch into a padded target, shockwave ripple, dark background, vintage 16mm look`
4. `Top-down shot of an open palm holding a coin, a hand blurs in and swaps the coin in a split second, sepia, film grain`

## 저작권 주의 (업로드 전 꼭 확인)

- 이 폴더의 영상에 들어간 **사진은 사용자가 제공한 바이럴 이미지**이며, 원 촬영자/권리자가 확인되지 않았습니다.
  저작권이 해결된 사진이 아니므로 그대로 올리면 신고 위험이 있습니다. 사진 파일은 저장소에 포함하지 않았습니다.
- 안전한 대안: Wikimedia Commons에서 라이선스가 **Public domain / CC BY**로 표시된 이소룡 사진
  (예: 1960년대 TV 시리즈 *The Green Hornet* 홍보 사진 중 저작권 표기 없이 배포되어 미국 퍼블릭 도메인인 것)을
  찾아 `--photo` 로 넣고, CC BY라면 설명란에 출처를 적으세요.
- 이소룡의 이름·초상권은 Bruce Lee Family Company가 관리합니다. 수익화 채널이라면 굿즈·광고처럼 보이지 않게
  정보/교육 목적의 내용으로 유지하세요.
- 바이럴 클로즈업 사진은 리터칭/보정 여부가 확인되지 않았으니 "실제 사진"이라는 라벨이 부담되면
  `SCENES`의 라벨을 "공개된 사진" 등으로 바꾸세요.
- 폰트: 나눔고딕(SIL OFL), 음악·효과음: 코드로 합성 → 저작권 문제 없음.
