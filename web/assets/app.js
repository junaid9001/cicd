const ui = {
  form: document.getElementById("analyze-form"),
  status: document.getElementById("status"),
  submit: document.getElementById("submit-btn"),
  profile: document.getElementById("profile"),
  recs: document.getElementById("recommendations"),
  files: document.getElementById("files"),
  downloadJson: document.getElementById("download-all"),
  downloadZip: document.getElementById("download-zip"),
  register: document.getElementById("register-btn"),
  login: document.getElementById("login-btn"),
  logout: document.getElementById("logout-btn"),
  authStatus: document.getElementById("auth-status"),
  healthBadge: document.getElementById("health-badge"),
  sessionBadge: document.getElementById("session-badge"),
  recent: document.getElementById("recent"),
};

let token = localStorage.getItem("repo2ci_token") || "";
let lastPayload = null;

function setMessage(el, text, type = "") {
  el.textContent = text;
  el.classList.remove("ok", "err");
  if (type) el.classList.add(type);
}

function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function authHeaders() {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Request failed");
    return data;
  }
  const text = await response.text();
  if (!response.ok) throw new Error(text || `Request failed with ${response.status}`);
  return text;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.headers || {}),
      ...authHeaders(),
    },
  });
  return parseResponse(response);
}

function currentPayload() {
  return {
    repo_url: document.getElementById("repo_url").value.trim(),
    ci_provider: document.getElementById("ci_provider").value,
    include_deploy: document.getElementById("include_deploy").checked,
    include_security: document.getElementById("include_security").checked,
  };
}

function renderProfile(data) {
  const { profile, ci_provider } = data;
  ui.profile.innerHTML = `
<div><strong>Provider:</strong> ${ci_provider}</div>
<div><strong>Primary:</strong> ${profile.primary_language}</div>
<div><strong>Languages:</strong> ${profile.languages.join(", ") || "Unknown"}</div>
<div><strong>Frameworks:</strong> ${profile.frameworks.join(", ") || "None detected"}</div>
<div><strong>Package Managers:</strong> ${profile.package_managers.join(", ") || "Unknown"}</div>
<div><strong>Dockerfile:</strong> ${profile.has_dockerfile ? "Yes" : "No"}</div>
<div><strong>Test Hints:</strong> ${profile.test_hints.join(", ") || "N/A"}</div>
  `;
}

function renderRecommendations(items) {
  ui.recs.innerHTML = "";
  for (const item of items || []) {
    const li = document.createElement("li");
    li.textContent = item;
    ui.recs.appendChild(li);
  }
}

function renderFiles(files) {
  if (!files || !files.length) {
    ui.files.classList.add("muted");
    ui.files.textContent = "No files generated.";
    return;
  }
  ui.files.classList.remove("muted");
  ui.files.innerHTML = "";
  for (const file of files) {
    const item = document.createElement("article");
    item.className = "file-card";
    item.innerHTML = `
      <header class="file-head">
        <code>${file.path}</code>
        <button type="button" class="btn-alt">Copy</button>
      </header>
      <pre><code>${escapeHtml(file.content)}</code></pre>
    `;
    item.querySelector("button").addEventListener("click", async () => {
      await navigator.clipboard.writeText(file.content);
    });
    ui.files.appendChild(item);
  }
}

function setLoggedInState(isLoggedIn, email = "") {
  ui.downloadJson.disabled = !isLoggedIn;
  ui.downloadZip.disabled = !isLoggedIn;
  ui.sessionBadge.textContent = isLoggedIn ? `Session: ${email || "active"}` : "No session";
  ui.sessionBadge.classList.toggle("muted", !isLoggedIn);
}

async function loadRecent() {
  if (!token) {
    ui.recent.classList.add("muted");
    ui.recent.textContent = "Login to load recent analyses.";
    return;
  }
  try {
    const items = await api("/api/analyses?limit=8");
    if (!items.length) {
      ui.recent.classList.add("muted");
      ui.recent.textContent = "No analyses yet.";
      return;
    }
    ui.recent.classList.remove("muted");
    ui.recent.innerHTML = "";
    for (const item of items) {
      const box = document.createElement("div");
      box.className = "recent-item";
      box.innerHTML = `
        <strong>${item.repo_url}</strong>
        <div>Provider: ${item.ci_provider}</div>
        <code>${item.created_at}</code>
      `;
      ui.recent.appendChild(box);
    }
  } catch (err) {
    ui.recent.classList.add("muted");
    ui.recent.textContent = "Unable to load recent analyses.";
  }
}

