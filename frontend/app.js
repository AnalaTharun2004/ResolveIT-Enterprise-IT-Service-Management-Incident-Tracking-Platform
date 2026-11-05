const API = "/api/v1";
const STATUSES = ["OPEN", "ASSIGNED", "IN_PROGRESS", "WAITING_FOR_USER", "RESOLVED", "CLOSED"];
const PRIORITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
const state = {
  token: localStorage.getItem("resolveit_token"),
  user: null,
  page: "dashboard",
  ticketPage: 1,
  pageSize: 10,
  filters: {},
  assetPage: 1,
  assetSearch: "",
  notificationPage: 1,
  currentTicket: null,
  categories: [],
  supportUsers: [],
};
let toastTimer;
let globalSearchTimer;
let globalSearchSequence = 0;

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const titleCase = (value) => String(value || "").replaceAll("_", " ").toLowerCase()
  .replace(/\b\w/g, (letter) => letter.toUpperCase());
const formatDate = (value) => value
  ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
  : "—";
const roleLabel = (role) => ({ ADMIN: "Administrator", AGENT: "Support engineer", USER: "Employee" }[role] || role);

function showToast(message, isError = false) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
}

function loadingMarkup(message = "Loading") {
  return `<div class="loading-state" role="status"><span class="spinner" aria-hidden="true"></span><span>${escapeHtml(message)}</span></div>`;
}

function setButtonBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    button.dataset.idleLabel = button.textContent;
    button.textContent = label;
  } else {
    button.textContent = button.dataset.idleLabel || button.textContent;
    delete button.dataset.idleLabel;
  }
  button.disabled = busy;
  button.setAttribute("aria-busy", String(busy));
}

function confirmAction(title, message, confirmLabel = "Confirm") {
  const dialog = document.querySelector("#confirm-dialog");
  document.querySelector("#confirm-title").textContent = title;
  document.querySelector("#confirm-message").textContent = message;
  const accept = document.querySelector("#confirm-accept");
  accept.textContent = confirmLabel;
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
  });
}

function validateTrimmedText(form, names) {
  for (const name of names) {
    const field = form.elements.namedItem(name);
    if (field) field.setCustomValidity(field.value.trim() ? "" : "Please enter a value that is not only spaces.");
  }
  return form.reportValidity();
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let response;
  try {
    response = await fetch(`${API}${path}`, { ...options, headers });
  } catch {
    throw new Error("Cannot reach ResolveIT. Check that the server is running.");
  }
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    if (response.status === 401 && state.token) signOut(false);
    const detail = body?.detail;
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join(", ") : (detail || `Request failed (${response.status})`));
  }
  return body;
}

function setAuthMode(mode) {
  const registering = mode === "register";
  document.querySelectorAll(".auth-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.authMode === mode));
  document.querySelector("#name-field").classList.toggle("hidden", !registering);
  document.querySelector("#auth-eyebrow").textContent = registering ? "GET STARTED" : "WELCOME BACK";
  document.querySelector("#auth-title").textContent = registering ? "Create your account" : "Sign in to your account";
  document.querySelector("#auth-subtitle").textContent = registering
    ? "Register to submit and track your IT requests."
    : "Access your support requests and updates.";
  document.querySelector("#auth-submit").textContent = registering ? "Create account" : "Sign in";
  document.querySelector("#auth-form [name=password]").autocomplete = registering ? "new-password" : "current-password";
  document.querySelector("#auth-error").textContent = "";
  document.querySelector("#auth-form").dataset.mode = mode;
}

async function handleAuth(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  const error = document.querySelector("#auth-error");
  const button = document.querySelector("#auth-submit");
  error.textContent = "";
  button.disabled = true;
  try {
    if (form.dataset.mode === "register") {
      await request("/auth/register", {
        method: "POST",
        body: JSON.stringify({ name: data.name, email: data.email, password: data.password }),
      });
      setAuthMode("login");
      form.elements.password.value = "";
      showToast("Account created. You can now sign in.");
      return;
    }
    const result = await request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: data.email, password: data.password }),
    });
    state.token = result.access_token;
    state.user = result.user;
    localStorage.setItem("resolveit_token", state.token);
    form.reset();
    showWorkspace();
  } catch (err) {
    error.textContent = err.message;
  } finally {
    button.disabled = false;
  }
}

function signOut(showMessage = true) {
  state.token = null;
  state.user = null;
  state.currentTicket = null;
  localStorage.removeItem("resolveit_token");
  document.querySelector("#app-view").classList.add("hidden");
  document.querySelector("#auth-view").classList.remove("hidden");
  if (showMessage) showToast("You have signed out.");
}

async function showWorkspace() {
  document.querySelector("#auth-view").classList.add("hidden");
  document.querySelector("#app-view").classList.remove("hidden");
  document.querySelector("#profile-name").textContent = state.user.name;
  document.querySelector("#profile-role").textContent = roleLabel(state.user.role);
  document.querySelector("#profile-avatar").textContent = state.user.name.trim().charAt(0).toUpperCase();
  document.querySelector("#admin-nav").classList.toggle("hidden", state.user.role !== "ADMIN");
  document.querySelector("#topbar-date").textContent = new Intl.DateTimeFormat(undefined, { dateStyle: "full" }).format(new Date());
  try {
    state.categories = await request("/categories");
    const notifications = await request("/notifications?limit=50");
    document.querySelector("#notification-dot").classList.toggle("hidden", !notifications.some((item) => !item.is_read));
  } catch (err) {
    showToast(err.message, true);
  }
  await navigate("dashboard");
}

const pageNames = {
  dashboard: "Overview",
  tickets: "Tickets",
  "new-ticket": "Create request",
  detail: "Ticket details",
  admin: "Administration",
  assets: "Assets",
  notifications: "Notifications",
};

