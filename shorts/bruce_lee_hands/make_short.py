"""이소룡의 손 - 30초 유튜브 쇼츠 생성기 (1080x1920, 30fps)

실사진 구간은 --photo 로 받은 이미지(좌: 손 클로즈업 / 우: 전신)를 켄번즈로 움직이고,
사진 사이의 빈 구간은 코드로 그린 재연 모션그래픽으로 채운다.
나레이션은 오프라인 espeak-ng 가이드 보이스(타이밍 확인용)이며, 최종본은 CapCut TTS 로 교체한다.

사용법:
  python make_short.py --photo hands.jpg --font NanumGothicExtraBold.ttf --out out.mp4
  python make_short.py --layout single --photo kato_1967.jpg --font NanumGothicExtraBold.ttf --out out.mp4
"""
import argparse
import math
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
DUR = 30.0
SR = 44100

# (시작, 끝, 종류, 상단 라벨, 나레이션/자막, 강조어)
SCENES = [
    (0.0, 3.6, "photo_close", "실제 사진", "이게… 이소룡의 손입니다", "이소룡의 손"),
    (3.6, 7.6, "photo_knuckle", "실제 사진", "마디마다 혹처럼 솟은 굳은살", "굳은살"),
    (7.6, 11.8, "dummy", "재연 그래픽", "나무인형과 샌드백을 수없이 두드린 흔적", "수없이"),
    (11.8, 15.6, "pushup", "재연 그래픽", "엄지와 검지, 두 손가락 팔굽혀펴기", "두 손가락"),
    (15.6, 20.4, "inch", "재연 그래픽", "1964년, 단 1인치 거리의 펀치", "1인치"),
    (20.4, 24.8, "coin", "전해지는 일화", "손을 쥐기 전에 동전을 바꿔치기했다죠", "동전"),
    (24.8, 30.0, "photo_full", "실제 사진", "재능이 아니라, 반복이 만든 손", "반복"),
]

# --layout single: 퍼블릭 도메인 인물 사진 1장만 있을 때. 손 클로즈업은 재연 그래픽으로 대체.
SINGLE_SCENES = [
    (0.0, 3.6, "photo_face", "공개 사진", "이소룡, 그 손에 숨은 이야기", "손"),
    (3.6, 7.6, "knuckles", "재연 그래픽", "마디마다 혹처럼 솟은 굳은살", "굳은살"),
] + SCENES[2:6] + [
    (24.8, 30.0, "photo_out", "공개 사진", "재능이 아니라, 반복이 만든 손", "반복"),
]

SEPIA = np.array([236, 214, 178], np.float32)
GOLD = (255, 196, 64)


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


# ---------------------------------------------------------------- 공통 레이어
def make_vignette():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)
    return np.clip(1.15 - d ** 2 * 0.75, 0.25, 1.0)[..., None]


def make_bg():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H * 0.45) / H) ** 2)
    g = np.clip(1 - d * 1.6, 0, 1)[..., None]
    return (np.array([18, 14, 10], np.float32) + g * np.array([70, 52, 34], np.float32))


def cover(img, cx, cy, zoom):
    """img 위의 (cx, cy) 비율 지점을 중심으로 9:16 영역을 잘라 W x H 로 확대."""
    iw, ih = img.size
    ch = min(ih, iw / (W / H)) / zoom
    cw = ch * W / H
    x0 = min(max(cx * iw - cw / 2, 0), iw - cw)
    y0 = min(max(cy * ih - ch / 2, 0), ih - ch)
    return img.resize((W, H), Image.BICUBIC, box=(x0, y0, x0 + cw, y0 + ch))


