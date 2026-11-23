// 정글러훈련소 데스크톱 앱 (Windows)
// - 파이썬 서버(server/)를 콘솔 창 없이 띄우고, 그 화면(web/)을 창에 보여 준다.
// - 창을 닫아도 트레이에 남아 게임을 자동 녹화한다.
// - GitHub 릴리스에서 새 버전을 받아 자동으로 업데이트한다.
"use strict";

const { app, BrowserWindow, Tray, Menu, ipcMain, shell, dialog, nativeImage, Notification, screen } = require("electron");
const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const net = require("node:net");
const http = require("node:http");
const { autoUpdater } = require("electron-updater");

const IS_WIN = process.platform === "win32";
const APP_NAME = "정글러훈련소";
const HIDDEN = process.argv.includes("--hidden"); // 컴퓨터를 켤 때 자동 실행: 트레이로만

// ---------- 경로 ----------
const BACKEND = app.isPackaged ? path.join(process.resourcesPath, "backend") : path.resolve(__dirname, "..");
const VENDOR = app.isPackaged ? path.join(process.resourcesPath, "vendor") : path.join(__dirname, "vendor");
// 영상이 커서 로밍 프로필(AppData\Roaming)이 아니라 Local에 둔다
const DATA = IS_WIN && process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "JungleBootCamp") : path.join(app.getPath("userData"), "data");
const PY_ENV = path.join(DATA, "venv");
const LOG = path.join(DATA, "app.log");

fs.mkdirSync(DATA, { recursive: true });
function log(...a) {
  const line = `[${new Date().toISOString()}] ${a.join(" ")}\n`;
  try { fs.appendFileSync(LOG, line); } catch { /* 로그 실패는 무시 */ }
  if (!app.isPackaged) process.stdout.write(line);
}

let win = null;
let tray = null;
let server = null; // 파이썬 서버 프로세스
let port = 8790;
let quitting = false;
let updateState = { status: "idle" };

// ---------- 하나만 실행 ----------
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => showWindow());
  app.whenReady().then(boot);
}

function uvPath() {
  const bundled = path.join(VENDOR, IS_WIN ? "uv.exe" : "uv");
  return fs.existsSync(bundled) ? bundled : "uv";
}

function baseEnv() {
  const localBin = path.join(app.getPath("home"), ".local", "bin"); // claude.exe 설치 위치
  const ffmpegDir = path.join(VENDOR, "ffmpeg");
  return {
    ...process.env,
    // ffmpeg, claude, uv(분석 중 Claude가 `uv run tools/zoom.py`를 실행한다)를 찾을 수 있게
    PATH: [ffmpegDir, VENDOR, localBin, process.env.PATH].join(path.delimiter),
    UV_PYTHON: "3.12",
    UV_PYTHON_PREFERENCE: "only-managed",
    UV_PYTHON_INSTALL_DIR: path.join(DATA, "python"),
    UV_CACHE_DIR: path.join(DATA, "uv-cache"),
    UV_PROJECT_ENVIRONMENT: PY_ENV,
    UV_NO_PROGRESS: "1",
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8",
  };
}

// 콘솔 창 없이 실행하고 출력을 받는다
function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { cwd: BACKEND, env: baseEnv(), windowsHide: true, ...opts });
    let out = "";
    const onData = (d) => {
      const s = d.toString();
      out += s;
      s.split(/\r?\n/).filter(Boolean).forEach((l) => { log(l); opts.onLine && opts.onLine(l); });
    };
    p.stdout && p.stdout.on("data", onData);
    p.stderr && p.stderr.on("data", onData);
    p.on("error", reject);
    p.on("exit", (code) => (code === 0 ? resolve(out) : reject(new Error(`${path.basename(cmd)} 종료 코드 ${code}\n${out.slice(-1500)}`))));
  });
}

