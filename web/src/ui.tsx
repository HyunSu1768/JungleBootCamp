import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, media, type Job, type Source } from "./api";

/** 주기적으로 다시 불러오기. active가 false면 한 번만 부른다. */
export function usePoll<T>(fn: () => Promise<T>, deps: unknown[], active: (d: T | undefined) => boolean, ms = 2500) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async () => {
    try {
      const d = await fnRef.current();
      setData(d);
      setError(undefined);
      return d;
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      const d = await reload();
      if (alive && active(d)) timer = window.setTimeout(tick, ms);
    };
    tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, reload };
}

export const isActive = (j: Job | null | undefined) => !!j && (j.status === "queued" || j.status === "running");

export function Dots() {
  return <span className="dots" aria-hidden><i /><i /><i /></span>;
}

export function PageHead({ eyebrow, title, sub, children, actions }: { eyebrow?: ReactNode; title: ReactNode; sub?: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head head-row">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1 className="t1">{title}</h1>
        {sub && <p className="sub">{sub}</p>}
        {children}
      </div>
      {actions && <div className="row desktop-only">{actions}</div>}
    </header>
  );
}

/** 모바일에선 하단 고정 버튼. 데스크톱에선 본문 안 버튼(mobileOnly면 데스크톱에서 숨김) */
export function BottomCTA({ children, mobileOnly }: { children: ReactNode; mobileOnly?: boolean }) {
  return (
    <div className={`bottom-cta ${mobileOnly ? "mobile-only" : ""}`}>
      <div className="bottom-cta-inner">{children}</div>
    </div>
  );
}

export function SourceBadge({ source }: { source: Source }) {
  if (source === "quote") return <span className="badge badge-blue">스트리머 발언</span>;
  if (source === "team") return <span className="badge badge-grey">팀 보이스</span>;
  if (source === "review") return <span className="badge badge-orange">리플레이 피드백</span>;
  if (source === "screen") return <span className="badge badge-green">화면 확인</span>;
  return <span className="badge badge-grey">추정</span>;
}

export function ResultBadge({ result }: { result?: string | null }) {
  if (result === "승") return <span className="badge badge-blue">승리</span>;
  if (result === "패") return <span className="badge badge-red">패배</span>;
  return null;
}

export function JobSteps({ job, detailLink = true }: { job: Job; detailLink?: boolean }) {
  const [cancelling, setCancelling] = useState(false);
  const cancel = async () => {
    if (!window.confirm("이 작업을 취소할까요? 지금까지 받은 영상은 남고, 분석은 처음부터 다시 해야 해요.")) return;
    setCancelling(true);
    try { await api.cancelJob(job.id); } catch { setCancelling(false); }
  };
  return (
    <div>
      <div className="steps">
        {job.steps.map((s, i) => (
          <div key={i} className={`step ${s.status}`}>
            <span className="step-dot">{s.status === "done" ? "✓" : s.status === "error" ? "!" : s.status === "cancelled" ? "–" : i + 1}</span>
            <span>{s.name}</span>
            {s.status === "running" && <Dots />}
          </div>
        ))}
      </div>
      {job.status === "queued" && <p className="small" style={{ marginTop: 12 }}>앞선 작업이 끝나면 시작해요</p>}
      {job.error && <p className="field-error" style={{ fontSize: 15 }}>{job.error}</p>}
      {job.log_tail && job.log_tail.length > 0 && isActive(job) && (
        <div className="log-mini">{job.log_tail.slice(-3).map((l, i) => <div key={i}>{l}</div>)}</div>
      )}
      {job.status === "cancelled" && <p className="small" style={{ marginTop: 12 }}>취소한 작업이에요</p>}
      <div className="row" style={{ marginTop: 12 }}>
      {isActive(job) && (
        <button className="btn btn-ghost btn-sm" onClick={cancel} disabled={cancelling}>
          {cancelling ? <>취소하는 중 <Dots /></> : "작업 취소"}
        </button>
      )}
      {detailLink && (
        <Link to={`/jobs/${job.id}`} className="small" style={{ color: "var(--blue-700)" }}>
          진행 기록 보기
        </Link>
      )}
      </div>
    </div>
  );
}

/* ---------- 이미지 확대 ---------- */
type LB = { open: (images: string[], index: number) => void };
const LightboxCtx = createContext<LB>({ open: () => {} });
export const useLightbox = () => useContext(LightboxCtx);

export function LightboxProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ images: string[]; index: number } | null>(null);
  const open = useCallback((images: string[], index: number) => setState({ images, index }), []);
  useEffect(() => {
    if (!state) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setState(null);
      if (e.key === "ArrowRight") setState((s) => s && { ...s, index: Math.min(s.images.length - 1, s.index + 1) });
      if (e.key === "ArrowLeft") setState((s) => s && { ...s, index: Math.max(0, s.index - 1) });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state]);
  return (
    <LightboxCtx.Provider value={{ open }}>
      {children}
      {state && (
        <div className="lightbox" onClick={() => setState(null)} role="dialog" aria-label="이미지 크게 보기">
          <img src={media(state.images[state.index])} alt="" onClick={(e) => e.stopPropagation()} />
          <div className="lightbox-bar" onClick={(e) => e.stopPropagation()}>
            <button aria-label="이전" onClick={() => setState({ ...state, index: Math.max(0, state.index - 1) })}>‹</button>
            <span>{fileLabel(state.images[state.index])} · {state.index + 1} / {state.images.length}</span>
            <button aria-label="다음" onClick={() => setState({ ...state, index: Math.min(state.images.length - 1, state.index + 1) })}>›</button>
            <button aria-label="닫기" onClick={() => setState(null)}>×</button>
          </div>
        </div>
      )}
    </LightboxCtx.Provider>
  );
}

/** "…/frames/1-26-35.jpg" → "VOD 1:26:35" */
export function fileLabel(p: string) {
  const m = p.match(/(\d+)-(\d{2})-(\d{2})(\.\d+)?\.jpg$/);
  return m ? `VOD ${m[1]}:${m[2]}:${m[3]}` : p.split("/").pop() ?? "";
}

export function FrameStrip({ frames }: { frames?: string[] }) {
  const lb = useLightbox();
  if (!frames || frames.length === 0) return null;
  return (
    <div className="frames">
      {frames.map((f, i) => (
        <img key={f} src={media(f)} alt={fileLabel(f)} loading="lazy" onClick={() => lb.open(frames, i)} />
      ))}
    </div>
  );
}

/* ---------- 토스트 ---------- */
export function useToast() {
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (!msg) return;
    const t = window.setTimeout(() => setMsg(null), 2600);
    return () => window.clearTimeout(t);
  }, [msg]);
  return { show: setMsg, node: msg ? <div className="toast" role="status">{msg}</div> : null };
}

export function Loading() {
  return (
    <div className="stack" style={{ marginTop: 40 }}>
      <div className="skeleton" style={{ height: 36, width: "60%" }} />
      <div className="skeleton" style={{ height: 20, width: "40%" }} />
      <div className="skeleton" style={{ height: 120, marginTop: 32 }} />
    </div>
  );
}

export function ErrorView({ message }: { message: string }) {
  return (
    <div className="empty">
      <div className="empty-icon">😥</div>
      <h2 className="t3">불러오지 못했어요</h2>
      <p className="sub">{message}</p>
    </div>
  );
}
