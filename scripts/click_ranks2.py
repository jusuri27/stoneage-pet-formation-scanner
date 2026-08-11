"""
click_ranks.py 는 화면을 캡처할 때마다 OCR로 "N위" 텍스트를 찾아 클릭하는 방식이라,
OCR 한 번에 ~1.9초가 걸리고 화면 상태에 따라 인식이 실패하는 경우도 있어서 느리고 불안정함
(gap 재시도 기능까지 넣어야 했음).

이 스크립트는 OCR을 아예 쓰지 않는 다른 접근을 쓴다: 랭킹 목록 화면의 레이아웃이 항상
일정하다는 점을 이용해, 미리 정해둔 좌표를 그대로 클릭한다. click_ranks.py 와 독립적으로
동작하도록 필요한 함수를 이 파일 안에 그대로 둔다(공용 모듈 import 안 함).

[지금까지 구현한 범위]
1~7위는 스크롤 없이 화면에 보이는 상태이므로, 각각 미리 정해둔 좌표를 순서대로 클릭
-> 펫 편성 화면 로딩 대기 -> 스크린샷 저장(screenshots/rank_N.png) -> ESC로 목록 복귀.
(8위 이후 스크롤 로직은 다음 단계에서 추가 예정)

좌표 출처
--------
example/example_image.png(557x993)를 OCR로 한 번 분석해서 "N위" 텍스트 위치를 뽑아낸 뒤,
화면 크기에 상관없이 쓸 수 있도록 (0~1 사이) 비율 좌표로 저장해뒀다. 실행할 때 실제 창
크기(win.width, win.height)를 곱해서 절대 좌표로 변환한다.

*** 주의 ***
- 좌표 검증(OCR 등으로 확인) 없이 순수 좌표만으로 클릭한다.
- example_image.png(557x993)와 실제 LDPlayer 캡처 창(보통 600x1030)은 가로세로 비율이
  완전히 같지는 않아서, 비율 좌표로 변환해도 약간의 오차가 있을 수 있다. 실행 후 결과를
  보고 좌표가 실제로 맞는지 눈으로 확인해볼 것을 권장.

*** ESC 확인용 템플릿 매칭 ***
- 렉 등으로 ESC 입력이 씹혀서 펫 편성 화면에 그대로 머무는 경우가 있어, ESC를 누른 뒤
  펫 편성 화면에만 보이는 배경 조각(example/check.png, 왼쪽 돌담)이 화면에 여전히 있는지
  OpenCV 템플릿 매칭(cv2.matchTemplate)으로 확인한다. OCR이 아니라 이미지 매칭이라 이
  파일의 "OCR 안 씀" 설계 원칙과도 어긋나지 않고, 작은 템플릿이라 매우 빠르다.
- check.png 도 example_image.png(557x993)와 같은 해상도에서 잘라낸 것이라, 실제 LDPlayer
  창 해상도가 다르면(보통 600x1030) 벽돌 무늬 크기가 살짝 달라 매칭 점수가 낮게 나올 수
  있다. CHECK_MATCH_THRESHOLD 로 조정.
"""

from __future__ import annotations

import os
import sys
import time

import cv2
import numpy as np
import pyautogui
import pygetwindow as gw
from PIL import Image

# ============================== 설정 ==============================

# 에뮬레이터 창 제목에 포함된 문자열(일부만 맞아도 됨). 대소문자 구분 없음.
WINDOW_TITLE = "LDPlayer(64)"

# 펫 편성 화면 스크린샷을 저장할 폴더. 기존 rank_1.png 등이 있는 프로젝트 루트의 screenshots/ 사용.
SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")

# ESC 재시도(템플릿 매칭으로 "아직 편성 화면"이라고 판단된 경우)가 발생했을 때, 그 순간의
# 화면을 남겨두는 디버그용 폴더. threshold 튜닝/오탐 확인용.
DEBUG_SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "debug_screenshots")

# ESC 확인용 템플릿 이미지. 펫 편성 화면에만 보이는 왼쪽 돌담 배경 조각.
CHECK_TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "example", "check.png")

