import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../contexts/AuthContext";
import { fetchStats } from "../api/endpoints";

/**
 * Internal Medyca-branded home (MEDYC-14). Two entry cards — Medyca and
 * Competitor — plus the Second Brain. Styled to the Medyca design tokens
 * (.claude/skills/ui-design): medical blue + red, Nunito Sans, pill buttons.
 * Deliberately light, unlike the dark analysis views it routes into.
 */
export default function Home() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: fetchStats });

  return (
    <div className="medyca-home">
      <style>{CSS}</style>
      <header className="mh-nav">
        <div className="mh-logo">Med<span>y</span>ca <em>· Intelligence</em></div>
        <button className="mh-logout" onClick={logout}>{t("nav.logout")}</button>
      </header>

      <main className="mh-main">
        <p className="mh-eyebrow">Content Intelligence</p>
        <h1 className="mh-title">Due pipeline, un solo cervello per i contenuti</h1>
        <p className="mh-sub">
          Analizza i contenuti di Medyca e dei competitor con la stessa struttura,
          e lascia che il Second Brain proponga i prossimi argomenti da trattare.
        </p>

        <div className="mh-cards">
          <button className="mh-card mh-card-primary" onClick={() => navigate("/medyca/clusters")}>
            <span className="mh-badge">La nostra voce</span>
            <h2>Medyca</h2>
            <p>I contenuti del profilo <b>@medyca.menopausa</b>: reel, trascrizioni, temi.</p>
            <div className="mh-stat">
              <span>{stats?.medyca.reels ?? "–"}</span> reel · <span>{stats?.medyca.clusters ?? "–"}</span> temi
            </div>
            <span className="mh-go">Apri →</span>
          </button>

          <button className="mh-card" onClick={() => navigate("/competitor/clusters")}>
            <span className="mh-badge mh-badge-alt">Ispirazione</span>
            <h2>Competitor</h2>
            <p>Cosa pubblicano gli altri account sulla menopausa: temi e argomenti.</p>
            <div className="mh-stat">
              <span>{stats?.competitor.reels ?? "–"}</span> reel · <span>{stats?.competitor.clusters ?? "–"}</span> temi
            </div>
            <span className="mh-go">Apri →</span>
          </button>
        </div>

        <button className="mh-brain" onClick={() => navigate("/second-brain")}>
          <div>
            <span className="mh-badge">Second Brain</span>
            <h3>Idee di contenuto, generate dai dati</h3>
            <p>Argomenti proposti dal confronto tra competitor e la copertura di Medyca (Instagram + blog).</p>
          </div>
          <div className="mh-brain-stat">
            <span>{stats?.content_ideas ?? "–"}</span>
            <small>idee</small>
          </div>
        </button>
      </main>
    </div>
  );
}

const CSS = `
.medyca-home {
  --navy:#2C4984; --heading:#346FAA; --primary:#C93B42; --primary-h:#A93037;
  --secondary:#4A6FAC; --surface:#EEF5FD; --border:#D5E3F2; --bg:#fff;
  position:fixed; inset:0; overflow-y:auto; background:var(--bg); color:var(--navy);
  font-family:'Nunito Sans',system-ui,sans-serif;
}
.mh-nav { display:flex; justify-content:space-between; align-items:center;
  padding:16px 32px; border-bottom:1px solid var(--border); }
.mh-logo { font-weight:700; font-size:22px; color:var(--heading); letter-spacing:-.02em; }
.mh-logo span { color:var(--primary); }
.mh-logo em { font-style:normal; font-weight:600; font-size:14px; color:var(--secondary); }
.mh-logout { background:var(--surface); border:1px solid var(--border); color:var(--navy);
  font-weight:600; padding:8px 16px; border-radius:999px; cursor:pointer; font-family:inherit; }
.mh-logout:hover { border-color:var(--secondary); }
.mh-main { max-width:920px; margin:0 auto; padding:64px 24px; }
.mh-eyebrow { text-transform:uppercase; letter-spacing:.12em; font-size:13px; font-weight:700;
  color:var(--secondary); margin:0 0 12px; }
.mh-title { font-size:clamp(28px,5vw,44px); font-weight:700; color:var(--heading);
  line-height:1.1; margin:0; letter-spacing:-.02em; }
.mh-sub { font-size:18px; color:var(--secondary); margin:16px 0 0; max-width:52ch; }
.mh-cards { display:grid; grid-template-columns:1fr 1fr; gap:24px; margin-top:48px; }
@media (max-width:720px){ .mh-cards{ grid-template-columns:1fr; } }
.mh-card { text-align:left; background:var(--surface); border:1px solid var(--border);
  border-radius:24px; padding:28px; cursor:pointer; font-family:inherit; color:var(--navy);
  transition:transform .2s cubic-bezier(.2,0,0,1), box-shadow .2s; display:flex; flex-direction:column; gap:8px; }
.mh-card:hover { transform:translateY(-4px); box-shadow:0 4px 16px rgba(44,73,132,.12); }
.mh-card:focus-visible { outline:3px solid var(--secondary); outline-offset:2px; }
.mh-card h2 { font-size:28px; font-weight:700; color:var(--heading); margin:4px 0 0; }
.mh-card p { color:var(--secondary); margin:0; font-size:15px; }
.mh-card-primary { background:#fff; border-color:var(--heading); }
.mh-badge { align-self:flex-start; background:#fff; border:1px solid var(--border);
  color:var(--secondary); font-weight:700; font-size:12px; text-transform:uppercase;
  letter-spacing:.08em; padding:4px 12px; border-radius:999px; }
.mh-card-primary .mh-badge { background:var(--surface); }
.mh-badge-alt { color:var(--primary); }
.mh-stat { margin-top:8px; font-size:14px; color:var(--secondary); }
.mh-stat span { font-weight:700; color:var(--navy); font-size:18px; }
.mh-go { margin-top:12px; font-weight:700; color:var(--primary); }
.mh-brain { width:100%; text-align:left; margin-top:24px; display:flex; justify-content:space-between;
  align-items:center; gap:24px; background:var(--heading); color:#fff; border:0; border-radius:24px;
  padding:28px; cursor:pointer; font-family:inherit;
  transition:transform .2s cubic-bezier(.2,0,0,1); }
.mh-brain:hover { transform:translateY(-3px); }
.mh-brain:focus-visible { outline:3px solid var(--primary); outline-offset:2px; }
.mh-brain .mh-badge { background:rgba(255,255,255,.14); border-color:rgba(255,255,255,.28); color:#fff; }
.mh-brain h3 { color:#fff; font-size:22px; font-weight:700; margin:10px 0 6px; }
.mh-brain p { color:#dbe7f5; margin:0; font-size:15px; max-width:60ch; }
.mh-brain-stat { text-align:center; flex:none; background:var(--primary); border-radius:16px; padding:16px 22px; }
.mh-brain-stat span { display:block; font-size:32px; font-weight:800; color:#fff; }
.mh-brain-stat small { color:#ffd9d3; font-weight:600; }
@media (prefers-reduced-motion:reduce){ .mh-card,.mh-brain{ transition:none; } }
`;
