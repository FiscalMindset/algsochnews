// components/ProgressPanel.jsx
import { CheckCircle, XCircle, Loader } from 'lucide-react'
import { buildExecutionConsoleLines, formatClock, retrySummary } from './consoleUtils'

const STEPS_FULL_VIDEO = [
  { label: 'Extracting article',   minPct: 5  },
  { label: 'Segmenting content',   minPct: 15 },
  { label: 'Generating headlines', minPct: 25 },
  { label: 'Writing narrations',   minPct: 35 },
  { label: 'QA & scoring',         minPct: 44 },
  { label: 'Planning visuals',     minPct: 55 },
  { label: 'Synthesizing audio',   minPct: 65 },
  { label: 'Rendering video',      minPct: 78 },
  { label: 'Finalizing output',    minPct: 92 },
]

const STEPS_EDITORIAL_ONLY = [
  { label: 'Extracting article',            minPct: 5  },
  { label: 'Segmenting content',            minPct: 15 },
  { label: 'Generating headlines',          minPct: 25 },
  { label: 'Writing narrations',            minPct: 35 },
  { label: 'QA & scoring',                  minPct: 44 },
  { label: 'Planning visuals',              minPct: 55 },
  { label: 'Finalizing editorial package',  minPct: 82 },
]

function stepStatus(step, progress, status) {
  if (status === 'done') return 'done'
  if (status === 'failed') return progress > step.minPct ? 'done' : 'idle'
  if (progress >= step.minPct + 10) return 'done'
  if (progress >= step.minPct) return 'active'
  return 'idle'
}