# 템플릿 매칭 점수(0~1, 1이 완전 일치)가 이 값 이상이면 "아직 펫 편성 화면"으로 판단.
CHECK_MATCH_THRESHOLD = 0.8

# ESC가 씹혀서 여전히 펫 편성 화면일 때 다시 눌러볼 최대 횟수.
# 다 써도 안 빠져나오면 강제로 다음 순위로 넘어간다(무한루프 방지).
ESC_RETRY_LIMIT = 3

# 1~7위 클릭 좌표 (창 너비/높이에 대한 비율, 0~1). example_image.png 분석 결과.
RANK_COORDS_FRAC: dict[int, tuple[float, float]] = {
    1: (0.4991, 0.2266),
    2: (0.2029, 0.2266),
    3: (0.7935, 0.2266),
    4: (0.1203, 0.4159),
    5: (0.1203, 0.5146),
    6: (0.1203, 0.6142),
    7: (0.1203, 0.7130),
}

# 고정 좌표로 클릭할 수 있는 마지막 순위. 이 이후(8위~)는 스크롤로 화면을 끌어올려서
# 같은 좌표(LAST_FIXED_RANK 자리)를 재사용해 클릭한다.
LAST_FIXED_RANK = 7

# 목록 한 행(row)의 세로 높이 비율(창 높이 기준). RANK_COORDS_FRAC 의 4~7위 y값 간격
# 평균으로 계산한 기준값(0.09903)에 스크롤이 살짝 부족한 것 같아 여유를 더 준 값.
# 8위 이후 스크롤할 때마다 기본적으로 이 값만큼(창 높이 곱해서) 스크롤한다.
ROW_HEIGHT_FRAC = 0.101

# 매번 조금씩 더 스크롤하다 보면 오차가 누적될 수 있어서, CORRECTION_INTERVAL 번째
# 스크롤마다 한 번씩은 원래 계산값(0.09)으로 되돌려 보정한다.
ROW_HEIGHT_FRAC_CORRECTION = 0.09
CORRECTION_INTERVAL = 20

# 마지막으로 캡처할 순위
LAST_RANK = 100

# 클릭 후 펫 편성 화면이 다 뜰 때까지 대기 시간(초)
WAIT_AFTER_CLICK = 1.8

# ESC로 목록 복귀 후 안정될 때까지 대기 시간(초)
WAIT_AFTER_ESC = 1.1

# 스크롤 후 화면이 안정될 때까지 대기 시간(초)
SCROLL_WAIT = 1.4

# True 로 하면 실제 클릭 없이 어디를 클릭할지 콘솔에만 출력(좌표 확인용)
DRY_RUN = False

# ====================================================================


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


def is_point_in_window(win, x: int, y: int) -> bool:
    """클릭하려는 좌표가 창 범위 안에 있는지 확인.
    좌표 계산이 잘못돼서 창 밖 좌표가 나오면 실수로 다른 창을 클릭하지 않도록 막는다."""
    return win.left <= x <= win.left + win.width and win.top <= y <= win.top + win.height


