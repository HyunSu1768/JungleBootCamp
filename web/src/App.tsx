import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, type AppInfo, type DebriefState } from "./api";
import { LightboxProvider } from "./ui";
import Home from "./pages/Home";
import AddVod from "./pages/AddVod";
import VodPage from "./pages/Vod";
import GamePage from "./pages/Game";
import JobPage from "./pages/Job";
import Concepts from "./pages/Concepts";
import ConceptPage from "./pages/Concept";
import Rules from "./pages/Rules";
import Review from "./pages/Review";
import Train from "./pages/Train";
import Mine from "./pages/Mine";
import Welcome from "./pages/Welcome";
import SettingsPage from "./pages/Settings";
import Debrief, { clock, useRemaining } from "./pages/Debrief";
import GrowthPage from "./pages/Growth";

const TABS = [
  { to: "/", label: "훈련", end: true },
  { to: "/mine", label: "내 게임" },
  { to: "/growth", label: "성장" },
  { to: "/vods", label: "프로 영상" },
  { to: "/concepts", label: "지식" },
];

/** 지식 탭 안의 하위 메뉴 */
const KNOWLEDGE = [
  { to: "/concepts", label: "개념" },
  { to: "/rules", label: "상황별 원칙" },
  { to: "/review", label: "서술형 복습" },
];

/** 판이 끝나면 복기 화면으로 데려가고, 잠금 동안 모든 화면 위에 남은 시간을 띄운다 */
function DebriefWatch() {
  const { pathname } = useLocation();
  const nav = useNavigate();
  const [st, setSt] = useState<DebriefState | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const { active } = await api.debriefActive();
        if (!alive) return;
        setSt(active);
        // 새로 끝난 판이면 한 번 복기 화면으로 (이미 데려간 판은 다시 끌고 가지 않는다)
        let seen: string | null = null;
        try { seen = localStorage.getItem("debrief-opened"); } catch { /* 저장소가 막혀 있어도 동작 */ }
        if (active && !active.done && active.locked && seen !== active.game_id) {
          try { localStorage.setItem("debrief-opened", active.game_id); } catch { /* */ }
          if (!window.location.pathname.startsWith("/debrief/")) nav(`/debrief/${active.game_id}`);
        }
      } catch { /* 서버가 잠깐 없을 때 */ }
    };
    void tick();
    const t = window.setInterval(tick, 5000);
    return () => { alive = false; window.clearInterval(t); };
  }, [nav]);
  const left = useRemaining(st?.lock_until);
  if (!st || left <= 0 || pathname.startsWith("/debrief/") || pathname === "/welcome") return null;
  return (
    <Link to={`/debrief/${st.game_id}`} className="lock-bar">
      <span>복기 시간 · 큐는 <b>{clock(left)}</b> 뒤에 풀려요</span>
      <span>복기하기 ›</span>
    </Link>
  );
}

function ScrollTop() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (!hash) window.scrollTo(0, 0);
  }, [pathname, hash]);
  return null;
}

export default function App() {
  const { pathname } = useLocation();
  const [app, setApp] = useState<AppInfo | null>(null);
  useEffect(() => { void api.appInfo().then(setApp).catch(() => {}); }, [pathname === "/welcome"]);
  // 데스크톱 앱 첫 실행: 온보딩(Claude 연결, 티어, 녹화)부터
  if (app?.desktop && !app.settings.onboarded && pathname !== "/welcome") return <Navigate to="/welcome" replace />;
  const section = (to: string) =>
    to === "/" ? pathname === "/"
    : to === "/vods" ? /^\/(vods|add|jobs)/.test(pathname)
    : to === "/mine" ? /^\/(mine|debrief)/.test(pathname)
    : to === "/concepts" ? /^\/(concepts|rules|review)/.test(pathname)
    : pathname.startsWith(to);
  const inKnowledge = section("/concepts");
  return (
    <LightboxProvider>
      <ScrollTop />
      <DebriefWatch />
      <nav className="nav">
        <div className="nav-inner">
          <Link to="/" className="brand">
            <span className="brand-mark">정</span>
            <span className="brand-text">정글러훈련소</span>
          </Link>
          <div className="nav-tabs" hidden={pathname === "/welcome"}>
            {TABS.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={() => `tab ${section(t.to) ? "active" : ""}`}
              >
                {t.label}
              </NavLink>
            ))}
          </div>
          <NavLink to="/settings" className={() => `nav-gear ${pathname === "/settings" ? "active" : ""}`} aria-label="설정">⚙︎</NavLink>
        </div>
      </nav>
      {inKnowledge && (
        <div className="subnav">
          {KNOWLEDGE.map((k) => (
            <NavLink key={k.to} to={k.to} className={() => `subtab ${pathname.startsWith(k.to) ? "on" : ""}`}>{k.label}</NavLink>
          ))}
        </div>
      )}
      <main className="page">
        <Routes>
          <Route path="/" element={<Train />} />
          <Route path="/vods" element={<Home />} />
          <Route path="/mine" element={<Mine />} />
          <Route path="/welcome" element={<Welcome />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/mine/:id" element={<GamePage />} />
          <Route path="/debrief/:id" element={<Debrief />} />
          <Route path="/growth" element={<GrowthPage />} />
          <Route path="/add" element={<AddVod />} />
          <Route path="/vods/:dir" element={<VodPage />} />
          <Route path="/vods/:dir/:n" element={<GamePage />} />
          <Route path="/jobs/:id" element={<JobPage />} />
          <Route path="/concepts" element={<Concepts />} />
          <Route path="/concepts/:id" element={<ConceptPage />} />
          <Route path="/rules" element={<Rules />} />
          <Route path="/review" element={<Review />} />
          <Route path="*" element={<div className="empty"><h2 className="t2">없는 페이지예요</h2></div>} />
        </Routes>
      </main>
    </LightboxProvider>
  );
}
