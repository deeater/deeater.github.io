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
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def clean_cell(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_probably_course_title(value: str) -> bool:
    value = clean_cell(value)
    low = normalize(value)

    if not value:
        return False

    if len(value) < 4 or len(value) > 160:
        return False

    blocked_keywords = [
        "home",
        "level",
        "difficulty",
        "category",
        "badge",
        "skill badge",
        "completion badge",
        "구글 클라우드 스터디 잼",
        "주의 사항",
        "학습 포인트",
        "이용 방법",
        "키워드",
        "카테고리",
        "난이도",
        "구분"
    ]

    if any(keyword in low for keyword in blocked_keywords):
        return False

    if not re.search(r"[A-Za-z]", value):
        return False

    return True


def detect_badge_type(row_text: str) -> str:
    text = normalize(row_text)

    if "skill badge" in text or "skills badge" in text or "스킬 배지" in text:
        return "Skill Badge"

    if "completion badge" in text or "completion" in text and "badge" in text or "수료 배지" in text:
        return "Badge"

    if "badge" in text or "배지" in text:
        return "Badge"

    return "Course"


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


def extract_courses_from_rows(sheet_name: str, rows):
    courses = []

    if not rows:
        return courses

    header_row_index = None
    title_idx = None
    level_idx = None
    type_idx = None

    for i, row in enumerate(rows[:25]):
        headers = [clean_cell(c) for c in row]

        possible_title_idx = find_header_index(
            headers,
            [
                "Course",
                "Course Name",
                "Title",
                "Content",
                "Module",
                "과정명",
                "콘텐츠명",
                "학습 콘텐츠",
                "코스명"
            ]
        )

        if possible_title_idx is not None:
            header_row_index = i
            title_idx = possible_title_idx
            level_idx = find_header_index(headers, ["Level", "Difficulty", "난이도"])
            type_idx = find_header_index(headers, ["Type", "Badge", "구분", "배지"])
            break

    if header_row_index is not None and title_idx is not None:
        for row in rows[header_row_index + 1:]:
            if title_idx >= len(row):
                continue

            title = clean_cell(row[title_idx])

            if not is_probably_course_title(title):
                continue

            row_text = " ".join(clean_cell(c) for c in row)
            badge_type = detect_badge_type(row_text)

            level = ""
            if level_idx is not None and level_idx < len(row):
                level = clean_cell(row[level_idx])

            if type_idx is not None and type_idx < len(row):
                explicit_type = clean_cell(row[type_idx])
                if explicit_type:
                    badge_type = detect_badge_type(explicit_type + " " + row_text)

            courses.append({
                "title": title,
                "sheet": sheet_name,
                "level": level,
                "type": badge_type,
                "isBadge": badge_type == "Badge",
                "isSkillBadge": badge_type == "Skill Badge"
            })

        return courses

    for row in rows:
        cells = [clean_cell(c) for c in row]
        row_text = " ".join(cells)

        title = ""

        for cell in cells:
            if is_probably_course_title(cell):
                title = cell
                break

        if not title:
            continue

        badge_type = detect_badge_type(row_text)

        level = ""
        for cell in cells:
            if cell in ["초급", "중급", "상급", "Beginner", "Intermediate", "Advanced"]:
                level = cell
                break

        courses.append({
            "title": title,
            "sheet": sheet_name,
            "level": level,
            "type": badge_type,
            "isBadge": badge_type == "Badge",
            "isSkillBadge": badge_type == "Skill Badge"
        })

    return courses


def load_courses_from_google_sheet(config):
    spreadsheet_id = config["spreadsheetId"]
    target_sheets = config["targetSheets"]

    all_courses = []
    seen = set()

    for sheet_name in target_sheets:
        rows = fetch_sheet_csv(spreadsheet_id, sheet_name)
        courses = extract_courses_from_rows(sheet_name, rows)

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
    total_badges = sum(1 for c in courses if c["isBadge"])
    total_skill_badges = sum(1 for c in courses if c["isSkillBadge"])

    students = []

    for profile in profiles:
        try:
            raw = extract_profile(profile["url"])

            earned_titles = {
                normalize(item["title"]): item
                for item in raw["earnedItems"]
            }

            completed_courses = []
            completed_count = 0
            badge_count = 0
            skill_badge_count = 0

            for course in courses:
                key = normalize(course["title"])
                completed = key in earned_titles

                if completed:
                    completed_count += 1

                    if course["isBadge"]:
                        badge_count += 1

                    if course["isSkillBadge"]:
                        skill_badge_count += 1

                completed_courses.append({
                    "title": course["title"],
                    "sheet": course["sheet"],
                    "level": course["level"],
                    "type": course["type"],
                    "isBadge": course["isBadge"],
                    "isSkillBadge": course["isSkillBadge"],
                    "completed": completed,
                    "earnedDate": earned_titles[key]["earnedDate"] if completed else None
                })

            students.append({
                "id": profile["id"],
                "name": raw["name"],
                "url": raw["url"],
                "league": raw["league"],
                "points": raw["points"],
                "completedCount": completed_count,
                "badgeCount": badge_count,
                "skillBadgeCount": skill_badge_count,
                "totalCourses": total_courses,
                "totalBadges": total_badges,
                "totalSkillBadges": total_skill_badges,
                "completionRate": round(completed_count / total_courses * 100, 1) if total_courses else 0,
                "courses": completed_courses
            })

            time.sleep(1)

        except Exception as e:
            students.append({
                "id": profile["id"],
                "name": "Fetch Failed",
                "url": profile["url"],
                "league": "",
                "points": 0,
                "completedCount": 0,
                "badgeCount": 0,
                "skillBadgeCount": 0,
                "totalCourses": total_courses,
                "totalBadges": total_badges,
                "totalSkillBadges": total_skill_badges,
                "completionRate": 0,
                "error": str(e),
                "courses": []
            })

    students.sort(
        key=lambda x: (
            x["skillBadgeCount"],
            x["badgeCount"],
            x["completedCount"],
            x["points"]
        ),
        reverse=True
    )

    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "spreadsheetId": config["spreadsheetId"],
        "totalCourses": total_courses,
        "totalBadges": total_badges,
        "totalSkillBadges": total_skill_badges,
        "students": students,
        "courses": courses
    }

    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Saved: {OUTPUT_FILE}")
    print(f"Courses: {total_courses}")
    print(f"Badges: {total_badges}")
    print(f"Skill Badges: {total_skill_badges}")


if __name__ == "__main__":
    main()
