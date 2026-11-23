import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type GrowthGame } from "../api";
import { ErrorView, Loading, PageHead, usePoll } from "../ui";
import { GoalStreak } from "./Mine";

const pct = (x: number | null | undefined) => (x == null ? "–" : `${Math.round(x * 100)}%`);

function Delta({ now, before, unit = "%p", invert = false, scale = 100 }: { now: number | null; before: number | null; unit?: string; invert?: boolean; scale?: number }) {
  if (now == null || before == null) return null;
  const d = scale === 100 ? Math.round((now - before) * 100) : Math.round((now - before) * scale * 10) / 10;
  if (d === 0) return <span className="delta">그대로</span>;
  const good = invert ? d < 0 : d > 0;
  return <span className={`delta ${good ? "up" : "down"}`}>{d > 0 ? "▲" : "▼"} {Math.abs(d)}{unit}</span>;
}

export default function GrowthPage() {
  const { data: g, error } = usePoll(api.growth, [], () => false);
  const { data: goals } = usePoll(api.goals, [], () => false);
  if (error) return <ErrorView message={error} />;
  if (!g) return <Loading />;
  const analyzed = g.games.filter((x) => x.accuracy != null);

  return (
    <div className="narrow-wrap growth">
      <PageHead title="성장" sub="내 게임의 판단이 실제로 좋아지고 있는지 봐요. 판이 끝날 때마다 쌓여요." />

      {analyzed.length === 0 ? (
        <div className="card card-tight"><p className="small" style={{ margin: 0 }}>분석한 내 게임이 아직 없어요. 한 판 하고 복기까지 끝내면 여기서부터 쌓여요.</p></div>
      ) : (
        <>
          <div className="stats growth-stats">
            <div className="stat">
              <div className="stat-num">{pct(g.accuracy.recent)}</div>
              <div className="stat-label">판단 정확도 (최근 {g.accuracy.recent_n}판)</div>
              <Delta now={g.accuracy.recent} before={g.accuracy.before} />
            </div>
            <div className="stat">
              <div className="stat-num">{pct(g.goal_rate)}</div>
              <div className="stat-label">{g.goal_n ? `목표 실천 (최근 ${g.goal_n}판)` : "목표 실천 (아직 판정 없음)"}</div>
            </div>
            <div className="stat">
              <div className="stat-num">{g.lessons.fixed.length}</div>
              <div className="stat-label">고친 실수 (2판 연속 나아짐)</div>
            </div>
            <div className="stat">
              <div className="stat-num">{g.metrics.deaths14.recent ?? "–"}</div>
              <div className="stat-label">14분 전 데스 (최근 5판 평균)</div>
              <Delta now={g.metrics.deaths14.recent} before={g.metrics.deaths14.before} unit="번" invert scale={1} />
            </div>
          </div>

          <section className="section">
            <h2 className="section-title">판마다 판단 정확도</h2>
            <p className="small" style={{ marginTop: -8 }}>분석이 고른 판단 포인트 중 좋은 선택의 비율이에요. 결과가 아니라 판단 기준이라, 져도 오를 수 있어요. 채운 점은 이긴 판이에요.</p>
            <AccuracyChart games={analyzed} />
          </section>
        </>
      )}

      {goals?.active && (
        <section className="section">
          <h2 className="section-title">지금 목표</h2>
          <div className="card card-blue">
            <div className="goal-text">{goals.active.text}</div>
            {goals.progress && goals.progress.games > 0 && <GoalStreak p={goals.progress} />}
          </div>
        </section>
      )}

      {g.categories.length > 0 && (
        <section className="section">
          <h2 className="section-title">유형별</h2>
          {g.weakest && (
            <div className="card card-tight video-fetch" style={{ marginBottom: 12 }}>
              <div><b>지금 가장 약한 유형: {g.weakest.category}</b>
                <div className="small">내 게임 {pct(g.weakest.game_rate)} · 훈련 {pct(g.weakest.train_rate)}. 이 유형 문제를 먼저 풀어요.</div></div>
              <Link className="btn btn-primary btn-sm" to={`/?start=10&category=${encodeURIComponent(g.weakest.category)}`}>훈련하기</Link>
            </div>
          )}
          <table className="cat-table">
            <thead><tr><th>유형</th><th>내 게임 판단</th><th>예측 훈련 (30일)</th></tr></thead>
            <tbody>
              {g.categories.map((c) => (
                <tr key={c.category}>
                  <td>{c.category}</td>
                  <td><Bar rate={c.game_rate} n={c.game_n} /></td>
                  <td><Bar rate={c.train_rate} n={c.train_n} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {(g.lessons.repeating.length > 0 || g.lessons.fixed.length > 0) && (
        <section className="section">
          <h2 className="section-title">복기 노트</h2>
          {g.lessons.repeating.length > 0 && (
            <div className="card card-tight" style={{ marginBottom: 12 }}>
              <div className="card-label">아직 반복하는 실수</div>
              <ul className="bullets" style={{ margin: 0 }}>{g.lessons.repeating.map((t) => <li key={t}>{t}</li>)}</ul>
            </div>
          )}
          {g.lessons.fixed.length > 0 && (
            <div className="card card-tight">
              <div className="card-label">고친 실수</div>
              <ul className="bullets" style={{ margin: 0 }}>{g.lessons.fixed.map((t) => <li key={t}>{t}</li>)}</ul>
            </div>
          )}
          <p className="small"><Link to="/mine">복기 노트 전체 보기 →</Link></p>
        </section>
      )}

      {g.train_weeks.length > 0 && (
        <section className="section">
          <h2 className="section-title">예측 훈련</h2>
          <div className="week-row">
            {g.train_weeks.map((w) => (
              <div key={w.week} className="week-cell" title={`${w.week} 주 · ${w.n}문제`}>
                <div className="week-bar"><span style={{ height: `${Math.round(w.rate * 100)}%` }} /></div>
                <div className="caption">{pct(w.rate)}</div>
                <div className="caption">{w.week.slice(5)}</div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Bar({ rate, n }: { rate: number | null; n: number }) {
  if (rate == null || n === 0) return <span className="caption">아직 없음</span>;
  return (
    <span className="mini-bar" title={`${n}개 중 ${Math.round(rate * n)}개`}>
      <span className="mini-track"><span className={rate < 0.5 ? "low" : ""} style={{ width: `${Math.round(rate * 100)}%` }} /></span>
      <span className="caption">{pct(rate)} · {n}</span>
    </span>
  );
}

/** 판마다 판단 정확도. 한 계열이라 범례 없이 제목이 이름이다. 점에 올리면 그 판 내용 */
function AccuracyChart({ games }: { games: GrowthGame[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const nav = useNavigate();
  const W = 640, H = 220, L = 36, R = 12, T = 12, B = 28;
  const n = games.length;
  const x = (i: number) => L + (n === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (n - 1));
  const y = (v: number) => T + (1 - v) * (H - T - B);
  const pts = games.map((g, i) => [x(i), y(g.accuracy ?? 0)] as const);
  const h = hover != null ? games[hover] : null;
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="판마다 판단 정확도" onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="grid" />
            <text x={L - 6} y={y(v) + 4} className="axis" textAnchor="end">{v * 100}%</text>
          </g>
        ))}
        {n > 1 && <polyline points={pts.map((p) => p.join(",")).join(" ")} className="line" />}
        {pts.map(([px, py], i) => (
          <g key={games[i].id} onMouseEnter={() => setHover(i)} onClick={() => nav(`/mine/${games[i].id}`)} style={{ cursor: "pointer" }}>
            <circle cx={px} cy={py} r={14} className="hit" />
            <circle cx={px} cy={py} r={hover === i ? 6 : 4.5} className={`dot ${games[i].result === "승" ? "win" : ""}`} />
          </g>
        ))}
        {[0, n - 1].filter((i, k, a) => a.indexOf(i) === k).map((i) => (
          <text key={i} x={x(i)} y={H - 8} className="axis" textAnchor={i === 0 && n > 1 ? "start" : "end"}>{games[i].played.slice(5)}</text>
        ))}
      </svg>
      {h && (
        <div className="chart-tip">
          <b>{h.played} · {h.champion} {h.result ?? ""}</b>
          <div>판단 {h.good + h.bad}개 중 좋은 선택 {h.good}개 ({pct(h.accuracy)})</div>
          {h.goal && <div>목표: {{ yes: "지킴", partial: "일부", no: "못 지킴", na: "상황 없음" }[h.goal] ?? h.goal}</div>}
          {(h.again > 0 || h.better > 0) && <div>반복한 실수 {h.again} · 나아진 실수 {h.better}</div>}
          <div className="caption">눌러서 이 판 보기</div>
        </div>
      )}
    </div>
  );
}