function AgentRail({ agents = [] }) {
  if (!agents.length) return null

  return (
    <div className="agent-rail">
      {agents.map((agent) => (
        <div key={agent.key} className={`agent-rail-card agent-rail-card--${agent.status}`}>
          <div className="agent-rail-name">{agent.name}</div>
          <div className="agent-rail-meta">
            <span>{agent.status}</span>
            <strong>{agent.progress || 0}%</strong>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function ProgressPanel({
  progress,
  message,
  status,
  backendStatus = 'unknown',
  backendStatusMessage = '',
  agents = [],
  workflowOverview = null,
  modelVerification = null,
  activityLog = [],
  traceEvents = [],
  runtimeLogs = [],
  articleUrl = '',
  jobId = null,
}) {
  const consoleLines = buildExecutionConsoleLines(activityLog, traceEvents, runtimeLogs)
  const {
    retryCount,
    retryEvents,
    reviewDecision,
    qaAverage,
    qaPassed,
  } = retrySummary(traceEvents, agents)
  const headerTitle =
    status === 'failed'
      ? 'Processing Failed'
      : status === 'done'
        ? 'Complete!'
        : message || 'Running LangGraph pipeline...'

  const backendToneClass = {
    online: 'backend-note--online',
    checking: 'backend-note--checking',
    degraded: 'backend-note--degraded',
    offline: 'backend-note--offline',
    unknown: 'backend-note--unknown',
  }[backendStatus] || 'backend-note--unknown'

  const activeSteps = workflowOverview?.video_required === false
    ? STEPS_EDITORIAL_ONLY
    : STEPS_FULL_VIDEO

  return (
    <div className="prog-panel glass fade-up">
      <div className="prog-header">
        <div className="prog-title">
          {status === 'failed'
            ? <><XCircle size={16} className="prog-icon-err" /> {headerTitle}</>
            : status === 'done'
            ? <><CheckCircle size={16} className="prog-icon-ok" /> {headerTitle}</>
            : <><span className="spinner" /> {headerTitle}</>
          }
        </div>
        <span className="prog-pct">{progress}%</span>
      </div>

      <div className="progress-bar-wrap">
        <div
          className="progress-bar-fill"
          style={{ width: `${progress}%` }}
        />
      </div>

      <p className="prog-message">{message}</p>

      <div className={`backend-note ${backendToneClass}`}>
        <strong>Backend:</strong> {backendStatus} {backendStatusMessage ? `| ${backendStatusMessage}` : ''}
      </div>

      {(articleUrl || jobId) && (
        <div className="workflow-note">
          {articleUrl && <div><strong>Source URL:</strong> <span className="mono-break">{articleUrl}</span></div>}
          {jobId && <div><strong>Job ID:</strong> <span className="mono-break">{jobId}</span></div>}
        </div>
      )}

      <AgentRail agents={agents} />

      {workflowOverview?.parallel_stage && (
        <div className="workflow-note">
          <strong>{workflowOverview.parallel_stage.label}:</strong> {workflowOverview.parallel_stage.tasks?.join(' + ')}
        </div>
      )}

      {modelVerification?.selected_model && (
        <div className="workflow-note">
          <strong>Model:</strong> {modelVerification.selected_model}
          {modelVerification.upgraded ? ' (auto-upgraded from configured model)' : ''}
        </div>
      )}

      {(retryCount > 0 || retryEvents.length > 0 || reviewDecision || status === 'processing') && (
        <div className="workflow-note">
          <strong>Retry visibility:</strong> retries={retryCount}
          {reviewDecision && (
            <div className="retry-lines">
              <div>
                decision={reviewDecision}
                {qaAverage != null ? ` | qa=${Number(qaAverage).toFixed(2)}` : ''}
                {qaPassed != null ? ` | passed=${String(qaPassed)}` : ''}
              </div>
              {retryCount === 0 && reviewDecision === 'finalize' && (
                <div>No retry executed: QA finalized this run on first pass.</div>
              )}
            </div>
          )}
          {!reviewDecision && status === 'processing' && (
            <div className="retry-lines">
              <div>QA decision pending...</div>
            </div>
          )}
          {retryEvents.length > 0 && (
            <div className="retry-lines">
              {retryEvents.slice(-8).map((event, idx) => (
                <div key={`retry-${idx}-${event.ts}`}>{formatClock(event.ts)} {event.agent_name || event.agent_key}: {event.decision || event.route_to}</div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="console-panel">
        <div className="console-title">Execution console</div>
        <div className="console-body">
          {consoleLines.length ? (
            consoleLines.map((line) => (
              <div key={line.key} className={`console-line console-line--${line.kind}`}>{line.text}</div>
            ))
          ) : (
            <div className="console-line">Waiting for first event...</div>
          )}
        </div>
      </div>

      <div className="steps">
        {activeSteps.map((step, i) => {
          const st = stepStatus(step, progress, status)
          return (
            <div key={i} className={`step step--${st}`}>
              <div className="step-dot">
                {st === 'done'   && <CheckCircle size={12} />}
                {st === 'active' && <Loader size={12} className="step-spin" />}
              </div>
              <span className="step-label">{step.label}</span>
            </div>
          )
        })}
      </div>

      <style>{`
        .prog-panel {
          border-radius: var(--radius-lg);
          padding: 24px 28px;
          display: flex; flex-direction: column; gap: 18px;
        }
        .prog-header {
          display: flex; align-items: center; justify-content: space-between;
        }
        .prog-title {
          display: flex; align-items: center; gap: 10px;
          font-size: 15px; font-weight: 600;
        }
        .prog-icon-ok { color: var(--accent-green); }
        .prog-icon-err { color: var(--accent-red); }
        .prog-pct {
          font-family: var(--font-mono); font-size: 22px;
          font-weight: 700; color: var(--accent-blue);
        }
        .prog-message {
          font-size: 13px; color: rgba(255,255,255,0.5);
          font-style: italic; min-height: 18px;
        }
        .agent-rail {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
          gap: 10px;
        }
        .agent-rail-card {
          padding: 12px;
          border-radius: 14px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .agent-rail-card--running {
          border-color: rgba(59,130,246,0.34);
          background: rgba(59,130,246,0.08);
        }
        .agent-rail-card--done {
          border-color: rgba(16,185,129,0.28);
          background: rgba(16,185,129,0.08);
        }
        .agent-rail-name {
          font-size: 11px;
          line-height: 1.5;
          color: rgba(255,255,255,0.82);
        }
        .agent-rail-meta {
          display: flex;
          justify-content: space-between;
          gap: 10px;
          font-size: 11px;
          color: rgba(255,255,255,0.46);
        }
        .workflow-note {
          border-radius: 14px;
          padding: 12px 14px;
          background: rgba(59,130,246,0.08);
          border: 1px solid rgba(59,130,246,0.16);
          font-size: 12px;
          line-height: 1.6;
          color: rgba(219,234,254,0.88);
        }
        .backend-note {
          border-radius: 12px;
          padding: 10px 12px;
          border: 1px solid rgba(148,163,184,0.32);
          background: rgba(148,163,184,0.1);
          font-size: 12px;
          line-height: 1.6;
          color: rgba(226,232,240,0.92);
          overflow-wrap: anywhere;
        }
        .backend-note--online {
          border-color: rgba(16,185,129,0.34);
          background: rgba(16,185,129,0.1);
          color: #bbf7d0;
        }
        .backend-note--checking {
          border-color: rgba(59,130,246,0.34);
          background: rgba(59,130,246,0.1);
          color: #dbeafe;
        }
        .backend-note--degraded {
          border-color: rgba(245,158,11,0.34);
          background: rgba(245,158,11,0.12);
          color: #fde68a;
        }
        .backend-note--offline {
          border-color: rgba(239,68,68,0.34);
          background: rgba(239,68,68,0.12);
          color: #fecaca;
        }
        .backend-note--unknown {
          border-color: rgba(148,163,184,0.32);
          background: rgba(148,163,184,0.1);
          color: rgba(226,232,240,0.92);
        }
        .mono-break {
          font-family: var(--font-mono);
          overflow-wrap: anywhere;
        }
        .retry-lines {
          margin-top: 8px;
          display: flex;
          flex-direction: column;
          gap: 4px;
          font-family: var(--font-mono);
          font-size: 11px;
          color: rgba(255,255,255,0.86);
        }
        .console-panel {
          border-radius: 14px;
          border: 1px solid rgba(255,255,255,0.14);
          background: rgba(2, 6, 14, 0.88);
          overflow: hidden;
        }
        .console-title {
          padding: 10px 12px;
          font-size: 11px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.55);
          background: rgba(255,255,255,0.04);
          border-bottom: 1px solid rgba(255,255,255,0.08);
        }
        .console-body {
          max-height: 260px;
          overflow: auto;
          padding: 10px 12px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .console-line {
          font-family: var(--font-mono);
          font-size: 11px;
          line-height: 1.5;
          color: rgba(255,255,255,0.78);
          white-space: pre-wrap;
          overflow-wrap: anywhere;
        }
        .console-line--trace {
          color: #bfdbfe;
        }
        .console-line--graph {
          color: #fde68a;
        }
        .console-line--graph-route {
          color: #fcd34d;
        }
        .console-line--trace-payload {
          color: #dbeafe;
        }
        .console-line--activity {
          color: rgba(165, 180, 252, 0.92);
        }
        .console-line--runtime-info,
        .console-line--runtime-main {
          color: rgba(220, 252, 231, 0.9);
        }
        .console-line--runtime-http {
          color: rgba(148, 163, 184, 0.8);
        }
        .console-line--runtime-debug {
          color: rgba(134, 239, 172, 0.88);
        }
        .console-line--runtime-warn {
          color: #fde68a;
        }
        .console-line--runtime-error {
          color: #fca5a5;
        }
        .console-line--runtime-scraper {
          color: #fcd34d;
        }
        .console-line--runtime-segmenter {
          color: #c4b5fd;
        }
        .console-line--runtime-narration {
          color: #93c5fd;
        }
        .console-line--runtime-qa {
          color: #fdba74;
        }
        .console-line--runtime-tts {
          color: #86efac;
        }
        .console-line--runtime-video,
        .console-line--runtime-html {
          color: rgba(220, 252, 231, 0.88);
        }
        .steps {
          display: grid; grid-template-columns: 1fr 1fr 1fr;
          gap: 10px;
        }
        @media (max-width: 840px) {
          .agent-rail {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }
        @media (max-width: 640px) {
          .steps { grid-template-columns: 1fr 1fr; }
          .agent-rail {
            grid-template-columns: 1fr;
          }
        }
        .step {
          display: flex; align-items: center; gap: 8px;
          font-size: 12px; color: rgba(255,255,255,0.3);
          transition: color var(--transition-base);
        }
        .step--done  { color: var(--accent-green); }
        .step--active { color: var(--accent-blue); }
        .step-dot {
          width: 20px; height: 20px; border-radius: 50%; flex-shrink: 0;
          display: flex; align-items: center; justify-content: center;
          border: 1px solid currentColor;
          background: rgba(255,255,255,0.04);
        }
        .step--done .step-dot {
          background: rgba(16,185,129,0.15); border-color: var(--accent-green);
        }
        .step--active .step-dot {
          background: rgba(59,130,246,0.15); border-color: var(--accent-blue);
        }
        .step-spin { animation: spin 1s linear infinite; }
        .step-label { flex: 1; }
      `}</style>
    </div>
  )
}
