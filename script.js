const DATA_URL = "data/leaderboard.json";
const REWARDS_URL = "data/rewards.json";

const DEFAULT_REWARDS = {
  officialRewards: [
    {
      title: "Official Reward Tier 1",
      description: "Earn 10 or more badges, including at least 6 skill badges.",
      minCompleted: 10,
      minSkillBadges: 6,
      items: ["Sticker", "Google Badge Set", "T-shirt"]
    },
    {
      title: "Official Reward Tier 2",
      description: "Earn 18 or more badges, including at least 9 skill badges.",
      minCompleted: 18,
      minSkillBadges: 9,
      items: ["Sticker", "Google Badge Set", "T-shirt", "Windbreaker"]
    },
    {
      title: "Official Reward Tier 3",
      description: "Earn 32 or more badges, including at least 16 skill badges.",
      minCompleted: 32,
      minSkillBadges: 16,
      items: ["Sticker", "Google Badge Set", "T-shirt", "Windbreaker", "Backpack"]
    }
  ],
  customRewards: []
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  try {
    const [leaderboard, rewardsConfig] = await Promise.all([
      fetchJson(withBust(DATA_URL)),
      fetchJson(withBust(REWARDS_URL), DEFAULT_REWARDS)
    ]);

    const rewards = normalizeRewards(rewardsConfig);

    renderUpdatedAt(leaderboard.updatedAt);
    renderRewards(rewards);
    renderLeaderboard(leaderboard.students || [], rewards);
    renderStudents(leaderboard.students || [], rewards);
  } catch (error) {
    showError(error);
  }
}

function withBust(url) {
  return `${url}?v=${Date.now()}`;
}

async function fetchJson(url, fallback = null) {
  try {
    const response = await fetch(url, { cache: "no-store" });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    if (fallback !== null) return fallback;
    throw error;
  }
}

function normalizeRewards(config) {
  const officialRewards = Array.isArray(config?.officialRewards)
    ? config.officialRewards
    : DEFAULT_REWARDS.officialRewards;

  const customRewards = Array.isArray(config?.customRewards)
    ? config.customRewards.filter((item) => item && item.enabled !== false)
    : [];

  const sortFn = (a, b) => {
    if ((a.minCompleted || 0) !== (b.minCompleted || 0)) {
      return (a.minCompleted || 0) - (b.minCompleted || 0);
    }

    return (a.minSkillBadges || 0) - (b.minSkillBadges || 0);
  };

  return {
    officialRewards: [...officialRewards].sort(sortFn),
    customRewards: [...customRewards].sort(sortFn)
  };
}

