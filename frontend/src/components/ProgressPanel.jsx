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

export default function ProgressPanel({ progress, message, status }) {
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
        .steps {
          display: grid; grid-template-columns: 1fr 1fr 1fr;
          gap: 10px;
        }
        @media (max-width: 640px) { .steps { grid-template-columns: 1fr 1fr; } }
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
