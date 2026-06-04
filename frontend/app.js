/**
 * app.js
 * Gère l'affichage des offres, les filtres, la pagination,
 * le mini-dashboard et la communication avec l'API FastAPI.
 */

const API = typeof API_URL !== "undefined" ? API_URL : "http://localhost:8000/api";
let currentPage  = 1;
let currentTech  = "";          // tag tech actif (ex: "Python")
let debounceTimer = null;

// --- État connexion / favoris ---
let authToken   = localStorage.getItem("alternax_token") || "";
let authEmail   = localStorage.getItem("alternax_email") || "";
let favoriteIds = new Set();    // ids des offres en favori (utilisateur connecté)
let authMode    = "login";      // "login" | "register" (modale)
let viewMode    = "all";        // "all" | "favorites"
let lastOffers  = [];           // offres actuellement affichées (pour re-rendu local)

// =============================================================================
// INITIALISATION
// =============================================================================

document.addEventListener("DOMContentLoaded", async () => {
  applyAuthMode();
  renderAuthUI();
  loadStats();
  loadSources();
  loadDashboard();
  await loadOffers(1);
  restoreSession();   // valide le token et charge les favoris si déjà connecté
});

// Fermer la modale avec la touche Échap
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeAuthModal();
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
  viewMode = "all";
  updateFavToggleUI();
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

  lastOffers = data.offers;
  showResults(data.offers, {
    count: data.offers.length ? `${data.total.toLocaleString("fr-FR")} offres trouvées` : "",
    emptyTitle: "Aucune offre trouvée",
    emptySubtitle: "Essayez d'élargir vos filtres",
  });

  renderPagination(data.page, data.pages);
}

/** Affiche une liste d'offres (ou l'état vide) dans la grille. */
function showResults(offers, { count, emptyTitle, emptySubtitle }) {
  const grid  = document.getElementById("offers-grid");
  const empty = document.getElementById("empty-state");
  const countEl = document.getElementById("result-count");

  if (!offers || offers.length === 0) {
    grid.innerHTML = "";
    document.getElementById("empty-title").textContent    = emptyTitle;
    document.getElementById("empty-subtitle").textContent = emptySubtitle;
    empty.classList.remove("hidden");
    countEl.textContent = "";
  } else {
    empty.classList.add("hidden");
    countEl.textContent = count;
    grid.innerHTML = offers.map(renderCard).join("");
  }
}

/** Re-rend les cartes actuellement affichées (ex. pour mettre à jour les cœurs). */
function rerenderCards() {
  if (lastOffers.length === 0) return;
  document.getElementById("offers-grid").innerHTML = lastOffers.map(renderCard).join("");
}

// =============================================================================
// RENDU D'UNE CARTE
// =============================================================================

function renderCard(offer) {
  const salary = offer.salary
    ? `<span>${escapeHtml(offer.salary)}</span>`
    : "";

  const date = offer.scraped_at
    ? `<span>${formatDate(offer.scraped_at)}</span>`
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

  const isFav = favoriteIds.has(offer.id);
  const favBtn = `
    <button class="fav-btn ${isFav ? "is-fav" : ""}"
            onclick="toggleFavorite(${offer.id}, this)"
            title="${isFav ? "Retirer des favoris" : "Ajouter aux favoris"}"
            aria-label="Favori">${isFav ? "♥" : "♡"}</button>`;

  return `
    <div class="offer-card">
      <div class="offer-head">
        <div class="offer-head-text">
          <p class="offer-title">${escapeHtml(offer.title)}</p>
          <p class="offer-company">${escapeHtml(offer.company || "Entreprise non précisée")}</p>
        </div>
        ${favBtn}
      </div>
      <div class="offer-meta">
        ${offer.location ? `<span>${escapeHtml(offer.location)}</span>` : ""}
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

async function fetchJson(url, options = {}) {
  try {
    const res = await fetch(url, options);
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

// =============================================================================
// AUTHENTIFICATION (connexion / inscription)
// =============================================================================

function authHeaders() {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {};
}

/** Met à jour l'affichage header selon l'état connecté/déconnecté. */
function renderAuthUI() {
  const loggedIn = !!authToken;
  document.getElementById("auth-logged-out").classList.toggle("hidden", loggedIn);

  const inEl = document.getElementById("auth-logged-in");
  inEl.classList.toggle("hidden", !loggedIn);
  inEl.classList.toggle("flex", loggedIn);

  document.getElementById("user-email").textContent = authEmail;
}

function setSession(token, email) {
  authToken = token;
  authEmail = email;
  localStorage.setItem("alternax_token", token);
  localStorage.setItem("alternax_email", email);
  renderAuthUI();
}

function clearSession() {
  authToken = "";
  authEmail = "";
  favoriteIds = new Set();
  localStorage.removeItem("alternax_token");
  localStorage.removeItem("alternax_email");
  renderAuthUI();
}

/** Au chargement : si un token existe, on le valide et on charge les favoris. */
async function restoreSession() {
  if (!authToken) { renderAuthUI(); return; }
  const me = await fetchJson(`${API}/me`, { headers: authHeaders() });
  if (!me) { clearSession(); return; }   // token invalide/expiré
  authEmail = me.email;
  localStorage.setItem("alternax_email", me.email);
  renderAuthUI();
  await loadFavoriteIds();
}

// --- Modale ---

function openAuthModal() {
  document.getElementById("auth-error").classList.add("hidden");
  document.getElementById("auth-modal").classList.remove("hidden");
  document.getElementById("auth-email").focus();
}

function closeAuthModal() {
  document.getElementById("auth-modal").classList.add("hidden");
}

function toggleAuthMode() {
  authMode = authMode === "login" ? "register" : "login";
  applyAuthMode();
}

/** Adapte les libellés de la modale selon le mode connexion/inscription. */
function applyAuthMode() {
  const isLogin = authMode === "login";
  document.getElementById("auth-title").textContent     = isLogin ? "Connexion" : "Créer un compte";
  document.getElementById("auth-subtitle").textContent  = isLogin
    ? "Connecte-toi pour retrouver tes offres favorites."
    : "Crée un compte pour sauvegarder tes offres favorites.";
  document.getElementById("auth-submit").textContent      = isLogin ? "Se connecter" : "Créer mon compte";
  document.getElementById("auth-switch-text").textContent = isLogin ? "Pas encore de compte ?" : "Déjà un compte ?";
  document.getElementById("auth-switch-btn").textContent  = isLogin ? "Créer un compte" : "Se connecter";
  document.getElementById("auth-password").autocomplete   = isLogin ? "current-password" : "new-password";
  document.getElementById("auth-error").classList.add("hidden");
}

async function submitAuth(event) {
  event.preventDefault();
  const email    = document.getElementById("auth-email").value.trim();
  const password = document.getElementById("auth-password").value;
  const errEl    = document.getElementById("auth-error");
  const submitBtn = document.getElementById("auth-submit");
  errEl.classList.add("hidden");
  submitBtn.disabled = true;

  const endpoint = authMode === "login" ? "login" : "register";
  let res;
  try {
    res = await fetch(`${API}/auth/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch (e) {
    errEl.textContent = "Impossible de joindre le serveur.";
    errEl.classList.remove("hidden");
    submitBtn.disabled = false;
    return;
  }

  const data = await res.json().catch(() => ({}));
  submitBtn.disabled = false;

  if (!res.ok) {
    errEl.textContent = data.detail || "Une erreur est survenue.";
    errEl.classList.remove("hidden");
    return;
  }

  setSession(data.token, data.email);
  closeAuthModal();
  document.getElementById("auth-form").reset();
  await loadFavoriteIds();
  showToast(authMode === "login" ? "Connecté ✓" : "Compte créé, bienvenue !");
}

