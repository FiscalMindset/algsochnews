// components/ProgressPanel.jsx
import { CheckCircle, XCircle, Loader } from 'lucide-react'

const STEPS = [
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

export default function ProgressPanel({ progress, message, status, agents = [], workflowOverview = null }) {
  return (
    <div className="prog-panel glass fade-up">
      <div className="prog-header">
        <div className="prog-title">
          {status === 'failed'
            ? <><XCircle size={16} className="prog-icon-err" /> Processing Failed</>
            : status === 'done'
            ? <><CheckCircle size={16} className="prog-icon-ok" /> Complete!</>
            : <><span className="spinner" /> Generating your video…</>
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

      <AgentRail agents={agents} />

      {workflowOverview?.parallel_stage && (
        <div className="workflow-note">
          <strong>{workflowOverview.parallel_stage.label}:</strong> {workflowOverview.parallel_stage.tasks?.join(' + ')}
        </div>
      )}

      <div className="steps">
        {STEPS.map((step, i) => {
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
          grid-template-columns: repeat(4, minmax(0, 1fr));
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
