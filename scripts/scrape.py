import csv
import io
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.json"
PROFILES_FILE = BASE_DIR / "profiles.json"
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = DATA_DIR / "leaderboard.json"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def clean_cell(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def find_header_index(headers, candidates):
    normalized_headers = [normalize(h) for h in headers]

    for candidate in candidates:
        candidate_norm = normalize(candidate)
        for idx, header in enumerate(normalized_headers):
            if candidate_norm == header:
                return idx

    for candidate in candidates:
        candidate_norm = normalize(candidate)
        for idx, header in enumerate(normalized_headers):
            if candidate_norm in header:
                return idx

    return None


def is_probably_course_title(value: str) -> bool:
    value = clean_cell(value)

    if not value:
        return False

    low = normalize(value)

    blocked_keywords = [
        "구글 클라우드 스터디 잼",
        "주의 사항",
        "google skills",
        "학습 포인트",
        "이용 방법",
        "키워드",
        "주요 학습 내용",
        "나에게 딱 맞는",
        "직접 검색",
        "gemini 활용",
        "level",
        "difficulty",
        "난이도",
        "카테고리",
        "category",
        "badge",
        "skill badge",
        "completion badge",
    ]

    if any(keyword in low for keyword in blocked_keywords):
        return False

    if len(value) < 4:
        return False

    if len(value) > 140:
        return False

    if not re.search(r"[A-Za-z]", value):
        return False

    return True


def detect_skill_badge(row_text: str) -> bool:
    text = normalize(row_text)

    return (
        "skill badge" in text
        or "skills badge" in text
        or "스킬 배지" in text
        or "스킬뱃지" in text
        or "스킬뱃" in text
    )


def detect_completion_badge(row_text: str) -> bool:
    text = normalize(row_text)

    return (
        "completion badge" in text
        or ("completion" in text and "badge" in text)
        or "수료 배지" in text
        or "수료뱃지" in text
    )


def fetch_sheet_csv(spreadsheet_id: str, sheet_name: str):
    encoded_sheet_name = quote(sheet_name)

    url = (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq"
        f"?tqx=out:csv&sheet={encoded_sheet_name}"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GoogleSkillsLeaderboard/1.0)"
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    content = response.content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(content))

    return list(reader)


def extract_courses_from_rows(sheet_name: str, rows):
    courses = []

    if not rows:
        return courses

    header_row_index = None
    title_idx = None
    level_idx = None
    badge_idx = None
    category_idx = None

    for i, row in enumerate(rows[:30]):
        headers = [clean_cell(c) for c in row]

        possible_title_idx = find_header_index(
            headers,
            [
                "과정명",
                "콘텐츠명",
                "학습 콘텐츠",
                "코스명",
                "Course",
                "Course Name",
                "Content",
                "Title",
                "Module",
            ],
        )

        if possible_title_idx is not None:
            header_row_index = i
            title_idx = possible_title_idx
            level_idx = find_header_index(headers, ["난이도", "Level", "Difficulty"])
            badge_idx = find_header_index(headers, ["Badge", "배지", "Type", "구분"])
            category_idx = find_header_index(headers, ["Category", "카테고리", "Keyword", "키워드"])
            break

    if header_row_index is not None and title_idx is not None:
        for row in rows[header_row_index + 1:]:
            if title_idx >= len(row):
                continue

            title = clean_cell(row[title_idx])

            if not is_probably_course_title(title):
                continue

            row_text = " ".join(clean_cell(c) for c in row)

            level = ""
            if level_idx is not None and level_idx < len(row):
                level = clean_cell(row[level_idx])

            badge_text = ""
            if badge_idx is not None and badge_idx < len(row):
                badge_text = clean_cell(row[badge_idx])

            category = ""
            if category_idx is not None and category_idx < len(row):
                category = clean_cell(row[category_idx])

            courses.append({
                "title": title,
                "level": level,
                "category": category or sheet_name,
                "sheet": sheet_name,
                "isSkillBadge": detect_skill_badge(row_text) or detect_skill_badge(badge_text),
                "isCompletionBadge": detect_completion_badge(row_text) or detect_completion_badge(badge_text)
            })

        return courses

    for row in rows:
        cells = [clean_cell(c) for c in row]
        row_text = " ".join(cells)

        candidate_title = ""

        for cell in cells:
            if is_probably_course_title(cell):
                candidate_title = cell
                break

        if not candidate_title:
            continue

        level = ""
        for cell in cells:
            if cell in ["초급", "중급", "상급"]:
                level = cell
                break

        courses.append({
            "title": candidate_title,
            "level": level,
            "category": sheet_name,
            "sheet": sheet_name,
            "isSkillBadge": detect_skill_badge(row_text),
            "isCompletionBadge": detect_completion_badge(row_text)
        })

    return courses


