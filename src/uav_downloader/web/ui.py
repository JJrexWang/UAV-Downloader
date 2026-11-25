"""HGhub-style single-page UI for the NAS web queue (dependency-free).

Account login: the session token issued by /api/login lives only in this
tab's JavaScript memory; media URLs use the ?t= query form because
<img>/<video> elements cannot set headers.
"""

HTML = '''<!doctype html>
<html lang="zh-Hans"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UAV Downloader Web</title><link rel="stylesheet" href="/app.css"><script src="/app.js" defer></script></head>
<body>
<section id="auth" class="gate">
  <div class="auth-card">
    <p class="eyebrow">NAS · WEB 队列</p>
    <h1>UAV Downloader</h1>
    <p class="muted">使用账号登录。首次使用默认账号 admin / admin，登录后会先要求修改密码。</p>
    <label for="loginUser">用户名</label>
    <input id="loginUser" type="text" autocomplete="username" spellcheck="false">
    <label for="loginPass">密码</label>
    <div class="row"><input id="loginPass" type="password" autocomplete="current-password"><button id="loginBtn" class="primary">登录</button></div>
    <p id="authNotice" class="notice" role="status" aria-live="polite"></p>
  </div>
</section>
<section id="forceChange" class="gate" hidden>
  <div class="auth-card">
    <p class="eyebrow">NAS · WEB 队列</p>
    <h1>先修改密码</h1>
    <p class="muted">这是首次登录，或密码刚被管理员重置。设置新密码后才能进入，无法跳过。</p>
    <label for="fcNew">新密码（至少 8 位）</label>
    <input id="fcNew" type="password" autocomplete="new-password">
    <label for="fcConfirm">确认新密码</label>
    <div class="row"><input id="fcConfirm" type="password" autocomplete="new-password"><button id="fcSubmit" class="primary">设置密码</button></div>
    <p id="fcNotice" class="notice" role="status" aria-live="polite"></p>
    <button id="fcLogout" class="ghost">退出登录</button>
  </div>
</section>
<section id="onboard" class="gate" hidden>
  <div class="auth-card">
    <p class="eyebrow">欢迎使用</p>
    <h1>再建一个常用账号</h1>
    <p class="muted">建议新建一个普通用户账号供日常使用，admin 只用来管理用户。也可以暂时跳过，之后随时在「用户管理」里创建。</p>
    <label for="obUser">用户名</label>
    <input id="obUser" type="text" autocomplete="off" spellcheck="false">
    <label for="obPass">密码（至少 8 位）</label>
    <input id="obPass" type="password" autocomplete="new-password">
    <label for="obRole">角色</label>
    <select id="obRole"><option value="user">普通用户</option><option value="admin">管理员</option></select>
    <div class="row gate-actions"><button id="obCreate" class="primary">创建账号并进入</button><button id="obSkip" class="ghost">暂时跳过</button></div>
    <p id="obNotice" class="notice" role="status" aria-live="polite"></p>
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
      <button data-view="users" class="nav-item" id="navUsers" hidden>用户管理</button>
    </nav>
    <div class="side-foot"><span class="dot"></span><span id="connState">未登录</span><button id="disconnect" class="ghost">退出</button></div>
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
        <div class="row" id="backfillRow" hidden><button id="backfillBtn" class="primary">一键补充入库</button><span class="meta">把本页不在库的作品下载并归入对应女优文件夹（按规范改名）</span><span id="bfStats" class="meta"></span><button id="bfListToggle" class="ghost" hidden>查看清单</button></div>
        <div id="bfMissingPanel" class="bf-missing" hidden></div>
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
      <div class="picker" id="actPicker">
        <div class="row">
          <input id="libActSearch" type="search" placeholder="输入女优名，点选后进入她的目录…" autocomplete="off">
          <button id="libActAll">全部女优</button>
        </div>
        <div id="libActList" class="picker-list" hidden></div>
      </div>
      <nav id="libCrumbs" class="crumbs" aria-label="当前位置"></nav>
      <div id="libFolders" class="grid lib-grid"></div>
      <div id="libGrid" class="grid lib-grid"></div>
    </section>
    <section id="view-queue" class="view" hidden>
      <div class="section-head"><h2>下载管理</h2><button id="clear">清除已结束记录</button></div>
      <div id="halted" class="warn" hidden><p>存储错误：队列已停止。确认磁盘健康与空间后再继续。</p><button id="resume" class="primary">已检查磁盘，继续队列</button></div>
      <div id="queueGroups"></div>
      <div id="queueDetail" hidden>
        <div class="row qd-head">
          <button id="queueBack">← 返回</button>
          <h3 id="queueDetailTitle"></h3>
          <span id="queueDetailMeta" class="meta"></span>
        </div>
        <div id="jobs"></div>
      </div>
    </section>
    <section id="view-actress" class="view" hidden>
      <h2>女优缺片</h2>
      <div class="card">
        <div id="actList" class="act-grid"></div>
        <div class="row wrap" style="margin-top:14px">
          <input id="actName" type="search" placeholder="输入女优名（中文 / 日文 / 繁体）…" autocomplete="off">
          <button id="actQuery" class="primary">查询缺片</button>
        </div>
        <p id="actStatus" class="meta"></p>
        <p id="actOwned" class="meta"></p>
        <div id="actOwnedGrid" class="chips"></div>
      </div>
      <div id="actGrid" class="grid"></div>
      <div id="actBar" class="sticky-bar" hidden>
        <span id="actSelText">已选 0 部</span>
        <button id="actEnqueue" class="primary">一键入队</button>
      </div>
    </section>
    <section id="view-filing" class="view" hidden>
      <div class="section-head"><h2>归类预览</h2><button id="ppRefresh">刷新</button></div>
      <p class="meta">下载完成后按番号规范生成的新名与归类去向。确认后才会移动文件；目标已存在时标记冲突，绝不覆盖。</p>
      <div id="ppList"></div>
      <div id="ppBar" class="sticky-bar" hidden>
        <span id="ppSelText">已选 0 项</span>
        <button id="ppExec" class="primary">执行选中</button>
        <button id="ppExecAll">全部执行</button>
        <button id="ppDismiss">忽略选中</button>
      </div>
    </section>
    <section id="view-organize" class="view" hidden>
      <h2>本地整理</h2>
      <div class="card">
        <div class="row wrap">
          <div class="chips" id="orgScopes">
            <button data-scope="" class="chip active">全部</button>
            <button data-scope="00-待分拣" class="chip">00-待分拣</button>
            <button data-scope="01-日本JAV" class="chip">01-日本JAV</button>
            <button data-scope="02-精选专辑" class="chip">02-精选专辑</button>
          </div>
          <button id="orgScan" class="primary">开始扫描</button>
        </div>
        <p class="meta">只动视频/封面/字幕 · 命名格式 番号-女优中文名（日文名）-中文片名 · 全名 ≤255 字节 · 符号半角 · 执行前会写入回滚记录。</p>
        <p id="orgStatus" class="meta"></p>
        <div id="orgStats" class="stat-grid" hidden>
          <div class="stat"><span class="stat-num" id="stScanned">0</span><span>扫描视频</span></div>
          <div class="stat"><span class="stat-num" id="stRename">0</span><span>可更名</span></div>
          <div class="stat"><span class="stat-num" id="stIso">0</span><span>疑似误识别（隔离）</span></div>
          <div class="stat"><span class="stat-num" id="stStd">0</span><span>已规范（F 级）</span></div>
        </div>
      </div>
      <div id="orgList"></div>
      <div id="orgIso"></div>
      <div id="orgBar" class="sticky-bar" hidden>
        <span id="orgSelText">已选 0 项</span>
        <button id="orgExec" class="primary">执行更名</button>
      </div>
      <div class="card">
        <div class="section-head"><h3>回滚记录</h3><button id="orgRollbackAll">撤销全部</button></div>
        <div id="orgLog"></div>
      </div>
    </section>
    <section id="view-users" class="view" hidden>
      <h2>用户管理</h2>
      <div class="card">
        <h3>新建用户</h3>
        <div class="settings-grid">
          <label><span>用户名</span><input id="nuUser" type="text" autocomplete="off" spellcheck="false"></label>
          <label><span>密码（至少 8 位）</span><input id="nuPass" type="password" autocomplete="new-password"></label>
          <label><span>角色</span><select id="nuRole"><option value="user">普通用户</option><option value="admin">管理员</option></select></label>
        </div>
        <button id="nuCreate" class="primary">新建用户</button>
      </div>
      <div class="card"><div id="userList"></div></div>
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
      <div class="card">
        <h3>修改密码</h3>
        <div class="settings-grid">
          <label><span>当前密码</span><input id="cpOld" type="password" autocomplete="current-password"></label>
          <label><span>新密码（至少 8 位）</span><input id="cpNew" type="password" autocomplete="new-password"></label>
          <label><span>确认新密码</span><input id="cpConfirm" type="password" autocomplete="new-password"></label>
        </div>
        <button id="cpSubmit" class="primary">修改密码</button>
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
<div id="bfModal" hidden>
  <div class="pl-backdrop" id="bfBackdrop"></div>
  <div class="pl-box bf-box">
    <div class="pl-head"><span>补充入库确认</span><button id="bfClose" class="icon-btn" aria-label="关闭">✕</button></div>
    <p id="bfSummary" class="meta"></p>
    <p id="bfCounts" class="meta"></p>
    <div id="bfList" class="bf-list"></div>
    <p id="bfError" class="notice"></p>
    <div class="row bf-actions">
      <button id="bfCancel" class="ghost">取消</button>
      <button id="bfConfirm" class="primary" disabled>确认下载 0 部</button>
    </div>
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
.gate{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.auth-card{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:32px;max-width:480px;width:100%}
.auth-card label{display:block;margin:18px 0 6px}.auth-card .row input{flex:1}
.auth-card .gate-actions{margin-top:20px}.auth-card .gate-actions .primary{flex:1}
#fcLogout{margin-top:10px;padding:7px 12px;font-size:13px}
.user-row{display:flex;align-items:center;gap:10px;padding:11px 0;border-bottom:1px solid var(--line);flex-wrap:wrap}
.user-row:last-child{border-bottom:0}
.user-main{flex:1;min-width:190px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.user-name{font-weight:700}
.user-row .actions{margin-top:0}
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
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:14px}
.stat{background:var(--s1);border:1px solid var(--line);border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:2px;color:var(--dim);font-size:13px}
.stat-num{font-size:24px;font-weight:800;color:var(--on)}
.plan{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.plan-head{display:flex;gap:10px;align-items:flex-start}
.plan-head input[type="checkbox"]{width:18px;height:18px;flex:none;margin-top:3px;accent-color:var(--pri)}
.plan-names{min-width:0;flex:1}
.plan-src{overflow-wrap:anywhere;color:var(--mut);font-size:14px}
.plan-arrow{color:var(--dim);margin:1px 0}
.plan-new{overflow-wrap:anywhere;font-weight:700}
.plan-target{color:var(--dim);font-size:13px;overflow-wrap:anywhere;margin-top:4px}
.plan-side{display:flex;flex-direction:column;gap:6px;align-items:flex-end;flex:none}
.pstatus{font-size:12px;padding:4px 10px;border-radius:999px;background:var(--s3);color:var(--mut)}
.pstatus.pending{background:#1f4d63;color:var(--pri)}
.pstatus.done{background:#234d31;color:var(--ok)}
.pstatus.conflict,.pstatus.error{background:#5a2d24;color:var(--bad)}
.grade{font-size:12px;font-weight:800;padding:3px 9px;border-radius:999px;background:var(--s3);color:var(--mut)}
.grade.A{background:#234d31;color:var(--ok)}
.grade.B{background:#1f4d63;color:var(--pri)}
.grade.C{background:#4a3a17;color:#f2c14e}
.grade.D{background:#5a2d24;color:var(--bad)}
.tag.low{background:#4a3a17;color:#f2c14e}
.sticky-bar{position:sticky;bottom:14px;display:flex;align-items:center;gap:10px;background:var(--s2);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:14px 0;box-shadow:0 6px 24px rgba(0,0,0,.35);z-index:5;flex-wrap:wrap}
.log-row{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid var(--line);font-size:13px}
.log-row .log-names{min-width:0;flex:1;overflow-wrap:anywhere;color:var(--mut)}
.log-row button{padding:6px 12px;font-size:12px}
.log-row.done{color:var(--dim)}
#toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%) translateY(20px);background:var(--s3);color:var(--on);border:1px solid var(--line);padding:11px 20px;border-radius:999px;font-size:14px;opacity:0;pointer-events:none;transition:.2s;z-index:80;max-width:92vw;text-align:center}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
#content.wide{max-width:none}
.lib-grid{grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
#backfillRow{margin-top:10px}
#bfListToggle{padding:6px 12px;font-size:13px;flex:none}
.bf-missing{margin-top:10px;background:var(--s1);border:1px solid var(--line);border-radius:10px;max-height:320px;overflow:auto;padding:4px 12px}
.bf-miss-row{display:grid;grid-template-columns:110px 1fr auto;gap:10px;align-items:center;padding:7px 0;border-bottom:1px solid var(--line);font-size:13px}
.bf-miss-row:last-child{border-bottom:0}
.bf-miss-code{font-weight:800;font-family:ui-monospace,Menlo,Consolas,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bf-miss-title{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--mut)}
.picker{position:relative;margin-bottom:12px}
.picker .row input[type="search"]{flex:1;min-width:200px}
.crumbs{display:flex;align-items:center;gap:4px;flex-wrap:wrap;margin-bottom:4px}
.crumbs button{background:transparent;border:0;padding:5px 7px;color:var(--mut);font-weight:600;border-radius:6px}
.crumbs button:hover{background:var(--s2);color:var(--on)}
.crumbs button.current{color:var(--on);cursor:default}
.crumbs button.current:hover{background:transparent;color:var(--on)}
.crumbs .sep{color:var(--dim);font-size:13px}
.folder-card{cursor:pointer}
.folder-card:hover{border-color:var(--s4)}
.folder-poster{background:linear-gradient(135deg,var(--s2),var(--s1))}
.folder-glyph{display:flex;align-items:center;justify-content:center}
.lib-more{grid-column:1/-1;padding:13px}
.sel-chip{display:inline-flex;align-items:center;gap:8px;border-radius:999px;padding:7px 8px 7px 14px;background:var(--pri);color:var(--onpri);border:1px solid var(--pri);font-size:13px;font-weight:600}
.sel-chip button{background:rgba(0,0,0,.18);border:0;color:inherit;border-radius:50%;width:20px;height:20px;padding:0;display:flex;align-items:center;justify-content:center;font-size:12px}
.picker-list{position:absolute;left:0;right:0;top:100%;margin-top:6px;background:var(--s2);border:1px solid var(--line);border-radius:10px;max-height:264px;overflow:auto;z-index:30;box-shadow:0 10px 30px rgba(0,0,0,.4)}
.picker-item{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;text-align:left;background:transparent;border:0;border-bottom:1px solid var(--line);border-radius:0;padding:10px 14px;font-weight:600}
.picker-item:last-child{border-bottom:0}
.picker-item:hover{background:var(--s3)}
.picker-item .cnt{color:var(--dim);font-size:12px;font-weight:400;flex:none}
.picker-empty{padding:12px 14px;color:var(--dim);font-size:13px}
.qgroup{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px;cursor:pointer}
.qgroup:hover{border-color:var(--s4);background:var(--s1)}
.qgroup progress{margin:12px 0 0}
.qgroup .chev{color:var(--dim);font-size:22px;flex:none;line-height:1}
.qd-head{margin-bottom:14px}
.qd-head h3{margin:0}
.act-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.act-cell{display:flex;align-items:center;gap:10px;background:var(--s1);border:1px solid var(--line);border-radius:10px;padding:10px 12px;min-width:0}
.act-cell-name{flex:1;min-width:0;font-weight:700;overflow-wrap:anywhere}
.act-cell-count{color:var(--dim);font-size:12px;flex:none}
.act-cell button{flex:none;padding:7px 12px;font-size:13px}
#bfModal{position:fixed;inset:0;z-index:70;display:flex;align-items:center;justify-content:center}
.bf-box{width:min(760px,94vw)}
.bf-list{max-height:44vh;overflow:auto;display:flex;flex-direction:column;gap:8px;margin:12px 0}
.bf-row{display:flex;gap:10px;align-items:flex-start;background:var(--s1);border:1px solid var(--line);border-radius:10px;padding:10px 12px;cursor:pointer}
.bf-row input[type="checkbox"]{width:18px;height:18px;flex:none;margin-top:2px;accent-color:var(--pri)}
.bf-main{flex:1;min-width:0}
.bf-line{font-size:14px;overflow-wrap:anywhere}
.bf-code{font-weight:800;margin-right:8px}
.bf-target{color:var(--dim);font-size:12px;overflow-wrap:anywhere;margin-top:2px}
.bf-actions{justify-content:flex-end;margin-top:8px}
@media(max-width:760px){
  #app{flex-direction:column}
  #sidebar{width:100%;height:auto;position:fixed;left:0;right:0;bottom:0;top:auto;z-index:50;border-right:0;border-top:1px solid var(--line);padding:6px 8px calc(6px + env(safe-area-inset-bottom))}
  .brand,.side-foot{display:none}
  #nav{flex-direction:row;overflow-x:auto;gap:2px}
  .nav-item{flex:none;padding:9px 10px;font-size:13px}
  .badge{margin-left:4px}
  #content{padding:18px 14px 110px}
  .settings-grid{grid-template-columns:1fr}
  .stat-grid{grid-template-columns:repeat(2,1fr)}
  .sticky-bar{bottom:86px}
  .grid{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}
}'''

