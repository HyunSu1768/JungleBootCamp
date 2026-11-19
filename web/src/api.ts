// 서버 API와 데이터 형식 (SCHEMA.md와 맞춘다)

export type Source = "quote" | "team" | "review" | "screen" | "guess";

export interface Step { name: string; status: "waiting" | "running" | "done" | "error" | "cancelled" }
export interface Job {
  id: string;
  kind: "scan" | "redetect" | "analyze";
  url: string;
  vod: string | null;
  game: number | null;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  steps: Step[];
  error: string | null;
  summary: string | null;
  created: number;
  finished: number | null;
  log_tail?: string[];
  log?: string[];
}

export interface VodSummary {
  dir: string | null;
  title: string;
  uploader: string;
  url: string | null;
  scanned: boolean;
  games: number;
  jungle_games: number;
  analyzed: number;
  job: Job | null;
  updated: number;
}

export interface GameEntry {
  n: number;
  draft_start: string | null;
  start: string;
  end: string;
  jungle: boolean;
  mode?: string;
  champion: string | null;
  result: string | null;
  note?: string;
  reviews?: { from: string; to: string; note?: string }[];
  analyzed: boolean;
  extracted: boolean;
  minutes: number | null;
  job: Job | null;
}

export interface VodDetail extends VodSummary {
  game_list: GameEntry[];
  sheets: { file: string; from: string; to: string }[];
}

export interface FightDetail { before: string; start: string; flow: string; decisive: string; uncertain: string[] }
export interface Fight {
  id: string;
  ingame: string;
  vod: string;
  title: string;
  situation: string;
  choice: string;
  reason: string;
  source: Source;
  quote: string | null;
  fight: FightDetail | null;
  concepts: string[];
  rule: string;
  background?: string[];
  frames: string[];
}
export interface Pick { order: number; champion: string; role: string }
export interface Draft {
  available: boolean;
  side?: string;
  bans?: { ally: string[]; enemy: string[] };
  picks?: { ally: Pick[]; enemy: Pick[] };
  my_pick?: { champion: string; order: number; reason: string; source: Source; quote: string | null };
  frames?: string[];
}
export interface Lane {
  lane: string;
  ally: string;
  enemy: string;
  priority: "ally" | "enemy" | "even";
  spikes: string;
  gank_setup: string;
  dive: string;
  verdict: "gank" | "protect" | "ignore";
  reason: string;
  source: Source;
  actual: string;
  background?: string[];
}
export interface JunglerInfo { champion: string; early: string; first_path: string; source: Source }
export interface Plan {
  draft: Draft | null;
  lanes: Lane[];
  junglers: { ally: JunglerInfo; enemy: JunglerInfo } | null;
  win_conditions: { ally: string; enemy: string } | null;
  jungle_plan: string;
  plan_source: Source;
  plan_quote: string | null;
  loading_frame: string | null;
}
export type ActionKind = "파밍" | "갱킹" | "카정" | "교전" | "오브젝트" | "시야" | "라인" | "이동" | "귀환" | "사망";
export interface Action { t: string; kind: ActionKind; label: string; where?: string; result?: string; why?: string }
export interface Decision {
  t: string;
  question: string;
  situation: string;
  options: { label: string; chosen: boolean; why: string }[];
  why: string;
  source?: Source;
  quote?: string | null;
  result: string;
  background?: string[];
  frames?: string[];
}
export interface Turn {
  id: string;
  from: string;
  to: string;
  vod_from: string;
  end: string;
  start_state: { level?: number; gold?: number; cs?: number; lanes?: string; next_objective?: string; enemy_jungler?: string };
  actions: Action[];
  decisions?: Decision[];
  intent: string;
  source: Source;
  quote: string | null;
  followed_plan: "yes" | "partial" | "no";
  deviation: string | null;
  gained: string[];
  lost: string[];
  exchange: string;
  verdict: "이득" | "교환" | "손해";
  frames: string[];
}
export interface EnemyTurn { id: string; from: string; to: string; actions: Action[]; confidence: "seen" | "inferred" | "unknown"; note?: string }
export interface ObjectiveCycle {
  objective: string;
  spawn: string;
  prep_from: string;
  prep: string;
  decision: "싸움" | "교환" | "포기" | "무혈";
  trade: string | null;
  result: string;
  taken_by: "ally" | "enemy" | "none";
  source: Source;
  frames: string[];
}
export interface TurningPoint { ingame: string; vod: string; title: string; what: string; why_decisive: string; better: string | null; frames: string[] }
export interface Operations {
  objective_cycles: ObjectiveCycle[];
  phases: { phase: string; range: string; summary: string; points: string[] }[];
  turning_points: TurningPoint[];
  plan_vs_result: string;
}
export type ReviewKind = "실수" | "잘한 점" | "대안" | "설명";
export interface ReviewComment {
  id: string;
  ingame: string | null;
  vod: string;
  kind: ReviewKind;
  said: string;
  point: string;
  refs: string[];
  frames: string[];
}
export interface Review {
  available: boolean;
  segments?: { from: string; to: string }[];
  summary?: string;
  comments?: ReviewComment[];
}

