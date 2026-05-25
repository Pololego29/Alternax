/**
 * app.js
 * Gère l'affichage des offres, les filtres, la pagination,
 * le mini-dashboard et la communication avec l'API FastAPI.
 */

const API = typeof API_URL !== "undefined" ? API_URL : "http://localhost:8000/api";
let currentPage  = 1;
let currentTech  = "";          // tag tech actif (ex: "Python")
let debounceTimer = null;

// =============================================================================
// INITIALISATION
// =============================================================================

document.addEventListener("DOMContentLoaded", () => {
  loadStats();
  loadSources();
  loadDashboard();
  loadOffers(1);
});

// =============================================================================
// STATS (barre du haut)
// =============================================================================

async function loadStats() {
  const data = await fetchJson(`${API}/stats`);
  if (!data) return;

  document.getElementById("stat-total").textContent = data.total.toLocaleString("fr-FR");

  // Badge par source
  const sourcesEl = document.getElementById("stat-sources");
  sourcesEl.innerHTML = Object.entries(data.by_source)
    .map(([src, count]) => `
      <div>
        <span class="opacity-75 capitalize">${src.replace("_", " ")}</span>
        <span class="ml-1 font-semibold">${count.toLocaleString("fr-FR")}</span>
      </div>
    `).join("");

  // Dernière collecte
  const raw = data.last_scrape;
  const lastEl = document.getElementById("stat-last");
  if (raw && raw !== "Jamais") {
    const d = new Date(raw);
    lastEl.textContent = d.toLocaleString("fr-FR", {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"
    });
  } else {
    lastEl.textContent = "Jamais";
  }
}

// =============================================================================
// DASHBOARD (top entreprises, lieux, technos, sources)
// =============================================================================

async function loadDashboard() {
  const data = await fetchJson(`${API}/dashboard?limit=5`);
  if (!data) return;

  renderDashList("dash-companies", data.top_companies);
  renderDashList("dash-locations", data.top_locations);
  renderDashList("dash-techs",     data.top_techs,    true);  // clickable
  renderDashList("dash-sources",   data.by_source);
}

function renderDashList(elementId, items, clickable = false) {
  const el = document.getElementById(elementId);
  if (!el) return;
  if (!items || items.length === 0) {
    el.innerHTML = `<li class="text-xs text-gray-400 italic">Aucune donnée</li>`;
    return;
  }
  const max = Math.max(...items.map(i => i.count));

  el.innerHTML = items.map(item => {
    const width = max > 0 ? (item.count / max) * 100 : 0;
    const onclick = clickable ? `onclick="filterByTech('${escapeAttr(item.name)}')"` : "";
    const cls     = clickable ? "dash-item-clickable" : "";
    return `
      <li class="dash-item ${cls}" style="--bar-width: ${width}%" ${onclick}>
        <span class="dash-name">${escapeHtml(item.name)}</span>
        <span class="dash-count">${item.count.toLocaleString("fr-FR")}</span>
      </li>
    `;
  }).join("");
}

// =============================================================================
// SOURCES (pour le select)
// =============================================================================

async function loadSources() {
  const sources = await fetchJson(`${API}/sources`);
  if (!sources) return;

  const select = document.getElementById("source");
  // On nettoie sauf l'option par défaut
  while (select.options.length > 1) select.remove(1);

  sources.forEach(src => {
    const opt = document.createElement("option");
    opt.value = src;
    opt.textContent = src.charAt(0).toUpperCase() + src.slice(1).replace("_", " ");
    select.appendChild(opt);
  });
}

// =============================================================================
// OFFRES
// =============================================================================

async function loadOffers(page = 1) {
  currentPage = page;
  showLoading(true);

  const search   = document.getElementById("search").value.trim();
  const location = document.getElementById("location").value.trim();
  const source   = document.getElementById("source").value;

  const params = new URLSearchParams({ page, per_page: 20 });
  if (search)      params.set("search",   search);
  if (location)    params.set("location", location);
  if (source)      params.set("source",   source);
  if (currentTech) params.set("tech",     currentTech);

  const data = await fetchJson(`${API}/offres?${params}`);
  showLoading(false);

  if (!data) return;

  const grid  = document.getElementById("offers-grid");
  const empty = document.getElementById("empty-state");
  const count = document.getElementById("result-count");

  if (data.offers.length === 0) {
    grid.innerHTML = "";
    empty.classList.remove("hidden");
    count.textContent = "";
  } else {
    empty.classList.add("hidden");
    count.textContent = `${data.total.toLocaleString("fr-FR")} offres trouvées`;
    grid.innerHTML = data.offers.map(renderCard).join("");
  }

  renderPagination(data.page, data.pages);
}

// =============================================================================
// RENDU D'UNE CARTE
// =============================================================================

