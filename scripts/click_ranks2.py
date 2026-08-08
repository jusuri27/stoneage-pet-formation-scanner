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
"""

from __future__ import annotations

import os
import sys
import time

import pyautogui
import pygetwindow as gw
from PIL import Image

# ============================== 설정 ==============================

# 에뮬레이터 창 제목에 포함된 문자열(일부만 맞아도 됨). 대소문자 구분 없음.
WINDOW_TITLE = "LDPlayer(64)"

# 펫 편성 화면 스크린샷을 저장할 폴더. 기존 rank_1.png 등이 있는 프로젝트 루트의 screenshots/ 사용.
SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")

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
ROW_HEIGHT_FRAC = 0.104

# 매번 조금씩 더 스크롤하다 보면 오차가 누적될 수 있어서, CORRECTION_INTERVAL 번째
# 스크롤마다 한 번씩은 원래 계산값(0.099)으로 되돌려 보정한다.
ROW_HEIGHT_FRAC_CORRECTION = 0.099
CORRECTION_INTERVAL = 10

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


def click_and_capture(win, rank_num: int, x: int, y: int) -> bool:
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

        pyautogui.press("esc")
        time.sleep(WAIT_AFTER_ESC)  # 목록 화면 복귀 대기
        return ok
    except Exception as e:
        print(f"  [오류] {rank_num}위 처리 중 문제 발생: {e}")
        return False


def main() -> None:
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
        if not click_and_capture(win, rank_num, x, y):
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
        if not click_and_capture(win, rank_num, x, y):
            failed.append(rank_num)

    print(f"\n완료. 실패: {len(failed)}개")
    if failed:
        print(f"  실패 목록: {failed}")


if __name__ == "__main__":
    main()