async function navigate(page) {
  if (page === "admin" && state.user.role !== "ADMIN") return;
  state.page = page;
  document.querySelectorAll(".nav-link").forEach((link) => {
    const active = link.dataset.page === page;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  document.querySelector("#page-title").textContent = pageNames[page] || "Overview";
  if (page === "dashboard") return renderDashboard();
  if (page === "tickets") return renderTickets();
  if (page === "new-ticket") return renderNewTicket();
  if (page === "assets") return renderAssets();
  if (page === "admin") return renderAdmin();
  if (page === "notifications") return renderNotifications();
  if (page === "detail" && state.currentTicket) return renderTicketDetail(state.currentTicket.id);
}

function heading(title, description, action = "") {
  return `<div class="page-heading"><div><h1>${escapeHtml(title)}</h1><p>${escapeHtml(description)}</p></div>${action ? `<div class="heading-actions">${action}</div>` : ""}</div>`;
}

function statusBadge(status) {
  return `<span class="badge badge-status-${escapeHtml(status.toLowerCase())}">${escapeHtml(titleCase(status))}</span>`;
}
function priorityBadge(priority) {
  return `<span class="badge badge-priority-${escapeHtml(priority.toLowerCase())}">${escapeHtml(priority)}</span>`;
}

function ticketRows(tickets) {
  if (!tickets.length) {
    return `<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">✓</div><h3>All clear</h3><p>No support requests match this view.</p></div></td></tr>`;
  }
  return tickets.map((ticket) => `<tr data-ticket-id="${ticket.id}" tabindex="0" role="link" aria-label="Open request ${String(ticket.id).padStart(4, "0")}: ${escapeHtml(ticket.title)}">
    <td><span class="ticket-title">${escapeHtml(ticket.title)}</span><span class="ticket-id">REQ-${String(ticket.id).padStart(4, "0")}</span></td>
    <td>${escapeHtml(ticket.category_name || "Uncategorized")}</td>
    <td>${priorityBadge(ticket.priority)}</td>
    <td>${statusBadge(ticket.status)}</td>
    <td>${escapeHtml(formatDate(ticket.created_at))}</td>
  </tr>`).join("");
}

function ticketTable(tickets, footer = "") {
  return `<div class="panel"><div class="table-wrap"><table class="ticket-table">
    <thead><tr><th>Request</th><th>Category</th><th>Priority</th><th>Status</th><th>Created</th></tr></thead>
    <tbody>${ticketRows(tickets)}</tbody></table></div>${footer}</div>`;
}

function bindTicketRows() {
  document.querySelectorAll("[data-ticket-id]").forEach((row) => {
    const openTicket = async () => {
    const id = Number(row.dataset.ticketId);
    try {
      state.currentTicket = await request(`/tickets/${id}`);
      await navigate("detail");
    } catch (err) {
      showToast(err.message, true);
    }
    };
    row.addEventListener("click", openTicket);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openTicket();
      }
    });
  });
}

function statCard(label, value, icon, caption) {
  return `<article class="stat-card"><div class="stat-top"><span>${escapeHtml(label)}</span><span class="stat-icon">${icon}</span></div><div class="stat-value">${value}</div><div class="stat-caption">${escapeHtml(caption)}</div></article>`;
}

async function renderDashboard() {
  const container = document.querySelector("#page-content");
  container.innerHTML = `${heading(`Good ${new Date().getHours() < 12 ? "morning" : "afternoon"}, ${state.user.name.split(" ")[0]}`, "Here’s what’s happening with your IT service desk today.", '<button class="button button-primary" data-action="new-ticket">＋ New request</button>')}<div id="dashboard-stats" class="stats-grid">${loadingMarkup("Loading service desk metrics")}</div><div id="dashboard-analytics"></div><div id="dashboard-table">${loadingMarkup("Loading recent requests")}</div>`;
  container.querySelector('[data-action="new-ticket"]').addEventListener("click", () => navigate("new-ticket"));
  try {
    const [page, analytics] = await Promise.all([
      request("/tickets?page=1&page_size=5"),
      request("/tickets/analytics"),
    ]);
    document.querySelector("#ticket-nav-count").textContent = page.total || "";
    const values = analytics.statuses;
    document.querySelector("#dashboard-stats").innerHTML = [
      statCard("Total requests", analytics.total, "▤", "All requests you can access"),
      statCard("Open", values.OPEN || 0, "◷", "Waiting to be picked up"),
      statCard("In progress", values.IN_PROGRESS || 0, "↗", "Currently being worked on"),
      statCard("Resolved", values.RESOLVED || 0, "✓", "Ready for confirmation"),
    ].join("");
    document.querySelector("#dashboard-analytics").innerHTML = `<div class="analytics-grid">${analyticsChart("Requests by status", analytics.statuses, STATUSES, analytics.total)}${analyticsChart("Requests by priority", analytics.priorities, PRIORITIES, analytics.total)}</div>`;
    document.querySelector("#dashboard-table").innerHTML = `<div class="panel"><div class="panel-heading"><div><h2>Recent requests</h2><p>Your latest service desk activity</p></div><button class="text-button" id="view-all">View all →</button></div>${ticketTable(page.items)}</div>`;
    document.querySelector("#view-all").addEventListener("click", () => navigate("tickets"));
    bindTicketRows();
  } catch (err) {
    container.insertAdjacentHTML("beforeend", `<p class="form-error">${escapeHtml(err.message)}</p>`);
  }
}

function analyticsChart(title, counts, order, total) {
  const rows = order.filter((key) => counts[key]).map((key) => {
    const count = counts[key];
    const width = total ? Math.max(4, Math.round((count / total) * 100)) : 0;
    return `<div class="chart-row"><span>${escapeHtml(titleCase(key))}</span><div class="chart-track"><i style="--bar-width:${width}%"></i></div><strong>${count}</strong></div>`;
  }).join("");
  return `<section class="panel chart-panel" role="img" aria-label="${escapeHtml(title)}"><div class="chart-heading"><div><h2>${escapeHtml(title)}</h2><p>${total} visible requests</p></div><span class="chart-total">${total}</span></div><div class="chart-rows">${rows || '<p class="muted chart-empty">No request data yet.</p>'}</div></section>`;
}