// ---------- 파이썬 환경 (첫 실행, 업데이트 뒤) ----------
async function ensurePython(status) {
  if (!app.isPackaged && process.env.JUNGLE_DEV_PYTHON) return process.env.JUNGLE_DEV_PYTHON; // 개발: 이미 있는 venv
  const stamp = path.join(PY_ENV, ".app-version");
  const py = path.join(PY_ENV, IS_WIN ? "Scripts/pythonw.exe" : "bin/python");
  const ver = app.getVersion();
  if (fs.existsSync(py) && fs.existsSync(stamp) && fs.readFileSync(stamp, "utf8") === ver) return py;
  const first = !fs.existsSync(py);
  status(first ? "처음 실행이라 분석 도구를 설치하고 있어요. 인터넷 속도에 따라 2~5분 걸려요." : "새 버전에 맞게 분석 도구를 정리하고 있어요.");
  await run(uvPath(), ["sync", "--frozen", "--no-dev", "--project", BACKEND], {
    onLine: (l) => { if (/Downloading|Installed|Prepared|Resolved/.test(l)) status(l.trim()); },
  });
  fs.writeFileSync(stamp, ver);
  return py;
}

// kb(프로 영상에서 모은 지식) 기본값을 데이터 폴더로 한 번 복사
function seedKb() {
  const dst = path.join(DATA, "kb");
  const src = path.join(BACKEND, "kb");
  fs.mkdirSync(dst, { recursive: true });
  if (!fs.existsSync(src)) return;
  for (const f of fs.readdirSync(src)) {
    const to = path.join(dst, f);
    if (!fs.existsSync(to)) fs.copyFileSync(path.join(src, f), to);
  }
}

function freePort(start) {
  return new Promise((resolve) => {
    const tryPort = (p) => {
      const s = net.createServer();
      s.once("error", () => tryPort(p + 1));
      s.once("listening", () => s.close(() => resolve(p)));
      s.listen(p, "127.0.0.1");
    };
    tryPort(start);
  });
}

function get(url, timeout = 1500) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout }, (res) => { res.resume(); resolve(res.statusCode); });
    req.on("error", () => resolve(0));
    req.on("timeout", () => { req.destroy(); resolve(0); });
  });
}

async function startServer(py) {
  port = await freePort(8790);
  const env = {
    ...baseEnv(),
    JUNGLE_DESKTOP: "1",
    JUNGLE_PORT: String(port),
    JUNGLE_VODS: path.join(DATA, "vods"),
    JUNGLE_KB: path.join(DATA, "kb"),
    JUNGLE_DB: path.join(DATA, "data", "app.db"),
    JUNGLE_APP_VERSION: app.getVersion(),
  };
  fs.mkdirSync(env.JUNGLE_VODS, { recursive: true });
  log("서버 시작", py, "port", port);
  // Windows: 콘솔 없는 pythonw로 띄운다. 서버가 띄우는 ffmpeg, claude는 server/platform_util.py가 숨긴 콘솔에서 실행한다
  server = spawn(py, ["-m", "server.desktop"], { cwd: BACKEND, env, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  server.stdout.on("data", (d) => log("[server]", d.toString().trimEnd()));
  server.stderr.on("data", (d) => log("[server]", d.toString().trimEnd()));
  server.on("exit", (code) => {
    log("서버 종료", code);
    server = null;
    if (!quitting) setTimeout(() => startServer(py).then(() => win && win.loadURL(appUrl())).catch((e) => log(e.stack)), 3000);
  });
  for (let i = 0; i < 120; i++) {
    if ((await get(`http://127.0.0.1:${port}/api/app`)) === 200) return;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("서버가 60초 안에 켜지지 않았어요");
}

const appUrl = () => `http://127.0.0.1:${port}/`;

async function stopServer() {
  if (!server) return;
  const pid = server.pid;
  // 녹화 중이던 판을 마무리하게 서버에 먼저 알리고, 그다음 프로세스 트리를 끈다
  await new Promise((resolve) => {
    const req = http.request({ host: "127.0.0.1", port, path: "/api/app/shutdown", method: "POST", timeout: 30000 }, (res) => { res.resume(); res.on("end", resolve); });
    req.on("error", resolve);
    req.on("timeout", () => { req.destroy(); resolve(); });
    req.end();
  });
  if (IS_WIN) await new Promise((r) => execFile("taskkill", ["/T", "/F", "/PID", String(pid)], { windowsHide: true }, () => r()));
  else try { process.kill(pid); } catch { /* 이미 끝남 */ }
  server = null;
}

// ---------- 창, 트레이 ----------
function getJson(url, timeout = 2000) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (c) => (body += c));
      res.on("end", () => { try { resolve(JSON.parse(body)); } catch { resolve(null); } });
    });
    req.on("error", () => resolve(null));
    req.on("timeout", () => { req.destroy(); resolve(null); });
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1360, height: 900, minWidth: 420, minHeight: 600,
    title: APP_NAME,
    icon: path.join(__dirname, "build", "icon.png"),
    show: !HIDDEN,
    autoHideMenuBar: true,
    backgroundColor: "#ffffff",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true,
      additionalArguments: [`--app-version=${app.getVersion()}`],
    },
  });
  win.setMenuBarVisibility(false);
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
  win.webContents.on("will-navigate", (e, url) => {
    if (!url.startsWith(`http://127.0.0.1:${port}`) && !url.startsWith("file:")) { e.preventDefault(); shell.openExternal(url); }
  });
  // 닫기 = 트레이로 (게임 녹화는 계속)
  win.on("close", (e) => {
    if (quitting) return;
    e.preventDefault();
    win.hide();
    if (!app._trayHinted && Notification.isSupported()) {
      app._trayHinted = true;
      new Notification({ title: APP_NAME, body: "트레이에서 계속 실행돼요. 게임을 시작하면 자동으로 녹화해요." }).show();
    }
  });
}