export interface Analysis {
  version: number;
  streamer: string;
  champion: string;
  enemy_jungler: string;
  result: string;
  length: string;
  context?: string;
  summary: string[];
  takeaways: string[];
  plan: Plan;
  turns: { ally: Turn[]; enemy: EnemyTurn[]; pattern: string };
  operations: Operations;
  fights: Fight[];
  review?: Review;
  own?: boolean;
  goal_check?: GoalCheck;
  next_goal?: { when: string; then: string; why?: string; rule_id?: string | null };
  new_concepts?: string[];
  new_rules?: string[];
  new_quizzes?: string[];
}
export interface GoalCheck {
  goal: string;
  followed: "yes" | "partial" | "no" | "na";
  evidence?: string;
  moments?: { t: string; followed: boolean; note?: string }[];
}
export interface GameDetail {
  vod: { dir: string; title: string; uploader: string; url: string | null; mine?: boolean };
  game: GameEntry;
  meta: Record<string, unknown>;
  analysis: Analysis;
}

export interface Concept {
  id: string;
  name: string;
  category: string;
  summary: string;
  definition: string;
  criteria: string[];
  exceptions: string[];
  examples: { game_ref: string; ref?: string; scene?: string; context?: string; note: string }[];
}
export interface Rule {
  id: string;
  category: string;
  when: string;
  then: string;
  concepts: string[];
  evidence: { game_ref: string; ref?: string; scene?: string; context?: string }[];
  exceptions: string[];
}
export interface Quiz {
  id: string;
  type?: "plan" | "next_turn" | "objective" | "fight";
  game_ref: string;
  ref?: string;
  scene?: string;
  category: string;
  image: string;
  ingame: string;
  situation: string;
  question: string;
  answer: string;
  explanation: string;
  concepts: string[];
}
export type QuizLog = Record<string, { date: string; result: "O" | "△" | "X"; answer: string }[]>;
export interface KB {
  concepts: Concept[];
  rules: Rule[];
  quizzes: Quiz[];
  quiz_log: QuizLog;
  games: Record<string, { streamer: string; champion: string; result: string; path: string }>;
}

export const CATEGORIES = ["밴픽", "라인 상성", "초반 동선", "턴 운영", "갱킹", "카정·맞갱", "오브젝트", "교전", "중후반 운영", "시야"];
export const QUIZ_TYPES: Record<string, string> = { plan: "플랜", next_turn: "다음 턴", objective: "오브젝트 준비", fight: "교전 판단" };

/** 인게임 "M:SS" → 초 */
export const secs = (t: string) => t.split(":").reduce((a, x) => a * 60 + Number(x), 0);