function currentFiltersQuery() {
  const params = new URLSearchParams({ page: String(state.ticketPage), page_size: String(state.pageSize) });
  if (state.filters.status) params.set("status", state.filters.status);
  if (state.filters.priority) params.set("priority", state.filters.priority);
  if (state.filters.category_id) params.set("category_id", state.filters.category_id);
  if (state.filters.q) params.set("q", state.filters.q);
  if (state.filters.created_from) params.set("created_from", state.filters.created_from);
  if (state.filters.created_to) params.set("created_to", state.filters.created_to);
  params.set("sort_by", state.filters.sort_by || "date");
  params.set("sort_order", state.filters.sort_order || "desc");
  return params.toString();
}

async function renderTickets() {
  const container = document.querySelector("#page-content");
  const action = '<button class="button button-primary" data-action="new-ticket">＋ New request</button>';
  container.innerHTML = `${heading("All tickets", "Search, filter, and follow the progress of support requests.", action)}
    <div class="panel">
      <div class="panel-heading ticket-filter-heading"><div><h2>Request queue</h2><p>Combine search, date, status, priority, and category filters</p></div>
        <div class="filters">
          <select id="filter-status" aria-label="Filter by status"><option value="">All statuses</option>${STATUSES.map((item) => `<option value="${item}">${titleCase(item)}</option>`).join("")}</select>
          <select id="filter-priority" aria-label="Filter by priority"><option value="">All priorities</option>${PRIORITIES.map((item) => `<option value="${item}">${titleCase(item)}</option>`).join("")}</select>
          <select id="filter-category" aria-label="Filter by category"><option value="">All categories</option>${state.categories.map((category) => `<option value="${category.id}">${escapeHtml(category.name)}</option>`).join("")}</select>
          <label class="filter-date">From<input type="date" id="filter-created-from" aria-label="Created from"></label>
          <label class="filter-date">To<input type="date" id="filter-created-to" aria-label="Created to"></label>
          <label class="filter-sort">Sort<select id="filter-sort-by" aria-label="Sort tickets by"><option value="date">Date</option><option value="priority">Priority</option><option value="status">Status</option></select></label>
          <select id="filter-sort-order" aria-label="Sort direction"><option value="desc">Descending</option><option value="asc">Ascending</option></select>
          <button type="button" class="text-button clear-filters" id="clear-filters">Clear filters</button>
        </div>
      </div>
      <div id="ticket-list" aria-live="polite">${loadingMarkup("Loading requests")}</div>
    </div>`;
  container.querySelector('[data-action="new-ticket"]').addEventListener("click", () => navigate("new-ticket"));
  for (const [id, key] of [
    ["filter-status", "status"], ["filter-priority", "priority"], ["filter-category", "category_id"],
    ["filter-created-from", "created_from"], ["filter-created-to", "created_to"],
    ["filter-sort-by", "sort_by"], ["filter-sort-order", "sort_order"],
  ]) {
    const control = document.querySelector(`#${id}`);
    control.value = state.filters[key] || (key === "sort_by" ? "date" : key === "sort_order" ? "desc" : "");
    control.addEventListener("change", () => {
      state.filters[key] = control.value;
      state.ticketPage = 1;
      loadTicketList();
    });
  }
  container.querySelector("#clear-filters").addEventListener("click", () => {
    state.filters = {};
    state.ticketPage = 1;
    renderTickets();
  });
  await loadTicketList();
}

async function loadTicketList() {
  const list = document.querySelector("#ticket-list");
  if (!list) return;
  list.setAttribute("aria-busy", "true");
  list.innerHTML = loadingMarkup("Applying filters");
  try {
    const result = await request(`/tickets?${currentFiltersQuery()}`);
    const start = result.total ? ((result.page - 1) * result.page_size) + 1 : 0;
    const end = Math.min(result.page * result.page_size, result.total);
    const footer = `<div class="table-footer"><span>Showing ${start}–${end} of ${result.total} requests</span><div class="pagination"><button id="previous-page" aria-label="Previous ticket page" ${result.page <= 1 ? "disabled" : ""}>← Previous</button><span>Page ${result.page}</span><button id="next-page" aria-label="Next ticket page" ${end >= result.total ? "disabled" : ""}>Next →</button></div></div>`;
    list.innerHTML = ticketTable(result.items, footer);
    document.querySelector("#previous-page").addEventListener("click", () => { state.ticketPage--; loadTicketList(); });
    document.querySelector("#next-page").addEventListener("click", () => { state.ticketPage++; loadTicketList(); });
    bindTicketRows();
  } catch (err) {
    list.innerHTML = `<div class="empty-state"><p>${escapeHtml(err.message)}</p></div>`;
  } finally {
    list.removeAttribute("aria-busy");
  }
}

