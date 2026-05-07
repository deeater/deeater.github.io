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


def normalize_for_match(text: str) -> str:
    text = str(text or "").lower()

    replacements = {
        "–": "-",
        "—": "-",
        "-": "-",
        "“": '"',
        "”": '"',
        "’": "'",
        "‘": "'",
        "®": "",
        "™": "",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_for_match(text: str) -> str:
    text = normalize_for_match(text)
    return re.sub(r"[^a-z0-9가-힣]+", "", text)


def clean_cell(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_probably_course_title(value: str) -> bool:
    value = clean_cell(value)
    low = normalize(value)

    if not value:
        return False

    if len(value) < 4 or len(value) > 180:
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
        "구분",
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

    if "completion badge" in text:
        return "Badge"

    if "completion" in text and "badge" in text:
        return "Badge"

    if "수료 배지" in text:
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
                "코스명",
            ],
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

            courses.append(
                {
                    "title": title,
                    "sheet": sheet_name,
                    "level": level,
                    "type": badge_type,
                    "isBadge": badge_type == "Badge",
                    "isSkillBadge": badge_type == "Skill Badge",
                }
            )

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

        courses.append(
            {
                "title": title,
                "sheet": sheet_name,
                "level": level,
                "type": badge_type,
                "isBadge": badge_type == "Badge",
                "isSkillBadge": badge_type == "Skill Badge",
            }
        )

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

        print(f"  Found courses: {len(courses)}")

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

    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    # 줄 단위 텍스트
    lines = [
        line.strip()
        for line in soup.get_text("\n", strip=True).splitlines()
        if line.strip()
    ]

    # 전체 검색용 텍스트
    profile_text = soup.get_text(" ", strip=True)
    profile_text = normalize_for_match(profile_text)

    name = "Unknown"
    league = ""
    points = 0

    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(" ", strip=True)

    for line in lines:
        if "League" in line:
            league = line.strip()

        points_match = re.search(r"([\d,]+)\s+points", line, re.IGNORECASE)
        if points_match:
            points = int(points_match.group(1).replace(",", ""))

    # 기존 방식도 유지: 운 좋게 같은 줄에 있는 경우를 잡기 위함
    earned_items = []

    for line in lines:
        if "Earned" in line:
            match = re.match(r"^(.*?)\s+Earned\s+(.+)$", line)
            if match:
                title = match.group(1).strip()
                earned_date = match.group(2).strip()

                if title:
                    earned_items.append(
                        {
                            "title": title,
                            "earnedDate": earned_date,
                        }
                    )

    return {
        "name": name,
        "url": url,
        "league": league,
        "points": points,
        "profileText": profile_text,
        "profileTextCompact": compact_for_match(profile_text),
        "earnedItems": earned_items,
    }


def course_exists_in_profile(profile: dict, course_title: str) -> bool:
    title_norm = normalize_for_match(course_title)
    title_compact = compact_for_match(course_title)

    profile_text = profile.get("profileText", "")
    profile_text_compact = profile.get("profileTextCompact", "")

    # 1차: 공백 정규화 후 그대로 포함되는지 확인
    if title_norm and title_norm in profile_text:
        return True

    # 2차: 특수문자, 공백 제거 후 포함되는지 확인
    # 단, 너무 짧은 제목은 오탐 가능성이 높으므로 제한
    if len(title_compact) >= 8 and title_compact in profile_text_compact:
        return True

    return False


def extract_earned_date_from_profile(profile_text: str, course_title: str):
    # 정확한 날짜 추출은 보조 기능이다.
    # 구조가 바뀌면 null이어도 완료 여부에는 영향 없음.
    text = normalize_for_match(profile_text)
    title = re.escape(normalize_for_match(course_title))

    pattern = title + r".{0,120}?earned\s+([a-z]{3,9}\s+\d{1,2},\s+\d{4}(?:\s+[a-z]{2,4})?)"

    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


def main():
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    profiles = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))

    courses = load_courses_from_google_sheet(config)

    total_courses = len(courses)
    total_badges = sum(1 for c in courses if c["isBadge"])
    total_skill_badges = sum(1 for c in courses if c["isSkillBadge"])

    students = []

    for profile_config in profiles:
        try:
            print(f"Loading profile: {profile_config['url']}")

            raw = extract_profile(profile_config["url"])

            earned_titles = {
                normalize(item["title"]): item for item in raw.get("earnedItems", [])
            }

            completed_courses = []
            completed_count = 0
            badge_count = 0
            skill_badge_count = 0

            debug_matched_titles = []

            for course in courses:
                key = normalize(course["title"])

                completed_by_old_method = key in earned_titles
                completed_by_text_search = course_exists_in_profile(raw, course["title"])

                completed = completed_by_old_method or completed_by_text_search

                earned_date = None

                if completed_by_old_method:
                    earned_date = earned_titles[key].get("earnedDate")

                if completed and not earned_date:
                    earned_date = extract_earned_date_from_profile(
                        raw.get("profileText", ""),
                        course["title"],
                    )

                if completed:
                    completed_count += 1
                    debug_matched_titles.append(course["title"])

                    if course["isBadge"]:
                        badge_count += 1

                    if course["isSkillBadge"]:
                        skill_badge_count += 1

                completed_courses.append(
                    {
                        "title": course["title"],
                        "sheet": course["sheet"],
                        "level": course["level"],
                        "type": course["type"],
                        "isBadge": course["isBadge"],
                        "isSkillBadge": course["isSkillBadge"],
                        "completed": completed,
                        "earnedDate": earned_date,
                    }
                )

            print(f"  Name: {raw['name']}")
            print(f"  Completed: {completed_count}")
            print(f"  Skill Badges: {skill_badge_count}")
            print(f"  Badges: {badge_count}")

            students.append(
                {
                    "id": profile_config["id"],
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
                    "completionRate": round(completed_count / total_courses * 100, 1)
                    if total_courses
                    else 0,
                    "courses": completed_courses,
                    "allEarnedItems": raw.get("earnedItems", []),
                    "debugMatchedTitles": debug_matched_titles,
                }
            )

            time.sleep(1)

        except Exception as e:
            print(f"Failed to load profile: {profile_config['url']}")
            print(str(e))

            students.append(
                {
                    "id": profile_config["id"],
                    "name": "Fetch Failed",
                    "url": profile_config["url"],
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
                    "courses": [],
                    "allEarnedItems": [],
                    "debugMatchedTitles": [],
                }
            )

    students.sort(
        key=lambda x: (
            x.get("skillBadgeCount", 0),
            x.get("badgeCount", 0),
            x.get("completedCount", 0),
            x.get("points", 0),
        ),
        reverse=True,
    )

    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "spreadsheetId": config["spreadsheetId"],
        "totalCourses": total_courses,
        "totalBadges": total_badges,
        "totalSkillBadges": total_skill_badges,
        "students": students,
        "courses": courses,
    }

    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("")
    print(f"Saved: {OUTPUT_FILE}")
    print(f"Courses: {total_courses}")
    print(f"Badges: {total_badges}")
    print(f"Skill Badges: {total_skill_badges}")


if __name__ == "__main__":
    main()
