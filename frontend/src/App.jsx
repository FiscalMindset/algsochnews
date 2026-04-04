// App.jsx — Root with nav + layout
import Dashboard from './Dashboard.jsx'
import { Zap } from 'lucide-react'

function Navbar() {
  return (
    <nav className="navbar">
      <div className="nav-inner">
        <div className="nav-brand">
          <div className="nav-logo">
            <Zap size={18} fill="currentColor" />
          </div>
          <span className="nav-name">NewsAI Studio</span>
          <span className="nav-version">v1.0</span>
        </div>
        <div className="nav-links">
          <a href="/api/docs" target="_blank" rel="noopener" className="nav-link">
            API Docs
          </a>
          <a href="#" className="nav-link nav-link--muted">About</a>
        </div>
      </div>
      <style>{`
        .navbar {
          position: sticky; top: 0; z-index: 100;
          border-bottom: 1px solid var(--border-subtle);
          background: rgba(11,15,26,0.85);
          backdrop-filter: blur(20px);
          -webkit-backdrop-filter: blur(20px);
        }
        .nav-inner {
          max-width: 1100px; margin: 0 auto;
          padding: 0 24px; height: 58px;
          display: flex; align-items: center; justify-content: space-between;
        }
        .nav-brand { display: flex; align-items: center; gap: 10px; }
        .nav-logo {
          width: 32px; height: 32px; border-radius: 8px;
          background: var(--gradient-primary);
          display: flex; align-items: center; justify-content: center;
          color: white; box-shadow: 0 0 16px rgba(59,130,246,0.4);
        }
        .nav-name { font-size: 15px; font-weight: 800; letter-spacing: -0.01em; }
        .nav-version {
          font-size: 10px; padding: 2px 7px; border-radius: var(--radius-full);
          background: rgba(59,130,246,0.15); color: var(--accent-blue);
          border: 1px solid rgba(59,130,246,0.3); font-family: var(--font-mono);
        }
        .nav-links { display: flex; align-items: center; gap: 4px; }
        .nav-link {
          font-size: 13px; font-weight: 500; color: rgba(255,255,255,0.6);
          text-decoration: none; padding: 6px 12px; border-radius: var(--radius-sm);
          transition: all var(--transition-fast);
        }
        .nav-link:hover { background: rgba(255,255,255,0.07); color: white; }
        .nav-link--muted { color: rgba(255,255,255,0.35); }
      `}</style>
    </nav>
  )
}

function Footer() {
  return (
    <footer className="footer">
      <p>Built with FastAPI · React · FFmpeg · Gemini AI</p>
      <style>{`
        .footer {
          text-align: center; padding: 32px;
          font-size: 12px; color: rgba(255,255,255,0.2);
          border-top: 1px solid var(--border-subtle);
        }
      `}</style>
    </footer>
  )
}

export default function App() {
  return (
    <>
      <div className="bg-animated" aria-hidden="true" />
      <div className="app-layout">
        <Navbar />
        <Dashboard />
        <Footer />
      </div>
      <style>{`
        .app-layout {
          position: relative; z-index: 1;
          min-height: 100vh;
          display: flex; flex-direction: column;
        }
      `}</style>
    </>
  )
}