function renderNewTicket() {
  const container = document.querySelector("#page-content");
  container.innerHTML = `${heading("Create a support request", "Tell us what’s going on and we’ll route your issue to the right team.")}<form id="new-ticket-form" class="panel form-panel">
    <div class="form-grid">
      <label class="field full-width">Request title<input name="title" minlength="4" maxlength="160" placeholder="e.g. Unable to connect to office Wi-Fi" required></label>
      <label class="field">Category<select name="category_id"><option value="">Choose a category</option>${state.categories.map((category) => `<option value="${category.id}">${escapeHtml(category.name)}</option>`).join("")}</select></label>
      <label class="field">Priority <span class="muted">(optional)</span><select name="priority"><option value="">Use category default</option>${PRIORITIES.map((priority) => `<option value="${priority}">${titleCase(priority)}</option>`).join("")}</select></label>
      <label class="field full-width">Describe the issue<textarea name="description" minlength="8" maxlength="10000" placeholder="Include what happened, when it started, and any steps you’ve already tried." required></textarea></label>
    </div>
    <div class="classification-control"><button type="button" class="button button-secondary" id="classify-ticket">✦ Suggest category and priority</button><span id="classification-message" class="muted">Uses your configured AI provider; review suggestions before submitting.</span></div>
    <div id="new-ticket-error" class="form-error"></div>
    <div class="form-actions"><button type="button" class="button button-quiet" data-action="cancel">Cancel</button><button type="submit" class="button button-primary">Submit request</button></div>
  </form>`;
  container.querySelector('[data-action="cancel"]').addEventListener("click", async () => {
    const form = container.querySelector("#new-ticket-form");
    const hasDraft = [...new FormData(form).values()].some((value) => String(value).trim());
    if (!hasDraft || await confirmAction("Discard this request?", "Your unsent request details will be lost.", "Discard")) navigate("tickets");
  });
  container.querySelector("#classify-ticket").addEventListener("click", async () => {
    const form = document.querySelector("#new-ticket-form");
    const data = Object.fromEntries(new FormData(form).entries());
    const message = document.querySelector("#classification-message");
    if (!data.title || !data.description) {
      message.textContent = "Enter a title and description before requesting suggestions.";
      return;
    }
    const button = document.querySelector("#classify-ticket");
    button.disabled = true;
    message.textContent = "Analyzing request…";
    try {
      const suggestion = await request("/tickets/classify", {
        method: "POST",
        body: JSON.stringify({ title: data.title, description: data.description }),
      });
      if (suggestion.category_id) form.elements.category_id.value = String(suggestion.category_id);
      form.elements.priority.value = suggestion.priority;
      const assignment = suggestion.suggested_assignment ? ` · Suggested team: ${suggestion.suggested_assignment}` : "";
      message.textContent = `Suggested ${suggestion.category_name || "no category"} · ${titleCase(suggestion.priority)} · ${suggestion.department}${assignment}. Review before submitting.`;
    } catch (err) {
      message.textContent = err.message;
    } finally {
      button.disabled = false;
    }
  });
  container.querySelector("#new-ticket-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!validateTrimmedText(form, ["title", "description"])) return;
    const data = Object.fromEntries(new FormData(form).entries());
    const payload = { title: data.title.trim(), description: data.description.trim() };
    if (data.category_id) payload.category_id = Number(data.category_id);
    if (data.priority) payload.priority = data.priority;
    const submit = form.querySelector('[type="submit"]');
    setButtonBusy(submit, true, "Submitting…");
    try {
      const ticket = await request("/tickets", { method: "POST", body: JSON.stringify(payload) });
      state.currentTicket = ticket;
      showToast("Your support request has been submitted.");
      await navigate("detail");
    } catch (err) {
      document.querySelector("#new-ticket-error").textContent = err.message;
    } finally {
      setButtonBusy(submit, false);
    }
  });
}