function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

/** 롤 클라이언트 위로 확실히 올린다 (Windows는 포커스를 뺏지 못하게 막아서, 잠깐 맨 위로 고정했다 푼다) */
function bringToFront() {
  if (!win) return;
  showWindow();
  win.setAlwaysOnTop(true);
  win.focus();
  setTimeout(() => win && win.setAlwaysOnTop(false), 1500);
}

function notify(title, body) {
  if (!Notification.isSupported()) return;
  const n = new Notification({ title, body });
  n.on("click", () => showWindow());
  n.show();
}

// ---------- 판 끝난 뒤 복기 ----------
// 녹화가 끝나면 서버가 복기 시간을 정한다. 앱을 앞으로 띄워 복기 화면을 열고, 에이전트가 큐를 막으면 다시 띄운다
let debrief = { id: null, blocked: 0 };
function watchDebrief() {
  setInterval(async () => {
    if (!port || !win) return;
    const r = await getJson(`${appUrl()}api/debrief/active`);
    const a = r && r.active;
    if (!a || !a.locked) return;
    const left = `${Math.floor(a.remaining / 60)}분 ${a.remaining % 60}초`;
    const open = () => {
      if (!win.webContents.getURL().includes(`/debrief/${a.game_id}`)) win.loadURL(`${appUrl()}debrief/${a.game_id}`);
      bringToFront();
    };
    if (a.game_id !== debrief.id) {
      debrief = { id: a.game_id, blocked: a.blocked };
      if (a.done) return;
      open();
      notify("수고했어요. 복기 시간이에요", `${left} 동안 큐를 막아 둘게요. 그동안 이 판을 같이 돌아봐요.`);
    } else if (a.blocked > debrief.blocked) {
      debrief.blocked = a.blocked;
      open();
      notify("복기 시간이라 큐를 취소했어요", `${left} 뒤에 큐를 돌릴 수 있어요.`);
    }
  }, 3000);
}

// ---------- 판 중 목표 알림 (오버레이) ----------
// 실행 의도(이러면 → 이렇게)는 그 상황 직전에 떠올라야 효과가 있다. 게임 위에 잠깐 띄우고, 포커스와 클릭은 뺏지 않는다.
// 롤은 '테두리 없음' 창 모드에서 보인다(전체 화면 모드에선 게임이 화면을 독점해서 안 보인다).
let overlay = null;
let overlayReady = null;
const ov = { timer: null, start: false, slot: -1, deaths: 0, champ: false, inGame: false };

function overlayWindow() {
  if (overlay && !overlay.isDestroyed()) return overlay;
  const d = screen.getPrimaryDisplay().bounds;
  const width = 600;
  overlay = new BrowserWindow({
    width, height: 170, x: d.x + Math.round((d.width - width) / 2), y: d.y + 56,
    frame: false, transparent: true, resizable: false, movable: false, focusable: false, skipTaskbar: true,
    show: false, hasShadow: false, alwaysOnTop: true, backgroundColor: "#00000000",
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true },
  });
  overlay.setAlwaysOnTop(true, "screen-saver");
  overlay.setIgnoreMouseEvents(true);
  overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  overlayReady = overlay.loadFile(path.join(__dirname, "overlay.html"));
  return overlay;
}

