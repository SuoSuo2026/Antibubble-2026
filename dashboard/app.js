let dashboardData = null;
let activeStatus = "all";
let activeCaseId = null;
let activePage = "console";
const caseGrid = document.querySelector("#caseGrid");
const detailPanel = document.querySelector("#detailPanel");
const memoPanel = document.querySelector("#memoPanel");
const historyPanel = document.querySelector("#historyPanel");
const phasePanel = document.querySelector("#phasePanel");
const literaturePanel = document.querySelector("#literaturePanel");
const manuscriptPanel = document.querySelector("#manuscriptPanel");
const showcasePanel = document.querySelector("#showcasePanel");
const dataAgentDesk = document.querySelector("#dataAgentDesk");
const paperProgressPanel = document.querySelector("#paperProgressPanel");
const consoleResearchPanel = document.querySelector("#consoleResearchPanel");
const consoleWritingPanel = document.querySelector("#consoleWritingPanel");
const searchInput = document.querySelector("#searchInput");
const rebuildBtn = document.querySelector("#rebuildBtn");
const exportSwitchesBtn = document.querySelector("#exportSwitchesBtn");
const switchDialog = document.querySelector("#switchDialog");
const switchExport = document.querySelector("#switchExport");

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function agentHeading(agentName, work, detail = "") {
  return `
    <div class="agent-heading">
      <div>
        <p class="eyebrow">${escapeHtml(agentName)}</p>
        <h3>${escapeHtml(work)}</h3>
        ${detail ? `<p>${escapeHtml(detail)}</p>` : ""}
      </div>
    </div>
  `;
}

function statusLabel(status) {
  return {
    processed: "已完成",
    needs_review: "待复核",
    raw_only: "未处理",
    paused: "暂停",
  }[status] || status;
}

function imageUrl(asset) {
  return asset ? encodeURI(asset.url) : "";
}

function bestRun(item) {
  return item.runs?.find((run) => run.run_id === item.best_run_id) || item.runs?.[0];
}