JS = r'''"use strict";
let sessionToken = "", session = 0, timer = null, readSeq = 0, busy = false, ppTimer = null;
let me = null, loginPassword = "";  // loginPassword only bridges login -> forced change; cleared right after.
let site = "jable", lastResults = [], lastQuery = "", libLoaded = false;
let queueActress = null, queueData = null;  // queueActress: null = group list, "" = 未分类 group, else actress name
let bfPlan = null, bfSel = new Set(), bfBusy = false;
let settings = {auto_rename: true, file_mode: "preview", lang: "zh-Hans"};
const $ = id => document.getElementById(id);
const STATUS = {pending: "等待中", running: "下载中", cancelling: "正在取消", completed: "完成", failed: "失败", cancelled: "已取消", interrupted: "中断，请重试"};
function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; }
let toastTimer = null;
function toast(message) { const t = $("toast"); t.textContent = message; t.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2600); }
async function api(path, body) {
  const requestSession = session;
  const response = await fetch(path, {method: body === undefined ? "GET" : "POST", cache: "no-store", credentials: "omit",
    headers: {"Authorization": "Bearer " + sessionToken, "Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) { if (session === requestSession) { toGate(); toast("登录已失效，请重新登录"); } throw new Error("Unauthorized"); }
  // Server says the password must be changed before anything else: jump to
  // the forced-change screen and let callers treat this as an auth failure.
  if (response.status === 403 && data.error === "must_change_password") { if (session === requestSession) showForceChange(); throw new Error("Unauthorized"); }
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}
function toGate(notice) {
  session++; readSeq++; sessionToken = ""; me = null; loginPassword = "";
  clearTimeout(timer); clearInterval(ppTimer);
  $("app").hidden = true; $("forceChange").hidden = true; $("onboard").hidden = true;
  $("bfModal").hidden = true; bfPlan = null; bfSel = new Set(); bfBusy = false; queueActress = null; queueData = null;
  $("auth").hidden = false; $("loginBtn").disabled = false;
  $("authNotice").textContent = notice || "";
  closePlayer(); libLoaded = false; actLoaded = false;
  disconnectMediaObserver();
  libPath = ""; libShowAll = false; libTreeData = null; libActData = []; libActLoaded = false;
}
async function logout() {
  const token = sessionToken;
  toGate();
  if (token) {
    try { await fetch("/api/logout", {method: "POST", cache: "no-store", credentials: "omit", headers: {"Authorization": "Bearer " + token, "Content-Type": "application/json"}, body: "{}"}); } catch (error) { /* already at the gate */ }
  }
}
function showForceChange() {
  $("auth").hidden = true; $("app").hidden = true; $("onboard").hidden = true;
  $("forceChange").hidden = false;
  $("fcNew").value = ""; $("fcConfirm").value = ""; $("fcNotice").textContent = "";
}
function showOnboard() {
  $("auth").hidden = true; $("app").hidden = true; $("forceChange").hidden = true;
  $("onboard").hidden = false;
  $("obNotice").textContent = "";
}
async function enterApp() {
  $("auth").hidden = true; $("forceChange").hidden = true; $("onboard").hidden = true;
  $("app").hidden = false;
  $("connState").textContent = me.username + " · " + (me.role === "admin" ? "管理员" : "普通用户");
  $("navUsers").hidden = me.role !== "admin";
  try { const data = await api("/api/queue"); renderQueue(data); timer = setTimeout(refreshQueue, 2000); }
  catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
}
function showView(name) {
  for (const item of document.querySelectorAll(".nav-item")) item.classList.toggle("active", item.dataset.view === name);
  for (const view of document.querySelectorAll(".view")) view.hidden = view.id !== "view-" + name;
  $("content").classList.toggle("wide", name === "library" || name === "actress");
  if (name !== "library") disconnectMediaObserver();
  if (name === "library" && !libLoaded) loadLibrary();
  if (name === "actress" && !actLoaded) loadActresses();
  if (name === "settings") loadSettings();
  if (name === "users") loadUsers();
  if (name === "filing") { loadPlans(); clearInterval(ppTimer); ppTimer = setInterval(loadPlans, 5000); }
  else clearInterval(ppTimer);
  if (name === "organize") loadOrgState();
}
/* ---------------- queue ---------------- */
const ACTIVE_STATUS = ["pending", "running", "cancelling"];
function jobCard(job) {
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
  return card;
}
function jobPercent(job) {
  if (job.status === "completed") return 100;
  return job.total ? Math.min(100, job.done / job.total * 100) : 0;
}
function groupCounts(jobs) {
  return {total: jobs.length,
          done: jobs.filter(j => j.status === "completed").length,
          active: jobs.filter(j => ACTIVE_STATUS.includes(j.status)).length};
}
function countsText(jobs) {
  const c = groupCounts(jobs);
  return "共 " + c.total + " 部 · 完成 " + c.done + " · 进行 " + c.active;
}
function renderQueue(data) {
  queueData = data;
  const active = data.jobs.filter(j => ACTIVE_STATUS.includes(j.status)).length;
  const badge = $("queueBadge"); badge.hidden = active === 0; badge.textContent = active;
  $("halted").hidden = !data.halted;
  // Group jobs by actress ("" = 未分类）.
  const groups = new Map();
  for (const job of data.jobs) {
    const key = job.actress || "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(job);
  }
  if (queueActress !== null && !groups.has(queueActress)) queueActress = null;
  if (queueActress === null) {
    $("queueDetail").hidden = true;
    const box = $("queueGroups"); box.hidden = false; box.replaceChildren();
    if (!data.jobs.length) {
      const empty = node("div", undefined, "empty");
      empty.append(node("div", "队", "empty-icon"), node("h3", "队列是空的"), node("p", "在搜索页粘贴视频网址，或从搜索结果一键加入。"));
      box.append(empty);
    }
    const keys = [...groups.keys()].sort((a, b) => {
      if (a === "") return 1; if (b === "") return -1;  // 未分类 always last
      const ga = groups.get(a), gb = groups.get(b);
      const actA = ga.some(j => ACTIVE_STATUS.includes(j.status)) ? 0 : 1;
      const actB = gb.some(j => ACTIVE_STATUS.includes(j.status)) ? 0 : 1;
      if (actA !== actB) return actA - actB;
      if (gb.length !== ga.length) return gb.length - ga.length;
      return a < b ? -1 : 1;
    });
    for (const key of keys) {
      const jobs = groups.get(key);
      const card = node("article", undefined, "qgroup");
      const head = node("div", undefined, "job-head");
      head.append(node("p", key || "未分类", "job-url"),
                  node("span", countsText(jobs), "meta"),
                  node("span", "›", "chev"));
      card.append(head);
      const progress = node("progress"); progress.max = 100;
      progress.value = jobs.reduce((sum, j) => sum + jobPercent(j), 0) / jobs.length;
      card.append(progress);
      card.onclick = () => { queueActress = key; renderQueue(queueData); };
      box.append(card);
    }
  } else {
    $("queueGroups").hidden = true;
    $("queueDetail").hidden = false;
    const jobs = groups.get(queueActress) || [];
    $("queueDetailTitle").textContent = queueActress || "未分类";
    $("queueDetailMeta").textContent = countsText(jobs);
    const container = $("jobs"); const fragment = document.createDocumentFragment();
    for (const job of jobs) fragment.append(jobCard(job));
    container.replaceChildren(fragment);
  }
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
  clearTimeout(timer); if (!sessionToken) return;
  const id = ++readSeq;
  try { const data = await api("/api/queue"); if (id === readSeq) renderQueue(data); }
  catch (error) { if (id === readSeq && error.message !== "Unauthorized") toast(error.message); }
  finally { if (sessionToken && id === readSeq) timer = setTimeout(refreshQueue, 2000); }
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
  $("backfillRow").hidden = true; $("bfMissingPanel").hidden = true;
  try {
    const data = await api("/api/search?q=" + encodeURIComponent(q) + "&site=" + encodeURIComponent(site));
    lastResults = data.results || [];
    lastQuery = q;
    const grid = $("results"); grid.replaceChildren();
    if (data.error) { $("searchStatus").textContent = ""; toast(data.error); }
    else $("searchStatus").textContent = "共 " + data.total + " 条结果，本页 " + lastResults.length + " 条";
    if (!lastResults.length && !data.error) { const e = node("div", undefined, "empty"); e.append(node("h3", "没有结果"), node("p", "换个关键词或站点试试。")); grid.append(e); }
    for (const item of lastResults) grid.append(resultCard(item));
    $("backfillRow").hidden = !lastResults.length;
    renderMissing();
  } catch (error) { $("searchStatus").textContent = ""; if (error.message !== "Unauthorized") toast(error.message); }
  finally { $("searchBtn").disabled = false; }
}
/* ---------------- search stats: 不在库清单 ---------------- */
/* 纯函数：从搜索结果算不在库统计（可单测）。items 保持结果原序。 */
function missingStats(results) {
  const list = results || [];
  let inLib = 0, inQueue = 0, downloadable = 0;
  const items = [];
  for (const item of list) {
    if (item.in_library) { inLib++; continue; }
    items.push(item);
    if (item.in_queue) inQueue++; else downloadable++;
  }
  return {total: list.length, inLib, missing: items.length, inQueue, downloadable, items};
}
function renderMissing() {
  const stats = missingStats(lastResults);
  const statsEl = $("bfStats"), toggle = $("bfListToggle"), panel = $("bfMissingPanel");
  panel.hidden = true; panel.replaceChildren();
  toggle.textContent = "查看清单";
  if (!lastResults.length) { statsEl.textContent = ""; toggle.hidden = true; return; }
  if (!stats.missing) { statsEl.textContent = "全部已在库（共 " + stats.inLib + " 条）"; toggle.hidden = true; return; }
  statsEl.textContent = "不在库 " + stats.missing + " 条 · 已在队列 " + stats.inQueue + " 条 · 可下载 " + stats.downloadable + " 条 · 已在库 " + stats.inLib + " 条";
  toggle.hidden = false;
  for (const item of stats.items) {
    const row = node("div", undefined, "bf-miss-row");
    row.append(node("span", item.code || "—", "bf-miss-code"),
      node("span", item.title || "", "bf-miss-title"),
      node("span", item.in_queue ? "已在队列" : "未下载", item.in_queue ? "tag queue" : "tag"));
    panel.append(row);
  }
}
/* ---------------- backfill （一键补充入库） ---------------- */
function renderBfConfirm() {
  const ready = bfPlan ? (bfPlan.items || []).filter(i => i.status === "ready").length : 0;
  const confirm = $("bfConfirm");
  confirm.hidden = !!bfPlan && ready === 0;
  confirm.disabled = !bfPlan || bfBusy || bfSel.size === 0;
  confirm.textContent = "确认下载 " + bfSel.size + " 部";
  $("bfCancel").textContent = bfPlan && ready === 0 ? "关闭" : "取消";
}
function renderBackfill() {
  const items = (bfPlan && bfPlan.items) || [];
  const ready = items.filter(i => i.status === "ready");
  bfSel = new Set();
  items.forEach((item, idx) => { if (item.status === "ready") bfSel.add(idx); });
  const join = values => [...new Set(values.filter(Boolean))].join("、");
  const cn = join(ready.map(i => i.actress_cn)), jp = join(ready.map(i => i.actress_jp));
  $("bfSummary").textContent = "女优 " + (cn || jp || "—") + (jp && cn ? "（" + jp + "）" : "") +
    " · 目标文件夹 " + (join(ready.map(i => i.target_dir)) || "—") + " · 可下载 " + ready.length + " 部";
  $("bfCounts").textContent = "已排除：已在库 " + items.filter(i => i.status === "in_library").length +
    " · 已在队列 " + items.filter(i => i.status === "in_queue").length +
    " · 无法识别女优 " + items.filter(i => i.status === "no_actress").length;
  const list = $("bfList"); list.replaceChildren();
  if (!ready.length) list.append(node("p", "没有可下载的新作品。", "meta"));
  items.forEach((item, idx) => {
    if (item.status !== "ready") return;
    const row = node("label", undefined, "bf-row");
    const box = document.createElement("input"); box.type = "checkbox"; box.checked = true;
    box.onchange = () => { box.checked ? bfSel.add(idx) : bfSel.delete(idx); renderBfConfirm(); };
    const main = node("div", undefined, "bf-main");
    const line = node("div", undefined, "bf-line");
    line.append(node("span", item.code || "—", "bf-code"), node("span", item.title || item.site_title || ""));
    main.append(line, node("div", item.target_name || "", "bf-target"));
    row.append(box, main);
    list.append(row);
  });
  renderBfConfirm();
}
function closeBackfill() { if (!bfBusy) $("bfModal").hidden = true; }
async function openBackfill() {
  if (!lastResults.length || bfBusy) return;
  bfPlan = null; bfSel = new Set();
  $("bfSummary").textContent = "正在计算入库计划…";
  $("bfCounts").textContent = "";
  $("bfList").replaceChildren();
  $("bfError").textContent = "";
  renderBfConfirm();
  $("bfModal").hidden = false;
  $("backfillBtn").disabled = true;
  try {
    bfPlan = await api("/api/backfill/plan", {
      items: lastResults.map(r => ({url: r.url, code: r.code || "", title: r.title || ""})),
      actress_hint: lastQuery});
    renderBackfill();
  } catch (error) {
    if (error.message !== "Unauthorized") $("bfError").textContent = error.message;
    renderBfConfirm();
  } finally { $("backfillBtn").disabled = false; }
}
const BF_SKIP_REASONS = {in_library: "已在库", in_queue: "已在队列", no_actress: "无法识别女优", invalid_url: "链接无效"};
function bfSkipSummary(skipped) {
  return (skipped || []).map(s => (s.code || "—") + "（" + (BF_SKIP_REASONS[s.reason] || s.reason || "未知原因") + "）").join("、");
}
async function confirmBackfill() {
  if (bfBusy || !bfPlan) return;
  const chosen = [...bfSel].map(idx => bfPlan.items[idx]).filter(Boolean);
  if (!chosen.length) return;
  bfBusy = true; renderBfConfirm(); $("bfError").textContent = "";
  try {
    const data = await api("/api/backfill/start", {
      items: chosen.map(i => ({
        url: i.url, code: i.code || "", title: i.title || i.site_title || "",
        actress_jp: i.actress_jp || "", actress_cn: i.actress_cn || "",
        target_dir: i.target_dir || "", target_name: i.target_name || ""})),
      actress_hint: lastQuery});
    const skipped = data.skipped || [];
    if (data.added > 0) {
      bfBusy = false;
      $("bfModal").hidden = true; bfPlan = null; bfSel = new Set();
      toast("已加入下载队列 " + data.added + " 部" + (skipped.length ? "，跳过 " + skipped.length + " 部：" + bfSkipSummary(skipped) : ""));
      refreshQueue();
      showView("queue");
    } else {
      // Nothing was enqueued: keep the dialog open and say why, instead
      // of landing the user on an empty queue with no explanation.
      $("bfError").textContent = skipped.length
        ? "未能加入队列：" + bfSkipSummary(skipped)
        : "未能加入队列。";
    }
  } catch (error) {
    if (error.message !== "Unauthorized") $("bfError").textContent = error.message;
  } finally { bfBusy = false; renderBfConfirm(); }
}
/* ---------------- library ---------------- */
function fmtSize(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"]; let v = bytes, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return v.toFixed(v >= 100 ? 0 : 1) + " " + units[i];
}
let libPath = "", libShowAll = false, libTreeData = null;
let libActData = [], libActLoaded = false;
const LIB_RENDER_CAP = 300;
function folderGlyph() {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "52");
  svg.setAttribute("height", "52");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(NS, "path");
  path.setAttribute("d", "M3 5.5A1.5 1.5 0 0 1 4.5 4h5l2 2.5h7A1.5 1.5 0 0 1 20 8v10.5a1.5 1.5 0 0 1-1.5 1.5h-14A1.5 1.5 0 0 1 3 18.5v-13Z");
  path.setAttribute("fill", "var(--pri)");
  path.setAttribute("opacity", ".9");
  svg.append(path);
  return svg;
}
/* Lazy media: a card's cover (or its server-generated preview frame) is
   requested only when the card approaches the viewport, so opening a big
   folder never fires hundreds of image requests at once. */
let mediaObserver = null;
function disconnectMediaObserver() {
  if (mediaObserver) { mediaObserver.disconnect(); mediaObserver = null; }
}
function ensureMediaObserver() {
  if (mediaObserver) return mediaObserver;
  mediaObserver = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const poster = entry.target;
      mediaObserver.unobserve(poster);
      const cover = poster.dataset.cover || "", rel = poster.dataset.rel || "";
      const img = document.createElement("img");
      img.alt = "";
      img.src = cover
        ? "/api/cover?rel=" + encodeURIComponent(cover) + "&t=" + encodeURIComponent(sessionToken)
        : "/api/thumb?rel=" + encodeURIComponent(rel) + "&t=" + encodeURIComponent(sessionToken);
      img.onerror = () => img.remove();
      poster.append(img);
    }
  }, {rootMargin: "300px"});
  return mediaObserver;
}
function libWorkCard(work) {
  const card = node("article", undefined, "work");
  const poster = node("div", undefined, "poster");
  poster.append(node("span", work.code || "—", "code-big"));
  poster.dataset.cover = work.cover_rel || "";
  poster.dataset.rel = work.rel || "";
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
  ensureMediaObserver().observe(poster);
  return card;
}
function libFolderCard(folder) {
  const card = node("article", undefined, "work folder-card");
  const poster = node("div", undefined, "poster folder-poster");
  const glyph = node("span", undefined, "folder-glyph");
  glyph.append(folderGlyph());
  poster.append(glyph);
  card.append(poster);
  const body = node("div", undefined, "work-body");
  body.append(node("div", folder.name, "work-title"));
  const meta = node("div", undefined, "work-meta");
  meta.append(node("span", folder.count + " 部"));
  body.append(meta);
  card.append(body);
  card.onclick = () => navigateLib(folder.rel);
  return card;
}
function renderCrumbs(crumbs) {
  const bar = $("libCrumbs"); bar.replaceChildren();
  (crumbs || []).forEach((crumb, i, all) => {
    if (i) bar.append(node("span", "›", "sep"));
    const last = i === all.length - 1;
    const b = node("button", crumb.name, last ? "current" : "");
    if (!last) b.onclick = () => navigateLib(crumb.rel);
    bar.append(b);
  });
}
function renderLibTree() {
  const data = libTreeData; if (!data) return;
  renderCrumbs(data.crumbs);
  const folders = data.folders || [], works = data.works || [];
  const fbox = $("libFolders"); fbox.replaceChildren();
  fbox.hidden = !folders.length;
  for (const folder of folders) fbox.append(libFolderCard(folder));
  const grid = $("libGrid"); grid.replaceChildren();
  if (!folders.length && !works.length) {
    const e = node("div", undefined, "empty");
    e.append(node("h3", "空目录"), node("p", "这个文件夹里还没有子文件夹或视频。"));
    grid.append(e);
    return;
  }
  const shown = libShowAll ? works : works.slice(0, LIB_RENDER_CAP);
  for (const work of shown) grid.append(libWorkCard(work));
  if (!libShowAll && works.length > LIB_RENDER_CAP) {
    const more = node("button", "显示全部（共 " + works.length + " 部）", "lib-more");
    more.onclick = () => {
      libShowAll = true; more.remove();
      for (const work of works.slice(LIB_RENDER_CAP)) grid.append(libWorkCard(work));
    };
    grid.append(more);
  }
}
async function loadLibraryTree() {
  disconnectMediaObserver();
  try {
    const data = await api("/api/library/tree?path=" + encodeURIComponent(libPath));
    libTreeData = data;
    libPath = data.path || "";
    libLoaded = true;
    renderLibTree();
  } catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
}
function navigateLib(path) {
  libPath = path || "";
  libShowAll = false;
  loadLibraryTree().then(() => { const v = $("view-library"); if (v) v.scrollIntoView(); });
}
async function loadLibActresses() {
  if (libActLoaded) return;
  try {
    const data = await api("/api/library/actresses");
    libActData = data.actresses || [];
    libActLoaded = true;
  } catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
}
function renderActPicker() {
  const list = $("libActList");
  const q = $("libActSearch").value.trim().toLowerCase();
  const matches = libActData.filter(a => !q || a.name.toLowerCase().includes(q));
  list.replaceChildren();
  if (!matches.length) list.append(node("div", "没有匹配的女优", "picker-empty"));
  for (const a of matches.slice(0, 200)) {
    const b = node("button", undefined, "picker-item");
    b.append(node("span", a.name), node("span", "库内 " + a.count + " 部", "cnt"));
    b.onclick = () => {
      $("libActSearch").value = "";
      list.hidden = true;
      navigateLib(a.dir);
    };
    list.append(b);
  }
  list.hidden = false;
}
async function loadLibrary() {
  loadLibActresses();
  await loadLibraryTree();
}
/* ---------------- player ---------------- */
function openPlayer(work) {
  $("plTitle").textContent = (work.code ? work.code + " " : "") + (work.title || "");
  $("plInfo").textContent = work.rel + " · " + fmtSize(work.size);
  const video = $("plVideo");
  video.src = "/api/stream?rel=" + encodeURIComponent(work.rel) + "&t=" + encodeURIComponent(sessionToken);
  $("player").hidden = false;
}
function closePlayer() {
  const video = $("plVideo");
  video.pause(); video.removeAttribute("src"); video.load();
  $("player").hidden = true;
}
/* ---------------- postprocess （归类预览） ---------------- */
const PP_STATUS = {pending: "待确认", done: "已完成", conflict: "冲突", error: "失败", dismissed: "已忽略"};
let ppPlans = [], ppSel = new Set();
function renderPlans() {
  const list = $("ppList"); list.replaceChildren();
  const visible = ppPlans.filter(p => p.status !== "dismissed");
  if (!visible.length) {
    const e = node("div", undefined, "empty");
    e.append(node("div", "归", "empty-icon"), node("h3", "暂无归类记录"), node("p", "下载完成后，待确认的重命名与归类会出现在这里。"));
    list.append(e);
  }
  for (const plan of visible) {
    const row = node("article", undefined, "plan");
    const head = node("div", undefined, "plan-head");
    if (plan.status === "pending") {
      const box = document.createElement("input"); box.type = "checkbox"; box.checked = ppSel.has(plan.id);
      box.onchange = () => { box.checked ? ppSel.add(plan.id) : ppSel.delete(plan.id); renderPlans(); };
      head.append(box);
    }
    const names = node("div", undefined, "plan-names");
    names.append(node("div", plan.src_name, "plan-src"), node("div", "↓", "plan-arrow"), node("div", plan.new_name, "plan-new"));
    names.append(node("div", plan.target_rel ? "→ " + plan.target_rel : "→ 原地重命名（不移动）", "plan-target"));
    if (plan.reason) names.append(node("p", plan.reason, "meta"));
    head.append(names);
    const side = node("div", undefined, "plan-side");
    side.append(node("span", PP_STATUS[plan.status] || plan.status, "pstatus " + plan.status));
    if (plan.source) side.append(node("span", plan.source, "tag"));
    head.append(side);
    row.append(head);
    list.append(row);
  }
  const pending = ppPlans.filter(p => p.status === "pending");
  ppSel = new Set([...ppSel].filter(id => pending.some(p => p.id === id)));
  $("ppBar").hidden = !pending.length;
  $("ppSelText").textContent = "已选 " + ppSel.size + " 项";
}
async function loadPlans() {
  try { const data = await api("/api/postprocess"); ppPlans = data.plans || []; renderPlans(); }
  catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
}
async function ppRun(path, ids, doneText) {
  if (!ids.length) { toast("先勾选要处理的条目"); return; }
  try {
    const data = await api(path, {ids});
    ppPlans = data.plans || ppPlans; ppSel.clear(); renderPlans();
    if (data.results) {
      const ok = data.results.filter(r => r.status === "done").length;
      const bad = data.results.length - ok;
      toast(doneText + "：成功 " + ok + (bad ? "，异常 " + bad : ""));
    } else toast(doneText);
  } catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
}
/* ---------------- organize （本地整理） ---------------- */
let orgScope = "", orgData = null, orgSel = new Set();
function orgEntryRow(entry, selectable) {
  const row = node("article", undefined, "plan");
  const head = node("div", undefined, "plan-head");
  if (selectable) {
    const box = document.createElement("input"); box.type = "checkbox"; box.checked = orgSel.has(entry.id);
    box.onchange = () => { box.checked ? orgSel.add(entry.id) : orgSel.delete(entry.id); renderOrg(); };
    head.append(box);
  }
  const names = node("div", undefined, "plan-names");
  names.append(node("div", entry.src_rel, "plan-src"), node("div", "↓", "plan-arrow"), node("div", entry.new_name || "—", "plan-new"));
  if (entry.reason) names.append(node("p", entry.reason, "meta"));
  head.append(names);
  const side = node("div", undefined, "plan-side");
  side.append(node("span", entry.grade + " 级", "grade " + entry.grade));
  if (entry.source) side.append(node("span", entry.source, "tag"));
  if (entry.actress_cn_low) side.append(node("span", "音译·低置信", "tag low"));
  head.append(side);
  row.append(head);
  return row;
}
function renderOrg() {
  const stats = orgData && orgData.stats;
  $("orgStats").hidden = !stats;
  if (stats) {
    $("stScanned").textContent = stats.scanned; $("stRename").textContent = stats.renamable;
    $("stIso").textContent = stats.isolated; $("stStd").textContent = stats.standard;
    $("orgStatus").textContent = orgData.scope ? "范围：" + orgData.scope : "范围：全部";
  }
  const list = $("orgList"); list.replaceChildren();
  const entries = (orgData && orgData.entries) || [];
  if (stats && !entries.length) {
    const e = node("div", undefined, "empty");
    e.append(node("div", "整", "empty-icon"), node("h3", "没有待更名的文件"), node("p", "这个范围里的视频都已符合命名规范，或无法识别番号。"));
    list.append(e);
  }
  for (const entry of entries) list.append(orgEntryRow(entry, true));
  const iso = $("orgIso"); iso.replaceChildren();
  const isolated = (orgData && orgData.isolated) || [];
  if (isolated.length) {
    iso.append(node("h3", "疑似误识别 · 已隔离（不会执行）"));
    for (const entry of isolated) iso.append(orgEntryRow(entry, false));
  }
  orgSel = new Set([...orgSel].filter(id => entries.some(e => e.id === id)));
  $("orgBar").hidden = !entries.length;
  $("orgSelText").textContent = "已选 " + orgSel.size + " 项";
  const logBox = $("orgLog"); logBox.replaceChildren();
  const log = (orgData && orgData.log) || [];
  if (!log.length) logBox.append(node("p", "暂无更名记录。", "meta"));
  for (const item of [...log].reverse()) {
    const row = node("div", undefined, "log-row" + (item.reverted ? " done" : ""));
    const names = node("div", undefined, "log-names");
    names.append(node("div", item.old_rel), node("div", "→ " + item.new_rel));
    row.append(names);
    if (item.reverted) row.append(node("span", "已撤销", "tag"));
    else {
      const b = node("button", "撤销");
      b.onclick = () => orgRollback([item.idx]);
      row.append(b);
    }
    logBox.append(row);
  }
  $("orgRollbackAll").disabled = !log.some(item => !item.reverted);
}
async function loadOrgState() {
  try { orgData = await api("/api/organize"); renderOrg(); }
  catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
}
async function orgRollback(ids) {
  if (!confirm("撤销选中的更名，把文件改回原名？")) return;
  try {
    const data = await api("/api/organize/rollback", ids === null ? {} : {ids});
    orgData = data;
    toast("已撤销 " + data.result.rolled + " 项" + (data.result.failed.length ? "，" + data.result.failed.length + " 项失败" : ""));
    renderOrg();
  } catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
}
/* ---------------- actress gap （女优缺片） ---------------- */
let actLoaded = false, actMissing = [], actSel = new Set();
function renderActList(actresses) {
  const grid = $("actList"); grid.replaceChildren();
  if (!actresses.length) { grid.append(node("span", "片库里还没有按女优归类的作品", "meta")); return; }
  for (const a of actresses) {
    const cell = node("div", undefined, "act-cell");
    cell.append(node("span", a.name_cn, "act-cell-name"),
                node("span", "库内 " + a.count + " 部", "act-cell-count"));
    const b = node("button", "查询缺片");
    b.onclick = () => { $("actName").value = a.name_cn; doActGap(); };
    cell.append(b);
    grid.append(cell);
  }
}
async function loadActresses() {
  try { const data = await api("/api/actress/list"); actLoaded = true; renderActList(data.actresses || []); }
  catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
}
function renderActBar() {
  $("actBar").hidden = !actMissing.length;
  $("actSelText").textContent = "已选 " + actSel.size + " 部";
}
function renderActGrid() {
  const grid = $("actGrid"); grid.replaceChildren();
  for (const item of actMissing) {
    const card = node("article", undefined, "work");
    const poster = node("div", undefined, "poster");
    poster.append(node("span", item.code || "—", "code-big"));
    if (item.thumbnail) { const img = document.createElement("img"); img.alt = ""; img.loading = "lazy"; img.src = item.thumbnail; img.onerror = () => img.remove(); poster.append(img); }
    card.append(poster);
    const body = node("div", undefined, "work-body");
    body.append(node("div", item.title || item.code, "work-title"));
    const meta = node("div", undefined, "work-meta");
    if (item.code) meta.append(node("span", item.code));
    if (item.in_queue) meta.append(node("span", "已在队列", "tag queue"));
    body.append(meta);
    const label = node("label", undefined, "row");
    const box = document.createElement("input"); box.type = "checkbox";
    box.checked = actSel.has(item.code); box.disabled = !!item.in_queue;
    box.style.width = "18px"; box.style.height = "18px"; box.style.flex = "none"; box.style.accentColor = "var(--pri)";
    box.onchange = () => { box.checked ? actSel.add(item.code) : actSel.delete(item.code); renderActBar(); };
    label.append(box, node("span", item.in_queue ? "已在队列" : "加入下载队列"));
    body.append(label);
    card.append(body); grid.append(card);
  }
  renderActBar();
}
async function doActGap() {
  const name = $("actName").value.trim();
  if (!name) { toast("请输入女优名，或点上面的片库女优"); return; }
  $("actQuery").disabled = true;
  $("actStatus").textContent = "查询中…（对照 Jable 全集需要几秒）";
  $("actOwned").textContent = "";
  $("actOwnedGrid").replaceChildren();
  $("actGrid").replaceChildren(); $("actBar").hidden = true;
  try {
    const data = await api("/api/actress/gap", {name});
    if (data.error) { $("actStatus").textContent = data.error; actMissing = []; actSel.clear(); return; }
    actMissing = data.missing || [];
    actSel = new Set(actMissing.filter(m => !m.in_queue).map(m => m.code));
    const who = (data.actress_cn || name) + (data.actress_jp ? "（" + data.actress_jp + "）" : "");
    $("actStatus").textContent = who + " · 全集 " + data.total + " 部 · 已有 " + (data.owned || []).length + " · 缺 " + actMissing.length + (data.cached ? " · 全集来自 24 小时内缓存" : "");
    const owned = data.owned || [];
    $("actOwned").textContent = owned.length ? "已有 " + owned.length + " 部：" : "";
    const ownedGrid = $("actOwnedGrid");
    for (const code of owned) ownedGrid.append(node("span", code, "tag lib"));
    if (!actMissing.length) toast("没有缺片，这个女优的全集都齐了");
    renderActGrid();
  } catch (error) { $("actStatus").textContent = ""; if (error.message !== "Unauthorized") toast(error.message); }
  finally { $("actQuery").disabled = false; }
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
/* ---------------- users （用户管理，管理员） ---------------- */
function renderUsers(users) {
  const box = $("userList"); box.replaceChildren();
  if (!users.length) { box.append(node("p", "暂无用户。", "meta")); return; }
  for (const user of users) {
    const row = node("div", undefined, "user-row");
    const main = node("div", undefined, "user-main");
    main.append(node("span", user.username, "user-name"));
    main.append(node("span", user.role === "admin" ? "管理员" : "普通用户", "tag" + (user.role === "admin" ? " queue" : "")));
    if (user.must_change) main.append(node("span", "待改密", "tag low"));
    main.append(node("span", "创建于 " + new Date(user.created * 1000).toLocaleDateString("zh-CN"), "meta"));
    row.append(main);
    const actions = node("div", undefined, "actions");
    const reset = node("button", "重置密码");
    reset.onclick = async () => {
      const pw = prompt("为 " + user.username + " 设置临时密码（至少 8 位），对方下次登录必须改密：");
      if (pw === null) return;
      try { await api("/api/users/reset", {username: user.username, new_password: pw}); toast("已重置 " + user.username + " 的密码，其现有登录已失效"); loadUsers(); }
      catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
    };
    actions.append(reset);
    const roleBtn = node("button", user.role === "admin" ? "设为普通用户" : "设为管理员");
    roleBtn.onclick = async () => {
      const next = user.role === "admin" ? "user" : "admin";
      if (!confirm("把 " + user.username + " 设为" + (next === "admin" ? "管理员" : "普通用户") + "？")) return;
      try {
        await api("/api/users/role", {username: user.username, role: next});
        if (me && user.username === me.username) { me.role = next; $("navUsers").hidden = next !== "admin"; $("connState").textContent = me.username + " · " + (next === "admin" ? "管理员" : "普通用户"); }
        toast("已更新 " + user.username + " 的角色");
        loadUsers();
      } catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
    };
    actions.append(roleBtn);
    const del = node("button", "删除");
    del.disabled = !!me && user.username === me.username;
    del.title = del.disabled ? "不能删除当前登录的账号" : "";
    del.onclick = async () => {
      if (!confirm("确定删除用户 " + user.username + "？此操作不可撤销。")) return;
      try { await api("/api/users/delete", {username: user.username}); toast("已删除 " + user.username); loadUsers(); }
      catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
    };
    actions.append(del);
    row.append(actions);
    box.append(row);
  }
}
async function loadUsers() {
  try { const data = await api("/api/users"); renderUsers(data.users || []); }
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
$("libRefresh").onclick = () => { libActLoaded = false; loadLibrary(); };
$("queueBack").onclick = () => { queueActress = null; if (queueData) renderQueue(queueData); };
$("backfillBtn").onclick = openBackfill;
$("bfListToggle").onclick = () => {
  const panel = $("bfMissingPanel");
  panel.hidden = !panel.hidden;
  $("bfListToggle").textContent = panel.hidden ? "查看清单" : "收起清单";
};
$("bfClose").onclick = closeBackfill;
$("bfCancel").onclick = closeBackfill;
$("bfBackdrop").onclick = closeBackfill;
$("bfConfirm").onclick = confirmBackfill;
document.addEventListener("keydown", event => { if (event.key === "Escape" && !$("bfModal").hidden) closeBackfill(); });
$("libActSearch").oninput = () => renderActPicker();
$("libActSearch").onfocus = () => renderActPicker();
$("libActSearch").onkeydown = event => { if (event.key === "Escape") $("libActList").hidden = true; };
$("libActAll").onclick = () => {
  $("libActSearch").value = ""; $("libActList").hidden = true;
  navigateLib("");
};
document.addEventListener("mousedown", event => {
  if (!$("actPicker").contains(event.target)) $("libActList").hidden = true;
});
$("actQuery").onclick = doActGap;
$("actName").onkeydown = event => { if (event.key === "Enter") doActGap(); };
$("actEnqueue").onclick = async () => {
  const chosen = actMissing.filter(m => actSel.has(m.code) && !m.in_queue);
  if (!chosen.length) { toast("先勾选要下载的缺片"); return; }
  $("actEnqueue").disabled = true;
  try {
    await api("/api/queue", {jobs: chosen.map(m => ({url: m.url}))});
    for (const m of chosen) { m.in_queue = true; actSel.delete(m.code); }
    renderActGrid(); refreshQueue();
    toast("已入队 " + chosen.length + " 部");
  } catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
  finally { $("actEnqueue").disabled = false; }
};
$("ppRefresh").onclick = loadPlans;
$("ppExec").onclick = () => ppRun("/api/postprocess/execute", [...ppSel], "归类执行完毕");
$("ppExecAll").onclick = () => ppRun("/api/postprocess/execute", ppPlans.filter(p => p.status === "pending").map(p => p.id), "归类执行完毕");
$("ppDismiss").onclick = () => ppRun("/api/postprocess/dismiss", [...ppSel], "已忽略选中条目");
for (const chip of document.querySelectorAll("#orgScopes .chip")) chip.onclick = () => {
  orgScope = chip.dataset.scope;
  for (const c of document.querySelectorAll("#orgScopes .chip")) c.classList.toggle("active", c === chip);
};
$("orgScan").onclick = async () => {
  $("orgScan").disabled = true; $("orgStatus").textContent = "扫描中…（大片库的元数据查询可能需要一会儿）";
  try {
    await api("/api/organize/scan", {scope: orgScope});
    orgSel.clear();
    await loadOrgState();
    for (const entry of (orgData.entries || [])) orgSel.add(entry.id);
    renderOrg();
    toast("扫描完成");
  } catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
  finally { $("orgScan").disabled = false; }
};
$("orgExec").onclick = async () => {
  const ids = [...orgSel];
  if (!ids.length) { toast("先勾选要更名的文件"); return; }
  if (!confirm("将更名 " + ids.length + " 个文件，执行前会写入回滚记录，可一键撤销。")) return;
  try {
    const data = await api("/api/organize/execute", {ids});
    orgData = data; orgSel.clear(); renderOrg();
    const ok = data.results.filter(r => r.ok).length;
    toast("更名完成：成功 " + ok + (data.results.length - ok ? "，跳过 " + (data.results.length - ok) : ""));
  } catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
};
$("orgRollbackAll").onclick = () => orgRollback(null);
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
$("disconnect").onclick = () => logout();
async function doLogin() {
  if ($("loginBtn").disabled) return;
  const active = ++session; $("loginBtn").disabled = true;
  const username = $("loginUser").value.trim();
  const password = $("loginPass").value; $("loginPass").value = "";
  try {
    const response = await fetch("/api/login", {method: "POST", cache: "no-store", credentials: "omit",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({username, password})});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "登录失败");
    if (active !== session) return;
    sessionToken = data.session;
    me = {username: data.username, role: data.role, must_change: data.must_change};
    $("authNotice").textContent = "";
    if (data.must_change) { loginPassword = password; showForceChange(); return; }
    enterApp();
  } catch (error) {
    if (active === session) $("authNotice").textContent = error.message;
  } finally { if (active === session) $("loginBtn").disabled = false; }
}
$("loginBtn").onclick = doLogin;
$("loginPass").onkeydown = event => { if (event.key === "Enter") doLogin(); };
$("loginUser").onkeydown = event => { if (event.key === "Enter") $("loginPass").focus(); };
$("fcLogout").onclick = () => logout();
$("fcSubmit").onclick = async () => {
  const newPw = $("fcNew").value, confirmPw = $("fcConfirm").value;
  if (newPw.length < 8) { $("fcNotice").textContent = "新密码至少 8 位"; return; }
  if (newPw !== confirmPw) { $("fcNotice").textContent = "两次输入的新密码不一致"; return; }
  $("fcSubmit").disabled = true;
  try {
    const data = await api("/api/change-password", {old_password: loginPassword, new_password: newPw});
    loginPassword = ""; $("fcNew").value = ""; $("fcConfirm").value = "";
    if (me) me.must_change = false;
    if (data.needs_onboarding) showOnboard(); else enterApp();
  } catch (error) {
    if (error.message !== "Unauthorized") $("fcNotice").textContent = error.message;
  } finally { $("fcSubmit").disabled = false; }
};
$("fcConfirm").onkeydown = event => { if (event.key === "Enter") $("fcSubmit").click(); };
$("obSkip").onclick = () => enterApp();
$("obCreate").onclick = async () => {
  const username = $("obUser").value.trim(), password = $("obPass").value, role = $("obRole").value;
  if (!username) { $("obNotice").textContent = "请输入用户名"; return; }
  if (password.length < 8) { $("obNotice").textContent = "密码至少 8 位"; return; }
  $("obCreate").disabled = true;
  try {
    await api("/api/users", {username, password, role});
    $("obUser").value = ""; $("obPass").value = "";
    toast("账号 " + username + " 已创建");
    enterApp();
  } catch (error) {
    if (error.message !== "Unauthorized") $("obNotice").textContent = error.message;
  } finally { $("obCreate").disabled = false; }
};
$("nuCreate").onclick = async () => {
  const username = $("nuUser").value.trim(), password = $("nuPass").value, role = $("nuRole").value;
  if (!username) { toast("请输入用户名"); return; }
  if (password.length < 8) { toast("密码至少 8 位"); return; }
  try {
    await api("/api/users", {username, password, role});
    $("nuUser").value = ""; $("nuPass").value = "";
    toast("用户 " + username + " 已创建");
    loadUsers();
  } catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
};
$("cpSubmit").onclick = async () => {
  const oldPw = $("cpOld").value, newPw = $("cpNew").value, confirmPw = $("cpConfirm").value;
  if (newPw.length < 8) { toast("新密码至少 8 位"); return; }
  if (newPw !== confirmPw) { toast("两次输入的新密码不一致"); return; }
  try {
    await api("/api/change-password", {old_password: oldPw, new_password: newPw});
    $("cpOld").value = ""; $("cpNew").value = ""; $("cpConfirm").value = "";
    toast("密码已修改");
  } catch (error) { if (error.message !== "Unauthorized") toast(error.message); }
};
'''