async function renderTicketDetail(ticketId) {
  const container = document.querySelector("#page-content");
  try {
    const [ticket, comments, linkedAssets, availableAssets] = await Promise.all([
      request(`/tickets/${ticketId}`),
      request(`/tickets/${ticketId}/comments`),
      request(`/tickets/${ticketId}/assets`),
      request("/assets"),
    ]);
    state.currentTicket = ticket;
    const isAdmin = state.user.role === "ADMIN";
    const isAgent = state.user.role === "AGENT";
    const canManage = isAdmin || (isAgent && ticket.assignee_id === state.user.id);
    const canClose = ticket.status === "RESOLVED" && (ticket.requester_id === state.user.id || isAdmin);
    const assigneeOptions = state.supportUsers.map((support) => `<option value="${support.id}" ${ticket.assignee_id === support.id ? "selected" : ""}>${escapeHtml(support.name)} · ${titleCase(support.role)}</option>`).join("");
    container.innerHTML = `${heading("Request details", `REQ-${String(ticket.id).padStart(4, "0")} · Submitted ${formatDate(ticket.created_at)}`, '<button class="button button-quiet" id="back-to-list">← Back to tickets</button>')}
      <div class="ticket-layout">
        <div>
          <section class="panel ticket-detail">
            <div class="ticket-detail-head"><div><h2>${escapeHtml(ticket.title)}</h2><div class="ticket-detail-meta">Opened by ${escapeHtml(ticket.requester_name)} · ${escapeHtml(ticket.category_name || "Uncategorized")}</div></div>${statusBadge(ticket.status)}</div>
            <div class="ticket-description">${escapeHtml(ticket.description)}</div>
            <div class="detail-kv">
              <div class="detail-item"><small>Priority</small><span>${priorityBadge(ticket.priority)}</span></div>
              <div class="detail-item"><small>Assigned to</small><span>${escapeHtml(ticket.assignee_name || "Not assigned")}</span></div>
              <div class="detail-item"><small>First response due</small><span>${escapeHtml(formatDate(ticket.response_due_at))}</span></div>
              <div class="detail-item"><small>SLA deadline</small><span>${escapeHtml(formatDate(ticket.sla_due_at))}</span></div>
              <div class="detail-item"><small>First response</small><span>${escapeHtml(formatDate(ticket.first_response_at))}</span></div>
              <div class="detail-item"><small>Last updated</small><span>${escapeHtml(formatDate(ticket.updated_at))}</span></div>
            </div>
          </section>
          <section class="panel ticket-assets-panel">
            <div class="panel-heading"><div><h2>Linked assets</h2><p>Equipment associated with this request</p></div></div>
            ${linkedAssets.length ? `<div class="table-wrap"><table class="ticket-table"><thead><tr><th>Asset</th><th>Type</th><th>Assigned to</th><th>Status</th></tr></thead><tbody>${linkedAssets.map((asset) => `<tr><td>${escapeHtml(asset.asset_tag)} · ${escapeHtml(asset.name)}</td><td>${escapeHtml(asset.asset_type)}</td><td>${escapeHtml(asset.assigned_user_name || "Unassigned")}</td><td>${titleCase(asset.status)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="asset-empty">No assets linked to this request.</p>`}
            ${canManage && availableAssets.length ? `<form id="link-asset-form" class="asset-link-form"><label class="field">Link an asset<select name="asset_id" required><option value="">Choose an asset</option>${availableAssets.filter((asset) => !linkedAssets.some((linked) => linked.id === asset.id)).map((asset) => `<option value="${asset.id}">${escapeHtml(asset.asset_tag)} · ${escapeHtml(asset.name)}</option>`).join("")}</select></label><button class="button button-secondary" type="submit">Link asset</button></form>` : ""}
          </section>
          <section class="panel" style="margin-top:14px">
            <div class="panel-heading"><div><h2>Conversation</h2><p>Keep all updates in one place</p></div></div>
            <div class="comment-list">${comments.length ? comments.map((comment) => `<article class="comment"><div class="comment-head"><span>${escapeHtml(comment.author_name)}</span><time>${escapeHtml(formatDate(comment.created_at))}</time></div><p>${escapeHtml(comment.body)}</p></article>`).join("") : `<div class="empty-state"><p>No comments yet. Start the conversation.</p></div>`}</div>
            ${ticket.status !== "CLOSED" ? `<form class="comment-form" id="comment-form"><textarea name="body" placeholder="Write a reply…" maxlength="5000" required></textarea><button class="button button-primary" type="submit">Send</button></form>` : ""}
          </section>
        </div>
        <aside>
          ${(canManage && ticket.status !== "CLOSED") ? `<section class="panel side-panel"><h3>Manage request</h3>
            <label class="field">Status<select id="edit-status">${STATUSES.filter((status) => status !== "CLOSED").map((status) => `<option value="${status}" ${status === ticket.status ? "selected" : ""}>${titleCase(status)}</option>`).join("")}</select></label>
            <label class="field">Priority<select id="edit-priority">${PRIORITIES.map((priority) => `<option ${priority === ticket.priority ? "selected" : ""}>${priority}</option>`).join("")}</select></label>
            ${isAdmin ? `<label class="field">Assign to<select id="edit-assignee"><option value="">Unassigned</option>${assigneeOptions}</select></label>` : ""}
            <button class="button button-primary" id="save-ticket">Save changes</button>
          </section>` : ""}
          ${canClose ? `<section class="panel side-panel"><h3>Resolved?</h3><p class="muted" style="font-size:10px;line-height:1.55">Close this request after confirming the issue is fixed.</p><button class="button button-secondary" id="close-ticket">Close request</button></section>` : ""}
          <section class="panel side-panel"><h3>Request information</h3><div class="detail-item"><small>Request ID</small><span>REQ-${String(ticket.id).padStart(4, "0")}</span></div><div class="detail-item" style="margin-top:14px"><small>Created</small><span>${escapeHtml(formatDate(ticket.created_at))}</span></div></section>
        </aside>
      </div>`;
    container.querySelector("#back-to-list").addEventListener("click", () => navigate("tickets"));
    const linkAssetForm = container.querySelector("#link-asset-form");
    if (linkAssetForm) linkAssetForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const assetId = new FormData(linkAssetForm).get("asset_id");
      try {
        await request(`/tickets/${ticket.id}/assets/${assetId}`, { method: "POST" });
        showToast("Asset linked to request.");
        await renderTicketDetail(ticket.id);
      } catch (err) {
        showToast(err.message, true);
      }
    });
    const commentForm = container.querySelector("#comment-form");
    if (commentForm) commentForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const body = new FormData(commentForm).get("body");
      try {
        await request(`/tickets/${ticket.id}/comments`, { method: "POST", body: JSON.stringify({ body }) });
        await renderTicketDetail(ticket.id);
        showToast("Reply added.");
      } catch (err) {
        showToast(err.message, true);
      }
    });
    const saveButton = container.querySelector("#save-ticket");
    if (saveButton) saveButton.addEventListener("click", async () => {
      const payload = {
        status: document.querySelector("#edit-status").value,
        priority: document.querySelector("#edit-priority").value,
      };
      const assignee = document.querySelector("#edit-assignee");
      if (assignee) payload.assignee_id = assignee.value ? Number(assignee.value) : null;
      try {
        await request(`/tickets/${ticket.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        showToast("Request updated.");
        await renderTicketDetail(ticket.id);
      } catch (err) {
        showToast(err.message, true);
      }
    });
    const closeButton = container.querySelector("#close-ticket");
    if (closeButton) closeButton.addEventListener("click", async () => {
      const confirmed = await confirmAction("Close this request?", "Closing confirms the issue is fixed. This request can no longer be edited.", "Close request");
      if (!confirmed) return;
      setButtonBusy(closeButton, true, "Closing…");
      try {
        await request(`/tickets/${ticket.id}/close`, { method: "POST" });
        showToast("Request closed.");
        await renderTicketDetail(ticket.id);
      } catch (err) {
        showToast(err.message, true);
      } finally {
        setButtonBusy(closeButton, false);
      }
    });
  } catch (err) {
    container.innerHTML = `${heading("Request unavailable", "This request could not be opened.")}<div class="panel empty-state"><p>${escapeHtml(err.message)}</p><button class="button button-secondary" id="detail-back">Back to tickets</button></div>`;
    container.querySelector("#detail-back").addEventListener("click", () => navigate("tickets"));
  }
}