async function validateTokenOnLoad() {
  if (!token) {
    setLoggedInState(false);
    return;
  }
  try {
    const me = await api("/api/auth/me");
    setLoggedInState(true, me.email);
    setMessage(ui.authStatus, "Session restored.", "ok");
    await loadRecent();
  } catch (err) {
    token = "";
    localStorage.removeItem("repo2ci_token");
    setLoggedInState(false);
    setMessage(ui.authStatus, "Stored session expired. Please login again.", "err");
  }
}

async function checkHealth() {
  try {
    await api("/api/health");
    ui.healthBadge.textContent = "API healthy";
    ui.healthBadge.className = "badge ok";
  } catch (err) {
    ui.healthBadge.textContent = "API unreachable";
    ui.healthBadge.className = "badge err";
  }
}

async function authFlow(endpoint, body) {
  const data = await api(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  token = data.access_token;
  localStorage.setItem("repo2ci_token", token);
  const me = await api("/api/auth/me");
  setLoggedInState(true, me.email);
  setMessage(ui.authStatus, "Authenticated successfully.", "ok");
  await loadRecent();
}

ui.register.addEventListener("click", async () => {
  try {
    await authFlow("/api/auth/register", {
      email: document.getElementById("auth_email").value.trim(),
      password: document.getElementById("auth_password").value,
      company: document.getElementById("auth_company").value.trim() || "My Company",
    });
  } catch (err) {
    setMessage(ui.authStatus, err.message || "Signup failed.", "err");
  }
});

ui.login.addEventListener("click", async () => {
  try {
    await authFlow("/api/auth/login", {
      email: document.getElementById("auth_email").value.trim(),
      password: document.getElementById("auth_password").value,
    });
  } catch (err) {
    setMessage(ui.authStatus, err.message || "Login failed.", "err");
  }
});

ui.logout.addEventListener("click", () => {
  token = "";
  lastPayload = null;
  localStorage.removeItem("repo2ci_token");
  setLoggedInState(false);
  setMessage(ui.authStatus, "Logged out.", "ok");
  setMessage(ui.status, "");
  ui.recent.classList.add("muted");
  ui.recent.textContent = "Login to load recent analyses.";
  ui.files.classList.add("muted");
  ui.files.textContent = "Generate a pipeline to view files.";
});

ui.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!token) {
    setMessage(ui.status, "Please login first.", "err");
    return;
  }
  ui.submit.disabled = true;
  setMessage(ui.status, "Analyzing repository and generating files...");
  try {
    const data = await api("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentPayload()),
    });
    lastPayload = data;
    renderProfile(data);
    renderRecommendations(data.recommendations);
    renderFiles(data.files);
    ui.downloadJson.disabled = false;
    ui.downloadZip.disabled = false;
    setMessage(ui.status, `Generated ${data.files.length} files for ${data.repository}.`, "ok");
    await loadRecent();
  } catch (err) {
    setMessage(ui.status, err.message || "Generation failed.", "err");
  } finally {
    ui.submit.disabled = false;
  }
});

ui.downloadJson.addEventListener("click", () => {
  if (!lastPayload) return;
  const blob = new Blob([JSON.stringify(lastPayload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "generated-cicd.json";
  a.click();
  URL.revokeObjectURL(url);
});

ui.downloadZip.addEventListener("click", async () => {
  if (!token) {
    setMessage(ui.status, "Please login first.", "err");
    return;
  }
  try {
    const response = await fetch("/api/analyze/zip", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify(currentPayload()),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "ZIP download failed");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "generated-cicd.zip";
    a.click();
    URL.revokeObjectURL(url);
    setMessage(ui.status, "ZIP downloaded.", "ok");
  } catch (err) {
    setMessage(ui.status, err.message || "ZIP download failed.", "err");
  }
});

checkHealth();
validateTokenOnLoad();