# ---------------------------------------------------------------- 장면 그리기
class Renderer:
    def __init__(self, photo, font_path, scenes=SCENES, face_y=0.3):
        self.scenes = scenes
        self.face_y = face_y
        src = Image.open(photo).convert("L")
        sw, sh = src.size
        if scenes is SINGLE_SCENES:
            self.full = src.filter(ImageFilter.UnsharpMask(radius=2, percent=60))
        else:
            # 업로드 이미지는 좌우 2분할 콜라주: 좌=손 클로즈업, 우=전신
            self.close = src.crop((0, 0, int(sw * 0.49), sh))
            self.full = src.crop((int(sw * 0.505), 0, sw, sh)).filter(
                ImageFilter.UnsharpMask(radius=2, percent=60))
        self.vig = make_vignette()
        self.bg = make_bg()
        self.font = lambda s: ImageFont.truetype(font_path, s)
        self.rng = np.random.default_rng(7)
        self.grain = [self.rng.normal(0, 9, (H // 2, W // 2, 1)).astype(np.float32)
                      for _ in range(6)]

    # 사진 -> 세피아 배열
    def tone(self, img_l):
        a = np.asarray(img_l, np.float32)[..., None] / 255.0
        return a * SEPIA

    def photo(self, kind, p):
        if kind == "photo_close":
            im = cover(self.close, 0.5, 0.55 - 0.05 * p, 1.0 + 0.18 * ease(p))
        elif kind == "photo_knuckle":
            im = cover(self.close, 0.42 + 0.05 * p, 0.58, 1.55 + 0.35 * ease(p))
        elif kind == "photo_face":  # 얼굴로 천천히 푸시인
            im = cover(self.full, 0.5, self.face_y + 0.05, 1.05 + 0.3 * ease(p))
        elif kind == "photo_out":  # 얼굴 클로즈업에서 전체로 줌아웃
            im = cover(self.full, 0.5, self.face_y + 0.15 * ease(p), 1.8 - 0.75 * ease(p))
        else:  # photo_full: 손에서 시작해 얼굴까지 끌어올리며 줌아웃
            q = ease(p)
            im = cover(self.full, 0.5, 0.68 - 0.33 * q, 1.9 - 0.85 * q)
        return self.tone(im)

    def knuckles(self, t, p, d):
        """주먹 쥔 손등 - 마디마다 굳은살이 차오른다."""
        img = Image.new("RGB", (W, H))
        dr = ImageDraw.Draw(img)
        skin, line = (215, 180, 145), (120, 85, 60)
        dr.rounded_rectangle((200, 560, 880, 1260), 150, fill=skin, outline=line, width=8)
        dr.rounded_rectangle((120, 900, 360, 1180), 110, fill=skin, outline=line, width=8)  # 엄지
        grow = ease((t - 0.4) / 2.2)
        for i in range(4):
            x = 290 + i * 165
            dr.line((x - 60, 700, x - 60, 1100), fill=line, width=5)
            r = 30 + 38 * grow
            y = 700 + 15 * (i % 2)
            dr.ellipse((x - r, y - r * 0.8, x + r, y + r * 0.8), fill=(228, 200, 165), outline=line, width=6)
            dr.ellipse((x - r * 0.5, y - r * 0.55, x - r * 0.05, y - r * 0.2), fill=(250, 235, 210))
        ring = 120 + 25 * math.sin(t * 6)
        cx = 535
        dr.ellipse((cx - 420, 700 - ring, cx + 420, 700 + ring), outline=GOLD, width=8)
        return np.asarray(img, np.float32), [("굳은살", 110, 330, GOLD)], None

    def dummy(self, t, p, d):
        img = Image.new("RGB", (W, H))
        dr = ImageDraw.Draw(img)
        wood, dark = (120, 78, 42), (70, 44, 24)
        cx = W // 2
        dr.rounded_rectangle((cx - 95, 330, cx + 95, 1250), 60, fill=wood, outline=dark, width=8)
        for y, ang in ((560, -18), (560, 18)):
            x2 = cx + (330 if ang > 0 else -330)
            dr.line((cx, y, x2, y - 70), fill=dark, width=46)
            dr.line((cx, y, x2, y - 70), fill=wood, width=32)
        dr.line((cx, 760, cx + 300, 800), fill=dark, width=46)
        dr.line((cx, 760, cx + 300, 800), fill=wood, width=32)
        dr.line((cx, 1050, cx - 220, 1260), fill=dark, width=56)
        dr.line((cx, 1050, cx - 220, 1260), fill=wood, width=40)
        arr = np.asarray(img, np.float32)
        hits = int(t / 0.42)
        local = (t % 0.42) / 0.42
        ov = Image.new("RGB", (W, H))
        od = ImageDraw.Draw(ov)
        hx, hy = [(cx - 40, 640), (cx + 50, 900), (cx - 10, 470)][hits % 3]
        r = 40 + 260 * local
        a = int(255 * (1 - local))
        for k in range(3):
            rr = r * (1 - 0.22 * k)
            od.ellipse((hx - rr, hy - rr, hx + rr, hy + rr), outline=(a, int(a * 0.75), a // 4), width=10 - 3 * k)
        fist = 120 * (1 - ease(local * 3))
        od.ellipse((hx - 70 - fist, hy - 55, hx + 50 - fist, hy + 55), fill=(int(a * 0.85), int(a * 0.7), int(a * 0.55)))
        arr = np.clip(arr + np.asarray(ov, np.float32), 0, 255)
        count = int(10000 * ease(p) ** 1.6)
        return arr, [("× {:,}".format(count), 140, 1290, GOLD), ("목인장 · 샌드백 · 마키와라", 60, 250, (230, 220, 200))], hits

    def pushup(self, t, p, d):
        img = Image.new("RGB", (W, H))
        dr = ImageDraw.Draw(img)
        gy = 1180
        dr.line((90, gy, W - 90, gy), fill=(150, 120, 90), width=8)
        phase = (math.sin(t * 2 * math.pi / 1.25 - math.pi / 2) + 1) / 2  # 0=아래 1=위
        hand_x = 330
        sh_y = gy - 150 - 170 * phase
        feet = (900, gy - 8)
        body = (230, 200, 160)
        dr.line((hand_x, gy - 10, hand_x + 10, sh_y), fill=body, width=34)  # 팔
        dr.line((hand_x + 10, sh_y, *feet), fill=body, width=58)  # 몸통+다리
        dr.ellipse((hand_x - 105, sh_y - 95, hand_x - 5, sh_y + 5), fill=body)  # 머리
        # 두 손가락 (엄지, 검지)
        for dx in (-22, 22):
            dr.line((hand_x + dx * 0.4, gy - 34, hand_x + dx, gy - 4), fill=GOLD, width=14)
        glow = 60 + 30 * math.sin(t * 9)
        dr.ellipse((hand_x - glow, gy - glow, hand_x + glow, gy + glow), outline=GOLD, width=5)
        reps = int(t / 1.25) + 1
        return np.asarray(img, np.float32), [("엄지 + 검지", 120, 560, GOLD), ("{}회".format(reps), 90, 1360, (240, 230, 210))], None

    def inch(self, t, p, d):
        img = Image.new("RGB", (W, H))
        dr = ImageDraw.Draw(img)
        texts = []
        if t < 1.6:
            s = ease(t / 0.5)
            texts.append(("1964", int(80 + 190 * s), 760, GOLD))
            texts.append(("롱비치 국제 가라테 대회", 58, 1080, (230, 220, 200)))
        else:
            k = t - 1.6
            base_y = 880
            # 자
            dr.rectangle((200, base_y + 170, 880, base_y + 230), fill=(200, 170, 110))
            for i in range(0, 681, 34):
                h = 40 if i % 170 == 0 else 20
                dr.line((200 + i, base_y + 170, 200 + i, base_y + 170 + h), fill=(60, 40, 20), width=4)
            punch = ease((k - 0.8) / 0.12)
            fist_x = 360 + 90 * punch
            target_x = 560 + (0 if k < 0.92 else 700 * ease((k - 0.92) / 0.6))
            dr.rounded_rectangle((fist_x - 140, base_y - 60, fist_x, base_y + 60), 40, fill=(230, 200, 160))
            dr.rectangle((target_x, base_y - 160, target_x + 140, base_y + 160), fill=(110, 110, 120))
            # 1인치 간격 표시
            if k < 0.8:
                dr.line((fist_x, base_y - 110, 450 + 110, base_y - 110), fill=GOLD, width=6)
                texts.append(("1 inch", 70, base_y - 200, GOLD))
            if k > 0.9:
                q = min((k - 0.9) / 0.5, 1)
                r = 40 + 500 * q
                a = int(255 * (1 - q))
                dr.ellipse((460 - r, base_y - r, 460 + r, base_y + r), outline=(a, int(a * 0.8), a // 3), width=12)
            texts.append(("원 인치 펀치", 100, 560, (240, 230, 210)))
        return np.asarray(img, np.float32), texts, None

    def coin(self, t, p, d):
        img = Image.new("RGB", (W, H))
        dr = ImageDraw.Draw(img)
        cx, cy = W // 2, 900
        dr.ellipse((cx - 330, cy - 240, cx + 330, cy + 240), fill=(205, 170, 135))
        for i, ang in enumerate((-60, -25, 5, 35)):
            x = cx - 180 + i * 120
            dr.rounded_rectangle((x - 45, cy - 520 + abs(ang) * 2, x + 45, cy - 180), 45, fill=(205, 170, 135))
        swap = 2.1
        if t < swap:
            col, label = (200, 200, 210), "은화"
        else:
            col, label = GOLD, "금화"
        if abs(t - swap) < 0.18:  # 순간 잔상
            q = (t - swap + 0.18) / 0.36
            for k in range(8):
                x = cx - 500 + 1000 * q - k * 40
                dr.ellipse((x - 90, cy - 90, x + 90, cy + 90), fill=(255, 240, 200))
        dr.ellipse((cx - 110, cy - 110, cx + 110, cy + 110), fill=col, outline=(90, 70, 30), width=8)
        return np.asarray(img, np.float32), [(label, 90, 1280, col)], None

    # 자막/라벨
    def overlay(self, arr, scene, t_in, extra):
        s, e, kind, tag, sub, key = scene
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        dr = ImageDraw.Draw(img)
        for txt, size, y, col in extra:
            f = self.font(size)
            w = dr.textlength(txt, font=f)
            dr.text(((W - w) / 2, y), txt, font=f, fill=col, stroke_width=6, stroke_fill=(0, 0, 0))
        # 상단 라벨 (실제 사진 / 재연 그래픽 구분)
        f = self.font(40)
        tw = dr.textlength(tag, font=f)
        colr = (200, 40, 40) if tag in ("실제 사진", "공개 사진") else (60, 60, 60)
        dr.rounded_rectangle((60, 150, 60 + tw + 50, 220), 14, fill=colr)
        dr.text((85, 158), tag, font=f, fill=(255, 255, 255))
        # 하단 자막 - 강조어 노란색, 살짝 팝업
        pop = 1.0 + 0.08 * (1 - ease(t_in / 0.18))
        f = self.font(int(74 * pop))
        pre, _, post = sub.partition(key)
        parts = [(pre, (255, 255, 255)), (key, GOLD), (post, (255, 255, 255))]
        total = sum(dr.textlength(x, font=f) for x, _ in parts)
        if total > W - 100:
            f = self.font(int(74 * pop * (W - 100) / total))
            total = sum(dr.textlength(x, font=f) for x, _ in parts)
        x, y = (W - total) / 2, 1520
        for txt, c in parts:
            dr.text((x, y), txt, font=f, fill=c, stroke_width=8, stroke_fill=(0, 0, 0))
            x += dr.textlength(txt, font=f)
        if s == 0.0 and t_in < 3.4:  # 오프닝 타이틀
            f = self.font(150)
            title = "이소룡의 손"
            w = dr.textlength(title, font=f)
            a = ease(t_in / 0.4)
            dr.text(((W - w) / 2, 330 - 40 * (1 - a)), title, font=f, fill=GOLD, stroke_width=10, stroke_fill=(0, 0, 0))
        return np.asarray(img, np.float32)

    def frame(self, n):
        t = n / FPS
        idx = next(i for i, sc in enumerate(self.scenes) if sc[0] <= t < sc[1] or i == len(self.scenes) - 1)
        sc = self.scenes[idx]
        s, e, kind = sc[:3]
        t_in, p = t - s, (t - s) / (e - s)
        extra, shake = [], 0
        if kind.startswith("photo"):
            arr = self.photo(kind, p)
            if kind == "photo_knuckle":
                # 마디 위로 지나가는 하이라이트 링
                ring = Image.new("L", (W, H))
                rd = ImageDraw.Draw(ring)
                r = 300 + 20 * math.sin(t * 6)
                rd.ellipse((W / 2 - r, H * 0.5 - r * 0.7, W / 2 + r, H * 0.5 + r * 0.7), outline=255, width=10)
                m = np.asarray(ring, np.float32)[..., None] / 255 * ease(t_in / 0.6)
                arr = arr * (1 - m) + m * np.array(GOLD, np.float32)
        else:
            arr, extra, hit = getattr(self, kind)(t_in, p, e - s)
            arr = self.bg + arr * 0.95 if arr.max() > 0 else self.bg
            arr = np.where(arr > self.bg, arr, self.bg)
            if hit is not None and (t_in % 0.42) < 0.08:
                shake = 14
        arr = self.overlay(arr, sc, t_in, extra)
        if shake:
            arr = np.roll(arr, (int(self.rng.integers(-shake, shake)), int(self.rng.integers(-shake, shake))), (0, 1))
        # 장면 전환: 앞 0.12초 화이트 플래시 (끊기는 컷을 부드럽게)
        if idx > 0 and t_in < 0.12:
            arr = arr + (255 - arr) * (1 - t_in / 0.12) * 0.85
        if t > DUR - 0.5:
            arr = arr * max(0.0, (DUR - t) / 0.5)
        g = self.grain[n % len(self.grain)].repeat(2, 0).repeat(2, 1)
        arr = arr * self.vig + g
        return np.clip(arr, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- 오디오
def espeak_tts(text, rate=175):
    import ctypes
    import espeakng_loader as L
    lib = ctypes.cdll.LoadLibrary(L.get_library_path())
    chunks = []
    CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)

    @CB
    def cb(wav, n, ev):
        if n > 0:
            chunks.append(ctypes.string_at(wav, n * 2))
        return 0

    sr = lib.espeak_Initialize(2, 0, L.get_data_path().encode(), 0)
    lib.espeak_SetSynthCallback(cb)
    lib.espeak_SetVoiceByName(b"ko")
    lib.espeak_SetParameter(1, rate, 0)
    lib.espeak_SetParameter(3, 35, 0)
    raw = text.encode()
    lib.espeak_Synth(raw, len(raw) + 1, 0, 0, 0, 0x11, None, None)
    lib.espeak_Synchronize()
    x = np.frombuffer(b"".join(chunks), np.int16).astype(np.float32) / 32768
    # 22.05k -> 44.1k 선형 보간
    return np.interp(np.arange(int(len(x) * SR / sr)) * sr / SR, np.arange(len(x)), x)


def build_audio(path, voice=True, scenes=SCENES):
    n = int(DUR * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    # 저음 드론 + 느린 트레몰로
    music = (0.10 * np.sin(2 * np.pi * 55 * t) + 0.05 * np.sin(2 * np.pi * 82.4 * t)
             + 0.03 * np.sin(2 * np.pi * 110 * t)) * (0.7 + 0.3 * np.sin(2 * np.pi * 0.25 * t))
    music *= np.clip(t / 1.0, 0, 1) * np.clip((DUR - t) / 1.5, 0, 1)

    def add(sig, at, gain):
        i = int(at * SR)
        j = min(n, i + len(sig))
        music[i:j] += sig[: j - i] * gain

    k = np.arange(int(0.6 * SR)) / SR
    drum = np.sin(2 * np.pi * (60 + 90 * np.exp(-k * 30)) * k) * np.exp(-k * 7)
    hit = np.sin(2 * np.pi * (140 + 300 * np.exp(-k * 60)) * k) * np.exp(-k * 22) + rng.normal(0, 0.4, len(k)) * np.exp(-k * 40)
    m = np.arange(int(0.35 * SR)) / SR
    whoosh = np.convolve(rng.normal(0, 1, len(m)), np.ones(40) / 40, "same") * np.sin(np.pi * m / 0.35) ** 2
    for i, sc in enumerate(scenes):
        add(drum, sc[0], 0.7)
        if i:
            add(whoosh, max(sc[0] - 0.2, 0), 0.5)
    s3 = SCENES[2]
    for x in np.arange(s3[0], s3[1] - 0.2, 0.42):
        add(hit, x, 0.35)
    add(drum, SCENES[4][0] + 1.6 + 0.92, 1.0)  # 원인치 펀치 임팩트
    add(hit, SCENES[4][0] + 1.6 + 0.92, 0.8)
    out = music
    if voice:
        vo = np.zeros(n)
        for sc in scenes:
            v = espeak_tts(sc[4].replace("…", ","))
            i = int((sc[0] + 0.2) * SR)
            j = min(n, i + len(v))
            vo[i:j] += v[: j - i] * 0.9
        out = music * 0.55 + vo
    out = out / max(1e-6, np.abs(out).max()) * 0.89
    pcm = (np.repeat(out[:, None], 2, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", required=True)
    ap.add_argument("--font", required=True)
    ap.add_argument("--out", default="bruce_lee_hands_short.mp4")
    ap.add_argument("--layout", choices=["collage", "single"], default="collage",
                    help="collage=손클로즈업|전신 2분할 이미지, single=인물 사진 1장(퍼블릭 도메인 사진용)")
    ap.add_argument("--face-y", type=float, default=0.3, help="single: 얼굴 중심의 세로 위치(0~1)")
    ap.add_argument("--no-voice", action="store_true", help="나레이션 없이 BGM/효과음만 (CapCut TTS 용)")
    a = ap.parse_args()
    out = Path(a.out)
    wav = out.with_suffix(".wav")
    scenes = SINGLE_SCENES if a.layout == "single" else SCENES
    build_audio(wav, voice=not a.no_voice, scenes=scenes)
    r = Renderer(a.photo, a.font, scenes, a.face_y)
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out),
    ], stdin=subprocess.PIPE)
    for n in range(int(DUR * FPS)):
        ff.stdin.write(r.frame(n).tobytes())
    ff.stdin.close()
    ff.wait()
    wav.unlink()
    print(out)


if __name__ == "__main__":
    main()