function candidateVideos(item) {
  const videos = bestRun(item)?.assets?.videos || [];
  const preferred = [
    videos.find((asset) => asset.name?.toLowerCase().endsWith("monitor.webm")) ||
      null,
    videos.find((asset) => asset.name?.toLowerCase().endsWith(".webm")) ||
      null,
    videos.find((asset) => asset.name?.toLowerCase().endsWith("monitor.mp4")) ||
      null,
    videos.find((asset) => asset.name?.toLowerCase().endsWith(".mp4")) ||
      null,
    videos[0] || null,
  ].filter(Boolean);
  const seen = new Set();
  return [...preferred, ...videos].filter((asset) => {
    const key = asset.url || asset.path || asset.name;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function bestVideo(item) {
  return candidateVideos(item)[0] || null;
}

function videoType(asset) {
  const name = asset?.name?.toLowerCase() || "";
  if (name.endsWith(".webm")) return "video/webm";
  if (name.endsWith(".mp4")) return "video/mp4";
  return "";
}

function isRigidBall(metrics = {}) {
  const experimentType = String(metrics.experiment_type || "").toLowerCase();
  return ["rigid_ball", "rigid", "solid_ball", "hard_sphere", "sphere"].includes(experimentType);
}

function accelerationValue(metrics = {}) {
  return metrics.primary_quad_accel_mm_s2 ?? metrics.primary_quad_accel_px_s2 ?? metrics.a_fit_osc_mean_mm_s2;
}

function accelerationUnit(metrics = {}) {
  if (metrics.primary_quad_accel_mm_s2 !== undefined || metrics.a_fit_osc_mean_mm_s2 !== undefined) return "mm/s²";
  if (metrics.primary_quad_accel_px_s2 !== undefined) return "px/s²";
  return "";
}

function cardTypeClass(metrics = {}) {
  return isRigidBall(metrics) ? "rigid-card" : "droplet-card";
}

function previewMedia(item, className = "thumb") {
  const fallback = item.best_preview ? imageUrl(item.best_preview) : "";
  return fallback
    ? `<img class="${className}" src="${fallback}" alt="${escapeHtml(item.display_name)} summary preview" loading="lazy" />`
    : `<div class="${className}"></div>`;
}

function startVideos() {
  // Video rendering is intentionally disabled for dashboard performance.
}

function replaceVideoWithFallback(video) {
  const fallback = video.dataset.fallbackSrc;
  if (!fallback || video.dataset.fallbackUsed) return;
  video.dataset.fallbackUsed = "1";
  const img = document.createElement("img");
  img.className = video.className;
  img.src = fallback;
  img.alt = video.dataset.fallbackAlt || "preview";
  img.loading = "lazy";
  video.replaceWith(img);
}

function scoreValue(item) {
  return item.best_score === null || item.best_score === undefined ? null : Number(item.best_score);
}

async function loadData(keepActive = true) {
  const previousActive = activeCaseId;
  const response = await fetch("./dashboard_data.json", { cache: "no-store" });
  dashboardData = await response.json();
  activeStatus = activeStatus || "all";
  const available = filteredCases();
  activeCaseId = keepActive && previousActive ? previousActive : (available[0] || dashboardData.cases[0])?.case_id ?? null;
  render();
}

function renderSummary() {
  const summary = dashboardData.summary;
  document.querySelector("#caseCount").textContent = summary.case_count;
  document.querySelector("#processedCount").textContent = summary.processed_count;
  document.querySelector("#runCount").textContent = summary.run_count;
  document.querySelector("#topCase").textContent = summary.top_case || "-";
}

function renderPaperProgress() {
  if (!paperProgressPanel) return;
  const manuscript = dashboardData.manuscript || {};
  const progress = manuscript.progress || {};
  const percent = Number(progress.percent || 0);
  paperProgressPanel.innerHTML = `
    <div class="paper-progress-head">
      <div>
        <p class="eyebrow">Paper Progress</p>
        <h2>论文完成度 ${fmt(percent, 0)}%</h2>
        <p>${escapeHtml(progress.stage || "early exploration")} · 创新度 ${escapeHtml(progress.innovation_level || "-")}</p>
      </div>
      <div class="paper-progress-score">
        <span><strong>${fmt(progress.data_score, 1)}</strong>数据</span>
        <span><strong>${fmt(progress.literature_score, 1)}</strong>文献</span>
        <span><strong>${fmt(progress.writing_score, 1)}</strong>写作</span>
        <span><strong>${fmt(progress.novelty_score, 1)}</strong>创新</span>
      </div>
    </div>
    <div class="progress-track"><span style="width:${Math.max(0, Math.min(100, percent))}%"></span></div>
    <ul class="note-list progress-notes">
      ${(progress.daily_push || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>
  `;
}

function memoBullets(text) {
  const raw = String(text || "").trim();
  if (!raw) return ["暂无备忘。"];
  return raw
    .split(/\r?\n|；|;|\。/)
    .map((item) => item.replace(/^[-*]\s*/, "").trim())
    .filter(Boolean);
}

function renderHistoryMemo() {
  const history = dashboardData.history || {};
  const items = history.recent_runs || [];
  const memo = history.memo || {};
  const sessionBrief = history.session_brief || {};
  const agents = dashboardData.agents || {};
  const agentRows = [agents.loop, agents.reviewer, agents.literature, agents.writer].filter(Boolean);
  memoPanel.innerHTML = `
    <h2>今日备忘录</h2>
    <ul class="note-list">
      ${memoBullets(memo.text).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>
  `;
  historyPanel.innerHTML = `
    <h2>历史处理记录</h2>
    <ul class="history-list">
      ${
        items.length
          ? items
              .slice(0, 8)
              .map(
                (item) => `
                  <li>
                    <button type="button" class="history-link" data-case-id="${escapeHtml(item.case_id)}">${escapeHtml(item.case_id)}</button>
                    <span>${escapeHtml(item.modified_at || "")}</span>
                    <span>评分 ${fmt(item.score, 1)}，R ${fmt(item.radius_rel_std_percent, 2)}%，a ${fmt(item.accel_mm_s2, 1)}</span>
                  </li>
                `,
              )
              .join("")
          : "<li>暂无历史处理记录</li>"
      }
    </ul>
  `;
  if (agentRows.length) {
    historyPanel.insertAdjacentHTML(
      "beforeend",
      `
        <div class="agent-roster">
          <h2>智能体分工</h2>
          ${agentRows
            .map(
              (agent) => `
                <div>
                  <strong>${escapeHtml(agent.name)}</strong>
                  <span>${escapeHtml(agent.role)}</span>
                  <small>${escapeHtml(agent.scope)}</small>
                </div>
              `,
            )
            .join("")}
        </div>
      `,
    );
  }
  historyPanel.querySelectorAll("button[data-case-id]").forEach((button) => {
    button.addEventListener("click", () => {
      activeCaseId = button.dataset.caseId;
      render();
    });
  });
  renderConsoleResearchWriting();
}

function renderConsoleResearchWriting() {
  const research = dashboardData.eureka_research || {};
  const manuscript = dashboardData.manuscript || {};
  if (consoleResearchPanel) {
    const themes = research.themes || [];
    consoleResearchPanel.innerHTML = `
      <h2>文献与创新线索</h2>
      <ul class="note-list">
        <li>近 5 年文献：${fmt(research.recent_count, 0)} 条。</li>
        ${themes.slice(0, 3).map((theme) => `<li>${escapeHtml(theme.name)}：${fmt(theme.count, 0)} 条匹配。</li>`).join("")}
      </ul>
    `;
  }
  if (consoleWritingPanel) {
    const progress = manuscript.progress || {};
    consoleWritingPanel.innerHTML = `
      <h2>今日写作推进</h2>
      <ul class="note-list">
        ${(progress.daily_push || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
        ${(progress.next_actions || []).slice(0, 2).map((item) => `<li>下一步：${escapeHtml(item)}</li>`).join("")}
      </ul>
    `;
  }
}

function renderPaperProgress() {
  if (!paperProgressPanel) return;
  const manuscript = dashboardData.manuscript || {};
  const progress = manuscript.progress || {};
  const percent = Number(progress.percent || 0);
  paperProgressPanel.innerHTML = `
    <div class="paper-progress-head">
      <div>
        <p class="eyebrow">Quill + Eureka Progress</p>
        <h2>论文完成度 ${fmt(percent, 0)}%</h2>
        <p>${escapeHtml(progress.stage || "early exploration")} · 创新度 ${escapeHtml(progress.innovation_level || "-")}</p>
      </div>
      <div class="paper-progress-score">
        <span><strong>${fmt(progress.data_score, 1)}</strong>数据</span>
        <span><strong>${fmt(progress.literature_score, 1)}</strong>文献</span>
        <span><strong>${fmt(progress.writing_score, 1)}</strong>写作</span>
        <span><strong>${fmt(progress.novelty_score, 1)}</strong>创新</span>
      </div>
    </div>
    <div class="progress-track"><span style="width:${Math.max(0, Math.min(100, percent))}%"></span></div>
    <ul class="note-list progress-notes">
      ${(progress.daily_push || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>
  `;
}

function memoBullets(text) {
  const raw = String(text || "").trim();
  if (!raw) return ["暂无备忘。"];
  return raw
    .split(/\r?\n|；|;|。/)
    .map((item) => item.replace(/^[-*]\s*/, "").trim())
    .filter(Boolean);
}

function sessionBriefBullets(text) {
  const raw = String(text || "").trim();
  if (!raw) return ["Quill 尚未执行本次会话刷新。"];
  return raw
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter((item) => item.startsWith("- "))
    .map((item) => item.replace(/^-\s*/, ""))
    .filter(Boolean);
}

function renderBulletList(items, emptyText = "暂无记录。") {
  const rows = (items || []).filter(Boolean);
  return rows.length
    ? rows.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
    : `<li>${escapeHtml(emptyText)}</li>`;
}

function renderHistoryMemo() {
  const history = dashboardData.history || {};
  const items = history.recent_runs || [];
  const memo = history.memo || {};
  const sessionBrief = history.session_brief || {};
  const agents = dashboardData.agents || {};
  const agentRows = [agents.loop, agents.reviewer, agents.literature, agents.writer].filter(Boolean);
  const research = dashboardData.eureka_research || {};
  const route = research.inspection_route || [];
  const conclusions = research.key_conclusions || [];
  const showcase = dashboardData.showcase || {};
  const pbFocus = research.pb_particle_brief || showcase.pb_particle_focus || {};
  const backlog = research.optimization_backlog || showcase.optimization_backlog || [];
  const talkTrack = showcase.talk_track || [];
  const style = research.presentation_style || [];
  const evidence = research.report_evidence_slides || [];

  memoPanel.innerHTML = `
    <p class="eyebrow">Daily Memo</p>
    <h2>今日备忘录</h2>
    <ul class="note-list">
      ${memoBullets(memo.text).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>
  `;
  historyPanel.innerHTML = `
    <p class="eyebrow">Thursday Readiness</p>
    <h2>突击检查摘要</h2>
    <ul class="note-list">
      ${renderBulletList(route.slice(0, 5), "暂无检查路线。")}
    </ul>
    ${
      evidence.length
        ? `<div class="evidence-strip">${evidence
            .slice(0, 2)
            .map((item) => `<span>${escapeHtml(item.file)} #${item.slide} · ${escapeHtml(item.text).slice(0, 120)}...</span>`)
            .join("")}</div>`
        : ""
    }
  `;
  consoleResearchPanel.innerHTML = `
    <p class="eyebrow">Eureka Conclusions</p>
    <h2>关键结论</h2>
    <ul class="note-list strong-notes">
      ${renderBulletList(conclusions.slice(0, 5), "Eureka 暂无关键结论。")}
    </ul>
    <div class="style-chip-row">
      ${style.map((item) => `<span><strong>${escapeHtml(item.title)}</strong>${escapeHtml(item.detail)}</span>`).join("")}
    </div>
  `;
  consoleWritingPanel.innerHTML = `
    <p class="eyebrow">Agents + Recent Runs</p>
    <h2>智能体分工与最近处理</h2>
    <div class="agent-roster compact">
      ${agentRows
        .map(
          (agent) => `
            <div>
              <strong>${escapeHtml(agent.name)}</strong>
              <span>${escapeHtml(agent.role)}</span>
              <small>${escapeHtml(agent.scope)}</small>
            </div>
          `,
        )
        .join("")}
    </div>
    <ul class="history-list compact-history">
      ${
        items.length
          ? items
              .slice(0, 6)
              .map(
                (item) => `
                  <li>
                    <button type="button" class="history-link" data-case-id="${escapeHtml(item.case_id)}">${escapeHtml(item.case_id)}</button>
                    <span>${escapeHtml(item.modified_at || "")}</span>
                    <span>评分 ${fmt(item.score, 1)}，R ${fmt(item.radius_rel_std_percent, 2)}%，a ${fmt(item.accel_mm_s2, 1)}</span>
                  </li>
                `,
              )
              .join("")
          : "<li>暂无历史处理记录</li>"
      }
    </ul>
  `;
  document.querySelectorAll("button[data-case-id]").forEach((button) => {
    button.addEventListener("click", () => {
      activeCaseId = button.dataset.caseId;
      activePage = "cases";
      render();
    });
  });
}

function renderConsoleResearchWriting() {
  // Console research and writing panels are rendered together in renderHistoryMemo.
}

function phasePoints() {
  return dashboardData.phase_space?.points || [];
}

function renderPhaseSpace() {
  if (!phasePanel) return;
  phasePanel.classList.add("phase-source-mode");
  const points = phasePoints().filter((point) => Number.isFinite(Number(point.radius_mm)) && Number.isFinite(Number(point.accel_g)));
  const pptSources = dashboardData.phase_space?.ppt_sources || [];
  const group = dashboardData.eureka_research?.group_meeting_summary || {};
  const phaseCandidates = group.phase_candidates || [];
  const width = 520;
  const height = 190;
  const pad = 32;
  const xs = points.map((p) => Number(p.radius_mm));
  const ys = points.map((p) => Number(p.accel_g));
  const minX = Math.min(...xs, 0);
  const maxX = Math.max(...xs, 1);
  const minY = Math.min(...ys, 0);
  const maxY = Math.max(...ys, 1.2);
  const sx = (x) => pad + ((x - minX) / Math.max(maxX - minX, 1e-9)) * (width - pad * 2);
  const sy = (y) => height - pad - ((y - minY) / Math.max(maxY - minY, 1e-9)) * (height - pad * 2);
  const provisionalPlot = `
    <svg class="phase-plot" viewBox="0 0 ${width} ${height}" role="img" aria-label="R vs acceleration phase plot">
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" />
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" />
      <text x="${width / 2}" y="${height - 6}">R / mm</text>
      <text x="5" y="18">|a| / g</text>
      ${
        points
          .map((point) => {
            const cls = point.experiment_type === "rigid_ball" ? "rigid-point" : "droplet-point";
            return `<circle class="${cls}" data-case-id="${escapeHtml(point.case_id)}" cx="${sx(Number(point.radius_mm))}" cy="${sy(Number(point.accel_g))}" r="5"><title>${escapeHtml(point.case_id)}: R=${fmt(point.radius_mm, 3)}, |a|/g=${fmt(point.accel_g, 2)}</title></circle>`;
          })
          .join("")
      }
    </svg>
  `;
  phasePanel.innerHTML = `
    <div class="phase-source-head">
      <p class="eyebrow">Eureka Phase Sources</p>
      <h2>结果相图：PPT 原图截取</h2>
      <p>已从 library 汇报 PPT 的候选页中抽取 ${fmt(pptSources.length, 0)} 张原始结果图；优先展示 PPT 内嵌原图，不在看板里临时重画。</p>
    </div>
    <div class="phase-source-grid ${pptSources.length ? "phase-image-grid" : ""}">
      ${
        pptSources.length
          ? pptSources
              .slice(0, 8)
              .map(
                (item) => `
                  <article class="phase-source-card phase-image-card">
                    <a href="${escapeHtml(item.image_url || "")}" target="_blank" rel="noreferrer">
                      <img src="${escapeHtml(item.image_url || "")}" alt="${escapeHtml(item.file || "PPT phase source")}, slide ${escapeHtml(item.slide || "-")}" loading="lazy" />
                    </a>
                    <span>Slide ${escapeHtml(item.slide || "-")}</span>
                    <h3>${escapeHtml(item.file || "group meeting ppt")}</h3>
                    <p>${escapeHtml(String(item.text || "").slice(0, 110))}</p>
                  </article>
                `,
              )
              .join("")
          : phaseCandidates.length
            ? phaseCandidates
              .slice(0, 6)
              .map(
                (item) => `
                  <article class="phase-source-card">
                    <span>Slide ${escapeHtml(item.slide || "-")}</span>
                    <h3>${escapeHtml(item.file || "group meeting ppt")}</h3>
                    <p>${escapeHtml(String(item.text || "").slice(0, 180))}</p>
                  </article>
                `,
              )
              .join("")
            : '<article class="phase-source-card"><span>Waiting</span><h3>未找到 PPT 相图候选页</h3><p>请确认 library 中是否已有包含相图或无量纲准则的 PPT。</p></article>'
      }
    </div>
    <details class="phase-provisional">
      <summary>展开当前数据点临时分区（仅作数据占位，不作为正式相图）</summary>
      <p>横轴 R，纵轴 |a|/g；后续正式相图会改用 PPT 截图或从 PPT 原图导出。</p>
      ${provisionalPlot}
    </details>
  `;
  phasePanel.querySelectorAll("circle[data-case-id]").forEach((point) => {
    point.addEventListener("click", () => {
      activeCaseId = point.dataset.caseId;
      render();
    });
  });
}

function renderLiteraturePage() {
  if (!literaturePanel) return;
  const digest = dashboardData.eureka_research || {};
  const group = digest.group_meeting_summary || {};
  const themes = digest.themes || [];
  const refs = digest.recent_references || [];
  const stackHighlights = digest.stack_highlights || [];
  const future = digest.future_work || [];
  const phaseCandidates = group.phase_candidates || [];
  literaturePanel.innerHTML = `
    <section class="research-hero meeting-hero">
      <div>
        <p class="eyebrow">Eureka Research Desk</p>
        <h2>近 5 年文献调研与未来工作指南</h2>
        <p>Eureka 基于 library 文献堆栈、组会文件文字线索和近年补充文献，整理后续实验与相图规划。PPT 图像暂不强行解析，可后续手动贴入。</p>
      </div>
      <div class="research-stats">
        <span><strong>Eureka</strong>文献观察智能体</span>
        <span><strong>${fmt(digest.recent_count, 0)}</strong>近 5 年文献</span>
        <span><strong>${fmt(zoteroSummary.unique_entry_count, 0)}</strong>Zotero 去重</span>
        <span><strong>${fmt(group.slide_count, 0)}</strong>组会 slides</span>
        <span><strong>${fmt(phaseCandidates.length, 0)}</strong>相图候选页</span>
      </div>
    </section>

    <section class="research-grid">
      <article class="research-card">
        <h3>组会相图候选</h3>
        <ul class="compact-list">
          ${
            phaseCandidates.length
              ? phaseCandidates
                  .slice(0, 6)
                  .map((item) => `<li><strong>${escapeHtml(item.file)} #${item.slide}</strong><span>${escapeHtml(item.text)}</span></li>`)
                  .join("")
              : "<li>暂无相图候选；可后续手动贴图到网站。</li>"
          }
        </ul>
      </article>

      <article class="research-card">
        <h3>未来工作</h3>
        <div class="future-list">
          ${future
            .map(
              (item) => `
                <div>
                  <strong>${escapeHtml(item.title)}</strong>
                  <ul>${(item.steps || []).map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ul>
                </div>
              `,
            )
            .join("")}
        </div>
      </article>

      <article class="research-card wide">
        <h3>近年补充文献雷达</h3>
        <div class="paper-wall">
          ${refs.map((ref) => renderPaperCard(ref)).join("")}
        </div>
      </article>

      <article class="research-card wide">
        <h3>精简主题簇</h3>
        <div class="theme-strip">
          ${themes
            .map((theme) => `<span><strong>${escapeHtml(theme.name)}</strong>${fmt(theme.count, 0)} 条近年匹配</span>`)
            .join("")}
        </div>
      </article>

      <article class="research-card wide">
        <h3>文献堆栈重点</h3>
        <div class="stack-grid">
          ${stackHighlights
            .slice(0, 8)
            .map(
              (ref) => `
                <div>
                  <strong>${renderReferenceInline(ref)}</strong>
                  <p>${escapeHtml(ref.keywords || "待补关键词/关键结果")}</p>
                </div>
              `,
            )
            .join("")}
        </div>
      </article>

      <article class="research-card wide">
        <h3>长期 APP 接入 Backlog</h3>
        <p>PPT、Adobe Illustrator、Phantom camera control 等应用接入先作为路线图记录。后续逐项确认需求后再开发，不影响当前数据处理、Franklin 质检和 Eureka 文献调研。</p>
      </article>
    </section>
  `;
}

function renderLiteraturePage() {
  if (!literaturePanel) return;
  const digest = dashboardData.eureka_research || {};
  const group = digest.group_meeting_summary || {};
  const themes = digest.themes || [];
  const refs = digest.recent_references || [];
  const stackHighlights = digest.stack_highlights || [];
  const future = digest.future_work || [];
  const zotero = digest.zotero_context || {};
  const zoteroSummary = zotero.summary || {};
  const phaseCandidates = group.phase_candidates || [];
  const style = digest.presentation_style || [];
  const conclusions = digest.key_conclusions || [];
  const evidence = digest.report_evidence_slides || [];
  const pbFocus = digest.pb_particle_brief || {};
  const backlog = digest.optimization_backlog || [];
  literaturePanel.innerHTML = `
    <section class="research-hero meeting-hero">
      <div>
        <p class="eyebrow">Eureka Research Desk</p>
        <h2>近 5 年文献调研与组会汇报模式</h2>
        <p>Eureka 已读取 library 文献堆栈与组会 PPT 文本，当前按“科学问题 → 文献缺口 → 相图/准则 → 下一轮实验”的方式组织科研进展。PPT 图像可后续手动补入，文献卡片会优先展示关键结果图。</p>
      </div>
      <div class="research-stats">
        <span><strong>${fmt(digest.recent_count, 0)}</strong>近 5 年文献</span>
        <span><strong>${fmt(zoteroSummary.unique_entry_count, 0)}</strong>Zotero 去重</span>
        <span><strong>${fmt(group.slide_count, 0)}</strong>组会 slides</span>
        <span><strong>${fmt(phaseCandidates.length, 0)}</strong>相图候选页</span>
      </div>
    </section>

    <section class="research-grid">
      <article class="research-card">
        <p class="eyebrow">Report Pattern</p>
        <h3>Eureka 学到的汇报方式</h3>
        <div class="style-chip-row vertical">
          ${style.map((item) => `<span><strong>${escapeHtml(item.title)}</strong>${escapeHtml(item.detail)}</span>`).join("")}
        </div>
      </article>

      <article class="research-card">
        <p class="eyebrow">Inspection Points</p>
        <h3>关键结论</h3>
        <ul class="compact-list">
          ${renderBulletList(conclusions.slice(0, 5), "暂无关键结论。")}
        </ul>
      </article>

      <article class="research-card wide">
        <h3>关键证据页</h3>
        <ul class="compact-list evidence-list">
          ${
            evidence.length
              ? evidence
                  .slice(0, 5)
                  .map((item) => `<li><strong>${escapeHtml(item.file)} #${item.slide}</strong><span>${escapeHtml(item.text)}</span></li>`)
                  .join("")
              : "<li>暂无 PPT 证据页。</li>"
          }
        </ul>
      </article>

      <article class="research-card wide">
        <h3>近年补充文献雷达</h3>
        <div class="paper-wall">
          ${refs.map((ref) => renderPaperCard(ref)).join("")}
        </div>
      </article>

      <article class="research-card">
        <h3>精简主题簇</h3>
        <div class="theme-strip">
          ${themes
            .map((theme) => `<span><strong>${escapeHtml(theme.name)}</strong>${fmt(theme.count, 0)} 条近年匹配</span>`)
            .join("")}
        </div>
      </article>

      <article class="research-card">
        <h3>下一步工作指南</h3>
        <div class="future-list">
          ${future
            .slice(0, 3)
            .map(
              (item) => `
                <div>
                  <strong>${escapeHtml(item.title)}</strong>
                  <ul>${(item.steps || []).slice(0, 2).map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ul>
                </div>
              `,
            )
            .join("")}
        </div>
      </article>

      <article class="research-card wide">
        <h3>文献堆栈重点</h3>
        <div class="stack-grid">
          ${stackHighlights
            .slice(0, 8)
            .map(
              (ref) => `
                <div>
                  <strong>${renderReferenceInline(ref)}</strong>
                  <p>${escapeHtml(ref.keywords || "待补关键词/关键结果")}</p>
                </div>
              `,
            )
            .join("")}
        </div>
      </article>
    </section>
  `;
}

function routeNodes() {
  return [
    { label: "PB / 液膜网络", sub: "可变形输运通道" },
    { label: "包覆态前体", sub: "液滴-气膜-液壳" },
    { label: "平行输运", sub: "自由飞行 / 导向 / 卡滞" },
    { label: "相图与准则", sub: "R, |v|, |a|/g, We-Bo" },
    { label: "论文输出", sub: "机制图 + 判据 + 方法" },
  ];
}

function renderResearchRoute(className = "") {
  const nodes = routeNodes();
  return `
    <div class="route-map ${className}">
      ${nodes
        .map(
          (node, index) => `
            <div class="route-node">
              <span>${index + 1}</span>
              <strong>${escapeHtml(node.label)}</strong>
              <small>${escapeHtml(node.sub)}</small>
            </div>
            ${index < nodes.length - 1 ? '<div class="route-arrow"></div>' : ""}
          `,
        )
        .join("")}
    </div>
  `;
}

function renderInnovationMap() {
  const tiles = [
    {
      label: "对象创新",
      title: "从“生成反气泡”推进到“包覆态输运”",
      detail: "把 PB/液膜看成软液体通道，讨论包覆液滴和颗粒在其中的输运图谱。",
    },
    {
      label: "方法创新",
      title: "视频自动处理连接相图",
      detail: "Sisyphus 提取 R、v、a，Franklin 质检，Eureka 给出文献约束下的解释方向。",
    },
    {
      label: "展示创新",
      title: "数据、文献、论文写作同屏推进",
      detail: "Quill 只写已完成事实，未知机制留空，便于日常实验后直接形成论文材料。",
    },
  ];
  return `
    <div class="innovation-map">
      ${tiles
        .map(
          (tile) => `
            <article>
              <span>${escapeHtml(tile.label)}</span>
              <strong>${escapeHtml(tile.title)}</strong>
              <p>${escapeHtml(tile.detail)}</p>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderInspectionLane(items) {
  const rows = (items || []).slice(0, 5);
  return `
    <div class="inspection-lane">
      ${rows
        .map(
          (item, index) => `
            <div>
              <span>${index + 1}</span>
              <p>${escapeHtml(item)}</p>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderClaimBoard(items) {
  const rows = (items || []).slice(0, 4);
  return `
    <div class="claim-board">
      ${rows
        .map(
          (item, index) => `
            <article>
              <span>C${index + 1}</span>
              <p>${escapeHtml(item)}</p>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderDataAgentDesk() {
  if (!dataAgentDesk) return;
  const cases = dashboardData.cases || [];
  const needsReview = cases.filter((item) => item.status === "needs_review").length;
  const confirmed = cases.filter((item) => item.status === "processed").length;
  const agentRows = [
    {
      name: "Sisyphus",
      role: "Loop 处理智能体",
      work: "自动处理 raw_data，生成 summary、指标和可复核产物。",
    },
    {
      name: "Franklin",
      role: "质检评分智能体",
      work: "复核 tracking、ROI、Vfr、半径/质心跳变和拟合可靠性。",
    },
  ];
  dataAgentDesk.innerHTML = `
    <section class="research-hero data-desk-hero">
      <div>
        <p class="eyebrow">Sisyphus + Franklin Data Desk</p>
        <h2>数据处理：Sisyphus 自动循环 + Franklin 质量复核</h2>
        <p>Sisyphus 负责把 raw_data 跑成 summary、指标和可复核产物；Franklin 负责判断 tracking、ROI/Vfr、半径/质心跳变和拟合可靠性。</p>
        <ul class="desk-work-list">
          ${agentRows.map((agent) => `<li><strong>${escapeHtml(agent.name)}</strong>${escapeHtml(agent.work)}</li>`).join("")}
        </ul>
      </div>
      <div class="research-stats data-desk-stats">
        ${agentRows
          .map((agent) => `<span><strong>${escapeHtml(agent.name)}</strong>${escapeHtml(agent.role)}</span>`)
          .join("")}
        <span><strong>${fmt(confirmed, 0)}</strong>已确认/完成</span>
        <span><strong>${fmt(needsReview, 0)}</strong>待复核</span>
      </div>
    </section>
  `;
}

function renderShowcasePage() {
  if (!showcasePanel) return;
  const showcase = dashboardData.showcase || {};
  const stats = showcase.stats || {};
  const pipeline = showcase.pipeline || [];
  const demoCases = showcase.demo_cases || [];
  showcasePanel.innerHTML = `
    <section class="showcase-slide showcase-cover">
      <div>
        <p class="eyebrow">Group Meeting Showcase</p>
        <h2>${escapeHtml(showcase.title || "从实验录像到论文素材")}</h2>
        <p>${escapeHtml(showcase.subtitle || "一页讲清本地 AI 科研工作流。")}</p>
      </div>
      <div class="showcase-kpis">
        <span><strong>${fmt(stats.case_count, 0)}</strong>Cases</span>
        <span><strong>${fmt(stats.processed_count, 0)}</strong>已处理</span>
        <span><strong>${fmt(stats.run_count, 0)}</strong>处理版本</span>
        <span><strong>${escapeHtml(stats.top_case || "-")}</strong>当前高分</span>
      </div>
    </section>

    <section class="showcase-slide">
      <div class="showcase-title-row">
        <span>01</span>
        <div>
          <p class="eyebrow">Pipeline</p>
          <h3>从 raw_data 到论文草稿</h3>
        </div>
      </div>
      <div class="showcase-pipeline">
        ${pipeline.map((step) => renderShowcaseStep(step)).join("")}
      </div>
    </section>

    <section class="showcase-slide">
      <div class="showcase-title-row">
        <span>02</span>
        <div>
          <p class="eyebrow">Evidence</p>
          <h3>代表性 Case：让图先说话</h3>
        </div>
      </div>
      <div class="showcase-case-grid">
        ${demoCases.length ? demoCases.map((item) => renderShowcaseCase(item)).join("") : '<p class="empty">暂无可展示 Case。</p>'}
      </div>
    </section>
  `;
}

function renderShowcaseStep(step) {
  return `
    <article class="showcase-step">
      <span>${escapeHtml(step.agent || "-")}</span>
      <strong>${escapeHtml(step.title || "")}</strong>
      <p>${escapeHtml(step.detail || "")}</p>
    </article>
  `;
}

function renderShowcaseCase(item) {
  const preview = item.preview;
  const score = item.score === null || item.score === undefined ? "-" : Number(item.score).toFixed(1);
  const typeLabel = item.type === "rigid" ? "硬质小球" : "液滴/液膜类";
  const accel = item.accel_mm_s2 === null || item.accel_mm_s2 === undefined ? "-" : `${fmt(item.accel_mm_s2, 1)} mm/s²`;
  return `
    <article class="showcase-case ${item.type === "rigid" ? "rigid" : "droplet"}">
      <div class="showcase-case-image">
        ${preview ? `<img src="${imageUrl(preview)}" alt="${escapeHtml(item.display_name || "case")}" loading="lazy" />` : "<span>Summary 图待生成</span>"}
      </div>
      <div class="showcase-case-body">
        <div>
          <strong>${escapeHtml(item.display_name || item.case_id || "-")}</strong>
          <span>${escapeHtml(typeLabel)} · ${escapeHtml(item.material || "-")}</span>
        </div>
        <dl>
          <dt>评分</dt><dd>${score}</dd>
          <dt>R</dt><dd>${fmt(item.radius_mean_mm, 3)} mm</dd>
          <dt>|v|</dt><dd>${fmt(item.velocity_abs_mean_mm_s, 1)} mm/s</dd>
          <dt>a</dt><dd>${escapeHtml(accel)}</dd>
        </dl>
        ${item.observation ? `<p>${escapeHtml(item.observation)}</p>` : ""}
      </div>
    </article>
  `;
}

function renderBacklogItem(item) {
  return `
    <div>
      <strong>${escapeHtml(item.title || "")}</strong>
      <span>${escapeHtml(item.status || "")}</span>
      <p>${escapeHtml(item.note || "")}</p>
    </div>
  `;
}

function renderNormalResearchPanel(pbFocus, backlog, talkTrack) {
  const checks = pbFocus?.experiment_checks || [];
  const refs = pbFocus?.references || [];
  return `
    <div class="normal-research-panel">
      <article>
        <p class="eyebrow">PB-Particle</p>
        <h3>${escapeHtml(pbFocus?.title || "PB-颗粒相互作用观察线")}</h3>
        <p>${escapeHtml(pbFocus?.claim || "Eureka 暂无 PB-颗粒摘要。")}</p>
        <ul class="compact-list">
          ${checks.slice(0, 3).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
        </ul>
      </article>
      <article>
        <p class="eyebrow">Feasible Backlog</p>
        <h3>可行优化，暂不动主流程</h3>
        <div class="normal-backlog-list">
          ${backlog.length ? backlog.map((item) => renderBacklogItem(item)).join("") : '<p class="empty">暂无暂缓优化项。</p>'}
        </div>
      </article>
      <article>
        <p class="eyebrow">Share Notes</p>
        <h3>组会/同学分享提示</h3>
        <ol class="compact-list">
          ${talkTrack.slice(0, 4).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
        </ol>
      </article>
      <article>
        <p class="eyebrow">Guardrail</p>
        <h3>Eureka / Franklin 边界</h3>
        <p>${escapeHtml(pbFocus?.franklin_boundary || "Eureka 只影响解释与复核建议，不自动改处理算法。")}</p>
        <div class="normal-reference-strip">
          ${refs.slice(0, 4).map((ref) => `<span>${renderReferenceInline(ref)}</span>`).join("")}
        </div>
      </article>
    </div>
  `;
}

function renderContributionCalendar(calendar) {
  const days = calendar?.days || [];
  if (!days.length) return "";
  const first = new Date(`${days[0].date}T00:00:00`);
  const leadingBlanks = Number.isFinite(first.getDay()) ? (first.getDay() + 6) % 7 : 0;
  const cells = [
    ...Array.from({ length: leadingBlanks }, () => null),
    ...days,
  ];
  const weekCount = Math.ceil(cells.length / 7);
  const monthLabels = [];
  let seenMonth = "";
  cells.forEach((day, index) => {
    if (!day) return;
    const date = new Date(`${day.date}T00:00:00`);
    const monthKey = `${date.getFullYear()}-${date.getMonth()}`;
    if (monthKey !== seenMonth && date.getDate() <= 7) {
      seenMonth = monthKey;
      monthLabels.push({
        label: `${date.getMonth() + 1}月`,
        column: Math.floor(index / 7) + 1,
      });
    }
  });
  const titleForDay = (day) => {
    const cats = (day.top_categories || [])
      .map((item) => `${item.label} ${fmt(item.points, 0)}`)
      .join(" / ");
    const details = (day.details || []).slice(0, 3).join("；");
    return `${day.date}：${fmt(day.score, 0)} 分${cats ? `｜${cats}` : ""}${details ? `｜${details}` : ""}`;
  };
  return `
    <section class="contribution-panel">
      <div class="contribution-head">
        <div>
          <p class="eyebrow">Research Contribution</p>
          <h3>推进日历</h3>
          <p>按数据处理、raw 录入、文献、写作、智能体记录和看板维护折算每日推进强度。</p>
        </div>
        <div class="contribution-stats">
          <span><strong>${fmt(calendar.active_days, 0)}</strong>推进日</span>
          <span><strong>${fmt(calendar.today_score, 0)}</strong>今日分</span>
          <span><strong>${fmt(calendar.current_streak, 0)}</strong>连续天</span>
        </div>
      </div>
      <div class="contribution-scroll">
        <div class="contribution-months" style="grid-template-columns: repeat(${weekCount}, 14px);">
          ${monthLabels.map((item) => `<span style="grid-column:${item.column}">${escapeHtml(item.label)}</span>`).join("")}
        </div>
        <div class="contribution-grid" style="grid-template-columns: repeat(${weekCount}, 14px);">
          ${cells
            .map((day) =>
              day
                ? `<span class="contribution-cell level-${day.level}" title="${escapeHtml(titleForDay(day))}" aria-label="${escapeHtml(titleForDay(day))}"></span>`
                : '<span class="contribution-cell empty" aria-hidden="true"></span>',
            )
            .join("")}
        </div>
      </div>
      <div class="contribution-legend">
        <span>Less</span>
        <i class="level-0"></i><i class="level-1"></i><i class="level-2"></i><i class="level-3"></i><i class="level-4"></i>
        <span>More</span>
      </div>
    </section>
  `;
}

function renderPaperProgress() {
  if (!paperProgressPanel) return;
  const manuscript = dashboardData.manuscript || {};
  const progress = manuscript.progress || {};
  const percent = Number(progress.percent || 0);
  const summary = dashboardData.summary || {};
  const history = dashboardData.history || {};
  const memo = history.memo || {};
  const sessionBrief = history.session_brief || {};
  const research = dashboardData.eureka_research || {};
  const conclusions = research.key_conclusions || [];
  const contributionCalendar = dashboardData.history?.contribution_calendar;
  const memoItems = [
    ...memoBullets(memo.text).slice(0, 3),
    ...sessionBriefBullets(sessionBrief.text).slice(0, 2),
  ];
  paperProgressPanel.innerHTML = `
    <section class="console-zone schedule-zone">
      <div class="console-zone-head">
        <div>
          <p class="eyebrow">Quill Refresh</p>
          <h2>日程进度</h2>
          <p>启动 Codex 并推进项目后，Quill 汇总当天实验、处理、文献和写作推进；日历按周一为第一行。</p>
        </div>
        <div class="paper-progress-score compact-score">
          <span><strong>${fmt(summary.case_count, 0)}</strong>Cases</span>
          <span><strong>${fmt(summary.processed_count, 0)}</strong>已处理</span>
          <span><strong>${fmt(summary.run_count, 0)}</strong>版本</span>
        </div>
      </div>
      ${renderContributionCalendar(contributionCalendar)}
    </section>
    <section class="console-zone progress-brief-zone">
      <div class="paper-progress-head compact-progress-head">
        <div>
          <p class="eyebrow">Quill + Eureka Brief</p>
          <h2>进展摘要 · 论文完成度 ${fmt(percent, 0)}%</h2>
          <p>${escapeHtml(progress.stage || "early exploration")} · 创新度 ${escapeHtml(progress.innovation_level || "-")}</p>
        </div>
        <div class="paper-progress-score compact-score">
          <span><strong>${fmt(progress.data_score, 1)}</strong>数据</span>
          <span><strong>${fmt(progress.literature_score, 1)}</strong>文献</span>
          <span><strong>${fmt(progress.writing_score, 1)}</strong>写作</span>
          <span><strong>${fmt(progress.novelty_score, 1)}</strong>创新</span>
        </div>
      </div>
      <div class="progress-track"><span style="width:${Math.max(0, Math.min(100, percent))}%"></span></div>
      <div class="console-brief-grid">
        <article>
          <p class="eyebrow">Today</p>
          <h3>今日推进</h3>
          <ul class="note-list">
            ${memoItems.length ? memoItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("") : "<li>暂无新增推进记录。</li>"}
          </ul>
        </article>
        <article>
          <p class="eyebrow">Inspection</p>
          <h3>可讲结论</h3>
          ${renderClaimBoard(conclusions.slice(0, 3))}
        </article>
      </div>
    </section>
  `;
}

function renderHistoryMemo() {
  const history = dashboardData.history || {};
  const items = history.recent_runs || [];
  const memo = history.memo || {};
  const sessionBrief = history.session_brief || {};
  const agents = dashboardData.agents || {};
  const agentRows = [agents.loop, agents.reviewer, agents.literature, agents.writer].filter(Boolean);
  const research = dashboardData.eureka_research || {};
  const route = research.inspection_route || [];
  const conclusions = research.key_conclusions || [];
  const showcase = dashboardData.showcase || {};
  const pbFocus = research.pb_particle_brief || showcase.pb_particle_focus || {};
  const backlog = research.optimization_backlog || showcase.optimization_backlog || [];
  const talkTrack = showcase.talk_track || [];

  memoPanel.innerHTML = `
    <p class="eyebrow">Daily Memo</p>
    <h2>今日备忘录</h2>
    <ul class="note-list">
      ${memoBullets(memo.text).slice(0, 5).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>
    <div class="session-brief">
      <p class="eyebrow">Quill Session</p>
      <h3>本次会话刷新</h3>
      <ul class="note-list">
        ${sessionBriefBullets(sessionBrief.text).slice(0, 5).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </div>
  `;
  historyPanel.innerHTML = `
    <p class="eyebrow">Thursday Readiness</p>
    <h2>突击检查路线</h2>
    ${renderInspectionLane(route)}
  `;
  consoleResearchPanel.innerHTML = `
    <p class="eyebrow">Eureka Claims</p>
    <h2>一眼可讲的关键结论</h2>
    ${renderClaimBoard(conclusions)}
    ${renderNormalResearchPanel(pbFocus, backlog, talkTrack)}
  `;
  consoleWritingPanel.innerHTML = `
    <p class="eyebrow">Agents + Recent Runs</p>
    <h2>智能体分工与最近处理</h2>
    <div class="agent-roster compact">
      ${agentRows
        .map(
          (agent) => `
            <div>
              <strong>${escapeHtml(agent.name)}</strong>
              <span>${escapeHtml(agent.role)}</span>
            </div>
          `,
        )
        .join("")}
    </div>
    <ul class="history-list compact-history">
      ${
        items.length
          ? items
              .slice(0, 5)
              .map(
                (item) => `
                  <li>
                    <button type="button" class="history-link" data-case-id="${escapeHtml(item.case_id)}">${escapeHtml(item.case_id)}</button>
                    <span>${escapeHtml(item.modified_at || "")}</span>
                    <span>评分 ${fmt(item.score, 1)}，R ${fmt(item.radius_rel_std_percent, 2)}%，a ${fmt(item.accel_mm_s2, 1)}</span>
                  </li>
                `,
              )
              .join("")
          : "<li>暂无历史处理记录</li>"
      }
    </ul>
  `;
  document.querySelectorAll("button[data-case-id]").forEach((button) => {
    button.addEventListener("click", () => {
      activeCaseId = button.dataset.caseId;
      activePage = "cases";
      render();
    });
  });
}

function renderLiteraturePage() {
  if (!literaturePanel) return;
  const digest = dashboardData.eureka_research || {};
  const group = digest.group_meeting_summary || {};
  const themes = digest.themes || [];
  const refs = digest.recent_references || [];
  const stackHighlights = digest.stack_highlights || [];
  const future = digest.future_work || [];
  const zotero = digest.zotero_context || {};
  const zoteroSummary = zotero.summary || {};
  const phaseCandidates = group.phase_candidates || [];
  const style = digest.presentation_style || [];
  const conclusions = digest.key_conclusions || [];
  const evidence = digest.report_evidence_slides || [];
  const pbFocus = digest.pb_particle_brief || {};
  const backlog = digest.optimization_backlog || [];
  literaturePanel.innerHTML = `
    <section class="research-hero meeting-hero">
      <div>
        <p class="eyebrow">Eureka Research Desk</p>
        <h2>文献调研：Eureka Literature & Research Desk</h2>
        <p>Eureka 负责整理 library、Zotero、近年补充文献和组会材料，把文献缺口、PB-颗粒问题、相图坐标和下一轮实验任务串起来。</p>
      </div>
      <div class="research-stats">
        <span><strong>Eureka</strong>文献观察智能体</span>
        <span><strong>${fmt(digest.recent_count, 0)}</strong>近 5 年文献</span>
        <span><strong>${fmt(zoteroSummary.unique_entry_count, 0)}</strong>Zotero 去重</span>
        <span><strong>${fmt(group.slide_count, 0)}</strong>组会 slides</span>
        <span><strong>${fmt(phaseCandidates.length, 0)}</strong>相图候选页</span>
      </div>
    </section>

    <section class="research-grid eureka-two-zones">
      <article class="research-card wide eureka-topic-zone zotero-digest-card">
        ${agentHeading("Eureka", "主题区 1：文献雷达与 Zotero Digest", "只保留最关键的文献卡、Zotero 摘要和主题簇；详细来源放入折叠区。")}
        <div class="eureka-zone-layout">
          <div class="eureka-zone-main">
            <h4>近年补充文献雷达</h4>
            <div class="paper-wall compact-paper-wall">
              ${refs.slice(0, 6).map((ref) => renderPaperCard(ref)).join("")}
            </div>
            <details class="eureka-zone-details">
              <summary>展开更多文献卡片与文献堆栈</summary>
              <div class="paper-wall compact-paper-wall">
                ${refs.slice(6).map((ref) => renderPaperCard(ref)).join("")}
              </div>
              <div class="stack-grid">
                ${stackHighlights
                  .slice(0, 8)
                  .map(
                    (ref) => `
                      <div>
                        <strong>${renderReferenceInline(ref)}</strong>
                        <p>${escapeHtml(ref.keywords || "待补关键词/关键结果")}</p>
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            </details>
          </div>
          <aside class="eureka-zone-side">
            ${renderZoteroDigestCompact(zotero)}
            <div class="theme-strip compact-theme-strip">
              ${themes
                .map((theme) => `<span><strong>${escapeHtml(theme.name)}</strong>${fmt(theme.count, 0)} 条近年匹配</span>`)
                .join("")}
            </div>
          </aside>
        </div>
      </article>

      <article class="research-card wide eureka-topic-zone pb-particle-card">
        ${agentHeading("Eureka", "主题区 2：研究路线与下一轮实验", "把路线图、关键结论、PB-颗粒问题和未来工作合并到一个推进区。")}
        <div class="eureka-zone-stack">
          ${renderResearchRoute("large")}
          ${renderInnovationMap()}
          <div class="eureka-planning-grid">
            <section>
              <h4>关键结论</h4>
              ${renderClaimBoard(conclusions)}
            </section>
            <section>
              <h4>${escapeHtml(pbFocus.title || "PB-颗粒相互作用观察线")}</h4>
              <p>${escapeHtml(pbFocus.claim || "Eureka 暂无 PB-颗粒摘要。")}</p>
              <ul class="compact-list">
                ${(pbFocus.experiment_checks || []).slice(0, 3).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
              </ul>
            </section>
            <section>
              <h4>暂缓优化</h4>
              <ul class="compact-list">
                ${backlog.map((item) => `<li><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.status || "")}</span></li>`).join("")}
              </ul>
            </section>
            <section>
              <h4>未来工作</h4>
              <div class="future-list">
                ${future
                  .slice(0, 3)
                  .map(
                    (item) => `
                      <div>
                        <strong>${escapeHtml(item.title)}</strong>
                        <ul>${(item.steps || []).slice(0, 2).map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ul>
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            </section>
          </div>
          <details class="eureka-zone-details">
            <summary>展开组会汇报模式与证据页</summary>
            <div class="style-chip-row vertical">
              ${style.map((item) => `<span><strong>${escapeHtml(item.title)}</strong>${escapeHtml(item.detail)}</span>`).join("")}
            </div>
            <ul class="compact-list evidence-list">
              ${
                evidence.length
                  ? evidence
                      .slice(0, 5)
                      .map((item) => `<li><strong>${escapeHtml(item.file)} #${item.slide}</strong><span>${escapeHtml(item.text)}</span></li>`)
                      .join("")
                  : "<li>暂无 PPT 证据页。</li>"
              }
            </ul>
            <p class="zotero-boundary">${escapeHtml(pbFocus.franklin_boundary || "Eureka 只影响解释与复核建议，不自动改处理算法。")}</p>
          </details>
        </div>
      </article>
    </section>
  `;
}

function renderZoteroDigestCompact(zotero) {
  if (!zotero?.available) {
    return '<p class="empty">尚未读取到 Zotero digest。</p>';
  }
  const summary = zotero.summary || {};
  const collections = zotero.collections || {};
  const topics = summary.top_topics || [];
  const refs = zotero.high_interest_preview || [];
  const boundary = zotero.integration_rule || "Zotero 只作为 Eureka/Quill 的证据背景，不自动改处理方法。";
  return `
    <div class="zotero-compact">
      <div class="zotero-compact-counts">
        <span><strong>${fmt(summary.unique_entry_count, 0)}</strong>去重</span>
        <span><strong>${fmt(summary.recent_2020_plus_count, 0)}</strong>2020+</span>
        <span><strong>${fmt(summary.doi_count, 0)}</strong>DOI</span>
        <span><strong>${fmt(summary.pdf_count, 0)}</strong>PDF</span>
        <span><strong>${fmt(collections.count, 0)}</strong>分类</span>
      </div>
      <h4>高相关候选</h4>
      <ol class="zotero-compact-refs">
        ${
          refs.length
            ? refs
                .slice(0, 5)
                .map((ref) => `<li>${renderZoteroReference(ref)}</li>`)
                .join("")
            : "<li>暂无高相关候选。</li>"
        }
      </ol>
      <details class="eureka-zone-details">
        <summary>展开 Zotero 主题与边界规则</summary>
        <div class="zotero-compact-topics">
          ${
            topics.length
              ? topics.slice(0, 8).map((item) => `<span><strong>${escapeHtml(item.topic)}</strong>${fmt(item.count, 0)} 条</span>`).join("")
              : "<span>暂无主题簇。</span>"
          }
        </div>
        ${renderZoteroCollections(collections.tree || [])}
        <p class="zotero-boundary">${escapeHtml(boundary)}</p>
      </details>
    </div>
  `;
}

function renderZoteroDigest(zotero) {
  if (!zotero?.available) {
    return `
      <p class="empty">尚未读取到 Zotero digest。请先运行 <code>python zotero_importer.py</code>，再运行 <code>python dashboard_builder.py</code>。</p>
    `;
  }
  const summary = zotero.summary || {};
  const collections = zotero.collections || {};
  const topics = summary.top_topics || [];
  const refs = zotero.high_interest_preview || [];
  const boundary = zotero.integration_rule || "Zotero 只作为 Eureka/Quill 的证据背景，不自动改处理方法。";
  return `
    <div class="zotero-overview">
      <span><strong>${escapeHtml(zotero.provider || "plugin")}</strong>读取来源</span>
      <span><strong>${fmt(summary.unique_entry_count, 0)}</strong>去重文献</span>
      <span><strong>${fmt(summary.recent_2020_plus_count, 0)}</strong>2020+ 文献</span>
      <span><strong>${fmt(summary.doi_count, 0)}</strong>DOI</span>
      <span><strong>${fmt(summary.pdf_count, 0)}</strong>本地 PDF</span>
      <span><strong>${fmt(collections.count, 0)}</strong>Zotero 分类</span>
    </div>
    <div class="zotero-layout">
      <div>
        <h4>主题簇</h4>
        <div class="zotero-topic-strip">
          ${
            topics.length
              ? topics.map((item) => `<span><strong>${escapeHtml(item.topic)}</strong>${fmt(item.count, 0)} 条</span>`).join("")
              : "<span>暂无主题簇。</span>"
          }
        </div>
        ${renderZoteroCollections(collections.tree || [])}
      </div>
      <div>
        <h4>高相关候选</h4>
        <ol class="zotero-ref-list">
          ${
            refs.length
              ? refs
                  .slice(0, 8)
                  .map(
                    (ref) => `
                      <li>
                        ${renderZoteroReference(ref)}
                        <span>${escapeHtml(ref.journal || "journal 待补")} · relevance ${fmt(ref.project_relevance, 1)} · ${escapeHtml(ref.has_pdf ? "PDF" : "no PDF")}</span>
                      </li>
                    `,
                  )
                  .join("")
              : "<li>暂无高相关候选。</li>"
          }
        </ol>
      </div>
    </div>
    <p class="zotero-boundary">${escapeHtml(boundary)}</p>
  `;
}

function renderZoteroCollections(tree) {
  if (!tree.length) return "";
  const rows = tree
    .slice(0, 5)
    .map((node) => {
      const children = (node.children || []).slice(0, 4).map((child) => child.name).join(" / ");
      return `<li><strong>${escapeHtml(node.name || "-")}</strong>${children ? `<span>${escapeHtml(children)}</span>` : ""}</li>`;
    })
    .join("");
  return `
    <h4 class="zotero-collections-title">Zotero 原分类</h4>
    <ul class="zotero-collection-list">${rows}</ul>
  `;
}

function renderZoteroReference(ref) {
  const label = `${ref.year || "-"} · ${ref.title || "Untitled"}`;
  const href = ref.doi
    ? `https://doi.org/${ref.doi}`
    : ref.url || (ref.title ? `https://scholar.google.com/scholar?q=${encodeURIComponent(ref.title)}` : "");
  return href
    ? `<a href="${escapeHtml(href)}" target="_blank">${escapeHtml(label)}</a>`
    : escapeHtml(label);
}

function renderManuscriptPage() {
  if (!manuscriptPanel) return;
  const draft = dashboardData.manuscript || {};
  const agent = draft.agent || {};
  const quillSections = draft.sections || [];
  const refs = draft.reference_context?.files || [];
  const paperData = dashboardData.paper_sections || {};
  const paperSections = paperData.sections || [];
  const budgets = paperData.budgets || {};
  const progress = draft.progress || {};

  // Paper sections list (from /write-section)
  const paperSectionList = paperSections.length
    ? paperSections.map((s) => renderPaperSectionCard(s, budgets)).join("")
    : `<p class="empty">尚未生成任何文章段落。使用 <code>/write-section &lt;section&gt;</code> 开始撰写。</p>`;

  // LaTeX source for each section
  const latexSource = paperSections.length
    ? paperSections.map((s) => {
        const latex = s.latex || "";
        if (!latex) return "";
        return `<details class="latex-detail"><summary>${escapeHtml(s.title)} <span class="muted">(${s.word_count || 0} words)</span></summary><pre><code>${escapeHtml(latex)}</code></pre></details>`;
      }).filter(Boolean).join("")
    : `<pre>${escapeHtml(draft.latex || "% TODO — Quill draft")}</pre>`;

  manuscriptPanel.innerHTML = `
    <section class="research-hero meeting-hero">
      <div>
        <p class="eyebrow">Quill Manuscript Desk + Writing Skills</p>
        <h2>文章撰写：PRL-style English Draft</h2>
        <p>左侧：使用 <code>/write-section</code> 生成的文章段落。
        右侧：对应的 LaTeX 源码。
        使用 <code>/paper-review</code> 审核，<code>/paper-compile</code> 编译。</p>
      </div>
      <div class="research-stats">
        <span><strong>${paperData.section_count || 0}</strong>/5 sections</span>
        <span><strong>${paperData.reviewed_count || 0}</strong> reviewed</span>
        <span><strong>${paperData.total_words || 0}</strong> words</span>
        <span><strong>${progress.percent || "?"}%</strong> Quill</span>
      </div>
    </section>

    <!-- Paper Sections: Left=Content, Right=LaTeX -->
    <section class="manuscript-layout">
      <article class="research-card manuscript-source">
        ${agentHeading("Write", "英文生成草稿", "/write-section 命令基于毕业论文 + Eureka文献 + Quill草稿生成PRL风格英文。")}
        ${paperSectionList}
      </article>
      <article class="research-card manuscript-latex">
        ${agentHeading("LaTeX", "源码对照", "右侧为 .tex 文件源码，可直接复制到 Manuscript.tex 中使用。")}
        ${latexSource}
      </article>
    </section>

    <!-- Word Budget Bar -->
    <section class="research-card">
      ${agentHeading("Word", "PRL 词数预算", "各段落及其 PRL 目标词数。")}
      ${renderWordBudgetBar(paperSections, budgets)}
    </section>

    <!-- Writing Rules Check -->
    <section class="research-card">
      ${agentHeading("Rules", "写作规则遵守状态 (R1-R6)", "点击箭头展开各规则的详细说明。")}
      <div class="rules-grid">
        <div class="rule-item"><span class="rule-badge ok">R1</span> 数据保真</div>
        <div class="rule-item"><span class="rule-badge ok">R2</span> 文献支撑</div>
        <div class="rule-item"><span class="rule-badge ok">R3</span> 留白策略</div>
        <div class="rule-item"><span class="rule-badge ok">R4</span> PRL简洁</div>
        <div class="rule-item"><span class="rule-badge ok">R5</span> 双模型</div>
        <div class="rule-item"><span class="rule-badge ok">R6</span> 术语一致</div>
      </div>
    </section>

    <!-- Original Quill Draft (collapsible) -->
    <section class="research-card">
      ${agentHeading("Quill", "旧版 Quill 自动草稿 (参考)", "Quill 原始生成的四段草稿；已由 /write-section 深度重写和扩展。")}
      <details class="latex-detail">
        <summary>展开 Quill 自动草稿</summary>
        ${quillSections.length
          ? quillSections.map((s) => {
              const body = s.body || "";
              const missing = s.missing?.length ? `<p class="empty">${escapeHtml(s.missing.join("; "))}</p>` : "";
              return `<section class="manuscript-section"><h4>${escapeHtml(s.title || "Untitled")}</h4>${body ? `<p>${escapeHtml(body).replaceAll("\\n\\n", "</p><p>")}</p>` : missing}</section>`;
            }).join("")
          : "<p class=\"empty\">暂无 Quill 草稿</p>"
        }
      </details>
    </section>

    <!-- Reference files -->
    <section class="research-card">
      ${agentHeading("Files", "参考稿件", "library/manuscript 中的 PDF/TEX 参考。")}
      <div class="asset-list">
        ${
          refs.length
            ? refs.map((file) => `<a href="${encodeURI(file.path)}" target="_blank">${escapeHtml(file.name)}</a>`).join("")
            : "<span>暂无参考稿件；可将 PDF/TEX 放入 library/manuscript。</span>"
        }
      </div>
    </section>

    <!-- PRL Paper Figures -->
    ${renderPaperFigures(dashboardData.paper_figures || [])}
  `;
}

function renderPaperSectionCard(section, budgets) {
  const budget = budgets[section.name] || 0;
  const wc = section.word_count || 0;
  const over = budget && wc > budget;
  const statusIcon = section.reviewed ? "✅" : section.has_content ? "📝" : "⬜";
  const statusClass = section.reviewed ? "reviewed" : section.has_content ? "draft" : "empty";
  const bodyHtml = section.body
    ? `<div class="paper-body">${escapeHtml(section.body).replaceAll("\\n\\n", "</p><p>").replaceAll("\\n", "<br>")}</div>`
    : `<p class="empty">待撰写 — 使用 <code>/write-section ${section.name}</code></p>`;
  return `
    <section class="paper-section-card ${statusClass}">
      <div class="paper-section-header">
        <h4>${statusIcon} ${escapeHtml(section.title)}</h4>
        <span class="wc-badge ${over ? "over" : "ok"}">${wc} / ${budget || "-"} words</span>
      </div>
      ${bodyHtml}
    </section>
  `;
}

function renderWordBudgetBar(sections, budgets) {
  if (!sections.length) return "<p class=\"empty\">暂无数据。</p>";
  return sections.map((s) => {
    const budget = budgets[s.name] || 1;
    const wc = s.word_count || 0;
    const pct = Math.min(100, Math.round(wc / budget * 100));
    const over = wc > budget;
    const barColor = over ? "var(--red, #dc2626)" : pct > 80 ? "var(--amber, #d97706)" : "var(--green, #16a34a)";
    return `
      <div class="budget-row">
        <span class="budget-label">${escapeHtml(s.title)}</span>
        <div class="budget-bar-bg"><div class="budget-bar-fill" style="width:${pct}%;background:${barColor};"></div></div>
        <span class="budget-num ${over ? "over" : ""}">${wc}/${budget}</span>
      </div>
    `;
  }).join("");
}

function renderPaperFigures(paperFigures) {
  if (!paperFigures || !paperFigures.length) {
    return `<section class="research-card">
      ${agentHeading("Figures", "论文插图", "论文中使用的关键插图。使用 /paper-sync 后可刷新。")}
      <p class="empty">暂无插图索引。运行 <code>python dashboard_builder.py</code> 生成。</p>
    </section>`;
  }
  return `
    <section class="research-card">
      ${agentHeading("Figures", "论文插图 (PRL Fig. 1-4)", "从毕业论文提取并映射到各 Section 的关键插图。点击展开查看。")}
      <div class="figure-gallery">
        ${paperFigures.map((fig) => renderFigureCard(fig)).join("")}
      </div>
    </section>
  `;
}

function renderFigureCard(fig) {
  const files = fig.files || [];
  const assetsBase = "assets/paper_figures/";
  const images = files.map((f, i) => {
    const src = assetsBase + f;
    return `<figure class="fig-sub">
      <img src="${encodeURI(src)}" alt="Fig. ${fig.fig_num}${String.fromCharCode(97 + i)}" loading="lazy" onerror="this.style.display='none'" />
    </figure>`;
  }).join("");

  return `
    <details class="figure-detail" open>
      <summary>
        <strong>Fig. ${fig.fig_num}</strong> — ${escapeHtml(fig.label)}
        <span class="muted">(${files.length} panel${files.length > 1 ? "s" : ""}, Section: ${escapeHtml(fig.section)})</span>
      </summary>
      <div class="figure-panels">${images}</div>
      <figcaption class="figure-caption">${escapeHtml(fig.caption || "")}</figcaption>
    </details>
  `;
}

function renderManuscriptSection(section, key) {
  const body = section[key] || "";
  const missing = section.missing?.length ? `<p class="empty">${escapeHtml(section.missing.join("; "))}</p>` : "";
  return `
    <section class="manuscript-section">
      <h4>${escapeHtml(section.title || "Untitled")}</h4>
      ${body ? `<p>${escapeHtml(body).replaceAll("\n\n", "</p><p>")}</p>` : missing}
    </section>
  `;
}

function renderReferenceInline(ref) {
  const label = `${ref.year || "-"} · ${ref.title || "Untitled"}`;
  const href = referenceHref(ref);
  return href
    ? `<a href="${escapeHtml(href)}" target="_blank">${escapeHtml(label)}</a>`
    : escapeHtml(label);
}

function referenceHref(ref) {
  if (ref.doi) return `https://doi.org/${ref.doi}`;
  if (ref.link) return ref.link;
  const query = encodeURIComponent(ref.title || "");
  return query ? `https://scholar.google.com/scholar?q=${query}` : "";
}

function renderPaperCard(ref) {
  const href = referenceHref(ref);
  const note = ref.keywords || ref.method || ref.summary || "待补关键词/关键结果";
  const source = ref.origin === "recent_external" ? "近年补充" : ref.origin === "web_seed" ? "外部种子" : "library";
  const figure = ref.figure_url || "";
  return `
    <article class="paper-card">
      <div class="paper-figure">
        ${
          figure
            ? `<img src="${encodeURI(figure)}" alt="${escapeHtml(ref.title || "paper figure")}" loading="lazy" />`
            : `<span>${escapeHtml(ref.year || "-")}</span><strong>自动补图待生成</strong><small>运行 paper_figure_fetcher.py 可自动替换</small>`
        }
      </div>
      <div class="paper-body">
        <h4>${href ? `<a href="${escapeHtml(href)}" target="_blank">${escapeHtml(ref.title || "Untitled")}</a>` : escapeHtml(ref.title || "Untitled")}</h4>
        <p>${escapeHtml(note)}</p>
        <div class="paper-meta">
          <span>${escapeHtml(source)}</span>
          <a href="${escapeHtml(href)}" target="_blank">${ref.doi ? "DOI" : ref.link ? "主页" : "Scholar 检索"}</a>
        </div>
      </div>
    </article>
  `;
}

function filteredCases() {
  const query = searchInput.value.trim().toLowerCase();
  return dashboardData.cases.filter((item) => {
    const matchesStatus = activeStatus === "all" || item.status === activeStatus;
    const haystack = `${item.case_id} ${item.display_name}`.toLowerCase();
    return matchesStatus && (!query || haystack.includes(query));
  });
}

function renderCaseGrid() {
  const cases = filteredCases();
  caseGrid.innerHTML = cases
    .map((item) => {
      const score = scoreValue(item);
      const width = score === null ? 0 : Math.max(0, Math.min(100, score));
      const metrics = item.metrics || {};
      const material = metrics.material || "-";
      const rigid = isRigidBall(metrics);
      const acceleration = accelerationValue(metrics);
      const accelUnit = accelerationUnit(metrics);
      return `
        <article class="case-card ${cardTypeClass(metrics)} ${item.case_id === activeCaseId ? "selected" : ""}" data-case-id="${escapeHtml(item.case_id)}">
          ${previewMedia(item)}
          <div class="card-body">
            <div class="card-title-row">
              <h2 class="card-title">${escapeHtml(item.display_name)}</h2>
              <span class="status ${item.status}">${statusLabel(item.status)}</span>
            </div>
            <div class="score-row">
              <span class="score">${score === null ? "-" : score.toFixed(1)}</span>
              <div class="bar" aria-hidden="true"><span style="width:${width}%"></span></div>
            </div>
            <div class="mini-stats">
              <span>材料<strong>${escapeHtml(material)}</strong></span>
              <span>半径均值<strong>${fmt(metrics.radius_mean_mm, 3)} mm</strong></span>
              <span>加速度拟合<strong>${fmt(acceleration, 1)} ${accelUnit}</strong></span>
              ${rigid ? "" : `<span>频率<strong>${fmt(metrics.freq_mean_hz, 2)} Hz</strong></span>`}
              <span>版本数<strong>${item.run_count}</strong></span>
            </div>
          </div>
        </article>
      `;
    })
    .join("");

  caseGrid.querySelectorAll(".case-card").forEach((card) => {
    card.addEventListener("click", () => {
      activeCaseId = card.dataset.caseId;
      render();
    });
  });
}

function getActiveCase() {
  return dashboardData.cases.find((item) => item.case_id === activeCaseId) || dashboardData.cases[0];
}

function renderScoreParts(review, metrics = {}) {
  if (!review) return '<p class="empty">还没有可评分的处理输出。</p>';
  const parts = review.score_parts || {};
  const flags = review.flags?.length ? review.flags.join(", ") : "无";
  return `
    <dl class="kv">
      <dt>总分</dt><dd>${fmt(review.reviewer_score, 1)}</dd>
      <dt>等级</dt><dd>${escapeHtml(review.band || "-")}</dd>
      <dt>Tracking</dt><dd>${fmt(parts.tracking, 1)}</dd>
      <dt>半径稳定</dt><dd>${fmt(parts.radius_stability, 1)}</dd>
      <dt>拟合稳定</dt><dd>${fmt(parts.fit_stability, 1)}</dd>
      <dt>标记</dt><dd>${escapeHtml(flags)}</dd>
    </dl>
  `;
}

function renderMetrics(metrics) {
  const rigid = isRigidBall(metrics);
  const rigidItems = [
    ["material", "材料"],
    ["radius_mean_mm", "半径均值 mm"],
    ["velocity_abs_mean_mm_s", "|v| mm/s"],
    ["primary_quad_accel_mm_s2", "x-t 二次拟合加速度 mm/s²"],
    ["radius_rel_std_percent", "半径相对波动 %"],
    ["raw_radius_rel_std_percent", "修正前半径波动 %"],
    ["radius_correction_model", "R 修正模型"],
    ["radius_focus_camera_distance", "焦点等效距离"],
    ["center_step_outlier_count", "质心突变次数"],
    ["primary_axis", "主运动方向"],
  ];
  const dropletItems = [
    ["material", "材料"],
    ["radius_mean_mm", "半径均值 mm"],
    ["a_fit_osc_mean_mm_s2", "a_fit_osc 均值"],
    ["freq_mean_hz", "振荡频率 Hz"],
    ["radius_rel_std_percent", "半径相对波动 %"],
    ["n_fits", "拟合次数"],
  ];
  const items = rigid ? rigidItems : dropletItems;
  return `
    <dl class="kv">
      ${items
        .map(([key, label]) => {
          const raw = metrics[key];
          const value = typeof raw === "string" ? escapeHtml(raw) : fmt(raw, key.includes("count") || key === "n_fits" ? 0 : 3);
          return `<dt>${label}</dt><dd>${value}</dd>`;
        })
        .join("")}
    </dl>
  `;
}

function renderEureka(item) {
  const eureka = item.eureka;
  if (!eureka) return '<p class="empty">Eureka 暂无独立观察。</p>';
  const directions = (eureka.analysis_directions || [])
    .map((line) => `<li>${escapeHtml(line)}</li>`)
    .join("");
  const coordination = (eureka.franklin_coordination || [])
    .map((line) => `<li>${escapeHtml(line)}</li>`)
    .join("");
  const citations = (eureka.literature_matches || [])
    .slice(0, 4)
    .map((ref) => {
      const label = `${ref.year || "-"} · ${ref.title || "Untitled"}`;
      const href = ref.doi ? `https://doi.org/${ref.doi}` : ref.link;
      const source = ref.origin === "web_seed" ? "web seed" : ref.source || "library";
      const originalNote = ref.keywords || ref.method || ref.summary || "";
      return `<li>${href ? `<a href="${escapeHtml(href)}" target="_blank">${escapeHtml(label)}</a>` : escapeHtml(label)}<span>${escapeHtml(source)}</span>${originalNote ? `<small>${escapeHtml(originalNote)}</small>` : ""}</li>`;
    })
    .join("");
  const gaps = (eureka.literature_gaps || [])
    .map((line) => `<li>${escapeHtml(line)}</li>`)
    .join("");
  return `
    <div class="eureka-card">
      <div class="eureka-head">
        <strong>Eureka 独立观察</strong>
        <span>${fmt(eureka.confidence, 0)}%</span>
      </div>
      <p>${escapeHtml(eureka.phenomenon_summary || "-")}</p>
      ${directions ? `<h4>可分析方向</h4><ul>${directions}</ul>` : ""}
      ${coordination ? `<h4>给 Franklin 的质检配合</h4><ul>${coordination}</ul>` : ""}
      ${citations ? `<h4>相关文献</h4><ol class="citation-list">${citations}</ol>` : ""}
      ${gaps ? `<h4>文献缺口</h4><ul>${gaps}</ul>` : ""}
    </div>
  `;
}

function renderEurekaTraining(item) {
  const rec = item.agent_recommendation || item.review || {};
  const training = rec.eureka_training || item.review?.eureka_training;
  const applied = rec.eureka_applied_rules || item.review?.eureka_applied_rules || [];
  const notes = rec.eureka_training_notes || item.review?.eureka_training_notes || [];
  if (!training && !applied.length && !notes.length) {
    return '<p class="empty">暂无 Eureka 训练记录。</p>';
  }
  const rules = (training?.rules || [])
    .filter((rule) => rule.enabled)
    .map(
      (rule) => `
        <li>
          <strong>${escapeHtml(rule.id)}</strong>
          <span>${escapeHtml(rule.target)} · ${escapeHtml(rule.risk_level || "-")}</span>
          <small>触发：${escapeHtml(rule.trigger || "-")}</small>
          <small>影响：${escapeHtml(rule.score_effect || "-")}</small>
        </li>
      `,
    )
    .join("");
  const appliedRows = applied
    .map((rule) => `<li>${escapeHtml(rule.id)}：${fmt(rule.score_delta, 1)} 分，触发于 ${escapeHtml(rule.triggered_by || "-")}</li>`)
    .join("");
  const noteRows = notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("");
  return `
    <div class="training-box">
      <p>模式：${escapeHtml(training?.mode || "auditable_qc_rules_only")}</p>
      <p class="guardrail">权限边界：Eureka 只影响 Franklin 评分、复核优先级和重跑建议；处理参数、算法和代码修改必须由你确认后才执行。</p>
      ${appliedRows ? `<h4>本 Case 已应用</h4><ul>${appliedRows}</ul>` : ""}
      ${noteRows ? `<h4>给 Franklin 的提示</h4><ul>${noteRows}</ul>` : ""}
      ${rules ? `<h4>启用规则白名单</h4><ol>${rules}</ol>` : ""}
    </div>
  `;
}

function switchChecked(item, name) {
  const caseSwitch = item.switches || {};
  const defaults = dashboardData.switches.default_method || {};
  if (name === "paused") return Boolean(caseSwitch.paused);
  return caseSwitch[name] ?? defaults[name] ?? false;
}

function renderSwitches(item) {
  const switches = [
    ["paused", "暂停该 Case"],
    ["tracking_refinement", "启用形态学修正"],
    ["use_quad_osc_fit", "启用二次项 + 振荡拟合"],
    ["export_video", "导出监控视频"],
    ["review_after_processing", "处理后自动评分"],
  ];
  return `
    <div class="switches">
      ${switches
        .map(
          ([name, label]) => `
            <label class="switch-row">
              <span>${label}</span>
              <input type="checkbox" data-switch="${name}" ${switchChecked(item, name) ? "checked" : ""} />
            </label>
          `,
        )
        .join("")}
      <p class="save-status" id="saveStatus"></p>
    </div>
  `;
}

function renderReviewActions(item) {
  if (item.status !== "needs_review") return "";
  return `
    <div class="review-actions">
      <button type="button" data-case-action="rerun">一键重跑</button>
      <button type="button" data-case-action="confirm">确认通过</button>
      <p class="save-status" id="caseActionStatus"></p>
    </div>
  `;
}

function renderAssets(item) {
  const run = bestRun(item);
  if (!run) return '<p class="empty">还没有处理产物。</p>';
  const images = run.assets.images || [];
  const links = images.slice(0, 10);
  return `<div class="asset-list">${links.map((asset) => `<a href="${encodeURI(asset.url)}" target="_blank">${escapeHtml(asset.name)}</a>`).join("")}</div>`;
}

function renderProductLinks(item) {
  const summary = item.best_preview;
  const videos = candidateVideos(item);
  if (!summary && !videos.length) return "";
  return `
    <div class="product-links">
      <h3>处理产物</h3>
      <div>
        ${summary ? `<a href="${imageUrl(summary)}" target="_blank">Summary 图</a>` : ""}
        ${videos[0] ? `<a href="${encodeURI(videos[0].url)}" target="_blank">追踪视频</a>` : ""}
      </div>
    </div>
  `;
}

function renderAgentRecommendation(item) {
  const rec = item.agent_recommendation;
  if (!rec) return '<p class="empty">还没有自动循环生成的复核建议。</p>';
  const flags = rec.flags?.length ? rec.flags.join(", ") : "无";
  const assumptions = rec.assumptions?.length ? rec.assumptions.join(", ") : "无";
  return `
    <dl class="kv">
      <dt>生成时间</dt><dd>${escapeHtml(rec.created_at || "-")}</dd>
      <dt>自动评分</dt><dd>${fmt(rec.reviewer_score, 1)}</dd>
      <dt>记忆修正</dt><dd>${fmt(rec.memory_score_adjustment, 1)}</dd>
      <dt>等级</dt><dd>${escapeHtml(rec.band || "-")}</dd>
      <dt>标记</dt><dd>${escapeHtml(flags)}</dd>
      <dt>默认假设</dt><dd>${escapeHtml(assumptions)}</dd>
    </dl>
    <p class="recommendation">${escapeHtml(rec.recommended_next_action || "-")}</p>
  `;
}

function renderAutoSelection(item) {
  const auto = item.metrics?.auto_selection;
  if (!auto) return '<p class="empty">没有自动 ROI / Vfr 候选记录。</p>';
  const selected = auto.selected_roi || {};
  const vfr = auto.selected_valid_frame_range || [];
  const candidates = auto.candidates || [];
  return `
    <dl class="kv">
      <dt>选中 ROI</dt><dd>${selected.x ?? "-"},${selected.y ?? "-"},${selected.w ?? "-"},${selected.h ?? "-"}</dd>
      <dt>选中 Vfr</dt><dd>${vfr.join(",") || "-"}</dd>
      <dt>候选数</dt><dd>${candidates.length}</dd>
      <dt>候选分</dt><dd>${fmt(auto.selected_score, 1)}</dd>
    </dl>
  `;
}

function renderPhaseDetail(item) {
  const point = phasePoints().find((entry) => entry.case_id === item.case_id);
  if (!point) return '<p class="empty">该 Case 暂无相图数据。</p>';
  return `
    <dl class="kv">
      <dt>R</dt><dd>${fmt(point.radius_mm, 3)} mm</dd>
      <dt>|v|</dt><dd>${fmt(point.velocity_abs_mm_s, 1)} mm/s</dd>
      <dt>|a|</dt><dd>${fmt(point.accel_abs_mm_s2, 1)} mm/s²</dd>
      <dt>|a| / g</dt><dd>${fmt(point.accel_g, 3)}</dd>
      <dt>预留 Re</dt><dd>${fmt(point.re)}</dd>
      <dt>预留 We</dt><dd>${fmt(point.we)}</dd>
    </dl>
  `;
}

function renderDetail() {
  const item = getActiveCase();
  if (!item) {
    detailPanel.innerHTML = '<p class="empty">还没有找到 Case。先把原始数据放进 raw_data，再点击重新扫描。</p>';
    return;
  }
  detailPanel.innerHTML = `
    <h2>${escapeHtml(item.display_name)}</h2>
    ${agentHeading("Sisyphus", "当前 Case 处理产物", "展示自动循环生成的 summary、追踪产物、复核入口和处理文件链接。")}
    ${previewMedia(item, "detail-image")}
    ${renderProductLinks(item)}
    ${renderReviewActions(item)}
    <div class="detail-section">
      ${renderEureka(item)}
    </div>
    <div class="detail-section">
      ${agentHeading("Franklin", "质量评分与复核", "检查 tracking 完整度、半径稳定、拟合稳定和异常标记。")}
      ${renderScoreParts(item.review, item.metrics || {})}
    </div>
    <div class="detail-section">
      ${agentHeading("Franklin", "复核规则与经验约束", "接收已确认的经验/文献约束，只影响评分和复核优先级。")}
      ${renderEurekaTraining(item)}
    </div>
    <div class="detail-section">
      ${agentHeading("Sisyphus", "核心指标提取", "汇总自动追踪得到的 R、v、a、有效帧和材料识别结果。")}
      ${renderMetrics(item.metrics || {})}
    </div>
    <div class="detail-section">
      ${agentHeading("Sisyphus", "相图数据出口", "把当前 Case 的 R、|v|、|a|/g 送入后续相图与无量纲数分析。")}
      ${renderPhaseDetail(item)}
    </div>
    <details class="detail-section advanced-detail">
      <summary>高级诊断与工程信息</summary>
      ${agentHeading("Sisyphus", "工程诊断与处理开关", "保留自动循环、ROI/Vfr 和产物链接，供需要时排查。")}
      <h3>处理开关</h3>
      ${renderSwitches(item)}
      <h3>自动循环建议</h3>
      ${renderAgentRecommendation(item)}
      <h3>自动 ROI / Vfr</h3>
      ${renderAutoSelection(item)}
      <h3>图像与视频</h3>
      ${renderAssets(item)}
    </details>
  `;

  detailPanel.querySelectorAll("input[data-switch]").forEach((input) => {
    input.addEventListener("change", () => updateCaseSwitch(item.case_id, input.dataset.switch, input.checked));
  });
  detailPanel.querySelectorAll("button[data-case-action]").forEach((button) => {
    button.addEventListener("click", () => runCaseAction(item.case_id, button.dataset.caseAction));
  });
}

async function updateCaseSwitch(caseId, key, value) {
  const statusEl = document.querySelector("#saveStatus");
  const switches = structuredClone(dashboardData.switches);
  switches.cases ||= {};
  switches.cases[caseId] ||= {};
  switches.cases[caseId][key] = value;
  statusEl.textContent = "保存中...";
  const response = await fetch("/api/switches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(switches),
  });
  if (!response.ok) {
    statusEl.textContent = "保存失败，请检查本地服务是否运行。";
    return;
  }
  statusEl.textContent = "已保存";
  await loadData();
}

async function runCaseAction(caseId, action) {
  const statusEl = document.querySelector("#caseActionStatus");
  if (statusEl) statusEl.textContent = action === "confirm" ? "确认中..." : "已发送重跑请求...";
  const response = await fetch("/api/case-action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_id: caseId, action }),
  });
  if (!response.ok) {
    if (statusEl) statusEl.textContent = "操作失败，请检查 run_dashboard.py 服务。";
    return;
  }
  await loadData();
}

function render() {
  document.querySelectorAll(".page-tab").forEach((item) => {
    const active = item.dataset.page === activePage;
    item.classList.toggle("active", active);
  });
  document.querySelectorAll("[data-page-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.pagePanel === activePage);
  });
  document.querySelectorAll(".filter").forEach((item) => {
    item.classList.toggle("active", item.dataset.status === activeStatus);
  });
  renderSummary();
  renderPaperProgress();
  renderHistoryMemo();
  renderPhaseSpace();
  renderShowcasePage();
  renderDataAgentDesk();
  renderLiteraturePage();
  renderManuscriptPage();
  renderCaseGrid();
  renderDetail();
  startVideos();
}

document.querySelectorAll(".page-tab").forEach((button) => {
  button.addEventListener("click", () => {
    activePage = button.dataset.page || "console";
    render();
  });
});

document.querySelectorAll(".filter").forEach((button) => {
  button.addEventListener("click", () => {
    activeStatus = button.dataset.status;
    activeCaseId = (filteredCases()[0] || dashboardData.cases[0])?.case_id ?? null;
    render();
  });
});

searchInput.addEventListener("input", () => {
  activeCaseId = (filteredCases()[0] || dashboardData.cases[0])?.case_id ?? null;
  render();
});

rebuildBtn.addEventListener("click", async () => {
  rebuildBtn.disabled = true;
  rebuildBtn.textContent = "扫描中...";
  await fetch("/api/rebuild", { cache: "no-store" });
  await loadData();
  rebuildBtn.disabled = false;
  rebuildBtn.textContent = "重新扫描";
});

exportSwitchesBtn.addEventListener("click", () => {
  switchExport.value = JSON.stringify(dashboardData.switches, null, 2);
  switchDialog.showModal();
});

loadData(false).catch((error) => {
  caseGrid.innerHTML = `<p class="empty">看板数据读取失败：${escapeHtml(error.message)}</p>`;
});
