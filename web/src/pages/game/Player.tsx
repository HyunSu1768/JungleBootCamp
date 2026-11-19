import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { hmsOf } from "./time";

/** 영상 위 한 지점 (VOD 초) */
export interface Mark { at: number; time: string; label: string; sub?: string; group?: string }

/** 플레이어에서 보는 한 구간. 시각은 모두 VOD 기준 초 */
export interface Clip {
  id: string;
  kind: string;          // "턴", "교전", "변곡점", "피드백"
  title: string;
  sub?: string;
  src: string;           // 영상 파일 URL
  base: number;          // 영상 파일 첫 프레임의 VOD 초
  start: number;
  end?: number;
  marks: Mark[];
  ingameOffset?: number; // VOD 초 - 인게임 초. 있으면 인게임 시계를 보여준다
}

const Ctx = createContext<(clips: Clip[], index: number, at?: number) => void>(() => {});
export const usePlayer = () => useContext(Ctx);

const SPEEDS = [1, 1.5, 2, 4];
const PRE_ROLL = 3; // 구간 시작 3초 전부터 틀어 맥락을 본다

export function PlayerProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ clips: Clip[]; index: number; at?: number } | null>(null);
  const open = useCallback((clips: Clip[], index: number, at?: number) => setState({ clips, index, at }), []);
  return (
    <Ctx.Provider value={open}>
      {children}
      {state && createPortal(
        <Player {...state} onIndex={(index) => setState({ ...state, index, at: undefined })} onClose={() => setState(null)} />,
        document.body,
      )}
    </Ctx.Provider>
  );
}

function Player({ clips, index, at, onIndex, onClose }: { clips: Clip[]; index: number; at?: number; onIndex: (i: number) => void; onClose: () => void }) {
  const clip = clips[index];
  const video = useRef<HTMLVideoElement>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const [now, setNow] = useState(clip.start);
  const [speed, setSpeed] = useState(() => Number(sessionStorageGet("player-speed")) || 2);
  const [stopAtEnd, setStopAtEnd] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const seek = useCallback((vodSec: number) => {
    const v = video.current;
    if (!v) return;
    v.currentTime = Math.max(0, vodSec - clip.base);
    void v.play().catch(() => {});
  }, [clip.base]);

  // 구간이 바뀌면 시작 지점으로
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    setError(null);
    const go = () => seek(at ?? clip.start - PRE_ROLL);
    if (v.readyState >= 1) go();
    else v.addEventListener("loadedmetadata", go, { once: true });
  }, [clip, at, seek]);

  useEffect(() => {
    if (video.current) video.current.playbackRate = speed;
    sessionStorageSet("player-speed", String(speed));
  }, [speed, clip]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const v = video.current;
      if (!v) return;
      if (e.key === "Escape") onClose();
      else if (e.key === " ") { e.preventDefault(); if (v.paused) void v.play(); else v.pause(); }
      else if (e.key === "ArrowLeft") v.currentTime -= 5;
      else if (e.key === "ArrowRight") v.currentTime += 5;
      else if (e.key === "ArrowUp" && index > 0) { e.preventDefault(); onIndex(index - 1); }
      else if (e.key === "ArrowDown" && index < clips.length - 1) { e.preventDefault(); onIndex(index + 1); }
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [onClose, onIndex, index, clips.length]);

  const onTime = () => {
    const v = video.current;
    if (!v) return;
    const t = clip.base + v.currentTime;
    setNow(t);
    if (stopAtEnd && clip.end != null && t >= clip.end && t < clip.end + 1.5 && !v.paused) v.pause();
  };

  const current = useMemo(() => {
    let k = -1;
    clip.marks.forEach((m, i) => { if (m.at <= now + 0.5) k = i; });
    return k;
  }, [clip.marks, now]);

  useEffect(() => {
    listRef.current?.querySelector(`[data-i="${current}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [current]);

  const span = clip.end != null ? clip.end - clip.start : null;
  const progress = span ? Math.min(1, Math.max(0, (now - clip.start) / span)) : null;
  const ingame = clip.ingameOffset != null ? now - clip.ingameOffset : null;

  return (
    <div className="player" role="dialog" aria-modal="true" aria-label={`${clip.kind} 영상`} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="player-box">
        <div className="player-head">
          <span className="player-kind">{clip.kind}</span>
          <b>{clip.title}</b>
          {clip.sub && <span className="player-sub">{clip.sub}</span>}
          <button className="player-x" onClick={onClose} aria-label="닫기">✕</button>
        </div>
        <div className="player-body">
          <div className="player-main">
            <div className="player-video">
              <video
                ref={video}
                src={clip.src}
                controls
                playsInline
                preload="metadata"
                onTimeUpdate={onTime}
                onError={() => setError("영상을 불러오지 못했어요. 원본 영상(video.mp4)이 지워졌거나 아직 받는 중일 수 있어요.")}
              />
              {error && <div className="player-error">{error}</div>}
            </div>
            <div className="player-bar">
              <span className="player-clock">
                {ingame != null && ingame >= 0 ? <>인게임 <b>{hmsOf(ingame)}</b></> : null}
                <span>VOD {hmsOf(now, true)}</span>
              </span>
              {progress != null && <div className="player-progress"><div style={{ width: `${progress * 100}%` }} /></div>}
              <div className="player-speeds" role="group" aria-label="재생 속도">
                {SPEEDS.map((s) => <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>{s}x</button>)}
              </div>
            </div>
            <div className="player-tools">
              <button disabled={index === 0} onClick={() => onIndex(index - 1)}>‹ 이전 {clip.kind}</button>
              <label><input type="checkbox" checked={stopAtEnd} onChange={(e) => setStopAtEnd(e.target.checked)} /> {clip.kind} 끝에서 멈추기</label>
              <button onClick={() => seek(clip.start - PRE_ROLL)}>처음부터</button>
              <button disabled={index === clips.length - 1} onClick={() => onIndex(index + 1)}>다음 {clip.kind} ›</button>
            </div>
          </div>
          <ol className="player-marks" ref={listRef}>
            {clip.marks.map((m, i) => (
              <li key={i} data-i={i}>
                <button className={i === current ? "on" : ""} onClick={() => seek(m.at - 2)}>
                  <span className="at">{m.time}</span>
                  {m.group && <i className={`sw sw-${m.group}`} />}
                  <span>{m.label}{m.sub && <span className="ar">{m.sub}</span>}</span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}

function sessionStorageGet(k: string) {
  try { return window.sessionStorage.getItem(k); } catch { return null; }
}
function sessionStorageSet(k: string, v: string) {
  try { window.sessionStorage.setItem(k, v); } catch { /* 저장 못 해도 재생은 된다 */ }
}