async function showOverlay(msg, ms) {
  const w = overlayWindow();
  await overlayReady;
  w.webContents.send("overlay", msg);
  if (!w.isVisible()) w.showInactive();
  clearTimeout(ov.timer);
  ov.timer = ms ? setTimeout(hideOverlay, ms) : null;
}

function hideOverlay() {
  clearTimeout(ov.timer);
  if (overlay && !overlay.isDestroyed() && overlay.isVisible()) {
    overlay.webContents.send("overlay", null);
    setTimeout(() => overlay && !overlay.isDestroyed() && overlay.hide(), 300);
  }
}

function watchOverlay() {
  setInterval(async () => {
    if (!port) return;
    const r = await getJson(`${appUrl()}api/overlay`);
    if (!r || !r.enabled || !r.goal) { if (ov.champ || ov.inGame) hideOverlay(); return; }
    const p = r.progress;
    const sub = p && p.games > 0 ? `${p.games + 1}판째 · ${p.streak}/${p.need}판 연속 지킴` : "";
    const inGame = r.state === "recording" && r.game_time != null;
    if (inGame) {
      if (!ov.inGame) Object.assign(ov, { inGame: true, start: false, slot: -1, deaths: r.deaths || 0, champ: false });
      const t = r.game_time;
      if (!ov.start && t < 90) {
        ov.start = true;
        showOverlay({ title: "이번 판 목표", sub, text: r.goal }, 12000);
      } else if ((r.deaths || 0) > ov.deaths) {
        ov.deaths = r.deaths;
        showOverlay({ title: "부활하면서 다시 보기", sub, text: r.goal }, 10000);
      } else {
        const slot = Math.floor(t / 300);  // 5분마다 한 번
        if (slot >= 1 && slot !== ov.slot && t % 300 < 30) {
          ov.slot = slot;
          showOverlay({ title: `${slot * 5}분 · 목표 다시 보기`, sub, text: r.goal }, 7000);
        }
      }
      return;
    }
    if (ov.inGame) { ov.inGame = false; hideOverlay(); }
    if (r.phase === "ChampSelect") {
      if (!ov.champ) { ov.champ = true; showOverlay({ title: "이번 판 목표", sub, text: r.goal }, 0); }
    } else if (ov.champ) {
      ov.champ = false;
      hideOverlay();
    }
  }, 2000);
}

function createTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, "build", "icon.png")).resize({ width: 16, height: 16 });
  tray = new Tray(icon);
  tray.setToolTip(APP_NAME);
  tray.on("click", showWindow);
  refreshTray();
}

function refreshTray() {
  if (!tray) return;
  const items = [
    { label: `${APP_NAME} 열기`, click: showWindow },
    { type: "separator" },
    updateState.status === "ready"
      ? { label: `새 버전 ${updateState.version} 설치하고 다시 시작`, click: installUpdate }
      : { label: "업데이트 확인", click: () => checkUpdates(true) },
    { label: `버전 ${app.getVersion()}`, enabled: false },
    { type: "separator" },
    { label: "종료", click: () => quit() },
  ];
  tray.setContextMenu(Menu.buildFromTemplate(items));
}

// ---------- 자동 업데이트 (GitHub 릴리스) ----------
function sendUpdate(state) {
  updateState = state;
  refreshTray();
  if (win) win.webContents.send("update", state);
}

function setupUpdater() {
  if (!app.isPackaged) return;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true; // 종료할 때 조용히 설치
  autoUpdater.logger = { info: (m) => log("[update]", m), warn: (m) => log("[update]", m), error: (m) => log("[update]", m), debug: () => {} };
  autoUpdater.on("checking-for-update", () => sendUpdate({ status: "checking" }));
  autoUpdater.on("update-not-available", () => sendUpdate({ status: "none" }));
  autoUpdater.on("update-available", (i) => sendUpdate({ status: "available", version: i.version }));
  autoUpdater.on("download-progress", (p) => sendUpdate({ status: "downloading", version: updateState.version, percent: p.percent }));
  autoUpdater.on("error", (e) => { log("[update] error", e && e.message); sendUpdate({ status: "error" }); });
  autoUpdater.on("update-downloaded", (i) => {
    sendUpdate({ status: "ready", version: i.version });
    // 게임 녹화 중일 수 있으니 강제로 재시작하지 않는다. 알림만 띄우고, 다음 종료 때 설치된다
    if (Notification.isSupported()) {
      const n = new Notification({ title: "새 버전이 준비됐어요", body: `${i.version} — 눌러서 지금 다시 시작하거나, 다음에 앱을 끌 때 설치돼요.` });
      n.on("click", installUpdate);
      n.show();
    }
  });
  checkUpdates(false);
  setInterval(() => checkUpdates(false), 2 * 60 * 60 * 1000);
}

