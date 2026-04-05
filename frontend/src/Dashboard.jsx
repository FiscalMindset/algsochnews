import { useState } from 'react'
import { AlertTriangle, RefreshCw, Tv } from 'lucide-react'

import AgentWorkflowPanel from './components/AgentWorkflowPanel.jsx'
import DownloadButton from './components/DownloadButton.jsx'
import LiveControlRoom from './components/LiveControlRoom.jsx'
import ProgressPanel from './components/ProgressPanel.jsx'
import ScriptPreview from './components/ScriptPreview.jsx'
import TimelineView from './components/TimelineView.jsx'
import URLInput from './components/URLInput.jsx'
import VideoPlayer from './components/VideoPlayer.jsx'
import useGenerate from './hooks/useGenerate.js'
import { videoUrl } from './api/client.js'

export default function Dashboard() {
  const [currentTime, setCurrentTime] = useState(0)
  const {
    jobId,
    status,
    progress,
    message,
    result,
    error,
    agents,
    activityLog,
    traceEvents,
    review,
    workflowOverview,
    modelVerification,
    generate,
    reset,
  } = useGenerate()

  const isDone = status === 'done'
  const isFailed = status === 'failed'
  const isProcessing = status === 'pending' || status === 'processing'
  const script = result?.script
  const vidUrl = jobId ? videoUrl(jobId) : null
  const visibleReview = script?.review || review
  const activeSegment =
    script?.segments?.find((segment) => currentTime >= segment.start_time && currentTime <= segment.end_time) ||
    script?.segments?.[0] ||
    null

  return (
    <main className="dashboard">
      <section className="hero fade-up">
        <div className="hero-badge">Algsoch News - live newsroom pipeline</div>
        <h1>
          Algsoch Newsroom
          <span> URL to Broadcast Screenplay + Video</span>
        </h1>
        <p>
          Build a visible newsroom pipeline, not a hidden summary box. The client can inspect extraction,
          editorial, packaging, QA, the structured JSON, and the final broadcast output in one place.
        </p>
      </section>

      {!isDone && (
        <section className="input-card fade-up fade-up-delay-1">
          <URLInput onSubmit={generate} disabled={isProcessing} />
        </section>
      )}

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

      {isProcessing && (
        <>
          <section className="fade-up fade-up-delay-2">
            <ProgressPanel
              progress={progress}
              message={message}
              status={status}
              agents={agents}
              workflowOverview={workflowOverview}
              modelVerification={modelVerification}
            />
          </section>
          <AgentWorkflowPanel
            agents={agents}
            activityLog={activityLog}
            traceEvents={traceEvents}
            review={visibleReview}
            workflowOverview={workflowOverview}
            modelVerification={modelVerification}
          />
        </>
      )}

      {isDone && result && (
        <>
          <div className="result-hero fade-up">
            <div className="result-meta">
              <div className="result-title">
                <Tv size={18} />
                <span>Broadcast Package Ready</span>
              </div>
              <div className="result-stats">
                <span>{script?.video_duration_sec}s runtime</span>
                <span>{script?.segments?.length} segments</span>
                <span>QA {(script?.qa_score * 100).toFixed(0)}%</span>
                <span>Model {script?.model_verification?.selected_model || modelVerification?.selected_model || 'n/a'}</span>
              </div>
            </div>
            <div className="result-actions">
              {vidUrl && <DownloadButton videoUrl={vidUrl} jobId={jobId} />}
              <button className="reset-btn" onClick={reset}>
                <RefreshCw size={15} /> New run
              </button>
            </div>
          </div>

          <AgentWorkflowPanel
            agents={result.agents || agents}
            activityLog={result.activity_log || activityLog}
            traceEvents={result.trace_events || traceEvents}
            review={visibleReview}
            workflowOverview={script?.workflow_overview || workflowOverview}
            modelVerification={script?.model_verification || result.model_verification || modelVerification}
          />

          {vidUrl && (
            <section className="fade-up fade-up-delay-1">
              <VideoPlayer
                videoUrl={vidUrl}
                title={script?.overall_headline || 'Algsoch News Broadcast'}
                activeSegment={activeSegment}
                onProgress={(time) => setCurrentTime(time)}
              />
            </section>
          )}

          {script && (
            <section className="fade-up fade-up-delay-1">
              <LiveControlRoom script={script} currentTime={currentTime} />
            </section>
          )}

          {script?.segments && (
            <section className="fade-up fade-up-delay-2">
              <TimelineView
                segments={script.segments}
                totalDuration={script.total_duration}
                currentTime={currentTime}
              />
            </section>
          )}

          {script && (
            <section className="fade-up fade-up-delay-3">
              <ScriptPreview script={script} />
            </section>
          )}
        </>
      )}

      <style>{`
        .dashboard {
          position: relative;
          z-index: 1;
          max-width: 1180px;
          margin: 0 auto;
          padding: 52px 24px 120px;
          display: flex;
          flex-direction: column;
          gap: 28px;
        }
        .hero {
          display: flex;
          flex-direction: column;
          gap: 16px;
          padding: 22px 0 6px;
        }
        .hero-badge {
          display: inline-flex;
          width: fit-content;
          padding: 7px 12px;
          border-radius: 999px;
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.09);
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.14em;
          color: rgba(255,255,255,0.48);
        }
        .hero h1 {
          font-size: clamp(2.7rem, 6vw, 4.6rem);
          line-height: 0.98;
          letter-spacing: -0.04em;
          max-width: 980px;
        }
        .hero h1 span {
          display: block;
          color: rgba(255,255,255,0.76);
        }
        .hero p {
          max-width: 760px;
          font-size: 16px;
          line-height: 1.8;
          color: rgba(255,255,255,0.56);
        }
        .input-card {
          background: linear-gradient(180deg, rgba(16,22,38,0.88), rgba(11,15,27,0.88));
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 28px;
          padding: 28px 32px;
          box-shadow: 0 24px 80px rgba(0,0,0,0.18);
        }
        .error-banner {
          display: flex;
          align-items: start;
          gap: 14px;
          padding: 18px 22px;
          border-radius: 18px;
          background: rgba(239,68,68,0.08);
          border: 1px solid rgba(239,68,68,0.28);
          color: #fca5a5;
        }
        .error-banner p {
          margin-top: 4px;
          color: rgba(255,255,255,0.58);
          font-size: 13px;
        }
        .retry-btn,
        .reset-btn {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          border-radius: 999px;
          cursor: pointer;
          font-weight: 700;
        }
        .retry-btn {
          margin-left: auto;
          background: rgba(239,68,68,0.12);
          border: 1px solid rgba(239,68,68,0.35);
          color: #fca5a5;
          padding: 10px 14px;
        }
        .result-hero {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 16px;
          flex-wrap: wrap;
        }
        .result-meta {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .result-title {
          display: inline-flex;
          align-items: center;
          gap: 10px;
          font-size: 22px;
          font-weight: 800;
        }
        .result-stats {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
        }
        .result-stats span {
          font-size: 12px;
          color: rgba(255,255,255,0.68);
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 999px;
          padding: 6px 10px;
        }
        .result-actions {
          display: flex;
          align-items: center;
          gap: 12px;
          flex-wrap: wrap;
        }
        .reset-btn {
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.1);
          color: rgba(255,255,255,0.72);
          padding: 12px 16px;
        }
      `}</style>
    </main>
  )
}
