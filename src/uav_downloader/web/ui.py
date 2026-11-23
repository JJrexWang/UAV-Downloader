"""HGhub-style single-page UI for the NAS web queue (dependency-free).

The access token lives only in this tab's JavaScript memory; media URLs use
the ?t= query form because <img>/<video> elements cannot set headers.
"""

HTML = '''<!doctype html>
<html lang="zh-Hans"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UAV Downloader Web</title><link rel="stylesheet" href="/app.css"><script src="/app.js" defer></script></head>
<body>
<section id="auth">
  <div class="auth-card">
    <p class="eyebrow">NAS · WEB 队列</p>
    <h1>UAV Downloader</h1>
    <p class="muted">输入访问令牌连接下载队列。令牌只保留在此标签页内存中，刷新后需重新输入。</p>
    <label for="token">访问令牌</label>
    <div class="row"><input id="token" type="password" autocomplete="off" spellcheck="false"><button id="connect" class="primary">连接</button></div>
    <p id="authNotice" class="notice" role="status" aria-live="polite"></p>
  </div>
</section>
<div id="app" hidden>
  <aside id="sidebar">
    <div class="brand"><span class="brand-mark">U</span><span class="brand-name">UAV Web</span></div>
    <nav id="nav">
      <button data-view="search" class="nav-item active">搜索</button>
      <button data-view="library" class="nav-item">我的片库</button>
      <button data-view="queue" class="nav-item">下载管理 <span id="queueBadge" class="badge" hidden>0</span></button>
      <button data-view="actress" class="nav-item">女优缺片</button>
      <button data-view="filing" class="nav-item">归类预览</button>
      <button data-view="organize" class="nav-item">本地整理</button>
      <button data-view="settings" class="nav-item">设置</button>
    </nav>
    <div class="side-foot"><span class="dot"></span><span id="connState">已连接</span><button id="disconnect" class="ghost">断开</button></div>
  </aside>
  <main id="content">
    <section id="view-search" class="view">
      <h2>搜索</h2>
      <div class="card">
        <div class="row wrap">
          <input id="q" type="search" placeholder="输入番号或女优名…" autocomplete="off">
          <div class="chips" id="siteChips">
            <button data-site="jable" class="chip active">Jable</button>
            <button data-site="missav" class="chip">MissAV</button>
            <button data-site="supjav" class="chip">SupJav</button>
          </div>
          <button id="searchBtn" class="primary">搜索</button>
        </div>
        <p id="searchStatus" class="meta"></p>
        <div id="results" class="grid"></div>
      </div>
      <div class="card">
        <h3>添加链接</h3>
        <label for="urls">视频网址（每行一个，最多 100 个）</label>
        <textarea id="urls" rows="4" placeholder="https://jable.tv/videos/…"></textarea>
        <div class="settings-grid">
          <label><span>画质</span><select id="resolution"><option value="highest">最高</option><option>1080</option><option>720</option><option>480</option><option>360</option><option value="lowest">最低</option></select></label>
          <label><span>分片线程</span><input id="workers" type="number" min="1" max="16" value="4"></label>
          <label><span>限速 MiB/s（0 不限）</span><input id="limit" type="number" min="0" max="1024" step="0.1" value="0"></label>
        </div>
        <button id="add" class="primary">加入队列</button>
      </div>
    </section>
    <section id="view-library" class="view" hidden>
      <div class="section-head"><h2>我的片库</h2><button id="libRefresh">刷新</button></div>
      <div class="chips" id="libChips"></div>
      <div id="libGrid" class="grid"></div>
    </section>
    <section id="view-queue" class="view" hidden>
      <div class="section-head"><h2>下载管理</h2><button id="clear">清除已结束记录</button></div>
      <div id="halted" class="warn" hidden><p>存储错误：队列已停止。确认磁盘健康与空间后再继续。</p><button id="resume" class="primary">已检查磁盘，继续队列</button></div>
      <div id="jobs"></div>
    </section>
    <section id="view-actress" class="view" hidden>
      <h2>女优缺片</h2>
      <div class="empty"><div class="empty-icon">缺</div><h3>女优缺片</h3><p>该模块在二期上线：对照女优全集列出未下载番号，并提供一键入队。</p></div>
    </section>
    <section id="view-filing" class="view" hidden>
      <h2>归类预览</h2>
      <div class="empty"><div class="empty-icon">归</div><h3>归类预览</h3><p>该模块在二期上线：下载完成后的重命名与归类待确认清单将出现在这里。</p></div>
    </section>
    <section id="view-organize" class="view" hidden>
      <h2>本地整理</h2>
      <div class="empty"><div class="empty-icon">整</div><h3>本地整理</h3><p>该模块在二期上线：扫描片库，生成番号规范化更名清单，先预览再执行。</p></div>
    </section>
    <section id="view-settings" class="view" hidden>
      <h2>设置</h2>
      <div class="card">
        <div class="setting-row"><div><h3>下载后自动重命名</h3><p class="meta">按番号规范化标准生成文件名：番号-女优中文名(日文名)-中文片名。</p></div>
        <label class="switch"><input id="setRename" type="checkbox"><span></span></label></div>
        <div class="setting-row"><div><h3>归类模式</h3><p class="meta">预览确认：先出清单确认后执行；全自动：下载完成直接归类。</p></div>
        <div class="segmented" id="setFileMode"><button data-mode="preview">预览确认</button><button data-mode="auto">全自动</button></div></div>
        <div class="setting-row"><div><h3>界面语言</h3><p class="meta">同时决定站点标题语言。</p></div>
        <select id="setLang"><option value="zh-Hans">简体中文</option><option value="zh">繁體中文</option><option value="en">English</option><option value="ja">日本語</option></select></div>
        <button id="saveSettings" class="primary">保存设置</button>
      </div>
      <div class="card info"><h3>关于</h3><p class="meta">镜像 ghcr.io/jjrexwang/uav-downloader · Web 队列<br>仅限局域网 / VPN 访问 · 同时只下载一部影片</p></div>
    </section>
  </main>
</div>
<div id="player" hidden>
  <div class="pl-backdrop" id="plBackdrop"></div>
  <div class="pl-box">
    <div class="pl-head"><span id="plTitle"></span><button id="plClose" class="icon-btn" aria-label="关闭">✕</button></div>
    <video id="plVideo" controls playsinline></video>
    <p id="plInfo" class="meta"></p>
  </div>
</div>
<div id="toast" role="status" aria-live="polite"></div>
</body></html>'''

