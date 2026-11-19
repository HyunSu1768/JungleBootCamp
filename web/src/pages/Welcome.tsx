import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, desktop, openUrl, TIERS, type AppInfo, type ClaudeStatus, type Profile } from "../api";
import { BottomCTA, Dots, Loading, usePoll } from "../ui";

/* ================= 온보딩: Claude 연결 → 티어 → 자동 녹화 ================= */
export default function Welcome() {
  const nav = useNavigate();
  const app = usePoll(api.appInfo, [], () => false);
  const me = usePoll(api.me, [], () => false);
  const [step, setStep] = useState(0);
  if (!app.data || !me.data) return <Loading />;

  const finish = async () => {
    await api.saveSettings({ onboarded: true });
    nav("/", { replace: true });
  };
  const steps = ["Claude 연결", "내 티어", "자동 녹화"];
  return (
    <div className="narrow-wrap welcome">
      <div className="welcome-steps">
        {steps.map((s, i) => <span key={s} className={i === step ? "on" : i < step ? "done" : ""}>{i < step ? "✓ " : `${i + 1}. `}{s}</span>)}
      </div>
      {step === 0 && <ClaudeStep onNext={() => setStep(1)} />}
      {step === 1 && <ProfileStep me={me.data} onNext={async (p) => { await api.saveMe(p); setStep(2); }} />}
      {step === 2 && <RecordStep app={app.data} onNext={finish} />}
    </div>
  );
}