async function renderAdmin() {
  const container = document.querySelector("#page-content");
  if (state.user.role !== "ADMIN") return;
  let slaPolicies = [];
  try {
    [state.supportUsers, slaPolicies] = await Promise.all([
      request("/admin/support-users"),
      request("/admin/sla-policies"),
    ]);
  } catch (err) {
    showToast(err.message, true);
    state.supportUsers = [];
  }
  container.innerHTML = `${heading("Administration", "Manage support team access and ticket categories.", '<button class="button button-quiet" data-action="admin-home">← Overview</button>')}
    <div class="admin-grid">
      <section class="panel admin-panel"><h2>Create a user</h2><p>Public sign-up is restricted to employee accounts.</p>
        <form id="admin-user-form">
          <label class="field">Full name<input name="name" minlength="2" maxlength="120" required></label>
          <label class="field">Email<input name="email" type="email" required></label>
          <label class="field">Temporary password<input name="password" type="password" minlength="8" maxlength="72" required></label>
          <label class="field">Role<select name="role"><option value="USER">Employee</option><option value="AGENT">Support engineer</option><option value="ADMIN">Administrator</option></select></label>
          <div class="form-error" id="admin-user-error"></div><button class="button button-primary" type="submit">Create account</button>
        </form>
      </section>
      <section class="panel admin-panel"><h2>Add a category</h2><p>Set the default priority used when a requester leaves it unspecified.</p>
        <form id="category-form">
          <label class="field">Category name<input name="name" minlength="2" maxlength="80" required></label>
          <label class="field">Description<input name="description" maxlength="255"></label>
          <label class="field">Default priority<select name="default_priority">${PRIORITIES.map((priority) => `<option value="${priority}" ${priority === "MEDIUM" ? "selected" : ""}>${titleCase(priority)}</option>`).join("")}</select></label>
          <div class="form-error" id="category-error"></div><button class="button button-primary" type="submit">Add category</button>
        </form>
      </section>
    </div>
    <section class="panel" style="margin-top:16px"><div class="panel-heading"><div><h2>Support team</h2><p>Administrators and engineers available for assignment</p></div></div>
      <div class="table-wrap"><table class="ticket-table"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Account</th></tr></thead><tbody>${state.supportUsers.map((member) => `<tr><td>${escapeHtml(member.name)}</td><td>${escapeHtml(member.email)}</td><td>${escapeHtml(roleLabel(member.role))}</td><td>${member.is_active ? "Active" : "Inactive"}</td></tr>`).join("") || `<tr><td colspan="4">No support team members found.</td></tr>`}</tbody></table></div>
    </section>
    <section class="panel" style="margin-top:16px"><div class="panel-heading"><div><h2>Ticket categories</h2><p>Current routing defaults</p></div></div>
      <div class="table-wrap"><table class="ticket-table"><thead><tr><th>Category</th><th>Description</th><th>Default priority</th></tr></thead><tbody>${state.categories.map((category) => `<tr><td>${escapeHtml(category.name)}</td><td>${escapeHtml(category.description || "—")}</td><td>${priorityBadge(category.default_priority)}</td></tr>`).join("") || `<tr><td colspan="3">No categories configured.</td></tr>`}</tbody></table></div>
    </section>
    <section class="panel sla-admin-panel"><div class="panel-heading"><div><h2>SLA targets</h2><p>Configure response and resolution targets by priority in minutes.</p></div></div>
      <form id="sla-policy-form"><div class="table-wrap"><table class="ticket-table sla-table"><thead><tr><th>Priority</th><th>Response (minutes)</th><th>Resolution (minutes)</th></tr></thead><tbody>${slaPolicies.map((policy) => `<tr><td>${priorityBadge(policy.priority)}</td><td><input class="sla-input" type="number" min="1" max="43200" name="${policy.priority}-response" value="${policy.response_minutes}" required></td><td><input class="sla-input" type="number" min="1" max="43200" name="${policy.priority}-resolution" value="${policy.resolution_minutes}" required></td></tr>`).join("")}</tbody></table></div>
      <div class="sla-form-actions"><span class="muted">Changes apply to new requests and future priority changes.</span><button class="button button-primary" type="submit">Save SLA targets</button></div></form>
    </section>`;

  container.querySelector('[data-action="admin-home"]').addEventListener("click", () => navigate("dashboard"));
  document.querySelector("#sla-policy-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      for (const policy of slaPolicies) {
        await request(`/admin/sla-policies/${policy.priority}`, {
          method: "PUT",
          body: JSON.stringify({
            response_minutes: Number(data[`${policy.priority}-response`]),
            resolution_minutes: Number(data[`${policy.priority}-resolution`]),
          }),
        });
      }
      showToast("SLA targets saved.");
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.querySelector("#admin-user-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await request("/admin/users", { method: "POST", body: JSON.stringify(data) });
      showToast("Account created.");
      await renderAdmin();
    } catch (err) {
      document.querySelector("#admin-user-error").textContent = err.message;
    }
  });
  document.querySelector("#category-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await request("/admin/categories", { method: "POST", body: JSON.stringify(data) });
      state.categories = await request("/categories");
      showToast("Category added.");
      await renderAdmin();
    } catch (err) {
      document.querySelector("#category-error").textContent = err.message;
    }
  });
}