/** 사용자 구분. 지금은 기기 하나 = 사용자 하나. 실서비스에선 로그인 토큰으로 바꾼다 */
export function userId(): string | null {
  try { return window.localStorage.getItem("jungle-user"); } catch { return null; }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  if (init?.body && typeof init.body === "string") headers["Content-Type"] = "application/json";
  const uid = userId();
  if (uid) headers["X-User-Id"] = uid;
  const r = await fetch(path, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) } });
  if (!r.ok) {
    let msg = `요청에 실패했어요 (${r.status})`;
    try {
      const d = await r.json();
      if (typeof d.detail === "string") msg = d.detail;
    } catch { /* 본문 없음 */ }
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  vods: () => req<VodSummary[]>("/api/vods"),
  addVod: (url: string) => req<Job>("/api/vods", { method: "POST", body: JSON.stringify({ url }) }),
  vod: (dir: string) => req<VodDetail>(`/api/vods/${encodeURIComponent(dir)}`),
  redetect: (dir: string) => req<Job>(`/api/vods/${encodeURIComponent(dir)}/redetect`, { method: "POST" }),
  analyze: (dir: string, n: number) =>
    req<Job>(`/api/vods/${encodeURIComponent(dir)}/games/${n}/analyze`, { method: "POST" }),
  game: (dir: string, n: number) => req<GameDetail>(`/api/vods/${encodeURIComponent(dir)}/games/${n}`),
  job: (id: string) => req<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) => req<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  kb: () => req<KB>("/api/kb"),
  quizResult: (id: string, result: string, answer: string) =>
    req(`/api/quiz/${id}/result`, { method: "POST", body: JSON.stringify({ result, answer }) }),
  quizFeedback: (id: string, answer: string) =>
    req<{ feedback: string }>(`/api/quiz/${id}/feedback`, { method: "POST", body: JSON.stringify({ answer }) }),
  me: () => req<Profile>("/api/me"),
  saveMe: (p: Partial<Profile>) => req<Profile>("/api/me", { method: "PUT", body: JSON.stringify(p) }),
  trainOverview: () => req<TrainOverview>("/api/train/overview"),
  trainSession: (n: number, category?: string | null, source = "all") =>
    req<{ items: TrainItem[] }>(`/api/train/session?n=${n}&source=${source}${category ? `&category=${encodeURIComponent(category)}` : ""}`),
  agent: () => req<AgentInfo>("/api/agent"),
  agentToken: () => req<{ token: string }>("/api/agent/token", { method: "POST", body: "{}" }),
  revokeAgent: () => req("/api/agent/tokens", { method: "DELETE" }),
  myGames: () => req<MyGame[]>("/api/mine"),
  myGame: (id: string) => req<MyGameDetail>(`/api/mine/${id}`),
  analyzeMine: (id: string) => req<Job>(`/api/mine/${id}/analyze`, { method: "POST" }),
  deleteMine: (id: string) => req(`/api/mine/${id}`, { method: "DELETE" }),
  myStats: () => req<MyStats>("/api/mine-stats"),
  goals: () => req<Goals>("/api/goals"),
  setGoal: (text: string, rule_id?: string | null) => req<Goal>("/api/goals", { method: "POST", body: JSON.stringify({ text, rule_id }) }),
  clearGoal: () => req("/api/goals/active", { method: "DELETE" }),
  checkGoal: (id: number, followed: string, note?: string) => req(`/api/goals/${id}`, { method: "PUT", body: JSON.stringify({ followed, note }) }),
  appInfo: () => req<AppInfo>("/api/app"),
  saveSettings: (p: Partial<DeviceSettings>) => req<DeviceSettings>("/api/settings", { method: "PUT", body: JSON.stringify(p) }),
  claude: (fresh = false) => req<ClaudeStatus>(`/api/claude${fresh ? "?fresh=true" : ""}`),
  claudeInstall: () => req("/api/claude/install", { method: "POST" }),
  claudeLogin: () => req("/api/claude/login", { method: "POST" }),
  claudeLoginCode: (code: string) => req("/api/claude/login/code", { method: "POST", body: JSON.stringify({ code }) }),
  claudeLoginWindow: () => req("/api/claude/login/window", { method: "POST" }),
  trainAnswer: (item_id: string, choice: number | null, confidence: number, ms: number) =>
    req<TrainReveal>("/api/train/answer", { method: "POST", body: JSON.stringify({ item_id, choice, confidence, ms }) }),
};

/* ---------- 사용자, 훈련 ---------- */
export const TIERS = ["아이언", "브론즈", "실버", "골드", "플래티넘", "에메랄드", "다이아몬드", "마스터", "그랜드마스터", "챌린저"];
export interface Profile {
  id: string;
  name: string | null;
  tier: string | null;
  division: string | null;
  role: string | null;
  weekly_games: number | null;
  goal_tier: string | null;
}
export interface TrainItem {
  id: string;
  game_ref: string;
  turn: string;
  own: boolean;
  category: string;
  streamer: string | null;
  champion: string | null;
  enemy_jungler: string | null;
  context: string | null;
  ingame: string;
  question: string;
  situation: string;
  options: { key: number; label: string }[];
  video: string | null;
  base: number | null;
  at: number | null;
  ingame_offset: number | null;
  image: string | null;
  lead: number;
}
export interface TrainReveal {
  correct: boolean;
  best: number;
  verdict: string | null;
  why: string | null;
  source: Source | null;
  quote: string | null;
  result: string | null;
  background: string[];
  options: { key: number; label: string; why: string; chosen: boolean }[];
  after: number;
  next: { due: string; interval_days: number };
}
export interface CatStat { n: number; ok: number; sure_wrong: number; rate: number }
export interface TrainOverview {
  total: number;
  due: number;
  new: number;
  own_total: number;
  streak: number;
  today: { n: number; ok: number };
  categories: Record<string, { total: number; due: number; new: number }>;
  stats: Record<string, CatStat>;
}

