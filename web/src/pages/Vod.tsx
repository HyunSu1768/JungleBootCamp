import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, thumbUrl, type GameEntry } from "../api";
import { Dots, ErrorView, JobSteps, Loading, PageHead, ResultBadge, isActive, useLightbox, usePoll, useToast } from "../ui";

export default function VodPage() {
  const { dir = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const lb = useLightbox();
  const [showSheets, setShowSheets] = useState(false);
  const { data: v, error, reload } = usePoll(
    () => api.vod(dir),
    [dir],
    (d) => !!d && (isActive(d.job) || d.game_list.some((g) => isActive(g.job))),
    3000,
  );

  if (error) return <ErrorView message={error} />;
  if (!v) return <Loading />;

  const analyze = async (g: GameEntry) => {
    try {
      await api.analyze(dir, g.n);
      toast.show(`${g.n}판 분석을 시작했어요`);
      reload();
    } catch (e) {
      toast.show((e as Error).message);
    }
  };
  const redetect = async () => {
    try {
      const j = await api.redetect(dir);
      nav(`/jobs/${j.id}`);
    } catch (e) {
      toast.show((e as Error).message);
    }
  };

  const scanning = isActive(v.job);
  const jungle = v.game_list.filter((g) => g.jungle);
  const others = v.game_list.filter((g) => !g.jungle);

  const row = (g: GameEntry) => {
    const running = isActive(g.job);
    const failed = g.job?.status === "error" && !g.analyzed;
    const desc = [g.mode, g.minutes ? `${g.minutes}분` : null, `VOD ${g.start}`, g.reviews?.length ? "리플레이 피드백 있음" : null].filter(Boolean).join(" · ");
    const inner = (
      <>
        <div className="thumb-wrap">
          <img className="thumb" src={thumbUrl(dir, g.n)} alt="" loading="lazy" onError={(e) => (e.currentTarget.style.visibility = "hidden")} />
        </div>
        <div className="list-body">
          <div className="list-title row" style={{ gap: 6 }}>
            {g.n}판{g.champion ? ` · ${g.champion}` : ""} <ResultBadge result={g.result} />
          </div>
          <div className="list-desc">{desc}</div>
          {running && g.job && (
            <div className="list-desc" style={{ color: "var(--blue-700)" }}>
              {g.job.status === "queued" ? "대기 중" : g.job.steps.find((s) => s.status === "running")?.name} <Dots />
            </div>
          )}
          {failed && <div className="list-desc" style={{ color: "var(--red)" }}>분석하다 멈췄어요</div>}
        </div>
      </>
    );
    if (g.analyzed && !running) {
      return (
        <Link key={g.n} to={`/vods/${encodeURIComponent(dir)}/${g.n}`} className="item-card">
          {inner}
          <div className="item-action"><span className="badge badge-green">분석 완료</span><span className="chev">›</span></div>
        </Link>
      );
    }
    return (
      <div key={g.n} className={`item-card ${g.jungle ? "" : "dim"}`}>
        {inner}
        <div className="item-action">
          {running && g.job ? (
            <Link to={`/jobs/${g.job.id}`} className="btn btn-ghost btn-sm">진행 보기</Link>
          ) : (
            <button className={`btn btn-sm ${g.jungle ? "btn-secondary" : "btn-ghost"}`} onClick={() => analyze(g)}>
              {failed ? "다시 분석" : "분석하기"}
            </button>
          )}
        </div>
      </div>
    );
  };

  const jobCard = v.job && (scanning || v.job.status === "error") ? <div className="card"><JobSteps job={v.job} /></div> : null;
  const tools = !scanning && v.scanned ? (
    <div className="row">
      <button className="btn btn-ghost btn-sm" onClick={() => setShowSheets((s) => !s)}>{showSheets ? "훑어본 화면 접기" : "훑어본 화면 보기"}</button>
      <button className="btn btn-ghost btn-sm" onClick={redetect}>판 다시 찾기</button>
    </div>
  ) : null;

  return (
    <>
      <PageHead eyebrow={<Link to="/vods">‹ 프로 영상</Link>} title={v.title} sub={v.uploader} />
      <div className="layout">
        <div>
          {jobCard && <div className="mobile-only" style={{ marginBottom: 32 }}>{jobCard}</div>}
          {v.game_list.length > 0 && (
            <>
              <section>
                <h2 className="section-title">정글 판 {jungle.length}개</h2>
                {jungle.length > 0 ? <div className="cards">{jungle.map(row)}</div> : <p className="small">정글로 한 판을 못 찾았어요.</p>}
              </section>
              {others.length > 0 && (
                <section className="section">
                  <h2 className="section-title">다른 판 {others.length}개</h2>
                  <p className="section-sub">정글이 아니거나 다른 모드예요</p>
                  <div className="cards">{others.map(row)}</div>
                </section>
              )}
            </>
          )}
          {tools && <section className="section mobile-only">{tools}</section>}
          {showSheets && (
            <section className="section stack">
              <p className="small">1분 간격 화면이에요. 판 구분이 틀렸으면 '판 다시 찾기'를 눌러 주세요.</p>
              {v.sheets.map((s, i) => (
                <figure key={s.file} style={{ margin: 0 }}>
                  <img
                    src={`/media/${encodeURIComponent(dir)}/scan/${s.file}`}
                    alt={`${s.from} ~ ${s.to}`}
                    style={{ borderRadius: 12, cursor: "zoom-in" }}
                    loading="lazy"
                    onClick={() => lb.open(v.sheets.map((x) => `${dir}/scan/${x.file}`), i)}
                  />
                  <figcaption className="caption" style={{ marginTop: 4 }}>{s.from} ~ {s.to}</figcaption>
                </figure>
              ))}
            </section>
          )}
        </div>

        <aside className="aside">
          {jobCard}
          <div className="card">
            <div className="stats" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
              <div><div className="stat-num">{v.games}</div><div className="stat-label">찾은 판</div></div>
              <div><div className="stat-num">{v.jungle_games}</div><div className="stat-label">정글 판</div></div>
              <div><div className="stat-num">{v.analyzed}</div><div className="stat-label">분석한 판</div></div>
            </div>
          </div>
          {tools && <div className="aside-block" style={{ marginTop: 16 }}>{tools}</div>}
          {v.url && (
            <div className="aside-block" style={{ marginTop: 12 }}>
              <a href={v.url} target="_blank" rel="noreferrer" className="small" style={{ color: "var(--blue-700)" }}>숲에서 다시보기 열기 ↗</a>
            </div>
          )}
        </aside>
      </div>
      {toast.node}
    </>
  );
}