/* ---------------- 1. Claude ---------------- */
export function ClaudePanel({ compact = false }: { compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const { data: st, reload } = usePoll<ClaudeStatus>(() => api.claude(), [], (d) => !d?.logged_in || !!d?.install.running || !!d?.login.running, 2000);
  if (!st) return <Loading />;

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    try { await fn(); await reload(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const waitingLogin = st.login.running && !st.logged_in;

  return (
    <div className="card claude-card">
      <div className="claude-head">
        <span className={`agent-dot ${st.logged_in ? "waiting" : "off"}`} />
        <div style={{ flex: 1 }}>
          <div className="agent-title">
            {st.logged_in ? "Claude에 연결됐어요" : !st.installed ? "Claude Code가 필요해요" : waitingLogin ? "브라우저에서 로그인해 주세요" : "Claude 계정으로 로그인해 주세요"}
          </div>
          <div className="small">
            {st.logged_in ? `${st.email ?? st.auth_method ?? ""} · ${st.version ?? ""}` :
              !st.installed ? "영상 분석은 이 PC의 Claude Code가 해요. 무료로 설치되고 1~3분 걸려요." :
              "Claude Pro 또는 Max 구독 계정으로 로그인하면, 분석이 구독 사용량 안에서 돌아가요."}
          </div>
        </div>
        {!st.installed && (
          <button className="btn btn-primary" disabled={busy || st.install.running} onClick={() => act(api.claudeInstall)}>
            {st.install.running ? <>설치 중 <Dots /></> : "설치하기"}
          </button>
        )}
        {st.installed && !st.logged_in && !waitingLogin && (
          <button className="btn btn-primary" disabled={busy} onClick={() => act(api.claudeLogin)}>Claude 로그인</button>
        )}
      </div>

      {st.install.running && <pre className="task-log">{st.install.log.join("\n")}</pre>}
      {st.install.error && !st.installed && (
        <p className="field-error">설치가 끝나지 않았어요 ({st.install.error}). 인터넷 연결을 확인하고 다시 눌러 주세요.</p>
      )}

      {waitingLogin && (
        <div className="login-help">
          <p className="small">브라우저에 Claude 로그인 화면이 열렸어요. 로그인하고 '승인'을 누르면 여기로 돌아와요 <Dots /></p>
          {st.login.url && <button className="btn btn-ghost btn-sm" onClick={() => openUrl(st.login.url!)}>로그인 화면 다시 열기</button>}
          <div className="code-row">
            <input className="input" placeholder="브라우저에 코드가 나오면 여기에 붙여 넣기" value={code} onChange={(e) => setCode(e.target.value)} />
            <button className="btn btn-secondary" disabled={!code.trim() || busy} onClick={() => act(async () => { await api.claudeLoginCode(code); setCode(""); })}>확인</button>
          </div>
          <button className="link-btn small" onClick={() => act(api.claudeLoginWindow)}>로그인이 안 되면: 로그인 창 직접 열기</button>
        </div>
      )}
      {!compact && st.installed && !st.logged_in && st.login.log.length > 0 && !waitingLogin && (
        <pre className="task-log">{st.login.log.slice(-4).join("\n")}</pre>
      )}
      {err && <p className="field-error">{err}</p>}
    </div>
  );
}

function ClaudeStep({ onNext }: { onNext: () => void }) {
  const { data: st } = usePoll(() => api.claude(), [], (d) => !d?.logged_in, 2000);
  return (
    <>
      <h1 className="t1">{"정글러훈련소에\n오신 걸 환영해요"}</h1>
      <p className="sub">프로 영상과 내 게임을 Claude가 분석해서, 판단 훈련 문제로 만들어 드려요. 먼저 이 PC의 Claude를 연결할게요.</p>
      <div style={{ marginTop: 24 }}><ClaudePanel /></div>
      <BottomCTA>
        <button className="btn btn-primary btn-lg" disabled={!st?.logged_in} onClick={onNext}>다음</button>
      </BottomCTA>
      {!st?.logged_in && <button className="link-btn small" style={{ marginTop: 16 }} onClick={onNext}>나중에 연결할게요</button>}
    </>
  );
}

/* ---------------- 2. 티어 ---------------- */
function ProfileStep({ me, onNext }: { me: Profile; onNext: (p: Partial<Profile>) => void }) {
  const [tier, setTier] = useState(me.tier ?? "");
  const [goal, setGoal] = useState(me.goal_tier ?? "");
  const [weekly, setWeekly] = useState(me.weekly_games ?? 5);
  return (
    <>
      <h1 className="t1">지금 티어를 알려 주세요</h1>
      <p className="sub">티어에 맞는 장면부터 훈련 문제로 내 드려요.</p>
      <label className="field-label" style={{ marginTop: 24 }}>지금 티어</label>
      <div className="row">{TIERS.map((t) => <button key={t} className={`chip ${tier === t ? "on" : ""}`} onClick={() => setTier(t)}>{t}</button>)}</div>
      <label className="field-label" style={{ marginTop: 20 }}>목표 티어</label>
      <div className="row">
        {TIERS.slice(Math.max(0, TIERS.indexOf(tier))).map((t) => <button key={t} className={`chip ${goal === t ? "on" : ""}`} onClick={() => setGoal(t)}>{t}</button>)}
      </div>
      <label className="field-label" style={{ marginTop: 20 }}>일주일에 몇 판 하세요?</label>
      <div className="row">
        {[3, 5, 10, 20].map((n) => <button key={n} className={`chip ${weekly === n ? "on" : ""}`} onClick={() => setWeekly(n)}>{n}판{n === 20 ? " 이상" : ""}</button>)}
      </div>
      <BottomCTA>
        <button className="btn btn-primary btn-lg" disabled={!tier} onClick={() => onNext({ tier, goal_tier: goal || null, weekly_games: weekly, role: "정글" })}>다음</button>
      </BottomCTA>
    </>
  );
}

/* ---------------- 3. 녹화 ---------------- */
export function RecordSettings({ app, onSaved }: { app: AppInfo; onSaved?: () => void }) {
  const [s, setS] = useState(app.settings);
  const [login, setLogin] = useState<boolean | null>(null);
  useEffect(() => { void desktop?.getOpenAtLogin().then(setLogin); }, []);
  const save = async (p: Partial<typeof s>) => { setS(await api.saveSettings(p)); onSaved?.(); };
  if (!app.desktop) {
    return <p className="small">브라우저로 보고 있어요. 게임하는 PC에 정글러훈련소 앱을 설치하면 자동으로 녹화돼요. (내 게임 → 녹화 에이전트 연결로 다른 PC를 연결할 수도 있어요)</p>;
  }
  return (
    <div className="settings-list">
      <label className="setting">
        <div><b>게임 자동 녹화</b><div className="small">롤 게임(소환사의 협곡)이 시작되면 녹화하고, 끝나면 정글 판을 분석해요.</div></div>
        <input type="checkbox" className="switch" checked={s.recording} onChange={(e) => save({ recording: e.target.checked })} />
      </label>
      {s.recording && (
        <div className="setting">
          <div><b>녹화할 모니터</b><div className="small">롤이 뜨는 모니터를 골라 주세요. 롤은 '테두리 없음' 창 모드를 권장해요.</div></div>
          <div className="row">{["0", "1", "2"].map((n) => <button key={n} className={`chip ${s.screen === n ? "on" : ""}`} onClick={() => save({ screen: n })}>{n === "0" ? "주 모니터" : `${Number(n) + 1}번째`}</button>)}</div>
        </div>
      )}
      {login !== null && (
        <label className="setting">
          <div><b>컴퓨터를 켜면 자동 실행</b><div className="small">트레이에 조용히 떠 있다가 게임을 녹화해요. 끄면 앱을 켠 동안에만 녹화해요.</div></div>
          <input type="checkbox" className="switch" checked={login} onChange={async (e) => setLogin(await desktop!.setOpenAtLogin(e.target.checked))} />
        </label>
      )}
    </div>
  );
}

function RecordStep({ app, onNext }: { app: AppInfo; onNext: () => void }) {
  return (
    <>
      <h1 className="t1">{"게임은 알아서\n녹화할게요"}</h1>
      <p className="sub">앱을 켜 두고 롤을 하면, 게임이 시작될 때 녹화를 시작하고 끝나면 분석해요. 녹화 중에도 게임 성능에 거의 영향을 주지 않게 그래픽카드로 녹화해요.</p>
      <div className="card" style={{ marginTop: 24 }}><RecordSettings app={app} /></div>
      <p className="caption" style={{ marginTop: 12 }}>녹화와 게임 기록은 이 PC에만 저장돼요. 롤 클라이언트가 공식으로 여는 게임 정보만 읽고, 게임 파일이나 메모리는 건드리지 않아요.</p>
      <BottomCTA><button className="btn btn-primary btn-lg" onClick={onNext}>시작하기</button></BottomCTA>
    </>
  );
}