CSS = '''*{box-sizing:border-box}
:root{--canvas:#1a1a1a;--bg:#202020;--s1:#272727;--s2:#2c2c2c;--s3:#343434;--s4:#3e3e3e;--on:#fff;--mut:#c5c5c5;--dim:#8b8b8b;--pri:#60cdff;--onpri:#003042;--line:rgba(255,255,255,.08);--ok:#7bd88f;--bad:#ff9a8a}
html,body{margin:0;padding:0}
body{background:var(--canvas);color:var(--on);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
[hidden]{display:none!important}
h1{font-size:28px;margin:0 0 10px}h2{font-size:21px;margin:0 0 16px}h3{font-size:16px;margin:0 0 8px}
.muted,.meta{color:var(--dim);font-size:13px}.meta{margin:6px 0}
.eyebrow{color:var(--pri);font-size:11px;letter-spacing:2px;font-weight:700;margin:0 0 10px}
button{font:inherit;font-weight:600;border:1px solid var(--line);border-radius:8px;background:var(--s3);color:var(--on);padding:9px 15px;cursor:pointer;white-space:nowrap}
button:hover{background:var(--s4)}button:disabled{opacity:.55;cursor:wait}
button.primary{background:var(--pri);border-color:var(--pri);color:var(--onpri)}button.primary:hover{filter:brightness(1.1)}
button.ghost{background:transparent}
input,select,textarea{font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--s1);color:var(--on);width:100%}
input:focus,select:focus,textarea:focus{outline:2px solid var(--pri);outline-offset:1px}
textarea{resize:vertical}
label{font-size:13px;color:var(--mut)}
.row{display:flex;align-items:center;gap:10px}.row.wrap{flex-wrap:wrap}
.row input[type="search"]{flex:1;min-width:200px}
#auth{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.auth-card{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:32px;max-width:480px;width:100%}
.auth-card label{display:block;margin:18px 0 6px}.auth-card .row input{flex:1}
.notice{color:var(--bad);min-height:22px;margin:12px 0 0}
#app{display:flex;min-height:100vh}
#sidebar{width:216px;flex:none;background:var(--bg);border-right:1px solid var(--line);padding:20px 14px;display:flex;flex-direction:column;gap:18px;position:sticky;top:0;height:100vh}
.brand{display:flex;align-items:center;gap:10px;padding:0 6px}
.brand-mark{width:34px;height:34px;border-radius:9px;background:var(--pri);color:var(--onpri);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:18px}
.brand-name{font-weight:700;font-size:17px}
#nav{display:flex;flex-direction:column;gap:4px}
.nav-item{display:flex;align-items:center;gap:8px;text-align:left;background:transparent;border:0;border-radius:8px;padding:10px 12px;color:var(--mut);font-weight:600}
.nav-item:hover{background:var(--s2);color:var(--on)}
.nav-item.active{background:var(--s3);color:var(--on)}
.badge{background:var(--pri);color:var(--onpri);border-radius:999px;font-size:12px;font-weight:800;padding:1px 8px;margin-left:auto}
.side-foot{margin-top:auto;display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim);padding:0 6px}
.side-foot .dot{width:8px;height:8px;border-radius:50%;background:var(--ok);flex:none}
.side-foot button{margin-left:auto;padding:5px 10px;font-size:12px}
#content{flex:1;min-width:0;padding:26px clamp(16px,3vw,36px) 60px;max-width:1240px}
.card{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:18px}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}
.section-head h2{margin:0}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{border-radius:999px;padding:7px 14px;background:var(--s2);font-size:13px}
.chip.active{background:var(--pri);color:var(--onpri);border-color:var(--pri)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px;margin-top:16px}
.work{background:var(--s1);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.poster{position:relative;aspect-ratio:16/9;background:linear-gradient(135deg,var(--s3),var(--s1));display:flex;align-items:center;justify-content:center;overflow:hidden}
.poster img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.poster .code-big{font-size:26px;font-weight:800;letter-spacing:1px;color:var(--dim)}
.dur{position:absolute;right:8px;bottom:8px;background:rgba(0,0,0,.72);color:#fff;font-size:12px;padding:2px 7px;border-radius:5px}
.work-body{padding:12px 14px;display:flex;flex-direction:column;gap:8px;flex:1}
.work-title{font-size:14px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:40px}
.work-meta{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim);flex-wrap:wrap}
.tag{font-size:12px;padding:3px 9px;border-radius:999px;background:var(--s3);color:var(--mut)}
.tag.lib{background:#234d31;color:var(--ok)}
.tag.queue{background:#1f4d63;color:var(--pri)}
.work-body button{margin-top:auto}
.settings-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:14px 0}
.settings-grid label{display:flex;flex-direction:column;gap:6px}
.job{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}
.job-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.job-url{overflow-wrap:anywhere;font-size:14px;margin:0;min-width:0}
.status{font-size:12px;padding:4px 10px;border-radius:999px;background:var(--s3);color:var(--mut);flex:none}
.status.completed{background:#234d31;color:var(--ok)}
.status.failed,.status.interrupted{background:#5a2d24;color:var(--bad)}
.status.running{background:#1f4d63;color:var(--pri)}
progress{width:100%;height:8px;accent-color:var(--pri);display:block;margin:14px 0 6px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.actions button{padding:7px 13px;font-size:13px}
details{margin-top:10px;color:var(--dim);font-size:12px}
details pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.5 ui-monospace,monospace}
.warn{background:#4a3421;border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.empty{background:var(--bg);border:1px dashed var(--s4);border-radius:12px;padding:56px 24px;text-align:center;color:var(--dim)}
.empty-icon{width:58px;height:58px;margin:0 auto 14px;border-radius:50%;background:var(--s2);display:flex;align-items:center;justify-content:center;font-size:22px;color:var(--mut)}
.empty h3{color:var(--on)}
.setting-row{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:14px 0;border-bottom:1px solid var(--line)}
.setting-row h3{margin:0 0 4px}.setting-row .meta{margin:0}
.setting-row select{width:auto;min-width:150px}
.switch{position:relative;display:inline-block;width:48px;height:26px;flex:none}
.switch input{opacity:0;width:0;height:0}
.switch span{position:absolute;inset:0;background:var(--s4);border-radius:999px;cursor:pointer;transition:.15s}
.switch span:before{content:"";position:absolute;width:20px;height:20px;border-radius:50%;background:#fff;top:3px;left:3px;transition:.15s}
.switch input:checked+span{background:var(--pri)}
.switch input:checked+span:before{transform:translateX(22px);background:var(--onpri)}
.segmented{display:flex;background:var(--s1);border:1px solid var(--line);border-radius:9px;overflow:hidden;flex:none}
.segmented button{border:0;border-radius:0;background:transparent;color:var(--mut)}
.segmented button.active{background:var(--pri);color:var(--onpri)}
#player{position:fixed;inset:0;z-index:60;display:flex;align-items:center;justify-content:center}
.pl-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.78)}
.pl-box{position:relative;background:var(--bg);border:1px solid var(--line);border-radius:12px;width:min(920px,94vw);max-height:92vh;overflow:auto;padding:16px}
.pl-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px;font-weight:700}
.icon-btn{width:38px;height:38px;border-radius:50%;padding:0;display:flex;align-items:center;justify-content:center;flex:none}
#plVideo{width:100%;background:#000;border-radius:8px;max-height:66vh}
#toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%) translateY(20px);background:var(--s3);color:var(--on);border:1px solid var(--line);padding:11px 20px;border-radius:999px;font-size:14px;opacity:0;pointer-events:none;transition:.2s;z-index:80;max-width:92vw;text-align:center}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
@media(max-width:760px){
  #app{flex-direction:column}
  #sidebar{width:100%;height:auto;position:fixed;left:0;right:0;bottom:0;top:auto;z-index:50;border-right:0;border-top:1px solid var(--line);padding:6px 8px calc(6px + env(safe-area-inset-bottom))}
  .brand,.side-foot{display:none}
  #nav{flex-direction:row;overflow-x:auto;gap:2px}
  .nav-item{flex:none;padding:9px 10px;font-size:13px}
  .badge{margin-left:4px}
  #content{padding:18px 14px 110px}
  .settings-grid{grid-template-columns:1fr}
  .grid{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}
}'''

