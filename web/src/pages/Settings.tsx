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
          <div><b>내 정글 판 자동 분석</b><div className="small">판마다 Claude 사용량이 들어요(35분 판 기준 15~20분 분석).</div></div>
          <input type="checkbox" className="switch" checked={(p as { auto_analyze?: number }).auto_analyze !== 0}
            onChange={async (e) => { await api.saveMe({ auto_analyze: e.target.checked ? 1 : 0 } as never); me.reload(); }} />
        </label>
      </section>
      <section className="section">
        <h2 className="section-title">앱 정보</h2>
        <Updates version={app.data.version} />
        <p className="caption">데이터 폴더: {app.data.data_dir}</p>
      </section>
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