function renderUpdatedAt(updatedAt) {
  const target = document.getElementById("updatedAt");

  if (!updatedAt) {
    target.textContent = "Unknown";
    return;
  }

  const date = new Date(updatedAt);

  if (Number.isNaN(date.getTime())) {
    target.textContent = updatedAt;
    return;
  }

  target.textContent = date.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function renderRewards(rewards) {
  const officialWrap = document.getElementById("officialRewards");
  const customWrap = document.getElementById("customRewards");
  const customSection = document.getElementById("customRewardSection");

  officialWrap.innerHTML = rewards.officialRewards
    .map((reward, index) => createRewardCard(reward, true, index))
    .join("");

  if (!rewards.customRewards.length) {
    customSection.classList.add("hidden");
    return;
  }

  customSection.classList.remove("hidden");

  customWrap.innerHTML = rewards.customRewards
    .map((reward) => createRewardCard(reward, false))
    .join("");
}

function createRewardCard(reward, isOfficial, officialIndex = 0) {
  const klass = isOfficial ? `official-${officialIndex + 1}` : "custom";
  const items = Array.isArray(reward.items) ? reward.items : [];

  return `
    <div class="reward-card ${klass}">
      <h4 class="reward-title">${escapeHtml(reward.title || "Reward")}</h4>
      <div class="reward-rule">
        ${escapeHtml(String(reward.minCompleted || 0))}+ badges /
        ${escapeHtml(String(reward.minSkillBadges || 0))}+ skill badges
      </div>
      ${reward.description ? `<p>${escapeHtml(reward.description)}</p>` : ""}
      <ul class="reward-items">
        ${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </div>
  `;
}

function renderLeaderboard(students, rewards) {
  const tbody = document.getElementById("leaderboardTableBody");
  const allRewards = [...rewards.officialRewards, ...rewards.customRewards];

  tbody.innerHTML = students
    .map((student, index) => {
      const rewardState = getRewardState(student, allRewards);

      return `
        <tr class="leaderboard-row">
          <td class="rank-cell">
            <span class="rank-badge">${index + 1}</span>
          </td>

          <td class="name-cell">
            <strong>${escapeHtml(student.name || "Unknown")}</strong>
            <span class="participant-sub">
              ${escapeHtml(student.league || "No league data")}
            </span>
          </td>

          <td class="score-cell">
            <span class="score-main">${student.badgeCount ?? 0}</span>
          </td>

          <td class="score-cell">
            <span class="score-main skill">${student.skillBadgeCount ?? 0}</span>
          </td>

          <td class="score-cell">
            <span class="score-main total">${student.completedCount ?? 0}</span>
          </td>

          <td class="reward-cell">
            <span class="reward-status">${escapeHtml(rewardState.title)}</span>
            <span class="reward-subtext">${escapeHtml(rewardState.subtext)}</span>
          </td>

          <td class="profile-cell">
            <a
              class="profile-link"
              href="${escapeAttribute(student.url || "#")}"
              target="_blank"
              rel="noopener noreferrer"
            >
              View
            </a>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderStudents(students, rewards) {
  const studentList = document.getElementById("studentList");
  const allRewards = [...rewards.officialRewards, ...rewards.customRewards];

  studentList.innerHTML = students
    .map((student, index) => {
      const completedCourses = (student.courses || []).filter((course) => course.completed);
      const generalCourses = completedCourses.filter((course) => !course.isSkillBadge);
      const skillCourses = completedCourses.filter((course) => course.isSkillBadge);

      const previewItems = completedCourses.slice(0, 5);
      const extraCount = completedCourses.length - previewItems.length;
      const rewardState = getRewardState(student, allRewards);

      const previewHtml = completedCourses.length
        ? `
          <div class="completed-preview">
            ${previewItems
              .map(
                (course) => `
                  <span class="course-chip ${course.isSkillBadge ? "skill" : "general"}">
                    ${escapeHtml(course.title || "Untitled")}
                  </span>
                `
              )
              .join("")}
            ${
              extraCount > 0
                ? `<span class="course-chip more">+ ${extraCount} more</span>`
                : ""
            }
          </div>
        `
        : `<div class="empty-box">No completed tracked items yet.</div>`;

      const buttonHtml =
        completedCourses.length > 0
          ? `
            <button class="completed-toggle" data-card-id="student-card-${index}">
              Show All
            </button>
          `
          : "";

      return `
        <article class="student-card" id="student-card-${index}">
          <div class="student-card-head">
            <div class="student-title-wrap">
              <h3>${escapeHtml(student.name || "Unknown")}</h3>
              <div class="student-meta">
                <a
                  href="${escapeAttribute(student.url || "#")}"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open Public Profile
                </a>
              </div>
            </div>
          </div>

          <div class="student-stats">
            <div class="stat-chip general">
              Completion <strong>${student.badgeCount ?? 0}</strong>
            </div>
            <div class="stat-chip skill">
              Skill <strong>${student.skillBadgeCount ?? 0}</strong>
            </div>
            <div class="stat-chip total">
              Total <strong>${student.completedCount ?? 0}</strong>
            </div>
          </div>

          <div class="current-reward-box">
            <strong>${escapeHtml(rewardState.title)}</strong>
            <p>${escapeHtml(rewardState.subtext)}</p>
          </div>

          ${previewHtml}
          ${buttonHtml}

          <div class="completed-full">
            ${renderCourseGroup("Completion Badges", generalCourses, false)}
            ${renderCourseGroup("Skill Badges", skillCourses, true)}
          </div>
        </article>
      `;
    })
    .join("");

  bindToggleButtons();
}

function renderCourseGroup(title, courses, isSkill) {
  if (!courses.length) {
    return `
      <div class="group-block">
        <h4>${escapeHtml(title)} (${courses.length})</h4>
        <div class="empty-box">No items in this category.</div>
      </div>
    `;
  }

  return `
    <div class="group-block">
      <h4>${escapeHtml(title)} (${courses.length})</h4>
      <div class="course-list">
        ${courses
          .map(
            (course) => `
              <div class="course-item">
                <div class="course-item-left">
                  <div class="course-name">${escapeHtml(course.title || "Untitled")}</div>
                  <div class="course-meta">
                    ${course.sheet ? `Category: ${escapeHtml(course.sheet)}` : ""}
                    ${course.earnedDate ? ` · Earned: ${escapeHtml(course.earnedDate)}` : ""}
                  </div>
                </div>
                <div class="course-type ${isSkill ? "skill" : "general"}">
                  ${isSkill ? "Skill Badge" : "Completion Badge"}
                </div>
              </div>
            `
          )
          .join("")}
      </div>
    </div>
  `;
}

function bindToggleButtons() {
  const buttons = document.querySelectorAll(".completed-toggle");

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const cardId = button.getAttribute("data-card-id");
      const card = document.getElementById(cardId);

      if (!card) return;

      const expanded = card.classList.toggle("expanded");
      button.textContent = expanded ? "Collapse" : "Show All";
    });
  });
}

function getRewardState(student, rewards) {
  if (!rewards.length) {
    return {
      title: "No reward configured",
      subtext: "You can configure rewards in data/rewards.json."
    };
  }

  const completedCount = student.completedCount ?? 0;
  const skillBadgeCount = student.skillBadgeCount ?? 0;

  const sorted = [...rewards].sort((a, b) => {
    if ((a.minCompleted || 0) !== (b.minCompleted || 0)) {
      return (a.minCompleted || 0) - (b.minCompleted || 0);
    }

    return (a.minSkillBadges || 0) - (b.minSkillBadges || 0);
  });

  const unlocked = sorted.filter(
    (reward) =>
      completedCount >= (reward.minCompleted || 0) &&
      skillBadgeCount >= (reward.minSkillBadges || 0)
  );

  if (unlocked.length) {
    const current = unlocked[unlocked.length - 1];

    return {
      title: `${current.title} Achieved`,
      subtext: `${completedCount} total / ${skillBadgeCount} skill badges`
    };
  }

  const next = sorted[0];
  const remainCompleted = Math.max((next.minCompleted || 0) - completedCount, 0);
  const remainSkill = Math.max((next.minSkillBadges || 0) - skillBadgeCount, 0);

  return {
    title: "No reward achieved yet",
    subtext: `${remainCompleted} more total and ${remainSkill} more skill badges needed`
  };
}

function showError(error) {
  const errorPanel = document.getElementById("errorPanel");
  const errorText = document.getElementById("errorText");

  errorPanel.classList.remove("hidden");
  errorText.textContent = `Failed to load leaderboard data: ${error.message}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}
