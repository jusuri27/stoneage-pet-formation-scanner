"""
월드 리그전 랭킹 목록에서 "N위" 글자를 찾아 클릭 -> 펫 편성 화면 스크린샷 저장을
RANK_RANGE 범위(기본 4위~100위) 전체에 대해 반복하는 스크립트.

동작 방식
---------
1. PC에 떠 있는 에뮬레이터(블루스택/LD플레이어 등) 창을 이름으로 찾는다.
2. 그 창 영역만 스크린샷으로 캡처하고 Tesseract OCR로 텍스트와 위치를 읽어온다.
3. "N위" 형태의 텍스트 중 아직 처리 안 한 TARGET_RANKS 항목을 화면에서 찾으면:
   a. 그 위치를 클릭 -> 펫 편성 화면이 뜰 때까지 대기
   b. 화면을 캡처해서 screenshots/rank_N.png 로 저장
   c. ESC 를 눌러 목록으로 복귀 -> 대기 후 2번부터 다시 반복 (스크롤 없이 같은 화면 먼저 확인)
4. 화면에서 못 찾으면 목록을 살짝 스크롤(드래그)하고 2번부터 반복한다.
5. TARGET_RANKS 를 모두 처리했거나 최대 스크롤 횟수에 도달하면 종료한다.

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

# 클릭할 순위 범위 (시작, 끝) 양쪽 다 포함. 예: (4, 100) -> 4위~100위.
RANK_RANGE = (4, 100)

# TARGET_RANKS 는 RANK_RANGE 로부터 자동 생성된다. "N위" 형태의 텍스트와 정확히
# 일치해야 매칭되므로 직접 수정하지 말고 RANK_RANGE 를 바꿀 것.
TARGET_RANKS = [f"{n}위" for n in range(RANK_RANGE[0], RANK_RANGE[1] + 1)]

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

# 순위 텍스트 클릭 후 펫 편성 화면이 다 뜰 때까지 대기 시간(초)
WAIT_AFTER_CLICK = 1.5

# 스크린샷 저장 후 ESC 눌러 목록으로 돌아왔을 때, 목록이 다시 안정될 때까지 대기 시간(초)
WAIT_AFTER_ESC = 0.8

# 펫 편성 화면 스크린샷을 저장할 폴더. 기존 rank_1.png 등이 있는 프로젝트 루트의 screenshots/ 사용.
SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")

# 스크롤 방식: "drag"(마우스 드래그로 스와이프) 또는 "wheel"(마우스 휠)
SCROLL_METHOD = "drag"

# 한 번에 스크롤할 픽셀 양(작게 조금씩 내리고 싶다면 값을 작게)
SCROLL_PIXELS = 150

# 스크롤 후 화면이 안정될 때까지 대기 시간(초)
SCROLL_WAIT = 0.8

# 목표 순위를 다 못 찾았을 때 최대 몇 번까지 스크롤을 반복할지.
# 4~100위(97개)를 다 훑어야 하므로 넉넉하게 잡는다. 화면에 한 번에 여러 순위가 보이고
# 스크롤 한 번에 여러 줄씩 넘어가는 걸 감안한 값이라, 실제로 부족하면 늘려서 재실행하면 된다.
MAX_SCROLLS = 60

# "gap" 재시도: 방금 처리한 순위(예: 6위)보다 작은 번호(예: 4위, 5위)가 아직 안 끝났다면,
# 화면을 지나쳐서 놓친 게 아니라 그 화면에서 OCR이 그 줄을 못 읽은 것으로 판단하고
# 위로 살짝 스크롤해서 다시 찾는다. 이때 최대 몇 번까지 위로 스크롤하며 재시도할지.
GAP_RETRY_SCROLLS = 3

# gap 재시도용 위로 스크롤은 관성(플링)으로 과하게 튀지 않도록, 짧은 거리를 여러 단계로
# 나눠 천천히 움직이다 멈춘 채로 잠깐 대기한 뒤 뗀다. 그 이동 거리(픽셀).
GAP_RETRY_SCROLL_PIXELS = 100

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


def parse_rank_number(text: str) -> int | None:
    """"8위" 같은 텍스트에서 순위 숫자만 뽑아낸다. 형식이 안 맞으면 None."""
    m = RANK_PATTERN.match(text)
    return int(m.group(1)) if m else None


def is_point_in_window(win, x: int, y: int) -> bool:
    """클릭하려는 좌표가 창 범위 안에 있는지 확인.
    OCR 좌표 계산이 잘못돼서 창 밖 좌표가 나오면 실수로 다른 창을 클릭하지 않도록 막는다."""
    return win.left <= x <= win.left + win.width and win.top <= y <= win.top + win.height


def save_rank_screenshot(win, rank_num: int) -> bool:
    """현재 화면(펫 편성 화면)을 캡처해서 screenshots/rank_N.png 로 저장.
    저장에 실패해도 전체 스크립트가 멈추지 않도록 예외를 여기서 잡고 성공 여부만 반환한다."""
    try:
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        image = capture_window(win)
        path = os.path.join(SCREENSHOTS_DIR, f"rank_{rank_num}.png")
        image.save(path)
        print(f"  -> 스크린샷 저장: {path}")
        return True
    except OSError as e:
        print(f"  [오류] {rank_num}위 스크린샷 저장 실패: {e}")
        return False


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


def scroll_up(win) -> None:
    """gap 재시도용으로 목록을 아주 살짝 위로 되돌린다.
    scroll_down 처럼 한 번에 빠르게 드래그하면 모바일 UI 특유의 관성(플링) 때문에
    의도한 것보다 훨씬 많이 튕겨서, 놓친 줄을 다시 지나쳐버릴 수 있다. 그래서 여기서는
    짧은 거리를 여러 단계로 나눠 천천히 이동하고, 마지막에 멈춘 채로 잠깐 대기했다가
    손을 떼서 관성이 거의 붙지 않게 한다."""
    cx = win.left + win.width // 2
    cy_start = win.top + int(win.height * 0.4)
    steps = 6

    pyautogui.moveTo(cx, cy_start, duration=0.1)
    pyautogui.mouseDown()
    for i in range(1, steps + 1):
        y = cy_start + int(GAP_RETRY_SCROLL_PIXELS * i / steps)
        pyautogui.moveTo(cx, y, duration=0.05)
    time.sleep(0.15)  # 움직임을 멈춘 채로 대기 -> 관성(플링) 방지
    pyautogui.mouseUp()

    time.sleep(SCROLL_WAIT)


def process_match(win, box: TextBox, remaining: list[str], done: set[str], failed: set[str]) -> int | None:
    """OCR로 찾은 "N위" 박스 하나를 실제로 처리한다: 좌표 검증 -> 클릭 -> 펫 편성 화면
    로딩 대기 -> 스크린샷 저장 -> ESC로 목록 복귀. remaining/done/failed 를 제자리에서 갱신하고,
    처리한 순위 숫자를 반환한다(좌표가 비정상이면 None)."""
    rank_num = parse_rank_number(box.text)
    x, y = box.center

    if rank_num is None or not is_point_in_window(win, x, y):
        print(f'  [오류] "{box.text}" 클릭 좌표가 비정상적이라 건너뜀: ({x}, {y})')
        remaining.remove(box.text)
        failed.add(box.text)
        return None

    print(f'  -> "{box.text}" 클릭 (좌표: {x}, {y})')
    if DRY_RUN:
        done.add(box.text)
    else:
        try:
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click()
            time.sleep(WAIT_AFTER_CLICK)  # 펫 편성 화면 로딩 대기

            if save_rank_screenshot(win, rank_num):
                done.add(box.text)
            else:
                failed.add(box.text)

            pyautogui.press("esc")
            time.sleep(WAIT_AFTER_ESC)  # 목록 화면 복귀 대기
        except Exception as e:
            print(f'  [오류] "{box.text}" 처리 중 문제 발생: {e}')
            failed.add(box.text)

    remaining.remove(box.text)
    return rank_num


def retry_missing_smaller_ranks(win, rank_num: int, remaining: list[str], done: set[str], failed: set[str]) -> None:
    """방금 rank_num 을 화면에서 찾아 처리했는데 그보다 작은 번호가 아직 remaining 에 남아있다면,
    화면을 이미 지나쳤어야 할 순위를 OCR이 놓친 것으로 보고 위로 살짝 스크롤하며 다시 찾는다.
    (뒷 순위는 인식했는데 앞 순위를 못 찾았다는 건 화면을 건너뛴 게 아니라 그 줄의 OCR
    인식 실패일 가능성이 높다는 판단에 따른 것)"""
    missing_smaller = sorted(n for n in map(parse_rank_number, remaining) if n is not None and n < rank_num)
    if not missing_smaller:
        return

    print(f"  [gap] {rank_num}위보다 작은 미완료 순위 발견: {missing_smaller} -> 위로 스크롤하며 재탐색")
    target_texts = {f"{n}위" for n in missing_smaller}

    for attempt in range(1, GAP_RETRY_SCROLLS + 1):
        try:
            scroll_up(win)
            image = capture_window(win)
        except Exception as e:
            print(f"  [오류] gap 재시도 중 문제 발생: {e}")
            break

        boxes = extract_rank_boxes(image, win.left, win.top)
        print(f"  [gap 재시도 {attempt}/{GAP_RETRY_SCROLLS}] OCR로 찾은 'N위' 텍스트: {[b.text for b in boxes]}")

        for box in boxes:
            if box.text in target_texts and box.text in remaining:
                process_match(win, box, remaining, done, failed)
                target_texts.discard(box.text)

        if not target_texts:
            print("  [gap] 놓친 순위 재탐색 성공")
            break
    else:
        print(f"  [gap] {GAP_RETRY_SCROLLS}번 재시도했지만 여전히 못 찾음: "
              f"{sorted(target_texts, key=parse_rank_number)}")


def main() -> None:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    if TESSDATA_DIR:
        os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR

    try:
        win = find_emulator_window(WINDOW_TITLE)
    except Exception as e:
        print(f"[오류] 에뮬레이터 창을 찾는 중 문제 발생: {e}")
        return
    print(f'대상 창: "{win.title}" ({win.left},{win.top} {win.width}x{win.height})')

    remaining = list(TARGET_RANKS)
    done: set[str] = set()
    failed: set[str] = set()  # 좌표 이상/스크린샷 저장 실패 등으로 건너뛴 순위

    scroll_attempt = 0
    while remaining and scroll_attempt <= MAX_SCROLLS:
        try:
            image = capture_window(win)
        except Exception as e:
            print(f"[오류] 화면 캡처 실패: {e}")
            break

        boxes = extract_rank_boxes(image, win.left, win.top)
        print(f"[스크롤 {scroll_attempt}] OCR로 찾은 'N위' 텍스트: {[b.text for b in boxes]}")

        # 화면에 보이는 목표 중 하나만 골라 처리한다. 클릭 한 번에 화면이 통째로 바뀌므로
        # 이전에 계산해둔 다른 박스 좌표는 더 이상 신뢰할 수 없다 -> 처리 후 매번 재캡처.
        match = next((b for b in boxes if b.text in remaining), None)

        if match is not None:
            rank_num = process_match(win, match, remaining, done, failed)
            if rank_num is not None:
                retry_missing_smaller_ranks(win, rank_num, remaining, done, failed)
            continue  # 스크롤 없이 같은 화면에서 남은 목표를 이어서 탐색

        # 이번 화면에서 못 찾았으면 스크롤해서 다음 화면으로
        scroll_attempt += 1
        if scroll_attempt <= MAX_SCROLLS:
            print(f"  이 화면에는 없음 -> 스크롤 후 재탐색 ({scroll_attempt}/{MAX_SCROLLS})")
            try:
                scroll_down(win)
            except Exception as e:
                print(f"[오류] 스크롤 실패: {e}")
                break

    print(f"\n완료: {len(done)}개, 실패: {len(failed)}개, 못 찾음: {len(remaining)}개")
    if failed:
        print(f"  실패 목록: {sorted(failed, key=parse_rank_number)}")
    if remaining:
        print(f"  못 찾은 목록: {remaining}")


if __name__ == "__main__":
    main()
