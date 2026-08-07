"""
월드 리그전 랭킹 목록에서 "4위", "5위", "6위" 글자를 찾아 마우스로 클릭하는 스크립트.

동작 방식
---------
1. PC에 떠 있는 에뮬레이터(블루스택/LD플레이어 등) 창을 이름으로 찾는다.
2. 그 창 영역만 스크린샷으로 캡처한다.
3. Tesseract OCR로 화면에서 텍스트와 그 위치(좌표)를 읽어온다.
4. "N위" 형태의 텍스트 중 TARGET_RANKS 에 있는 것을 찾아 마우스로 클릭한다.
5. 아직 못 찾은 순위가 남아 있으면 목록을 살짝 스크롤(드래그)하고 2번부터 반복한다.
6. TARGET_RANKS 를 모두 클릭했거나 최대 스크롤 횟수에 도달하면 종료한다.

사전 준비
---------
1) 아래 명령으로 파이썬 패키지 설치
      pip install -r requirements.txt

2) Tesseract OCR "엔진"은 pip으로 설치되지 않는 별도 프로그램이라 직접 설치해야 함
      https://github.com/UB-Mannheim/tesseract/wiki  (Windows 설치 파일)
   설치 중 "Additional language data" 에서 Korean(kor)을 꼭 체크할 것.
   설치 후 TESSERACT_CMD 경로를 실제 설치 위치에 맞게 아래에서 수정.

3) WINDOW_TITLE 을 실제 에뮬레이터 창 제목(작업표시줄에 뜨는 이름)의 일부로 수정.
   예) BlueStacks 는 보통 "BlueStacks App Player" 같은 이름을 가짐.
   확인하려면 이 파일을 그냥 실행해보면 첫 줄에 현재 잡히는 창 제목 후보들을 출력해줌.

주의
----
- pyautogui 는 마우스가 화면 왼쪽 최상단 모서리(0,0)로 순간 이동하면 즉시 실행을 중단시키는
  안전장치(FAIL-SAFE)가 있음. 스크립트가 폭주할 때 마우스를 화면 좌상단 구석으로 확 밀어붙이면
  즉시 멈춘다.
- 에뮬레이터가 마우스 휠 스크롤을 지원하지 않는 경우가 많아 기본값은 "드래그 스크롤"이다.
  게임이 휠 스크롤을 지원한다면 SCROLL_METHOD 를 "wheel" 로 바꿔도 된다.
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass

import pyautogui
import pygetwindow as gw
import pytesseract
from PIL import Image
from pytesseract import Output

# ============================== 설정 ==============================

# tessdata(언어 데이터) 폴더. Program Files 에 쓰기 권한이 없어 한국어 언어팩(kor.traineddata)을
# 이 사용자 폴더에 따로 받아 두고 여기서 지정한다. 관리자 권한으로 Program Files\Tesseract-OCR\tessdata
# 에 직접 넣었다면 이 값은 비워둬도(None) 된다.
TESSDATA_DIR = os.path.expandvars(r"%LOCALAPPDATA%\tessdata")

# 클릭하고 싶은 순위 목록. "N위" 형태의 텍스트와 정확히 일치해야 매칭된다.
# TARGET_RANKS = ["4위", "5위", "6위", "7위", "8위", "9위"]
TARGET_RANKS = ["8위", "9위"]

# 에뮬레이터 창 제목에 포함된 문자열(일부만 맞아도 됨). 대소문자 구분 없음.
# WINDOW_TITLE = "BlueStacks"
WINDOW_TITLE = "LDPlayer(64)"

# Tesseract 실행 파일 경로. 설치 위치에 맞게 수정.
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# OCR 언어. 한글 인식 필요하므로 kor 필수, 숫자 인식 보조로 eng 같이 사용.
OCR_LANG = "kor+eng"

# --psm 11 = "sparse text": 화면을 하나의 문단으로 묶으려 하지 않고, 흩어진 텍스트 조각들을
# 최대한 개별적으로 찾아냄. 아이콘/아바타 이미지가 섞인 게임 UI에서 엉뚱한 것끼리 한 줄로
# 묶이는 걸 줄여줌.
TESSERACT_CONFIG = "--psm 11"

# 같은 tesseract "줄"에 속한 단어라도, 가로 간격이 이 값(픽셀)보다 벌어지면 서로 다른
# 텍스트 조각으로 취급해서 안 합침. 값이 너무 작으면 "4"+"위"처럼 붙어야 할 것도 갈라지고,
# 너무 크면 옆의 무관한 텍스트/아이콘까지 하나로 합쳐진다.
WORD_GAP_PX = 15

# 클릭 사이 대기 시간(초). 게임 반응/화면 전환 여유 시간.
CLICK_DELAY = 1.0

# 스크롤 방식: "drag"(마우스 드래그로 스와이프) 또는 "wheel"(마우스 휠)
SCROLL_METHOD = "drag"

# 한 번에 스크롤할 픽셀 양(작게 조금씩 내리고 싶다면 값을 작게)
SCROLL_PIXELS = 150

# 스크롤 후 화면이 안정될 때까지 대기 시간(초)
SCROLL_WAIT = 0.8

# 목표 순위를 다 못 찾았을 때 최대 몇 번까지 스크롤을 반복할지
MAX_SCROLLS = 15

# True 로 하면 실제 클릭 없이 어디를 클릭할지 콘솔에만 출력(동작 확인용)
DRY_RUN = False

# True 로 하면 OCR이 화면에서 읽어낸 텍스트를 전부(줄 단위) 콘솔에 출력. "N위" 패턴에
# 안 걸려서 왜 못 찾는지 확인할 때 켜서 사용.
DEBUG_OCR = True

# ====================================================================


RANK_PATTERN = re.compile(r"^\s*(\d+)\s*위\s*$")


@dataclass
class TextBox:
    text: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2


def find_emulator_window(title_substring: str):
    """제목에 title_substring 이 포함된 창을 찾아 반환. 못 찾으면 후보 목록을 보여주고 종료."""
    matches = [w for w in gw.getAllWindows() if title_substring.lower() in w.title.lower() and w.title.strip()]
    if not matches:
        all_titles = sorted({w.title for w in gw.getAllWindows() if w.title.strip()})
        print(f'"{title_substring}" 을(를) 포함한 창을 찾지 못했습니다. 현재 열려 있는 창 목록:')
        for t in all_titles:
            print(f"  - {t}")
        print("\nWINDOW_TITLE 값을 위 목록 중 하나에 맞게 수정한 뒤 다시 실행하세요.")
        sys.exit(1)
    win = matches[0]
    if win.isMinimized:
        win.restore()
    win.activate()
    time.sleep(0.3)
    return win


def capture_window(win) -> Image.Image:
    """창 영역만 스크린샷으로 캡처. 좌표는 스크린 절대좌표 기준."""
    region = (win.left, win.top, win.width, win.height)
    return pyautogui.screenshot(region=region)


def extract_rank_boxes(image: Image.Image, win_left: int, win_top: int) -> list[TextBox]:
    """OCR로 이미지에서 "N위" 형태의 텍스트와 그 화면 절대좌표를 추출."""
    data = pytesseract.image_to_data(image, lang=OCR_LANG, output_type=Output.DICT, config=TESSERACT_CONFIG)

    # 1) 먼저 tesseract가 매긴 "줄"(block/par/line) 단위로 단어들을 모은다.
    lines: dict[tuple[int, int, int], list[int]] = {}
    n = len(data["text"])
    for i in range(n):
        text = data["text"][i].strip()
        if not text:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(i)

    if DEBUG_OCR:
        print("  [OCR 디버그] 인식된 텍스트 조각 목록:")

    boxes: list[TextBox] = []
    for idxs in lines.values():
        idxs.sort(key=lambda i: data["left"][i])

        # 2) 같은 줄이라도 가로 간격이 WORD_GAP_PX 이상 벌어지면 별개 조각으로 쪼갠다.
        #    (게임 UI는 아이콘/아바타가 텍스트 사이에 끼어 있어서, tesseract가 옆의 무관한
        #    텍스트까지 같은 줄로 묶어버리는 걸 막기 위함)
        clusters: list[list[int]] = []
        current: list[int] = [idxs[0]]
        for i in idxs[1:]:
            prev = current[-1]
            gap = data["left"][i] - (data["left"][prev] + data["width"][prev])
            if gap > WORD_GAP_PX:
                clusters.append(current)
                current = [i]
            else:
                current.append(i)
        clusters.append(current)

        for cluster in clusters:
            joined = "".join(data["text"][i].strip() for i in cluster)
            confs = [data["conf"][i] for i in cluster]
            m = RANK_PATTERN.match(joined)

            if DEBUG_OCR:
                status = "MATCH" if m else "-----"
                print(f"    [{status}] {joined!r}  (conf={confs})")

            if not m:
                continue
            lefts = [data["left"][i] for i in cluster]
            tops = [data["top"][i] for i in cluster]
            rights = [data["left"][i] + data["width"][i] for i in cluster]
            bottoms = [data["top"][i] + data["height"][i] for i in cluster]
            boxes.append(
                TextBox(
                    text=joined,
                    left=win_left + min(lefts),
                    top=win_top + min(tops),
                    right=win_left + max(rights),
                    bottom=win_top + max(bottoms),
                )
            )
    return boxes


def scroll_down(win) -> None:
    cx = win.left + win.width // 2
    cy_top = win.top + int(win.height * 0.6)
    cy_bottom = cy_top - SCROLL_PIXELS

    if SCROLL_METHOD == "wheel":
        pyautogui.moveTo(cx, cy_top)
        pyautogui.scroll(-SCROLL_PIXELS)
    else:  # drag
        pyautogui.moveTo(cx, cy_top, duration=0.1)
        pyautogui.mouseDown()
        pyautogui.moveTo(cx, cy_bottom, duration=0.35)
        pyautogui.mouseUp()

    time.sleep(SCROLL_WAIT)


def main() -> None:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    if TESSDATA_DIR:
        os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR

    win = find_emulator_window(WINDOW_TITLE)
    print(f'대상 창: "{win.title}" ({win.left},{win.top} {win.width}x{win.height})')

    remaining = list(TARGET_RANKS)
    clicked: set[str] = set()

    for scroll_attempt in range(MAX_SCROLLS + 1):
        if not remaining:
            break

        image = capture_window(win)
        boxes = extract_rank_boxes(image, win.left, win.top)
        found_texts = [b.text for b in boxes]
        print(f"[시도 {scroll_attempt}] OCR로 찾은 'N위' 텍스트: {found_texts}")

        for box in boxes:
            if box.text in remaining and box.text not in clicked:
                x, y = box.center
                print(f'  -> "{box.text}" 클릭 위치: ({x}, {y})')
                if not DRY_RUN:
                    pyautogui.moveTo(x, y, duration=0.2)
                    pyautogui.click()
                clicked.add(box.text)
                remaining.remove(box.text)
                time.sleep(CLICK_DELAY)

        if not remaining:
            break

        if scroll_attempt < MAX_SCROLLS:
            print(f"  아직 못 찾음: {remaining} -> 스크롤 후 재시도")
            scroll_down(win)

    if remaining:
        print(f"\n찾지 못한 순위: {remaining} (MAX_SCROLLS={MAX_SCROLLS} 도달)")
    else:
        print("\n모든 대상 순위를 클릭 완료했습니다.")


if __name__ == "__main__":
    main()
