// Dashboard.jsx — Main page
import { useState } from 'react'
import { Tv, RefreshCw, AlertTriangle } from 'lucide-react'
import URLInput       from './components/URLInput.jsx'
import ProgressPanel  from './components/ProgressPanel.jsx'
import VideoPlayer    from './components/VideoPlayer.jsx'
import ScriptPreview  from './components/ScriptPreview.jsx'
import TimelineView   from './components/TimelineView.jsx'
import DownloadButton from './components/DownloadButton.jsx'
import useGenerate    from './hooks/useGenerate.js'
import { videoUrl }   from './api/client.js'

export default function Dashboard() {
  const { jobId, status, progress, message, result, error, generate, reset } = useGenerate()

  const isDone       = status === 'done'
  const isFailed     = status === 'failed'
  const isProcessing = status === 'pending' || status === 'processing'
  const script       = result?.script
  const vidUrl       = jobId ? videoUrl(jobId) : null

  return (
    <main className="dashboard">
      {/* ---- HERO ---- */}
      <section className="hero fade-up">
        <div className="hero-eyebrow">
          <span className="live-dot" />
          <span>AI-Powered · Real-time · Production Ready</span>
        </div>
        <h1 className="hero-title">
          <span className="text-gradient">AI News</span>{' '}
          <span>Video Generator</span>
        </h1>
        <p className="hero-sub">
          Drop any news article URL &mdash; get a fully-rendered broadcast video
          with narration, headlines, visuals, and cinematic transitions in minutes.
        </p>
      </section>

      {/* ---- INPUT CARD ---- */}
      {!isDone && (
        <section className="card fade-up fade-up-delay-1">
          <URLInput onSubmit={generate} disabled={isProcessing} />
        </section>
      )}

      {/* ---- ERROR ---- */}
      {isFailed && (
        <div className="error-banner fade-up">
          <AlertTriangle size={18} />
          <div>
            <strong>Generation failed</strong>
            <p>{error}</p>
          </div>
          <button className="retry-btn" onClick={reset}>
            <RefreshCw size={15} /> Try again
          </button>
        </div>
      )}

      {/* ---- PROGRESS ---- */}
      {isProcessing && (
        <section className="fade-up fade-up-delay-2">
          <ProgressPanel progress={progress} message={message} status={status} />
        </section>
      )}

      {/* ---- RESULTS ---- */}
      {isDone && result && (
        <>
          {/* Result header bar */}
          <div className="result-bar fade-up">
            <div className="result-bar-left">
              <Tv size={18} />
              <span>Video Ready</span>
              {script && (
                <span className="result-dur">
                  {Math.round(script.total_duration)}s · {script.segments?.length} segments
                </span>
              )}
            </div>
            <div className="result-bar-right">
              {vidUrl && <DownloadButton videoUrl={vidUrl} jobId={jobId} />}
              <button className="reset-btn" onClick={reset}>
                <RefreshCw size={15} /> New video
              </button>
            </div>
          </div>

          {/* Video player */}
          {vidUrl && (
            <section className="fade-up fade-up-delay-1">
              <VideoPlayer
                videoUrl={vidUrl}
                title={script?.overall_headline || 'AI Generated News Video'}
              />
            </section>
          )}

          {/* Timeline */}
          {script?.segments && (
            <section className="fade-up fade-up-delay-2">
              <TimelineView
                segments={script.segments}
                totalDuration={script.total_duration}
              />
            </section>
          )}

          {/* Script */}
          {script && (
            <section className="fade-up fade-up-delay-3">
              <ScriptPreview script={script} />
            </section>
          )}
        </>
      )}

      <style>{`
        .dashboard {
          position: relative; z-index: 1;
          max-width: 900px; margin: 0 auto;
          padding: 60px 24px 120px;
          display: flex; flex-direction: column; gap: 28px;
        }
        .hero { text-align: center; }
        .hero-eyebrow {
          display: inline-flex; align-items: center; gap: 10px;
          font-size: 12px; font-weight: 600; letter-spacing: 0.12em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.4);
          background: rgba(255,255,255,0.05);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-full);
          padding: 6px 16px; margin-bottom: 24px;
        }
        .hero-title {
          font-size: clamp(2.4rem, 6vw, 4rem);
          font-weight: 900; line-height: 1.1;
          letter-spacing: -0.03em;
          margin-bottom: 18px;
        }
        .hero-sub {
          font-size: 16px; color: rgba(255,255,255,0.5);
          max-width: 580px; margin: 0 auto;
          line-height: 1.7;
        }
        .card {
          background: var(--bg-card);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-xl);
          padding: 32px 36px;
          backdrop-filter: blur(12px);
        }
        .error-banner {
          display: flex; align-items: flex-start; gap: 14px;
          background: rgba(239,68,68,0.08);
          border: 1px solid rgba(239,68,68,0.3);
          border-radius: var(--radius-lg);
          padding: 20px 24px; color: var(--accent-red);
        }
        .error-banner p { color: rgba(255,255,255,0.55); font-size: 13px; margin-top: 4px; }
        .retry-btn {
          margin-left: auto; display: flex; align-items: center; gap: 6px;
          background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.4);
          color: var(--accent-red); border-radius: var(--radius-md);
          padding: 8px 16px; font-size: 13px; font-weight: 600; cursor: pointer;
          transition: all var(--transition-base); flex-shrink: 0;
        }
        .retry-btn:hover { background: rgba(239,68,68,0.25); }
        .result-bar {
          display: flex; align-items: center; justify-content: space-between;
          flex-wrap: wrap; gap: 12px;
        }
        .result-bar-left {
          display: flex; align-items: center; gap: 10px;
          font-size: 16px; font-weight: 700;
          color: rgba(255,255,255,0.9);
        }
        .result-dur {
          font-size: 13px; font-family: var(--font-mono);
          color: rgba(255,255,255,0.4); font-weight: 400;
        }
        .result-bar-right { display: flex; align-items: center; gap: 12px; }
        .reset-btn {
          display: flex; align-items: center; gap: 6px;
          background: rgba(255,255,255,0.06);
          border: 1px solid var(--border-subtle);
          color: rgba(255,255,255,0.6);
          border-radius: var(--radius-md);
          padding: 12px 18px; font-size: 13px; font-weight: 600;
          cursor: pointer; transition: all var(--transition-base);
        }
        .reset-btn:hover {
          background: rgba(255,255,255,0.1); color: white;
        }
      `}</style>
    </main>
  )
}
