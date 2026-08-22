"""
click_ranks2.py 가 저장해둔 screenshots/rank_{순위}_{격자클릭순번}_{조련사이름}.png
스크린샷들을 pets/ 폴더의 펫 참조 이미지와 매칭해서, 순위별 편성 데이터를 JSON으로
만드는 스크립트.

[조련사 이름]
파일명(rank_N_idx_조련사이름.png)에 click_ranks2.py가 초상화 매칭으로 이미 확정해둔
이름이 있으므로 다시 매칭하지 않고 그대로 쓴다. 격자클릭순번(idx) 오름차순이 그대로
JSON의 position(1~6)이 된다.

[펫 매칭 방식]
스크린샷 하단 "파티" 영역의 카드 3칸을 고정 픽셀 좌표(ICON_BOXES)로 잘라내서 pets/
폴더 이미지와 OpenCV 템플릿 매칭(cv2.matchTemplate)으로 비교한다. 조련사 초상화
매칭(assets/)과 달리 펫 카드는 캡처 시점마다 스케일이 살짝 다를 수 있어서, 배율을
PET_MATCH_SCALES 범위에서 바꿔가며 제일 점수 높은 경우를 찾는다.

pets/ 폴더에는 같은 펫이 기존 이름과 "이름2" 형태의 신규 버전으로 둘 다 있는 경우가
있는데, 실측해보니 어느 한쪽이 항상 더 정확하지는 않고 펫마다 달랐다(예: 구루마루는
신규가 더 정확했지만 아이스만모는 기존이 더 정확했음). 그래서 이름 뒤 "2"는 다른
펫이 아니라 같은 펫의 다른 참조 이미지로 취급해서, 매칭 시 두 버전을 모두 시도하고
더 높은 점수를 쓴다.

카드 3칸 중 어떤 참조 이미지와도 PET_MATCH_THRESHOLD 이상 매칭되지 않으면 "unknown"
으로 저장한다(아직 pets/에 해당 펫 참조 이미지가 없거나 인식이 안 되는 경우).
"""

from __future__ import annotations

import glob
import json
import os
import re

import cv2
import numpy as np

# ============================== 설정 ==============================

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCREENSHOTS_DIR = os.path.join(_PROJECT_ROOT, "screenshots")
PETS_DIR = os.path.join(_PROJECT_ROOT, "pets")
OUTPUT_JSON_PATH = os.path.join(_PROJECT_ROOT, "formation_data.json")

# 처리할 리더보드 순위 범위(포함). screenshots/ 에 실제로 있는 순위에 맞게 조절해서 쓴다.
RANK_START = 1
RANK_END = 13

# 파티 카드 3칸의 고정 픽셀 좌표(x1, y1, x2, y2). screenshots 해상도(600x1030) 기준으로,
# rank_1_1_lucy.png 등 실제 스크린샷에서 카드 테두리를 눈으로 확인해 잡은 값이다.
# 모든 스크린샷이 같은 위치에서 캡처된 동일 레이아웃이라 순위/조련사와 상관없이 고정.
ICON_BOXES: list[tuple[int, int, int, int]] = [
    (262, 751, 325, 820),
    (331, 751, 394, 820),
    (400, 751, 464, 820),
]

# 펫 템플릿 매칭 점수(0~1)가 이 값 이상이어야 그 펫으로 확정한다.
PET_MATCH_THRESHOLD = 0.8

# 펫 카드 매칭 시 템플릿을 리사이즈해볼 배율 목록(80%~120%, 5% 단위).
PET_MATCH_SCALES = [x / 100 for x in range(80, 125, 5)]

# ====================================================================