async function logout() {
  try {
    await fetch(`${API}/auth/logout`, { method: "POST", headers: authHeaders() });
  } catch (e) { /* on déconnecte côté client quoi qu'il arrive */ }
  clearSession();
  if (viewMode === "favorites") {
    loadOffers(1);          // on quitte la vue favoris
  } else {
    rerenderCards();        // les cœurs repassent à vide
  }
  showToast("Déconnecté");
}

// =============================================================================
// FAVORIS
// =============================================================================

/** Charge l'ensemble des ids favoris (et rafraîchit les cœurs visibles). */
async function loadFavoriteIds() {
  if (!authToken) return;
  const data = await fetchJson(`${API}/favorites`, { headers: authHeaders() });
  if (!data) return;
  favoriteIds = new Set(data.ids);
  if (viewMode === "all") rerenderCards();
}

/** Ajoute / retire une offre des favoris (nécessite d'être connecté). */
async function toggleFavorite(offerId, btnEl) {
  if (!authToken) {
    showToast("Connecte-toi pour sauvegarder des favoris");
    openAuthModal();
    return;
  }

  const isFav  = favoriteIds.has(offerId);
  const method = isFav ? "DELETE" : "POST";

  let res;
  try {
    res = await fetch(`${API}/favorites/${offerId}`, { method, headers: authHeaders() });
  } catch (e) {
    showToast("Erreur réseau, réessaie");
    return;
  }
  if (!res.ok) { showToast("Erreur, réessaie"); return; }

  if (isFav) favoriteIds.delete(offerId);
  else       favoriteIds.add(offerId);

  if (viewMode === "favorites" && isFav) {
    // On vient de retirer un favori → on l'enlève de la liste affichée.
    lastOffers = lastOffers.filter(o => o.id !== offerId);
    showResults(lastOffers, {
      count: favCountLabel(lastOffers.length),
      emptyTitle: "Aucun favori pour l'instant",
      emptySubtitle: "Clique sur le ♥ d'une offre pour la sauvegarder ici.",
    });
  } else {
    updateFavButton(btnEl, !isFav);
  }
}

function updateFavButton(btn, isFav) {
  if (!btn) return;
  btn.classList.toggle("is-fav", isFav);
  btn.textContent = isFav ? "♥" : "♡";
  btn.title = isFav ? "Retirer des favoris" : "Ajouter aux favoris";
}

/** Bascule entre la vue "toutes les offres" et la vue "mes favoris". */
function toggleFavoritesView() {
  if (viewMode === "favorites") loadOffers(1);
  else                          loadFavoritesView();
}

async function loadFavoritesView() {
  viewMode = "favorites";
  updateFavToggleUI();
  showLoading(true);

  const data = await fetchJson(`${API}/favorites`, { headers: authHeaders() });
  showLoading(false);
  if (!data) return;

  favoriteIds = new Set(data.ids);
  lastOffers  = data.offers;
  document.getElementById("pagination").innerHTML = "";

  showResults(data.offers, {
    count: favCountLabel(data.offers.length),
    emptyTitle: "Aucun favori pour l'instant",
    emptySubtitle: "Clique sur le ♥ d'une offre pour la sauvegarder ici.",
  });
}

function favCountLabel(n) {
  return n === 0 ? "" : `${n} favori${n > 1 ? "s" : ""}`;
}

function updateFavToggleUI() {
  const btn = document.getElementById("fav-toggle");
  if (btn) btn.classList.toggle("fav-toggle-active", viewMode === "favorites");
}