function renderCard(offer) {
  const salary = offer.salary
    ? `<span>💰 ${escapeHtml(offer.salary)}</span>`
    : "";

  const date = offer.scraped_at
    ? `<span>🕐 ${formatDate(offer.scraped_at)}</span>`
    : "";

  const desc = offer.description
    ? `<p class="offer-description">${escapeHtml(offer.description)}</p>`
    : "";

  // Tags techniques (clickables pour filtrer)
  const tags = Array.isArray(offer.tech_tags) && offer.tech_tags.length > 0
    ? `<div class="offer-tags">
         ${offer.tech_tags.map(tag => `
           <button class="tech-tag ${tag === currentTech ? "active" : ""}"
                   onclick="event.stopPropagation(); filterByTech('${escapeAttr(tag)}')">
             ${escapeHtml(tag)}
           </button>
         `).join("")}
       </div>`
    : "";

  return `
    <div class="offer-card">
      <div>
        <p class="offer-title">${escapeHtml(offer.title)}</p>
        <p class="offer-company">${escapeHtml(offer.company || "Entreprise non précisée")}</p>
      </div>
      <div class="offer-meta">
        ${offer.location ? `<span>📍 ${escapeHtml(offer.location)}</span>` : ""}
        ${salary}
        ${date}
      </div>
      ${desc}
      ${tags}
      <div class="offer-footer">
        <span class="source-badge">${escapeHtml(offer.source)}</span>
        ${offer.url
          ? `<a href="${escapeAttr(offer.url)}" target="_blank" rel="noopener" class="offer-link">Voir l'offre →</a>`
          : ""}
      </div>
    </div>
  `;
}

// =============================================================================
// FILTRE PAR TAG TECHNIQUE
// =============================================================================

function filterByTech(tag) {
  // Toggle : si on clique sur le tag déjà actif, on le désactive
  currentTech = (currentTech === tag) ? "" : tag;
  renderTechFilterChip();
  loadOffers(1);
  window.scrollTo({ top: document.getElementById("offers-grid").offsetTop - 100, behavior: "smooth" });
}

function clearTechFilter() {
  currentTech = "";
  renderTechFilterChip();
  loadOffers(1);
}

function renderTechFilterChip() {
  const wrapper = document.getElementById("active-filters");
  const label   = document.getElementById("tech-filter-label");
  if (currentTech) {
    label.textContent = currentTech;
    wrapper.classList.remove("hidden");
    wrapper.classList.add("flex");
  } else {
    wrapper.classList.add("hidden");
    wrapper.classList.remove("flex");
  }
}

// =============================================================================
// PAGINATION
// =============================================================================

function renderPagination(page, totalPages) {
  const el = document.getElementById("pagination");
  if (totalPages <= 1) { el.innerHTML = ""; return; }

  const buttons = [];

  if (page > 1) {
    buttons.push(btn("←", page - 1));
  }

  const range = pagesRange(page, totalPages);
  range.forEach(p => {
    if (p === "...") {
      buttons.push(`<span class="px-2 text-gray-400">…</span>`);
    } else {
      buttons.push(btn(p, p, p === page));
    }
  });

  if (page < totalPages) {
    buttons.push(btn("→", page + 1));
  }

  el.innerHTML = buttons.join("");
}

function btn(label, page, active = false) {
  return `<button class="page-btn ${active ? "active" : ""}" onclick="loadOffers(${page})">${label}</button>`;
}

function pagesRange(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  if (current <= 4) return [1, 2, 3, 4, 5, "...", total];
  if (current >= total - 3) return [1, "...", total-4, total-3, total-2, total-1, total];
  return [1, "...", current-1, current, current+1, "...", total];
}

// =============================================================================
// ACTIONS
// =============================================================================

function debouncedSearch() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => loadOffers(1), 400);
}

function resetFilters() {
  document.getElementById("search").value   = "";
  document.getElementById("location").value = "";
  document.getElementById("source").value   = "";
  currentTech = "";
  renderTechFilterChip();
  loadOffers(1);
}

function refresh() {
  loadStats();
  loadSources();
  loadDashboard();
  loadOffers(currentPage);
  showToast("Données actualisées");
}

// =============================================================================
// UTILITAIRES
// =============================================================================

async function fetchJson(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.error("Erreur API :", e);
    return null;
  }
}

function showLoading(show) {
  document.getElementById("loading").classList.toggle("hidden", !show);
  document.getElementById("offers-grid").classList.toggle("hidden", show);
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(str) {
  return String(str ?? "")
    .replace(/'/g, "\\'")
    .replace(/"/g, "&quot;");
}

function showToast(msg) {
  let toast = document.querySelector(".toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.className = "toast";
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 4000);
}