def load_check_template() -> np.ndarray:
    """ESC 확인용 템플릿 이미지(check.png)를 그레이스케일로 불러온다.
    이 파일을 못 읽으면 이후 모든 ESC 확인이 무의미해지므로, main() 시작 시 한 번만 불러와
    실패하면 스크립트를 시작하기 전에 바로 알 수 있게 한다(매 순위마다 다시 읽지 않음)."""
    template = cv2.imread(CHECK_TEMPLATE_PATH, cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise FileNotFoundError(f"ESC 확인용 템플릿 이미지를 찾을 수 없음: {CHECK_TEMPLATE_PATH}")
    return template


def save_debug_screenshot(image: Image.Image, rank_num: int, attempt: int) -> None:
    """ESC 재시도가 발생한 순간의 화면을 debug_screenshots/rank_N_attemptN.png 로 저장.
    템플릿 매칭이 왜 "아직 편성 화면"이라고 판단했는지(진짜 잔류인지 오탐인지) 나중에 눈으로
    확인할 수 있게 남겨두는 용도. 저장 실패해도 ESC 재시도 흐름 자체는 계속돼야 하므로
    예외를 여기서 잡는다."""
    try:
        os.makedirs(DEBUG_SCREENSHOTS_DIR, exist_ok=True)
        path = os.path.join(DEBUG_SCREENSHOTS_DIR, f"rank_{rank_num}_attempt{attempt}.png")
        image.save(path)
        print(f"    [디버그] 재시도 스크린샷 저장: {path}")
    except OSError as e:
        print(f"    [경고] 디버그 스크린샷 저장 실패: {e}")


def is_still_formation_screen(win, rank_num: int, attempt: int, check_template: np.ndarray) -> bool:
    """ESC를 누른 뒤에도 여전히 펫 편성 화면인지 템플릿 매칭으로 확인한다.
    펫 편성 화면에만 보이는 배경(check_template)이 현재 창 화면 어딘가에서 충분히 높은
    점수로 발견되면 아직 화면 전환이 안 된 것으로 판단한다. 매칭 자체가 실패하면 판단할
    수 없으므로 보수적으로 "아직 편성 화면"으로 취급해 재시도를 유도한다."""
    try:
        screenshot = capture_window(win)
        screen_gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
        result = cv2.matchTemplate(screen_gray, check_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        # CHECK_MATCH_THRESHOLD 값을 튜닝할 때 실제 점수를 봐야 하므로 확인할 때마다 남긴다.
        print(f"    [템플릿 매칭] 점수={max_val:.3f} (threshold={CHECK_MATCH_THRESHOLD})")

        still_formation = max_val >= CHECK_MATCH_THRESHOLD
        if still_formation:
            # 재시도가 필요한(비정상) 경우에만 그 순간 화면을 디버그용으로 남긴다.
            save_debug_screenshot(screenshot, rank_num, attempt)
        return still_formation
    except Exception as e:
        print(f"  [경고] ESC 확인용 템플릿 매칭 실패, 안전하게 재시도 처리: {e}")
        return True


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


def scroll_one_row(win, row_height_frac: float = ROW_HEIGHT_FRAC) -> None:
    """목록을 row_height_frac(창 높이 비율) 만큼 아래로 스크롤한다.
    빠른 드래그는 모바일 UI 특유의 관성(플링) 때문에 스크롤 거리가 매번 달라질 수 있는데,
    이 스크립트는 좌표를 그대로 재사용하는 방식이라 스크롤 거리가 어긋나면 그 이후 모든
    순위가 밀려버린다. 그래서 짧은 거리를 여러 단계로 나눠 천천히 이동하고, 마지막에
    멈춘 채로 잠깐 대기했다가 손을 떼서 관성 없이 최대한 일정하게 움직이도록 한다."""
    cx = win.left + win.width // 2
    cy_top = win.top + int(win.height * 0.6)
    row_px = int(row_height_frac * win.height)
    steps = 6

    pyautogui.moveTo(cx, cy_top, duration=0.1)
    pyautogui.mouseDown()
    for i in range(1, steps + 1):
        y = cy_top - int(row_px * i / steps)
        pyautogui.moveTo(cx, y, duration=0.05)
    time.sleep(0.15)  # 움직임을 멈춘 채로 대기 -> 관성(플링) 방지
    pyautogui.mouseUp()

    time.sleep(SCROLL_WAIT)


def coord_to_pixels(win, x_frac: float, y_frac: float) -> tuple[int, int]:
    """비율 좌표(0~1)를 현재 창 크기 기준 절대 화면 좌표로 변환."""
    x = win.left + round(x_frac * win.width)
    y = win.top + round(y_frac * win.height)
    return x, y


def click_and_capture(win, rank_num: int, x: int, y: int, check_template: np.ndarray) -> bool:
    """좌표를 클릭해서 펫 편성 화면을 캡처/저장하고 ESC로 목록에 복귀한다.
    성공 여부를 반환하며, 실패해도 예외를 여기서 잡아 다음 순위 진행에 지장이 없게 한다."""
    if not is_point_in_window(win, x, y):
        print(f"  [오류] {rank_num}위 클릭 좌표가 창 범위를 벗어남: ({x}, {y})")
        return False

    print(f"  -> {rank_num}위 클릭 (좌표: {x}, {y})")
    if DRY_RUN:
        return True

    try:
        pyautogui.moveTo(x, y, duration=0.2)
        pyautogui.click()
        time.sleep(WAIT_AFTER_CLICK)  # 펫 편성 화면 로딩 대기

        ok = save_rank_screenshot(win, rank_num)

        # ESC를 누른 뒤 실제로 목록 화면으로 돌아왔는지 템플릿 매칭으로 확인한다. 렉 등으로
        # ESC 입력이 씹혀서 편성 화면에 그대로 머무는 경우가 있어, check.png 배경이 여전히
        # 보이면(비정상) 다시 ESC를 눌러 재시도한다.
        for attempt in range(1, ESC_RETRY_LIMIT + 1):
            pyautogui.press("esc")
            time.sleep(WAIT_AFTER_ESC)  # 목록 화면 복귀 대기

            if not is_still_formation_screen(win, rank_num, attempt, check_template):
                break  # 정상: 목록 화면으로 복귀 확인됨

            print(f"  [경고] {rank_num}위 ESC 후에도 편성 화면 감지됨 -> 재시도 "
                  f"({attempt}/{ESC_RETRY_LIMIT})")
        else:
            print(f"  [오류] {rank_num}위 ESC {ESC_RETRY_LIMIT}회 재시도했지만 여전히 "
                  f"편성 화면으로 보임 -> 강제로 다음 순위 진행")

        return ok
    except Exception as e:
        print(f"  [오류] {rank_num}위 처리 중 문제 발생: {e}")
        return False


def main() -> None:
    try:
        check_template = load_check_template()
    except Exception as e:
        print(f"[오류] ESC 확인용 템플릿 이미지를 불러오는 중 문제 발생: {e}")
        return

    try:
        win = find_emulator_window(WINDOW_TITLE)
    except Exception as e:
        print(f"[오류] 에뮬레이터 창을 찾는 중 문제 발생: {e}")
        return
    print(f'대상 창: "{win.title}" ({win.left},{win.top} {win.width}x{win.height})')

    failed: list[int] = []

    # 1~7위: 스크롤 없이 고정 좌표를 순서대로 클릭
    for rank_num in sorted(RANK_COORDS_FRAC):
        x_frac, y_frac = RANK_COORDS_FRAC[rank_num]
        x, y = coord_to_pixels(win, x_frac, y_frac)
        if not click_and_capture(win, rank_num, x, y, check_template):
            failed.append(rank_num)

    # 8위~100위: 매번 한 행씩 스크롤해서 LAST_FIXED_RANK(7위) 자리로 다음 순위를 끌어올린 뒤,
    # 그 좌표를 그대로 재사용해서 클릭. (이전에 클릭했던 7위 위치 + 스크롤 반복)
    x_frac, y_frac = RANK_COORDS_FRAC[LAST_FIXED_RANK]
    for scroll_count, rank_num in enumerate(range(LAST_FIXED_RANK + 1, LAST_RANK + 1), start=1):
        # CORRECTION_INTERVAL 번째 스크롤마다 보정값(ROW_HEIGHT_FRAC_CORRECTION)을 사용해
        # 누적된 오차를 되돌린다.
        if scroll_count % CORRECTION_INTERVAL == 0:
            row_height_frac = ROW_HEIGHT_FRAC_CORRECTION
            print(f"  [보정] {scroll_count}번째 스크롤 -> ROW_HEIGHT_FRAC={row_height_frac}")
        else:
            row_height_frac = ROW_HEIGHT_FRAC

        try:
            scroll_one_row(win, row_height_frac)
        except Exception as e:
            print(f"[오류] {rank_num}위 스크롤 실패: {e}")
            failed.append(rank_num)
            continue

        x, y = coord_to_pixels(win, x_frac, y_frac)
        if not click_and_capture(win, rank_num, x, y, check_template):
            failed.append(rank_num)

    print(f"\n완료. 실패: {len(failed)}개")
    if failed:
        print(f"  실패 목록: {failed}")


if __name__ == "__main__":
    main()