def load_courses_from_google_sheet(config):
    spreadsheet_id = config["spreadsheetId"]
    target_sheets = config["targetSheets"]

    all_courses = []
    seen = set()

    for sheet_name in target_sheets:
        print(f"Loading sheet: {sheet_name}")

        rows = fetch_sheet_csv(spreadsheet_id, sheet_name)
        courses = extract_courses_from_rows(sheet_name, rows)

        print(f"  found courses: {len(courses)}")

        for course in courses:
            key = normalize(course["title"])

            if key in seen:
                continue

            seen.add(key)
            all_courses.append(course)

        time.sleep(0.5)

    return all_courses


def extract_profile(url: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GoogleSkillsLeaderboard/1.0)"
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    name = "Unknown"
    league = ""
    points = 0
    earned_items = []

    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(" ", strip=True)

    for line in lines:
        if "League" in line:
            league = line.strip()

        points_match = re.search(r"([\d,]+)\s+points", line, re.IGNORECASE)
        if points_match:
            points = int(points_match.group(1).replace(",", ""))

    for line in lines:
        if " Earned " in line:
            match = re.match(r"^(.*?)\s+Earned\s+(.+)$", line)
            if match:
                title = match.group(1).strip()
                earned_date = match.group(2).strip()

                if title:
                    earned_items.append({
                        "title": title,
                        "earnedDate": earned_date
                    })

    return {
        "name": name,
        "url": url,
        "league": league,
        "points": points,
        "earnedItems": earned_items
    }


def main():
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    profiles = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))

    courses = load_courses_from_google_sheet(config)

    total_courses = len(courses)
    total_skill_badges = sum(1 for c in courses if c["isSkillBadge"])
    total_completion_badges = sum(1 for c in courses if c["isCompletionBadge"])
    total_normal_courses = total_courses - total_skill_badges

    results = []

    for profile in profiles:
        try:
            print(f"Loading profile: {profile['url']}")

            raw = extract_profile(profile["url"])

            earned_titles = {
                normalize(item["title"]): item
                for item in raw["earnedItems"]
            }

            course_status = []
            completed_count = 0
            completed_skill_badge_count = 0
            completed_completion_badge_count = 0
            completed_normal_count = 0

            for course in courses:
                key = normalize(course["title"])
                completed = key in earned_titles

                if completed:
                    completed_count += 1

                    if course["isSkillBadge"]:
                        completed_skill_badge_count += 1
                    else:
                        completed_normal_count += 1

                    if course["isCompletionBadge"]:
                        completed_completion_badge_count += 1

                course_status.append({
                    "title": course["title"],
                    "level": course["level"],
                    "category": course["category"],
                    "sheet": course["sheet"],
                    "isSkillBadge": course["isSkillBadge"],
                    "isCompletionBadge": course["isCompletionBadge"],
                    "completed": completed,
                    "earnedDate": earned_titles[key]["earnedDate"] if completed else None
                })

            completion_rate = 0
            if total_courses > 0:
                completion_rate = round(completed_count / total_courses * 100, 1)

            results.append({
                "id": profile["id"],
                "name": raw["name"],
                "url": raw["url"],
                "league": raw["league"],
                "points": raw["points"],
                "completedCount": completed_count,
                "totalCount": total_courses,
                "completedNormalCount": completed_normal_count,
                "totalNormalCount": total_normal_courses,
                "completedSkillBadgeCount": completed_skill_badge_count,
                "totalSkillBadgeCount": total_skill_badges,
                "completedCompletionBadgeCount": completed_completion_badge_count,
                "totalCompletionBadgeCount": total_completion_badges,
                "completionRate": completion_rate,
                "courses": course_status,
                "allEarnedItems": raw["earnedItems"]
            })

            time.sleep(1)

        except Exception as e:
            results.append({
                "id": profile["id"],
                "name": "수집 실패",
                "url": profile["url"],
                "error": str(e),
                "completedCount": 0,
                "totalCount": total_courses,
                "completedNormalCount": 0,
                "totalNormalCount": total_normal_courses,
                "completedSkillBadgeCount": 0,
                "totalSkillBadgeCount": total_skill_badges,
                "completedCompletionBadgeCount": 0,
                "totalCompletionBadgeCount": total_completion_badges,
                "completionRate": 0,
                "courses": []
            })

    results.sort(
        key=lambda x: (
            x.get("completedCount", 0),
            x.get("completedSkillBadgeCount", 0),
            x.get("points", 0)
        ),
        reverse=True
    )

    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "spreadsheetId": config["spreadsheetId"],
        "totalCourses": total_courses,
        "totalNormalCourses": total_normal_courses,
        "totalSkillBadges": total_skill_badges,
        "totalCompletionBadges": total_completion_badges,
        "courses": courses,
        "students": results
    }

    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Loaded courses: {total_courses}")
    print(f"Skill Badges: {total_skill_badges}")
    print(f"Completion Badges: {total_completion_badges}")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