JS = r'''"use strict";
let token = "", session = 0, timer = null, readSeq = 0, busy = false;
let site = "jable", lastResults = [], libLoaded = false, libFilter = {type: "all", value: ""};
let settings = {auto_rename: true, file_mode: "preview", lang: "zh-Hans"};
const $ = id => document.getElementById(id);
const STATUS = {pending: "等待中", running: "下载中", cancelling: "正在取消", completed: "完成", failed: "失败", cancelled: "已取消", interrupted: "中断，请重试"};
function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; }
let toastTimer = null;
function toast(message) { const t = $("toast"); t.textContent = message; t.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2600); }
async function api(path, body) {
  const requestSession = session;
  const response = await fetch(path, {method: body === undefined ? "GET" : "POST", cache: "no-store", credentials: "omit",
    headers: {"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body)});
  if (response.status === 401) { if (session === requestSession) { disconnect(); toast("令牌不正确或已失效"); } throw new Error("Unauthorized"); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}
function disconnect() {
  session++; readSeq++; token = ""; clearTimeout(timer);
  $("app").hidden = true; $("auth").hidden = false; $("connect").disabled = false;
  closePlayer(); libLoaded = false;
}
function showView(name) {
  for (const item of document.querySelectorAll(".nav-item")) item.classList.toggle("active", item.dataset.view === name);
  for (const view of document.querySelectorAll(".view")) view.hidden = view.id !== "view-" + name;
  if (name === "library" && !libLoaded) loadLibrary();
  if (name === "settings") loadSettings();
}
/* ---------------- queue ---------------- */
function renderQueue(data) {
  const active = data.jobs.filter(j => ["pending", "running", "cancelling"].includes(j.status)).length;
  const badge = $("queueBadge"); badge.hidden = active === 0; badge.textContent = active;
  $("halted").hidden = !data.halted;
  const container = $("jobs"); const fragment = document.createDocumentFragment();
  if (!data.jobs.length) {
    const empty = node("div", undefined, "empty");
    empty.append(node("div", "队", "empty-icon"), node("h3", "队列是空的"), node("p", "在搜索页粘贴视频网址，或从搜索结果一键加入。"));
    fragment.append(empty);
  }
  for (const job of data.jobs) {
    const card = node("article", undefined, "job");
    const head = node("div", undefined, "job-head");
    head.append(node("p", job.url, "job-url"), node("span", STATUS[job.status] || job.status, "status " + job.status));
    card.append(head);
    const progress = node("progress"); progress.max = job.total || 1;
    if (job.total) progress.value = Math.min(job.done, job.total);
    else if (job.status !== "running") progress.value = job.status === "completed" ? 1 : 0;
    card.append(progress);
    const count = job.total ? Math.floor(job.done) + " / " + Math.floor(job.total) + " " + job.unit : "等待来源或进度";
    card.append(node("p", count + " · " + (job.speed_bps / 1048576).toFixed(2) + " MiB/s · " + job.resolution, "meta"));
    const actions = node("div", undefined, "actions");
    if (["pending", "running"].includes(job.status)) { const b = node("button", "取消"); b.onclick = () => queueAction("/api/cancel", {id: job.id}); actions.append(b); }
    if (["failed", "cancelled", "interrupted", "completed"].includes(job.status)) { const b = node("button", "重试"); b.onclick = () => queueAction("/api/retry", {id: job.id}); actions.append(b); }
    if (actions.childNodes.length) card.append(actions);
    const details = node("details"); details.append(node("summary", "事件记录"), node("pre", (job.logs || []).join("\n")));
    card.append(details);
    fragment.append(card);
  }
  container.replaceChildren(fragment);
  // Keep search result badges in sync with queue membership.
  const queued = new Set(data.jobs.map(j => (j.url || "").replace(/\/+$/, "") + "/"));
  for (const card of document.querySelectorAll("#results .work")) {
    const url = card.dataset.url; if (!url) continue;
    const tag = card.querySelector(".tag.queue");
    const inQueue = queued.has(url.replace(/\/+$/, "") + "/");
    if (tag) tag.hidden = !inQueue;
    const btn = card.querySelector("button.primary");
    if (btn && inQueue) { btn.disabled = true; btn.textContent = "已在队列"; }
  }
}
async function refreshQueue() {
  clearTimeout(timer); if (!token) return;
  const id = ++readSeq;
  try { const data = await api("/api/queue"); if (id === readSeq) renderQueue(data); }
  catch (error) { if (id === readSeq && error.message !== "Unauthorized") toast(error.message); }
  finally { if (token && id === readSeq) timer = setTimeout(refreshQueue, 2000); }
}
async function queueAction(path, body) {
  if (busy) return; busy = true;
  try { await api(path, body); await refreshQueue(); }
  catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
  finally { busy = false; }
}
/* ---------------- search ---------------- */
function resultCard(item) {
  const card = node("article", undefined, "work"); card.dataset.url = item.url;
  const poster = node("div", undefined, "poster");
  poster.append(node("span", item.code || "—", "code-big"));
  if (item.thumbnail) { const img = document.createElement("img"); img.alt = ""; img.loading = "lazy"; img.src = item.thumbnail; img.onerror = () => img.remove(); poster.append(img); }
  if (item.duration) poster.append(node("span", item.duration, "dur"));
  card.append(poster);
  const body = node("div", undefined, "work-body");
  body.append(node("div", item.title || item.code || item.url, "work-title"));
  const meta = node("div", undefined, "work-meta");
  if (item.code) meta.append(node("span", item.code));
  meta.append(node("span", item.site));
  if (item.in_library) meta.append(node("span", "已在库", "tag lib"));
  const qtag = node("span", "已在队列", "tag queue"); qtag.hidden = !item.in_queue; meta.append(qtag);
  body.append(meta);
  const btn = node("button", item.in_queue ? "已在队列" : "下载", "primary");
  btn.disabled = !!item.in_queue;
  btn.onclick = async () => {
    btn.disabled = true;
    try { await api("/api/queue", {jobs: [{url: item.url}]}); item.in_queue = true; qtag.hidden = false; btn.textContent = "已在队列"; toast("已加入队列"); refreshQueue(); }
    catch (error) { btn.disabled = false; if (error.message !== "Unauthorized") toast(error.message); }
  };
  body.append(btn); card.append(body);
  return card;
}
async function doSearch() {
  const q = $("q").value.trim();
  if (!q) { toast("请输入番号或女优名"); return; }
  $("searchBtn").disabled = true; $("searchStatus").textContent = "搜索中…";
  try {
    const data = await api("/api/search?q=" + encodeURIComponent(q) + "&site=" + encodeURIComponent(site));
    lastResults = data.results || [];
    const grid = $("results"); grid.replaceChildren();
    if (data.error) { $("searchStatus").textContent = ""; toast(data.error); }
    else $("searchStatus").textContent = "共 " + data.total + " 条结果，本页 " + lastResults.length + " 条";
    if (!lastResults.length && !data.error) { const e = node("div", undefined, "empty"); e.append(node("h3", "没有结果"), node("p", "换个关键词或站点试试。")); grid.append(e); }
    for (const item of lastResults) grid.append(resultCard(item));
  } catch (error) { $("searchStatus").textContent = ""; if (error.message !== "Unauthorized") toast(error.message); }
  finally { $("searchBtn").disabled = false; }
}
/* ---------------- library ---------------- */
function fmtSize(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"]; let v = bytes, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return v.toFixed(v >= 100 ? 0 : 1) + " " + units[i];
}
let libWorks = [];
function renderLibChips(data) {
  const chips = $("libChips"); chips.replaceChildren();
  const add = (label, type, value) => {
    const b = node("button", label, "chip" + (libFilter.type === type && libFilter.value === value ? " active" : ""));
    b.onclick = () => { libFilter = {type, value}; renderLibChips(data); renderLibGrid(); };
    chips.append(b);
  };
  add("全部", "all", "");
  for (const name of data.actresses) add(name, "actress", name);
  for (const name of data.folders) if (name !== "01-日本JAV") add(name, "folder", name);
}
function renderLibGrid() {
  const grid = $("libGrid"); grid.replaceChildren();
  const works = libWorks.filter(w =>
    libFilter.type === "all" ? true :
    libFilter.type === "actress" ? w.actress === libFilter.value : w.folder === libFilter.value);
  if (!works.length) { const e = node("div", undefined, "empty"); e.append(node("h3", "片库是空的"), node("p", "这个分类下还没有视频。")); grid.append(e); return; }
  for (const work of works) {
    const card = node("article", undefined, "work");
    const poster = node("div", undefined, "poster");
    poster.append(node("span", work.code || "—", "code-big"));
    if (work.cover) { const img = document.createElement("img"); img.alt = ""; img.loading = "lazy"; img.src = "/api/cover?rel=" + encodeURIComponent(work.cover) + "&t=" + encodeURIComponent(token); img.onerror = () => img.remove(); poster.append(img); }
    card.append(poster);
    const body = node("div", undefined, "work-body");
    body.append(node("div", work.title || work.code || work.rel, "work-title"));
    const meta = node("div", undefined, "work-meta");
    if (work.code) meta.append(node("span", work.code));
    if (work.actress) meta.append(node("span", work.actress));
    meta.append(node("span", fmtSize(work.size)));
    body.append(meta);
    const btn = node("button", "播放", "primary");
    btn.onclick = () => openPlayer(work);
    body.append(btn); card.append(body);
    grid.append(card);
  }
}
async function loadLibrary() {
  try {
    const data = await api("/api/library");
    libWorks = data.works || []; libLoaded = true;
    renderLibChips(data); renderLibGrid();
  } catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
}
/* ---------------- player ---------------- */
function openPlayer(work) {
  $("plTitle").textContent = (work.code ? work.code + " " : "") + (work.title || "");
  $("plInfo").textContent = work.rel + " · " + fmtSize(work.size);
  const video = $("plVideo");
  video.src = "/api/stream?rel=" + encodeURIComponent(work.rel) + "&t=" + encodeURIComponent(token);
  $("player").hidden = false;
}
function closePlayer() {
  const video = $("plVideo");
  video.pause(); video.removeAttribute("src"); video.load();
  $("player").hidden = true;
}
/* ---------------- settings ---------------- */
function renderSettings() {
  $("setRename").checked = !!settings.auto_rename;
  for (const b of document.querySelectorAll("#setFileMode button")) b.classList.toggle("active", b.dataset.mode === settings.file_mode);
  $("setLang").value = settings.lang;
}
async function loadSettings() {
  try { settings = await api("/api/settings"); renderSettings(); }
  catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
}
/* ---------------- wiring ---------------- */
for (const item of document.querySelectorAll(".nav-item")) item.onclick = () => showView(item.dataset.view);
for (const chip of document.querySelectorAll("#siteChips .chip")) chip.onclick = () => {
  site = chip.dataset.site;
  for (const c of document.querySelectorAll("#siteChips .chip")) c.classList.toggle("active", c === chip);
};
$("searchBtn").onclick = doSearch;
$("q").onkeydown = event => { if (event.key === "Enter") doSearch(); };
$("add").onclick = async () => {
  const urls = $("urls").value.split(/\r?\n/).map(v => v.trim()).filter(Boolean);
  if (!urls.length || urls.length > 100) { toast("请输入 1 至 100 个网址"); return; }
  await queueAction("/api/queue", {jobs: urls.map(url => ({url, resolution: $("resolution").value, max_workers: Number($("workers").value), speed_limit_mib: Number($("limit").value)}))});
  toast("已加入队列");
};
$("clear").onclick = () => queueAction("/api/clear", {});
$("resume").onclick = () => { if (confirm("已确认磁盘健康及剩余空间？")) queueAction("/api/resume", {}); };
$("libRefresh").onclick = () => { libLoaded = false; loadLibrary(); };
$("plClose").onclick = closePlayer;
$("plBackdrop").onclick = closePlayer;
document.addEventListener("keydown", event => { if (event.key === "Escape" && !$("player").hidden) closePlayer(); });
for (const b of document.querySelectorAll("#setFileMode button")) b.onclick = () => { settings.file_mode = b.dataset.mode; renderSettings(); };
$("saveSettings").onclick = async () => {
  settings.auto_rename = $("setRename").checked;
  settings.lang = $("setLang").value;
  try { settings = await api("/api/settings", settings); renderSettings(); toast("设置已保存"); }
  catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
};
$("disconnect").onclick = disconnect;
$("connect").onclick = async () => {
  if ($("connect").disabled) return;
  const active = ++session; $("connect").disabled = true;
  token = $("token").value.trim(); $("token").value = "";
  try {
    const data = await api("/api/queue");
    if (active !== session) return;
    $("auth").hidden = true; $("app").hidden = false; $("authNotice").textContent = "";
    renderQueue(data); timer = setTimeout(refreshQueue, 2000);
  } catch (error) {
    if (active === session) { disconnect(); $("authNotice").textContent = error.message === "Unauthorized" ? "令牌不正确" : error.message; }
  } finally { if (active === session) $("connect").disabled = false; }
};
$("token").onkeydown = event => { if (event.key === "Enter") $("connect").click(); };
'''
