import { useEffect, useState } from 'react'
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
  const [scriptViewRequest, setScriptViewRequest] = useState('screenplay')
  const [pendingScriptScroll, setPendingScriptScroll] = useState('')
  const {
    articleUrl,
    previewVideoUrl,
    jobId,
    status,
    progress,
    message,
    result,
    error,
    agents,
    activityLog,
    traceEvents,
    runtimeLogs,
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
  const sourceUrl = script?.article_url || articleUrl
  const visibleReview = script?.review || review
  const activeSegment =
    script?.segments?.find((segment) => currentTime >= segment.start_time && currentTime <= segment.end_time) ||
    script?.segments?.[0] ||
    null

  useEffect(() => {
    if (isDone) {
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [isDone, jobId])

  useEffect(() => {
    if (!pendingScriptScroll || !isDone) return

    const blockId = pendingScriptScroll === 'json' ? 'script-json-block' : 'script-screenplay-block'
    const sectionId = 'script-preview-section'

    const timer = window.setTimeout(() => {
      const target = document.getElementById(blockId)
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' })
      } else {
        const section = document.getElementById(sectionId)
        section?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
      setPendingScriptScroll('')
    }, 90)

    return () => window.clearTimeout(timer)
  }, [pendingScriptScroll, isDone, scriptViewRequest, result])

  function jumpToScript(view) {
    setScriptViewRequest(view)
    setPendingScriptScroll(view)
  }

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
              activityLog={activityLog}
              traceEvents={traceEvents}
              runtimeLogs={runtimeLogs}
              articleUrl={articleUrl}
              jobId={jobId}
            />
          </section>
          <AgentWorkflowPanel
            agents={agents}
            activityLog={activityLog}
            traceEvents={traceEvents}
            runtimeLogs={runtimeLogs}
            review={visibleReview}
            workflowOverview={workflowOverview}
            modelVerification={modelVerification}
          />
          {previewVideoUrl && (
            <section className="fade-up fade-up-delay-1">
              <div className="processing-preview-note">
                Video render is complete. Running final render QA checks before packaging finishes.
              </div>
              <VideoPlayer
                videoUrl={previewVideoUrl}
                title="In-progress broadcast preview"
                onProgress={(time) => setCurrentTime(time)}
                llmEnhanced={Boolean(modelVerification?.selected_model)}
              />
            </section>
          )}
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
                {sourceUrl && <span className="result-url-chip">Source URL visible below</span>}
              </div>
              {sourceUrl && (
                <div className="result-source-line">
                  <strong>Source URL:</strong>{' '}
                  <a href={sourceUrl} target="_blank" rel="noreferrer">{sourceUrl}</a>
                </div>
              )}
              {vidUrl && (
                <div className="result-source-line">
                  <strong>Video URL:</strong>{' '}
                  <a href={vidUrl} target="_blank" rel="noreferrer">{vidUrl}</a>
                </div>
              )}
            </div>
            <div className="result-actions">
              {vidUrl && <DownloadButton videoUrl={vidUrl} jobId={jobId} />}
              <button className="quick-view-btn" onClick={() => jumpToScript('screenplay')}>
                Screenplay
              </button>
              <button className="quick-view-btn" onClick={() => jumpToScript('json')}>
                JSON
              </button>
              <button className="reset-btn" onClick={reset}>
                <RefreshCw size={15} /> New run
              </button>
            </div>
          </div>

          {script && (
            <section id="script-preview-section" className="fade-up fade-up-delay-1">
              <ScriptPreview script={script} requestedView={scriptViewRequest} />
            </section>
          )}

          <AgentWorkflowPanel
            agents={result.agents || agents}
            activityLog={result.activity_log || activityLog}
            traceEvents={result.trace_events || traceEvents}
            runtimeLogs={result.runtime_logs || runtimeLogs}
            review={visibleReview}
            workflowOverview={script?.workflow_overview || workflowOverview}
            modelVerification={script?.model_verification || result.model_verification || modelVerification}
          />

          {vidUrl && (
            <section className="fade-up fade-up-delay-1">
              <VideoPlayer
                videoUrl={vidUrl}
                title={script?.overall_headline || 'Algsoch News Broadcast'}
                script={script}
                activeSegment={activeSegment}
                onProgress={(time) => setCurrentTime(time)}
                llmEnhanced={Boolean(script?.llm_enhanced)}
              />
            </section>
          )}

          {script && (
            <section className="production-suite fade-up fade-up-delay-1">
              <LiveControlRoom script={script} currentTime={currentTime} />
              {script?.segments && (
                <TimelineView
                  segments={script.segments}
                  totalDuration={script.total_duration}
                  currentTime={currentTime}
                />
              )}
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
        .result-url-chip {
          border-color: rgba(59,130,246,0.34) !important;
          background: rgba(59,130,246,0.12) !important;
          color: #bfdbfe !important;
        }
        .result-source-line {
          margin-top: 2px;
          font-size: 12px;
          line-height: 1.6;
          color: rgba(255,255,255,0.72);
          overflow-wrap: anywhere;
        }
        .result-source-line a {
          color: #93c5fd;
          text-decoration: underline;
        }
        .result-actions {
          display: flex;
          align-items: center;
          gap: 12px;
          flex-wrap: wrap;
        }
        .production-suite {
          display: flex;
          flex-direction: column;
          gap: 24px;
        }
        .processing-preview-note {
          margin: 0 0 10px;
          border-radius: 12px;
          border: 1px solid rgba(59,130,246,0.25);
          background: rgba(59,130,246,0.1);
          color: #dbeafe;
          font-size: 12px;
          line-height: 1.6;
          padding: 10px 12px;
        }
        .quick-view-btn,
        .reset-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border-radius: 999px;
          cursor: pointer;
          font-weight: 700;
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.1);
          color: rgba(255,255,255,0.72);
          padding: 12px 16px;
        }
        .quick-view-btn {
          min-width: 116px;
          background: linear-gradient(135deg, rgba(59,130,246,0.24), rgba(37,99,235,0.16));
          border-color: rgba(59,130,246,0.4);
          color: #dbeafe;
        }
        .quick-view-btn:hover {
          background: linear-gradient(135deg, rgba(59,130,246,0.36), rgba(37,99,235,0.22));
          border-color: rgba(59,130,246,0.58);
        }
        @media (max-width: 720px) {
          .result-actions {
            width: 100%;
          }
          .quick-view-btn,
          .reset-btn {
            flex: 1;
            min-width: 0;
          }
        }
      `}</style>
    </main>
  )
}
