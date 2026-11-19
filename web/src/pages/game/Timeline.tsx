import { createPortal } from "react-dom";
import { useRef, useState, useEffect } from "react";
import { secs, type Action, type ActionKind, type EnemyTurn, type Turn } from "../../api";

/** 행동 종류 → 색 그룹. 3색만 쓴다(색각 검사 통과), 세부 종류는 라벨과 툴팁으로 구분 */
export type Group = "grow" | "act" | "obj" | "etc" | "dead";
export const groupOf = (k: ActionKind): Group =>
  k === "파밍" ? "grow" : k === "갱킹" || k === "카정" || k === "교전" ? "act" : k === "오브젝트" ? "obj" : k === "사망" ? "dead" : "etc";
export const GROUP_LABEL: Record<Group, string> = { grow: "성장", act: "개입", obj: "오브젝트", etc: "이동·귀환·기타", dead: "사망" };

interface Seg { turnId: string; a: Action; from: number; to: number; faint?: boolean }

function segments(turns: { id: string; to: string; actions: Action[] }[], faint?: (id: string) => boolean): Seg[] {
  const out: Seg[] = [];
  for (const t of turns) {
    const acts = [...t.actions].sort((x, y) => secs(x.t) - secs(y.t));
    acts.forEach((a, i) => {
      const from = secs(a.t);
      const to = i + 1 < acts.length ? secs(acts[i + 1].t) : Math.max(from + 5, secs(t.to));
      if (to > from) out.push({ turnId: t.id, a, from, to, faint: faint?.(t.id) });
    });
  }
  return out;
}

export function Legend() {
  return (
    <div className="legend">
      {(["grow", "act", "obj", "etc"] as Group[]).map((g) => (
        <span key={g}><i className={`sw sw-${g}`} />{GROUP_LABEL[g]}</span>
      ))}
      <span><i className="sw sw-unknown" />상대 위치 모름</span>
    </div>
  );
}

export default function Timeline({
  ally, enemy, total, selected, onSelect,
}: { ally: Turn[]; enemy: EnemyTurn[]; total: number; selected: string | null; onSelect: (id: string) => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<{ x: number; y: number; below: boolean; seg: Seg } | null>(null);
  // 스크롤하면 툴팁이 막대에서 떨어지니 숨긴다
  useEffect(() => {
    if (!tip) return;
    const hide = () => setTip(null);
    window.addEventListener("scroll", hide, { passive: true, capture: true });
    return () => window.removeEventListener("scroll", hide, { capture: true });
  }, [tip]);
  const pct = (s: number) => `${(s / total) * 100}%`;
  const allySegs = segments(ally);
  const enemyKnown = enemy.filter((e) => e.confidence !== "unknown");
  const enemySegs = segments(enemyKnown, (id) => enemy.find((e) => e.id === id)?.confidence === "inferred");
  const ticks: number[] = [];
  for (let m = 5; m * 60 < total; m += 5) ticks.push(m * 60);

  // 툴팁은 화면 기준(fixed)으로 띄운다. 가로 스크롤 영역 안에 두면 위쪽이 잘린다
  const place = (x: number, top: number, bottom: number, seg: Seg) => {
    const below = top < 170; // 위에 자리가 없으면 아래로
    const half = 130;
    setTip({ x: Math.min(Math.max(x, half + 8), window.innerWidth - half - 8), y: below ? bottom : top, below, seg });
  };
  const show = (e: React.MouseEvent, seg: Seg) => {
    const r = e.currentTarget.getBoundingClientRect();
    place(e.clientX, r.top, r.bottom, seg);
  };

  const row = (segs: Seg[], who: "ally" | "enemy") => (
    <div className={`tl-track ${who === "enemy" ? "tl-unknown" : ""}`}>
      {who === "ally" && ally.map((t) => (
        <span key={t.id} className="tl-turn-mark" style={{ left: pct(secs(t.from)) }} aria-hidden />
      ))}
      {segs.map((s, i) => (
        <button
          key={i}
          className={`tl-seg g-${groupOf(s.a.kind)} ${s.faint ? "faint" : ""} ${selected && selected === s.turnId ? "on" : ""} ${selected && selected !== s.turnId && who === "ally" ? "dim" : ""}`}
          style={{ left: pct(s.from), width: `calc(${pct(s.to - s.from)} - 2px)` }}
          onMouseMove={(e) => show(e, s)}
          onMouseLeave={() => setTip(null)}
          onFocus={(e) => { const r = e.currentTarget.getBoundingClientRect(); place(r.left + r.width / 2, r.top, r.bottom, s); }}
          onBlur={() => setTip(null)}
          onClick={() => who === "ally" && onSelect(s.turnId)}
          aria-label={`${s.a.t} ${s.a.kind} ${s.a.label}`}
        />
      ))}
    </div>
  );

  return (
    <div className="tl-scroll">
      <div className="tl" ref={wrap}>
        <div className="tl-row">
          <div className="tl-name">우리 정글</div>
          <div className="tl-body">
            <div className="tl-turns">
              {ally.map((t) => (
                <button key={t.id} className={`tl-turn-label ${selected === t.id ? "on" : ""}`} style={{ left: pct(secs(t.from)) }} onClick={() => onSelect(t.id)}>
                  {t.id.toUpperCase()}
                </button>
              ))}
            </div>
            {row(allySegs, "ally")}
          </div>
        </div>
        <div className="tl-row">
          <div className="tl-name">상대 정글</div>
          <div className="tl-body">{row(enemySegs, "enemy")}</div>
        </div>
        <div className="tl-row">
          <div className="tl-name" />
          <div className="tl-body tl-axis">
            <span style={{ left: 0 }}>0분</span>
            {ticks.map((t) => <span key={t} style={{ left: pct(t) }}>{t / 60}분</span>)}
          </div>
        </div>
        {tip && createPortal(
          <div className={`tl-tip ${tip.below ? "below" : ""}`} style={{ left: tip.x, top: tip.y }}>
            <div className="tl-tip-head"><i className={`sw sw-${groupOf(tip.seg.a.kind)}`} />{tip.seg.a.t} · {tip.seg.a.kind}</div>
            <div className="tl-tip-title">{tip.seg.a.label}</div>
            {tip.seg.a.where && <div className="tl-tip-sub">{tip.seg.a.where}</div>}
            {tip.seg.a.result && <div className="tl-tip-sub">{tip.seg.a.result}</div>}
            {tip.seg.faint && <div className="tl-tip-sub">추론한 위치예요</div>}
          </div>,
          document.body,
        )}
      </div>
    </div>
  );
}

/** 한 턴 안의 시간 비율 막대 (턴 카드용) */
export function TurnBar({ actions, to }: { actions: Action[]; to: string }) {
  const segs = segments([{ id: "x", to, actions }]);
  if (segs.length === 0) return null;
  const start = segs[0].from;
  const len = Math.max(1, segs[segs.length - 1].to - start);
  return (
    <div className="turnbar" aria-hidden>
      {segs.map((s, i) => (
        <span key={i} className={`g-${groupOf(s.a.kind)}`} style={{ width: `${((s.to - s.from) / len) * 100}%` }} />
      ))}
    </div>
  );
}

/** 턴 목록에서 성장, 개입, 오브젝트에 쓴 시간 비율 */
export function timeShare(turns: Turn[]) {
  const acc: Record<Group, number> = { grow: 0, act: 0, obj: 0, etc: 0, dead: 0 };
  for (const s of segments(turns)) acc[groupOf(s.a.kind)] += s.to - s.from;
  const sum = Object.values(acc).reduce((a, b) => a + b, 0) || 1;
  return { acc, sum };
}