export const media = (p: string) => `/media/${p.split("/").map(encodeURIComponent).join("/")}`;
export const thumbUrl = (dir: string, n: number) => `/api/vods/${encodeURIComponent(dir)}/games/${n}/thumb`;

/** game_ref("<vod>/game2") + 판 안의 위치(t2, f1, o1, p1, lane-탑) → 분석 화면 경로 */
export const gamePath = (gameRef: string, ref?: string) => {
  if (gameRef.startsWith("mine/")) return `/mine/${gameRef.split("/")[2]}${ref ? `#${encodeURIComponent(ref)}` : ""}`;
  const [vod, g] = gameRef.split("/");
  return `/vods/${encodeURIComponent(vod)}/${g.replace("game", "")}${ref ? `#${encodeURIComponent(ref)}` : ""}`;
};

/* ---------- 내 게임 ---------- */
export interface AgentStatus { state: "waiting" | "recording" | "off"; version: string; platform: string; game_time: number | null; champion: string | null; elapsed: number | null; pending: number }
export interface AgentInfo {
  online: boolean;
  status: AgentStatus | null;
  tokens: { label: string; created: string; last_seen: string | null }[];
  server: string;
  local_server: string;
}
export interface Goal { id: number; text: string; rule_id: string | null; game_id: string | null; followed: string | null; note: string | null; created: string; game_title?: string; played?: string }
export interface Goals {
  active: Goal | null;
  history: Goal[];
  suggestions: { rule_id: string; category: string; when: string; then: string; why: string | null }[];
}
export interface GameMetrics {
  result: string | null;
  champion: string | null;
  role: string | null;
  minutes: number | null;
  kda: [number, number, number] | null;
  cs10: number | null;
  cs14: number | null;
  deaths_before_14: number;
  early_takedowns: number;
  kp: number | null;
  vision: number | null;
  objectives: Record<string, { ally: number; enemy: number }>;
  late_start?: boolean;
}
export interface MyGame {
  id: string;
  title: string;
  champion: string | null;
  result: string | null;
  played: string;
  role: string | null;
  created: string;
  metrics: GameMetrics;
  analyzed: boolean;
  job: Job | null;
  goal: Goal | null;
}
export interface MyGameDetail extends MyGame, Omit<GameDetail, "analysis"> { analysis: Analysis | null }
export interface MyStats {
  weeks: { week: string; games: number; win_rate: number; cs10: number | null; deaths_before_14: number | null; early_takedowns: number | null; objective_share: number | null }[];
  goals: Record<string, number>;
}

/* ---------- 앱, Claude 연결 ---------- */
export interface DeviceSettings { recording: boolean; screen: string; audio: string | null; onboarded: boolean; analysis?: "fast" | "deep" }
export interface AppInfo {
  version: string;
  desktop: boolean;
  platform: "windows" | "mac" | "linux";
  data_dir: string;
  settings: DeviceSettings;
  recorder: { managed: boolean; running: boolean; fails: number };
}
export interface TaskView { running: boolean; error: string | null; url: string | null; log: string[] }
export interface ClaudeStatus {
  installed: boolean;
  path: string | null;
  version: string | null;
  logged_in: boolean;
  auth_method: string | null;
  email: string | null;
  git_bash: string | null;
  platform: string;
  install: TaskView;
  login: TaskView;
}

/** 데스크톱 앱(Electron preload)이 넣어 주는 다리. 웹 브라우저에서는 없다 */
export interface DesktopBridge {
  version: string;
  checkForUpdates: () => Promise<{ status: string; version?: string }>;
  installUpdate: () => void;
  onUpdate: (cb: (u: { status: string; version?: string; percent?: number }) => void) => () => void;
  openExternal: (url: string) => void;
  setOpenAtLogin: (on: boolean) => Promise<boolean>;
  getOpenAtLogin: () => Promise<boolean>;
}
export const desktop = (window as unknown as { desktop?: DesktopBridge }).desktop;
export const openUrl = (url: string) => (desktop ? desktop.openExternal(url) : window.open(url, "_blank", "noopener"));