async function checkUpdates(manual) {
  if (!app.isPackaged) return { status: "dev" };
  try {
    const r = await autoUpdater.checkForUpdates();
    if (manual && r && !r.isUpdateAvailable) dialog.showMessageBox({ message: "최신 버전이에요", detail: `버전 ${app.getVersion()}` });
    return updateState;
  } catch (e) {
    log("[update] check failed", e.message);
    return { status: "error" };
  }
}

async function installUpdate() {
  quitting = true;
  await stopServer();
  autoUpdater.quitAndInstall(true, true); // 조용히 설치하고 다시 실행
}

async function quit() {
  quitting = true;
  await stopServer();
  app.quit();
}

// ---------- 렌더러 다리 (preload.js) ----------
ipcMain.handle("app:version", () => app.getVersion());
ipcMain.handle("update:check", () => checkUpdates(false));
ipcMain.handle("update:state", () => updateState);
ipcMain.on("update:install", () => installUpdate());
ipcMain.on("open-external", (_e, url) => { if (/^https?:\/\//.test(url)) shell.openExternal(url); });
ipcMain.handle("login-item:get", () => app.getLoginItemSettings().openAtLogin);
ipcMain.handle("login-item:set", (_e, on) => {
  app.setLoginItemSettings({ openAtLogin: !!on, args: ["--hidden"] });
  return app.getLoginItemSettings().openAtLogin;
});

// ---------- 시작 ----------
async function boot() {
  app.setAppUserModelId("io.github.hyunsu1768.junglebootcamp");
  createWindow();
  createTray();
  await win.loadFile(path.join(__dirname, "splash.html"));
  const status = (msg) => win && win.webContents.send("splash", msg);
  try {
    // 처음 설치하면 컴퓨터를 켤 때 자동 실행을 켠다 (설정에서 끌 수 있다)
    const flag = path.join(DATA, ".login-item-set");
    if (app.isPackaged && !fs.existsSync(flag)) {
      app.setLoginItemSettings({ openAtLogin: true, args: ["--hidden"] });
      fs.writeFileSync(flag, "1");
    }
    seedKb();
    const py = await ensurePython(status);
    status("서버를 켜고 있어요");
    await startServer(py);
    await win.loadURL(appUrl());
    setupUpdater();
    watchDebrief();
    watchOverlay();
    if (process.env.JUNGLE_DEV_SNAPSHOT) {
      // 개발 확인용: 화면을 파일로 저장하고 끝낸다
      setTimeout(async () => {
        fs.writeFileSync(process.env.JUNGLE_DEV_SNAPSHOT, (await win.webContents.capturePage()).toPNG());
        if (process.env.JUNGLE_DEV_OVERLAY) {  // 오버레이 모양 확인용
          await showOverlay(JSON.parse(process.env.JUNGLE_DEV_OVERLAY), 0);
          await new Promise((res) => setTimeout(res, 800));
          fs.writeFileSync(process.env.JUNGLE_DEV_SNAPSHOT.replace(/\.png$/, "-overlay.png"), (await overlay.webContents.capturePage()).toPNG());
        }
        quit();
      }, 4000);
    }
  } catch (e) {
    log("시작 실패", e.stack || e.message);
    status(`시작하지 못했어요: ${e.message}\n로그: ${LOG}`);
    showWindow();
  }
}

app.on("window-all-closed", (e) => e.preventDefault()); // 트레이에 남는다
app.on("before-quit", () => { quitting = true; });
app.on("will-quit", () => {
  // 업데이트 설치 등으로 바로 끝날 때도 서버 트리를 정리
  if (server && IS_WIN) execFile("taskkill", ["/T", "/F", "/PID", String(server.pid)], { windowsHide: true });
});