async function renderAssets() {
  const container = document.querySelector("#page-content");
  const isAdmin = state.user.role === "ADMIN";
  const statuses = ["IN_STOCK", "ACTIVE", "IN_REPAIR", "RETIRED"];
  container.innerHTML = `${heading("Asset register", "Track company equipment, ownership, warranty, and service history.", isAdmin ? '<button class="button button-primary" data-action="new-asset">＋ Register asset</button>' : "")}<div id="asset-content">${loadingMarkup("Loading asset register")}</div>`;
  const assetContent = container.querySelector("#asset-content");
  let assets = [];
  let users = [];
  let total = 0;
  try {
    const [page, userResult] = await Promise.all([
      request(`/assets?page=${state.assetPage}&page_size=10${state.assetSearch ? `&q=${encodeURIComponent(state.assetSearch)}` : ""}`),
      isAdmin ? request("/admin/users") : Promise.resolve([]),
    ]);
    assets = page.items;
    total = page.total;
    users = userResult;
  } catch (err) {
    assetContent.innerHTML = `<div class="panel empty-state"><p>${escapeHtml(err.message)}</p></div>`;
    return;
  }
  const userOptions = users.map((user) => `<option value="${user.id}">${escapeHtml(user.name)} · ${titleCase(user.role)}</option>`).join("");
  assetContent.innerHTML = `${isAdmin ? `<form id="asset-form" class="panel asset-form hidden"><div class="form-grid">
      <label class="field">Asset tag<input name="asset_tag" minlength="2" maxlength="40" placeholder="AST-0042" required></label>
      <label class="field">Device name<input name="name" minlength="2" maxlength="120" placeholder="Operations laptop" required></label>
      <label class="field">Type<input name="asset_type" minlength="2" maxlength="80" placeholder="Laptop, printer, license…" required></label>
      <label class="field">Serial number<input name="serial_number" maxlength="120"></label>
      <label class="field">Assign to<select name="assigned_user_id"><option value="">Unassigned</option>${userOptions}</select></label>
      <label class="field">Status<select name="status">${statuses.map((item) => `<option value="${item}">${titleCase(item)}</option>`).join("")}</select></label>
      <label class="field">Warranty expires<input name="warranty_expires_at" type="date"></label>
      <label class="field">Notes<input name="notes" maxlength="5000"></label>
    </div><div class="form-error" id="asset-error"></div><div class="form-actions"><button type="button" class="button button-quiet" data-action="cancel-asset">Cancel</button><button class="button button-primary" type="submit">Save asset</button></div></form>` : ""}
    <section class="panel asset-list-panel"><div class="panel-heading asset-heading"><div><h2>Company equipment</h2><p>${total} registered assets</p></div><form id="asset-search-form" class="list-search"><label class="sr-only" for="asset-search-input">Search assets</label><input id="asset-search-input" type="search" value="${escapeHtml(state.assetSearch)}" placeholder="Search assets"><button class="button button-secondary" type="submit">Search</button></form></div>
      <div class="table-wrap"><table class="ticket-table asset-table"><thead><tr><th>Asset tag</th><th>Device</th><th>Serial number</th><th>Assigned to</th><th>Status</th><th>Warranty</th>${isAdmin ? "<th></th>" : ""}</tr></thead><tbody>${assets.length ? assets.map((asset) => `<tr data-asset-row="${asset.id}"><td><strong>${escapeHtml(asset.asset_tag)}</strong></td><td>${escapeHtml(asset.name)}<small>${escapeHtml(asset.asset_type)}</small></td><td>${escapeHtml(asset.serial_number || "—")}</td><td>${isAdmin ? `<select class="asset-inline-select" data-asset-assignee aria-label="Assigned user for ${escapeHtml(asset.asset_tag)}"><option value="">Unassigned</option>${users.map((user) => `<option value="${user.id}" ${user.id === asset.assigned_user_id ? "selected" : ""}>${escapeHtml(user.name)}</option>`).join("")}</select>` : escapeHtml(asset.assigned_user_name || "Unassigned")}</td><td>${isAdmin ? `<select class="asset-inline-select" data-asset-status aria-label="Status for ${escapeHtml(asset.asset_tag)}">${statuses.map((item) => `<option value="${item}" ${item === asset.status ? "selected" : ""}>${titleCase(item)}</option>`).join("")}</select>` : titleCase(asset.status)}</td><td>${escapeHtml(asset.warranty_expires_at || "—")}</td>${isAdmin ? `<td><button class="text-button" type="button" data-action="save-asset" data-id="${asset.id}">Save</button></td>` : ""}</tr>`).join("") : `<tr><td colspan="${isAdmin ? 7 : 6}"><div class="empty-state"><h3>${state.assetSearch ? "No matching assets" : "No assets registered"}</h3><p>${isAdmin ? "Register company equipment to begin tracking ownership and warranty." : "Assets assigned to you will appear here."}</p></div></td></tr>`}</tbody></table></div>
      <div class="table-footer"><span>Showing ${total ? (state.assetPage - 1) * 10 + 1 : 0}–${Math.min(state.assetPage * 10, total)} of ${total} assets</span><div class="pagination"><button id="asset-prev" aria-label="Previous asset page" ${state.assetPage <= 1 ? "disabled" : ""}>← Previous</button><span>Page ${state.assetPage}</span><button id="asset-next" aria-label="Next asset page" ${state.assetPage * 10 >= total ? "disabled" : ""}>Next →</button></div></div>
    </section>`;

  container.querySelector('[data-action="new-asset"]')?.addEventListener("click", () => assetContent.querySelector("#asset-form").classList.remove("hidden"));
  const searchForm = assetContent.querySelector("#asset-search-form");
  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    state.assetSearch = searchForm.querySelector("#asset-search-input").value.trim();
    state.assetPage = 1;
    renderAssets();
  });
  assetContent.querySelector("#asset-prev").addEventListener("click", () => { state.assetPage--; renderAssets(); });
  assetContent.querySelector("#asset-next").addEventListener("click", () => { state.assetPage++; renderAssets(); });
  if (!isAdmin) return;
  const assetForm = container.querySelector("#asset-form");
  assetForm.querySelector('[data-action="cancel-asset"]').addEventListener("click", async () => {
    const hasDraft = [...new FormData(assetForm).values()].some((value) => String(value).trim());
    if (!hasDraft || await confirmAction("Discard this asset?", "The asset details you entered will be lost.", "Discard")) assetForm.classList.add("hidden");
  });
  assetForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!validateTrimmedText(assetForm, ["asset_tag", "name", "asset_type"])) return;
    const data = Object.fromEntries(new FormData(assetForm).entries());
    data.asset_tag = data.asset_tag.trim();
    data.name = data.name.trim();
    data.asset_type = data.asset_type.trim();
    const payload = { ...data, assigned_user_id: data.assigned_user_id ? Number(data.assigned_user_id) : null };
    if (!payload.warranty_expires_at) delete payload.warranty_expires_at;
    if (!payload.serial_number) delete payload.serial_number;
    if (!payload.notes) delete payload.notes;
    const submit = assetForm.querySelector('[type="submit"]');
    setButtonBusy(submit, true, "Saving…");
    try {
      await request("/assets", { method: "POST", body: JSON.stringify(payload) });
      showToast("Asset registered.");
      await renderAssets();
    } catch (err) {
      document.querySelector("#asset-error").textContent = err.message;
    } finally {
      setButtonBusy(submit, false);
    }
  });
  container.querySelectorAll('[data-action="save-asset"]').forEach((button) => button.addEventListener("click", async () => {
    const row = button.closest("tr");
    const assignee = row.querySelector("[data-asset-assignee]").value;
    const payload = {
      assigned_user_id: assignee ? Number(assignee) : null,
      status: row.querySelector("[data-asset-status]").value,
    };
    try {
      await request(`/assets/${button.dataset.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      showToast("Asset updated.");
    } catch (err) {
      showToast(err.message, true);
    }
  }));
}

async function renderNotifications() {
  const container = document.querySelector("#page-content");
  container.innerHTML = `${heading("Notifications", "Updates about assignments and ticket conversations.")}<section class="panel"><div id="notification-list" class="notice-list" aria-live="polite">${loadingMarkup("Loading notifications")}</div></section>`;
  const list = container.querySelector("#notification-list");
  try {
    const [page, recent] = await Promise.all([
      request(`/notifications?page=${state.notificationPage}&page_size=10`),
      request("/notifications?limit=50"),
    ]);
    document.querySelector("#notification-dot").classList.toggle("hidden", !recent.some((item) => !item.is_read));
    const start = page.total ? ((page.page - 1) * page.page_size) + 1 : 0;
    const end = Math.min(page.page * page.page_size, page.total);
    list.innerHTML = page.items.length
      ? `${page.items.map((item) => `<article class="notice-item ${item.is_read ? "" : "unread"}"><div class="notice-icon" aria-hidden="true">↗</div><div class="notice-copy">${escapeHtml(item.message)}<time>${escapeHtml(formatDate(item.created_at))}</time></div>${item.is_read ? "" : `<button class="text-button" data-read-id="${item.id}">Mark read</button>`}</article>`).join("")}<div class="table-footer"><span>Showing ${start}–${end} of ${page.total} notifications</span><div class="pagination"><button id="notification-prev" aria-label="Previous notification page" ${page.page <= 1 ? "disabled" : ""}>← Previous</button><span>Page ${page.page}</span><button id="notification-next" aria-label="Next notification page" ${end >= page.total ? "disabled" : ""}>Next →</button></div></div>`
      : `<div class="empty-state"><div class="empty-icon">♧</div><h3>You’re all caught up</h3><p>New updates will show up here.</p></div>`;
    list.querySelector("#notification-prev")?.addEventListener("click", () => { state.notificationPage--; renderNotifications(); });
    list.querySelector("#notification-next")?.addEventListener("click", () => { state.notificationPage++; renderNotifications(); });
    list.querySelectorAll("[data-read-id]").forEach((button) => button.addEventListener("click", async () => {
      setButtonBusy(button, true, "Saving…");
      try {
        await request(`/notifications/${button.dataset.readId}/read`, { method: "PATCH" });
        await renderNotifications();
      } catch (err) { showToast(err.message, true); }
    }));
  } catch (err) {
    list.innerHTML = `<div class="empty-state"><p>${escapeHtml(err.message)}</p></div>`;
  }
}

function closeGlobalSearch() {
  const input = document.querySelector("#global-search-input");
  const results = document.querySelector("#global-search-results");
  results.classList.add("hidden");
  input.setAttribute("aria-expanded", "false");
}

async function searchWorkspace(query) {
  const normalized = query.trim();
  const results = document.querySelector("#global-search-results");
  const input = document.querySelector("#global-search-input");
  const sequence = ++globalSearchSequence;
  if (normalized.length < 2) {
    closeGlobalSearch();
    return;
  }
  results.classList.remove("hidden");
  input.setAttribute("aria-expanded", "true");
  results.innerHTML = loadingMarkup("Searching tickets and assets");
  try {
    const [tickets, assets] = await Promise.all([
      request(`/tickets?q=${encodeURIComponent(normalized)}&page=1&page_size=5`),
      request(`/assets?q=${encodeURIComponent(normalized)}&page=1&page_size=5`),
    ]);
    if (sequence !== globalSearchSequence || input.value.trim() !== normalized) return;
    const items = [
      ...tickets.items.map((ticket) => `<button class="search-result" type="button" role="option" data-result-type="ticket" data-id="${ticket.id}"><span class="search-result-kind">REQ-${String(ticket.id).padStart(4, "0")}</span><strong>${escapeHtml(ticket.title)}</strong><small>${escapeHtml(titleCase(ticket.status))} · ${escapeHtml(titleCase(ticket.priority))}</small></button>`),
      ...assets.items.map((asset) => `<button class="search-result" type="button" role="option" data-result-type="asset" data-id="${asset.id}" data-tag="${escapeHtml(asset.asset_tag)}"><span class="search-result-kind">ASSET</span><strong>${escapeHtml(asset.name)}</strong><small>${escapeHtml(asset.asset_tag)} · ${escapeHtml(titleCase(asset.status))}</small></button>`),
    ];
    results.innerHTML = items.length ? items.join("") : `<div class="search-empty">No matching tickets or assets.</div>`;
    results.querySelectorAll("[data-result-type]").forEach((button) => button.addEventListener("click", async () => {
      closeGlobalSearch();
      input.value = "";
      if (button.dataset.resultType === "ticket") {
        try {
          state.currentTicket = await request(`/tickets/${button.dataset.id}`);
          await navigate("detail");
        } catch (err) { showToast(err.message, true); }
      } else {
        state.assetSearch = button.dataset.tag;
        state.assetPage = 1;
        await navigate("assets");
      }
    }));
  } catch (err) {
    if (sequence !== globalSearchSequence) return;
    results.innerHTML = `<div class="search-empty">${escapeHtml(err.message)}</div>`;
  }
}

document.querySelectorAll("[data-auth-mode]").forEach((button) => button.addEventListener("click", () => setAuthMode(button.dataset.authMode)));
document.querySelector("#auth-form").addEventListener("submit", handleAuth);
document.querySelector("#logout-button").addEventListener("click", async () => {
  if (await confirmAction("Sign out of ResolveIT?", "You will need to sign in again to view your workspace.", "Sign out")) signOut();
});
document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.page)));
document.querySelector("#notification-button").addEventListener("click", () => navigate("notifications"));
document.querySelector("#global-search").addEventListener("submit", (event) => {
  event.preventDefault();
  searchWorkspace(document.querySelector("#global-search-input").value);
});
document.querySelector("#global-search-input").addEventListener("input", (event) => {
  clearTimeout(globalSearchTimer);
  const query = event.currentTarget.value;
  globalSearchTimer = setTimeout(() => searchWorkspace(query), 220);
});
document.querySelector("#global-search-input").addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown") {
    const firstResult = document.querySelector("#global-search-results [role=option]");
    if (firstResult) { event.preventDefault(); firstResult.focus(); }
  } else if (event.key === "Escape") {
    closeGlobalSearch();
  }
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    document.querySelector("#global-search-input").focus();
  }
  if (event.key === "Escape") closeGlobalSearch();
});
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest("#global-search")) closeGlobalSearch();
});
setAuthMode("login");

if (state.token) {
  request("/auth/me")
    .then((user) => { state.user = user; return showWorkspace(); })
    .catch(() => signOut(false));
}