def imread_unicode(path: str, flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    """한글이 포함된 경로의 이미지를 읽는다.
    cv2.imread는 Windows에서 비ASCII 경로를 제대로 못 읽는 경우가 있어서, 파일을
    바이트로 먼저 읽은 뒤 cv2.imdecode로 디코딩하는 방식을 쓴다. 파일이 없거나
    이미지가 아니면 예외를 올려서 호출부가 처리하게 한다."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError as e:
        raise FileNotFoundError(f"이미지 파일을 읽을 수 없음: {path} ({e})") from e

    img = cv2.imdecode(data, flags)
    if img is None:
        raise FileNotFoundError(f"이미지 디코딩 실패(손상됐거나 이미지 형식이 아님): {path}")
    return img


def load_pet_templates(pet_dir: str) -> dict[str, list[np.ndarray]]:
    """pets/ 폴더의 모든 이미지를 불러와 {펫 이름: 후보 이미지 목록} 으로 반환한다.
    main() 시작 시 한 번만 불러와 재사용한다. 이름 끝이 "2"이고 원본 이름(예:
    디어룬2.png -> 디어룬.png)도 폴더에 있으면 같은 펫의 다른 버전으로 보고 같은
    이름 아래 후보로 묶는다. 폴더가 없거나 이미지를 하나도 못 읽으면 이후 매칭이
    전부 무의미해지므로 예외를 그대로 올린다."""
    if not os.path.isdir(pet_dir):
        raise FileNotFoundError(f"pets 폴더를 찾을 수 없음: {pet_dir}")

    all_names = {f[:-4] for f in os.listdir(pet_dir) if f.lower().endswith(".png")}

    templates: dict[str, list[np.ndarray]] = {}
    for fname in sorted(os.listdir(pet_dir)):
        if not fname.lower().endswith(".png"):
            continue
        stem = fname[:-4]
        canonical = stem[:-1] if stem.endswith("2") and stem[:-1] in all_names else stem
        try:
            img = imread_unicode(os.path.join(pet_dir, fname))
        except FileNotFoundError as e:
            print(f"  [경고] 펫 참조 이미지 로드 실패, 건너뜀: {e}")
            continue
        templates.setdefault(canonical, []).append(img)

    if not templates:
        raise FileNotFoundError(f"pets 폴더에 유효한 png 이미지가 하나도 없음: {pet_dir}")
    return templates


def match_pet_name(icon: np.ndarray, templates: dict[str, list[np.ndarray]]) -> tuple[str, float]:
    """카드 이미지 하나(icon)를 pets 템플릿 전체와 비교해서 가장 점수 높은 펫 이름을
    찾는다. 이름당 후보 이미지(기존/신규 버전)가 여러 개면 그중 최고 점수만 쓴다.
    최고 점수가 PET_MATCH_THRESHOLD 미만이면(확신할 수 없으면) "unknown"을 반환해
    호출부가 매칭 실패로 처리하게 한다."""
    best_name, best_score = "unknown", -1.0
    for name, candidate_imgs in templates.items():
        for pet_img in candidate_imgs:
            ph, pw = pet_img.shape[:2]
            for scale in PET_MATCH_SCALES:
                rw, rh = int(pw * scale), int(ph * scale)
                if rw < 8 or rh < 8 or rw >= icon.shape[1] or rh >= icon.shape[0]:
                    continue
                resized = cv2.resize(pet_img, (rw, rh))
                result = cv2.matchTemplate(icon, resized, cv2.TM_CCOEFF_NORMED)
                _, score, _, _ = cv2.minMaxLoc(result)
                if score > best_score:
                    best_name, best_score = name, score

    if best_score < PET_MATCH_THRESHOLD:
        return "unknown", best_score
    return best_name, best_score


def find_rank_screenshot_files(rank_num: int) -> list[tuple[int, str]]:
    """이번 순위(rank_num)의 격자 클릭 스크린샷 파일들을 (격자클릭순번idx, 경로) 쌍으로,
    idx 오름차순 정렬해서 반환한다. idx는 파일명에 그대로 남아있는 실제 격자 클릭
    순번(1~25)이며, JSON의 position 값으로도 그대로 쓰인다. 파일명이
    rank_{순위}_{idx}_{이름}.png 형식이 아니면(예: 순위 원본 rank_N.png) 제외한다."""
    pattern = os.path.join(SCREENSHOTS_DIR, f"rank_{rank_num}_*_*.png")
    idx_pattern = re.compile(rf"rank_{rank_num}_(\d+)_.+\.png$")

    files_with_idx: list[tuple[int, str]] = []
    for path in glob.glob(pattern):
        m = idx_pattern.search(os.path.basename(path))
        if m:
            files_with_idx.append((int(m.group(1)), path))

    files_with_idx.sort(key=lambda pair: pair[0])
    return files_with_idx


def extract_trainer_name(path: str) -> str | None:
    """파일명(rank_{순위}_{idx}_{조련사이름}.png)에서 조련사 이름을 뽑아낸다.
    click_ranks2.py가 초상화 매칭으로 이미 확정해둔 값이라 다시 매칭하지 않고 그대로
    쓴다. 형식이 예상과 다르면 None을 반환해 호출부가 그 파일을 건너뛰게 한다."""
    m = re.search(r"rank_\d+_\d+_(.+)\.png$", os.path.basename(path))
    return m.group(1) if m else None


def build_rank_entry(
    rank_num: int,
    templates: dict[str, list[np.ndarray]],
    failure_log: list[str],
) -> dict | None:
    """순위 하나(rank_num)의 격자 클릭 스크린샷들을 전부 읽어서 groups 배열을 만든다.
    파일이 하나도 없으면 None을 반환해 호출부가 이 순위를 건너뛰게 한다. 정확히
    6개가 아니어도(촬영이 덜 됐거나 예외 상황) 있는 만큼만 처리하고 경고를 남긴다.
    한 파일 처리가 실패해도(읽기/매칭 실패 등) 나머지 파일은 계속 처리한다.
    매칭 성공 로그는 바로 출력하지만, 실패(unknown) 로그는 진행 중 로그에 섞이면
    나중에 찾기 어려워서 failure_log 에 모아두고 main() 이 전체 작업이 끝난 뒤 한
    번에 모아서 출력하게 한다."""
    files = find_rank_screenshot_files(rank_num)
    if not files:
        print(f"[경고] {rank_num}위 스크린샷 파일을 찾을 수 없음 -> 건너뜀")
        return None
    if len(files) != 6:
        print(f"[경고] {rank_num}위 스크린샷이 6개가 아니라 {len(files)}개 -> 있는 만큼만 처리")

    groups = []
    for position, path in files:  # position은 파일명의 실제 격자 클릭 순번(idx) 그대로
        trainer = extract_trainer_name(path)
        if trainer is None:
            print(f"  [오류] {rank_num}위 파일명 형식이 예상과 달라 건너뜀: {path}")
            continue

        try:
            screenshot = imread_unicode(path)
            pet_names = []
            for (x1, y1, x2, y2) in ICON_BOXES:
                icon = screenshot[y1:y2, x1:x2]
                name, score = match_pet_name(icon, templates)
                pet_names.append(name)
                if name == "unknown":
                    failure_log.append(f"[경고] {rank_num}위 {trainer} 카드 매칭 실패"
                                        f"(최고 점수 {score:.3f}) -> unknown")
                else:
                    print(f"  [성공] {rank_num}위 {trainer} 카드 매칭 성공"
                          f"(최고 점수 {score:.3f}) -> {name}")
        except Exception as e:
            print(f"  [오류] {rank_num}위 {trainer} 스크린샷 처리 중 문제 발생: {e}")
            continue

        groups.append({
            "position": position,
            "trainer": trainer,
            "pet1": pet_names[0],
            "pet2": pet_names[1],
            "pet3": pet_names[2],
        })

    return {"rank": rank_num, "groups": groups}


def main() -> None:
    try:
        templates = load_pet_templates(PETS_DIR)
    except Exception as e:
        print(f"[오류] 펫 참조 이미지를 불러오는 중 문제 발생: {e}")
        return

    rankings = []
    failure_log: list[str] = []  # 매칭 실패(unknown) 로그를 모아뒀다가 마지막에 한 번에 출력
    for rank_num in range(RANK_START, RANK_END + 1):
        entry = build_rank_entry(rank_num, templates, failure_log)
        if entry is not None:
            rankings.append(entry)

    result = {"rankings": rankings}
    try:
        with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n완료. {len(rankings)}개 순위를 {OUTPUT_JSON_PATH} 에 저장했습니다.")
    except OSError as e:
        print(f"[오류] JSON 저장 실패: {e}")

    if failure_log:
        print(f"\n=== 매칭 실패 목록 ({len(failure_log)}건) ===")
        for line in failure_log:
            print(line)


if __name__ == "__main__":
    main()
