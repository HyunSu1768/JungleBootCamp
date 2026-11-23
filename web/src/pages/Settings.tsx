import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, desktop, TIERS } from "../api";
import { Dots, Loading, PageHead, usePoll } from "../ui";
import { ClaudePanel, RecordSettings } from "./Welcome";

export default function Settings() {
  const app = usePoll(api.appInfo, [], () => false);
  const me = usePoll(api.me, [], () => false);
  if (!app.data || !me.data) return <Loading />;
  const p = me.data;
  return (
    <div className="narrow-wrap">
      <PageHead title="설정" />
      <section className="section">
        <h2 className="section-title">Claude</h2>
        <ClaudePanel compact />
      </section>
      <section className="section">
        <h2 className="section-title">녹화</h2>
        <div className="card"><RecordSettings app={app.data} onSaved={app.reload} /></div>
        {!app.data.desktop && <p className="small"><Link to="/mine">녹화 에이전트 연결 →</Link></p>}
      </section>
      <section className="section">
        <h2 className="section-title">내 티어</h2>
        <div className="row">
          {TIERS.map((t) => <button key={t} className={`chip ${p.tier === t ? "on" : ""}`} onClick={async () => { await api.saveMe({ tier: t }); me.reload(); }}>{t}</button>)}
        </div>
        <label className="setting" style={{ marginTop: 16 }}>
          <div><b>내 정글 판 자동 분석</b><div className="small">판이 끝나면 바로 분석해요. 판마다 Claude 사용량이 들어요.</div></div>
          <input type="checkbox" className="switch" checked={p.auto_analyze !== 0}
            onChange={async (e) => { await api.saveMe({ auto_analyze: e.target.checked ? 1 : 0 }); me.reload(); }} />
        </label>
      </section>
      <section className="section">
        <h2 className="section-title">목표와 복기</h2>
        {app.data.desktop && (
          <label className="setting" style={{ marginBottom: 16 }}>
            <div><b>판 중에 목표 띄우기</b><div className="small">챔피언 선택, 게임 시작, 5분마다, 죽었을 때 화면 위쪽에 지금 목표를 잠깐 띄워요. 클릭은 게임으로 그대로 가요. 롤을 '테두리 없음' 창 모드로 해야 보여요.</div></div>
            <input type="checkbox" className="switch" checked={app.data.settings.overlay !== false}
              onChange={async (e) => { await api.saveSettings({ overlay: e.target.checked }); app.reload(); }} />
          </label>
        )}
        <label className="setting">
          <div><b>복기 시간 동안 큐 막기</b><div className="small">판이 끝나면 복기 화면을 띄우고, 정한 시간 동안 롤 클라이언트에서 큐를 돌리면 취소해요. 바꾸면 다음 판부터 적용돼요.</div></div>
          <input type="checkbox" className="switch" checked={p.review_lock !== 0}
            onChange={async (e) => { await api.saveMe({ review_lock: e.target.checked ? 1 : 0 }); me.reload(); }} />
        </label>
        {p.review_lock !== 0 && (
          <div className="row" style={{ marginTop: 12 }}>
            {[5, 10, 15, 20].map((n) => (
              <button key={n} className={`chip ${(p.review_minutes ?? 10) === n ? "on" : ""}`}
                onClick={async () => { await api.saveMe({ review_minutes: n }); me.reload(); }}>{n}분</button>
            ))}
          </div>
        )}
      </section>
      <section className="section">
        <h2 className="section-title">분석 방식</h2>
        <AnalysisMode value={app.data.settings.analysis ?? "fast"} onSaved={app.reload} />
      </section>
      <section className="section">
        <h2 className="section-title">앱 정보</h2>
        <Updates version={app.data.version} />
        <p className="caption">데이터 폴더: {app.data.data_dir}</p>
      </section>
    </div>
  );
}

const MODES = [
  { id: "fast", title: "빠르게", desc: "35분 판 기준 Claude 분석 4분 안팎. 판단 포인트는 턴마다 2개쯤이에요." },
  { id: "deep", title: "꼼꼼하게", desc: "8분 안팎. 판단 포인트가 더 많고 상황 설명이 더 자세해요. 사용량도 2배쯤 들어요." },
] as const;

function AnalysisMode({ value, onSaved }: { value: string; onSaved: () => void }) {
  return (
    <div className="option-list">
      {MODES.map((m) => (
        <button key={m.id} className={`option-card ${value === m.id ? "on" : ""}`}
          onClick={async () => { await api.saveSettings({ analysis: m.id }); onSaved(); }}>
          <b>{m.title}</b>
          <span className="small">{m.desc}</span>
        </button>
      ))}
    </div>
  );
}

function Updates({ version }: { version: string }) {
  const [u, setU] = useState<{ status: string; version?: string; percent?: number } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => desktop?.onUpdate(setU), []);
  if (!desktop) return <p className="small">버전 {version}</p>;
  const label: Record<string, string> = {
    checking: "새 버전을 확인하고 있어요",
    none: "최신 버전이에요",
    available: `새 버전 ${u?.version ?? ""}을 받고 있어요`,
    downloading: `새 버전 받는 중 ${Math.round(u?.percent ?? 0)}%`,
    ready: `새 버전 ${u?.version ?? ""}이 준비됐어요`,
    error: "업데이트 확인에 실패했어요",
  };
  return (
    <div className="card card-tight">
      <div className="setting" style={{ padding: 0 }}>
        <div><b>버전 {desktop.version}</b><div className="small">{u ? label[u.status] ?? u.status : "새 버전이 나오면 자동으로 받아서, 앱을 다시 켤 때 설치해요."}</div></div>
        {u?.status === "ready" ? (
          <button className="btn btn-primary btn-sm" onClick={() => desktop!.installUpdate()}>지금 다시 시작</button>
        ) : (
          <button className="btn btn-secondary btn-sm" disabled={busy} onClick={async () => { setBusy(true); try { setU(await desktop!.checkForUpdates()); } finally { setBusy(false); } }}>
            {busy ? <Dots /> : "업데이트 확인"}
          </button>
        )}
      </div>
    </div>
  );
}
