import { useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle, Clock, FileText, Loader, RefreshCw } from 'lucide-react'

function StatusIcon({ status }) {
  if (status === 'done') return <CheckCircle size={14} />
  if (status === 'failed') return <AlertTriangle size={14} />
  if (status === 'running') return <Loader size={14} className="agent-spin" />
  return <Clock size={14} />
}

function renderValue(value) {
  if (value == null) return '—'
  if (typeof value === 'number' || typeof value === 'string') return String(value)
  const serialized = Array.isArray(value)
    ? JSON.stringify(value, null, 2)
    : JSON.stringify(value, null, 2)
  if (!serialized) return '—'
  if (serialized.length <= 2200) return serialized
  return `${serialized.slice(0, 2200)}\n...truncated`
}

function formatClock(ts) {
  if (!ts) return '—'
  const parsed = Number(ts)
  if (!Number.isFinite(parsed)) return '—'
  return new Date(parsed * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function formatDuration(start, end) {
  if (!start || !end) return '—'
  const seconds = Math.max(0, Number(end) - Number(start))
  if (!Number.isFinite(seconds)) return '—'
  return `${seconds.toFixed(1)}s`
}

function formatEventType(value) {
  if (!value) return 'event'
  return String(value).replace(/_/g, ' ')
}

function AgentCard({ agent, index, traceEvents = [] }) {
  const [showDetails, setShowDetails] = useState(false)
  const agentEvents = useMemo(
    () => (
      (traceEvents || [])
        .filter((event) => event.agent_key === agent.key)
        .sort((left, right) => Number(left.ts || 0) - Number(right.ts || 0))
        .slice(-20)
    ),
    [traceEvents, agent.key],
  )
  const duration = formatDuration(agent.started_at, agent.finished_at)

  return (
    <article className={`agent-card agent-card--${agent.status}`}>
      <div className="agent-card-top">
        <div className="agent-id">Agent {index + 1}</div>
        <div className={`agent-status agent-status--${agent.status}`}>
          <StatusIcon status={agent.status} />
          <span>{agent.status}</span>
        </div>
      </div>

      <h3 className="agent-name">{agent.name}</h3>
      <p className="agent-role">{agent.role}</p>

      {agent.llm_model && <div className="agent-model">Model: {agent.llm_model}</div>}

      <div className="agent-progress-track">
        <div className="agent-progress-fill" style={{ width: `${agent.progress || 0}%` }} />
      </div>

      <p className="agent-summary">{agent.summary || 'Waiting for work allocation.'}</p>

      <div className="agent-lifecycle-summary">
        <span>start: {formatClock(agent.started_at)}</span>
        <span>end: {formatClock(agent.finished_at)}</span>
        <span>duration: {duration}</span>
      </div>

      <div className="agent-card-actions">
        <button
          type="button"
          className="agent-inspect-btn"
          onClick={() => setShowDetails((value) => !value)}
        >
          {showDetails ? 'Hide how this worked' : 'How this worked'}
        </button>
        <span className="metric-chip">events: {agent.event_count || 0}</span>
      </div>

      {showDetails && (
        <div className="agent-detail-stack">
          {agent.current_input != null && (
            <div className="agent-output">
              <div className="agent-output-label">Input</div>
              <pre className="agent-output-value">{renderValue(agent.current_input)}</pre>
            </div>
          )}

          {agent.tools_used?.length > 0 && (
            <div className="agent-tools">
              {agent.tools_used.map((tool) => (
                <span key={`${agent.key}-${tool}`} className="metric-chip">tool: {tool}</span>
              ))}
            </div>
          )}

          {agent.decisions?.length > 0 && (
            <div className="agent-decisions">
              {agent.decisions.slice(-3).map((decision, idx) => (
                <div key={`${agent.key}-decision-${idx}`} className="agent-decision-item">{decision}</div>
              ))}
            </div>
          )}

          <div className="agent-metrics">
            {agent.retry_count > 0 && <span className="metric-chip"><RefreshCw size={11} /> Retry {agent.retry_count}</span>}
            {agent.branch && <span className="metric-chip">Branch: {agent.branch}</span>}
            {Object.entries(agent.metrics || {}).slice(0, 4).map(([key, value]) => (
              <span key={key} className="metric-chip">{key.replace(/_/g, ' ')}: {String(value)}</span>
            ))}
          </div>

          {agentEvents.length > 0 && (
            <div className="agent-output">
              <div className="agent-output-label">Lifecycle timeline</div>
              <div className="agent-trace-list">
                {agentEvents.map((event, idx) => (
                  <div key={`${agent.key}-trace-${event.ts}-${idx}`} className="agent-trace-item">
                    <strong>Step {idx + 1}: {formatEventType(event.event_type)}</strong>
                    <span>{event.message}</span>
                    <em>time: {formatClock(event.ts)}</em>
                    {event.tools?.length > 0 && <em>tools: {event.tools.join(', ')}</em>}
                    {event.decision && <em>decision: {event.decision}</em>}
                    {event.route_to && <em>route: {event.route_to}</em>}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="agent-outputs">
            {(agent.outputs || []).slice(-4).map((output, idx) => (
              <div key={idx} className="agent-output">
                <div className="agent-output-label">{output.label}</div>
                <pre className="agent-output-value">{renderValue(output.value)}</pre>
              </div>
            ))}
          </div>
        </div>
      )}
    </article>
  )
}

function TraceStream({ traceEvents = [] }) {
  if (!traceEvents?.length) return null
  return (
    <section className="activity-panel">
      <div className="activity-title">Trace events</div>
      <div className="activity-list">
        {traceEvents.slice(-14).reverse().map((event, index) => (
          <div key={`${event.ts}-${index}`} className="activity-item">
            <strong>{event.agent_name}</strong>
            <div>{event.event_type} - {event.message}</div>
            {event.decision && <div>decision: {event.decision}</div>}
            {event.route_to && <div>route: {event.route_to}</div>}
          </div>
        ))}
      </div>
    </section>
  )
}

function ExtractionPanel({ agents = [] }) {
  const extractionAgent = agents.find((agent) => agent.key === 'extraction')
  if (!extractionAgent) return null

  const outputs = extractionAgent.outputs || []
  const candidates = outputs.find((item) => item.label === 'Candidates')?.value || []
  const extractedPreview = outputs.find((item) => item.label === 'Extracted preview')?.value
  const attempts = outputs.find((item) => item.label === 'Extractor attempts')?.value || []

  return (
    <section className="review-panel">
      <div className="review-header">
        <div className="review-title">
          <FileText size={16} />
          <span>Extraction transparency</span>
        </div>
      </div>

      {extractedPreview && (
        <div className="review-note">
          <strong>Selected extraction preview:</strong> {String(extractedPreview).slice(0, 420)}
        </div>
      )}

      {!!candidates.length && (
        <div className="review-grid">
          {candidates.map((candidate, idx) => (
            <div key={`${candidate.method}-${idx}`} className="review-item">
              <div className="review-item-top">
                <strong>{candidate.method}</strong>
                <span>{candidate.status || 'accepted'} · {candidate.score || 0}</span>
              </div>
              <p>{candidate.reason || 'No reason provided.'}</p>
              {candidate.selector_used && <p><strong>Selector:</strong> {candidate.selector_used}</p>}
              {candidate.dom_tags?.length > 0 && (
                <div className="review-mini-list">
                  {candidate.dom_tags.map((tagName, tagIndex) => (
                    <span key={`${candidate.method}-tag-${tagIndex}`}>tag: {tagName}</span>
                  ))}
                </div>
              )}
              {candidate.extraction_signals?.length > 0 && (
                <div className="review-mini-list">
                  {candidate.extraction_signals.map((signal, signalIndex) => (
                    <span key={`${candidate.method}-signal-${signalIndex}`}>{signal}</span>
                  ))}
                </div>
              )}
              {candidate.preview_excerpt && <p><em>{candidate.preview_excerpt}</em></p>}
              {candidate.dropped_samples?.length > 0 && (
                <div className="review-mini-list">
                  {candidate.dropped_samples.map((sample, sidx) => (
                    <span key={`${candidate.method}-drop-${sidx}`}>{sample}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {!!attempts.length && (
        <div className="review-notes">
          {attempts.map((attempt, idx) => (
            <div key={`${attempt.method}-${idx}`} className="review-note">
              <strong>{attempt.method}</strong>: {attempt.status} · {attempt.reason}
              {attempt.selector_used && <div className="review-note-meta">selector: {attempt.selector_used}</div>}
              {attempt.dom_tags?.length > 0 && <div className="review-note-meta">tags: {attempt.dom_tags.join(', ')}</div>}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function ReviewPanel({ review }) {
  if (!review) return null
  return (
    <section className="review-panel">
      <div className="review-header">
        <div className="review-title">
          <FileText size={16} />
          <span>QA Review</span>
        </div>
        <div className={`review-badge ${review.passed ? 'review-badge--pass' : 'review-badge--fail'}`}>
          {review.passed ? 'Pass' : 'Needs Work'} · {review.overall_average}/5
        </div>
      </div>

      {review.score_explanation && (
        <div className="review-note">{review.score_explanation}</div>
      )}

      <div className="review-grid">
        {(review.criteria || []).map((criterion) => (
          <div key={criterion.key} className="review-item">
            <div className="review-item-top">
              <strong>{criterion.label}</strong>
              <span>{criterion.score}/5</span>
            </div>
            <p>{criterion.reason}</p>
            {!!criterion.evidence?.length && (
              <div className="review-mini-list">
                {criterion.evidence.map((line, idx) => (
                  <span key={`${criterion.key}-e-${idx}`}>{line}</span>
                ))}
              </div>
            )}
            {criterion.recommendation && <p><strong>Recommendation:</strong> {criterion.recommendation}</p>}
          </div>
        ))}
      </div>

      {!!review.segment_diagnostics?.length && (
        <div className="review-grid">
          {review.segment_diagnostics.map((segment) => (
            <div key={`diag-${segment.segment_id}`} className="review-item">
              <div className="review-item-top">
                <strong>Segment {segment.segment_id}: {segment.headline}</strong>
                <span>{segment.score}/5 · {segment.status}</span>
              </div>
              {!!segment.strengths?.length && (
                <p>Strengths: {segment.strengths.join(' | ')}</p>
              )}
              {!!segment.issues?.length && (
                <p>Issues: {segment.issues.join(' | ')}</p>
              )}
              {segment.recommendation && <p><strong>Action:</strong> {segment.recommendation}</p>}
            </div>
          ))}
        </div>
      )}

      {!!review.next_actions?.length && (
        <div className="review-notes">
          {review.next_actions.map((note, index) => (
            <div key={`next-${index}`} className="review-note">{note}</div>
          ))}
        </div>
      )}

      {review.notes?.length > 0 && (
        <div className="review-notes">
          {review.notes.map((note, index) => (
            <div key={index} className="review-note">{note}</div>
          ))}
        </div>
      )}
    </section>
  )
}

function WorkflowMap({ workflowOverview }) {
  if (!workflowOverview) return null

  return (
    <section className="workflow-map">
      <div className="workflow-map-title">Routing map</div>
      <div className="workflow-flow">
        {(workflowOverview.sequential_path || []).map((label) => (
          <div key={label} className="workflow-node">{label}</div>
        ))}
      </div>
      {workflowOverview.parallel_stage && (
        <div className="workflow-parallel">
          <strong>{workflowOverview.parallel_stage.label}</strong>
          <span>{workflowOverview.parallel_stage.tasks?.join(' + ')}</span>
        </div>
      )}
      {!!workflowOverview.conditional_edges?.length && (
        <div className="workflow-edges">
          {workflowOverview.conditional_edges.map((edge) => (
            <span key={edge} className="workflow-edge">{edge}</span>
          ))}
        </div>
      )}
    </section>
  )
}

export default function AgentWorkflowPanel({ agents = [], activityLog = [], traceEvents = [], review = null, workflowOverview = null, modelVerification = null }) {
  if (!agents.length && !activityLog.length && !traceEvents.length && !review && !workflowOverview) return null

  return (
    <section className="workflow-panel fade-up">
      <div className="workflow-header">
        <div>
          <p className="workflow-kicker">Visible orchestration</p>
          <h2>Agent Workflow</h2>
        </div>
        <p className="workflow-sub">Extraction, editorial, packaging, QA, and video generation are surfaced so the client can inspect the work, not just the final answer.</p>
      </div>

      {modelVerification?.selected_model && (
        <section className="workflow-map">
          <div className="workflow-map-title">Model verification</div>
          <div className="workflow-parallel">
            <strong>Configured:</strong> <span>{modelVerification.configured_model}</span>
          </div>
          <div className="workflow-parallel">
            <strong>Selected:</strong> <span>{modelVerification.selected_model}</span>
          </div>
          <div className="workflow-parallel">
            <strong>Status:</strong> <span>{modelVerification.verification_ok ? 'Verified' : 'Fallback mode'}</span>
          </div>
          {modelVerification.note && <div className="workflow-parallel"><span>{modelVerification.note}</span></div>}
        </section>
      )}

      <WorkflowMap workflowOverview={workflowOverview} />

      <div className="agent-grid">
        {agents.map((agent, index) => (
          <AgentCard key={agent.key} agent={agent} index={index} traceEvents={traceEvents} />
        ))}
      </div>

      <div className="workflow-bottom">
        <ExtractionPanel agents={agents} />
        <div className="activity-panel">
          <div className="activity-title">Live activity log</div>
          <div className="activity-list">
            {activityLog.slice(-10).reverse().map((item, index) => (
              <div key={`${item}-${index}`} className="activity-item">{item}</div>
            ))}
          </div>
        </div>
        <TraceStream traceEvents={traceEvents} />
        <ReviewPanel review={review} />
      </div>

      <style>{`
        .workflow-panel {
          display: flex;
          flex-direction: column;
          gap: 20px;
        }
        .workflow-header {
          display: flex;
          align-items: end;
          justify-content: space-between;
          gap: 16px;
          flex-wrap: wrap;
        }
        .workflow-kicker {
          font-size: 11px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.42);
          margin-bottom: 6px;
        }
        .workflow-header h2 {
          font-size: 24px;
          line-height: 1.1;
        }
        .workflow-sub {
          max-width: 540px;
          color: rgba(255,255,255,0.55);
          font-size: 13px;
          line-height: 1.7;
        }
        .agent-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 14px;
        }
        .workflow-map {
          display: flex;
          flex-direction: column;
          gap: 10px;
          padding: 16px 18px;
          border-radius: 20px;
          background: rgba(7,11,20,0.88);
          border: 1px solid rgba(255,255,255,0.08);
        }
        .workflow-map-title {
          font-size: 11px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.38);
        }
        .workflow-flow {
          display: flex;
          gap: 10px;
          flex-wrap: wrap;
        }
        .workflow-node {
          font-size: 12px;
          color: rgba(255,255,255,0.82);
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 999px;
          padding: 7px 10px;
        }
        .workflow-parallel {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: center;
          font-size: 12px;
          color: rgba(255,255,255,0.68);
        }
        .workflow-edges {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .workflow-edge {
          font-size: 11px;
          color: #bfdbfe;
          background: rgba(59,130,246,0.1);
          border: 1px solid rgba(59,130,246,0.2);
          border-radius: 999px;
          padding: 5px 8px;
        }
        .agent-card {
          background: linear-gradient(180deg, rgba(13, 18, 32, 0.92), rgba(8, 12, 22, 0.92));
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          padding: 18px;
          display: flex;
          flex-direction: column;
          gap: 12px;
          box-shadow: 0 14px 40px rgba(0,0,0,0.22);
        }
        .agent-card--running { border-color: rgba(59,130,246,0.5); }
        .agent-card--done { border-color: rgba(16,185,129,0.4); }
        .agent-card-top {
          display: flex;
          justify-content: space-between;
          gap: 10px;
          align-items: center;
        }
        .agent-id {
          font-size: 10px;
          letter-spacing: 0.16em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.35);
        }
        .agent-status {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 11px;
          text-transform: capitalize;
          padding: 6px 10px;
          border-radius: 999px;
          border: 1px solid rgba(255,255,255,0.12);
          color: rgba(255,255,255,0.72);
        }
        .agent-status--running {
          border-color: rgba(59,130,246,0.45);
          color: #93c5fd;
          background: rgba(59,130,246,0.12);
        }
        .agent-status--done {
          border-color: rgba(16,185,129,0.45);
          color: #6ee7b7;
          background: rgba(16,185,129,0.12);
        }
        .agent-status--failed {
          border-color: rgba(239,68,68,0.45);
          color: #fca5a5;
          background: rgba(239,68,68,0.12);
        }
        .agent-name {
          font-size: 18px;
          line-height: 1.3;
        }
        .agent-role {
          font-size: 13px;
          line-height: 1.7;
          color: rgba(255,255,255,0.52);
        }
        .agent-progress-track {
          height: 6px;
          border-radius: 999px;
          overflow: hidden;
          background: rgba(255,255,255,0.07);
        }
        .agent-progress-fill {
          height: 100%;
          background: linear-gradient(90deg, #38bdf8, #6366f1);
          border-radius: 999px;
        }
        .agent-summary {
          font-size: 13px;
          line-height: 1.6;
          color: rgba(255,255,255,0.78);
        }
        .agent-card-actions {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }
        .agent-lifecycle-summary {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .agent-lifecycle-summary span {
          font-size: 11px;
          color: rgba(255,255,255,0.62);
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 999px;
          padding: 4px 8px;
        }
        .agent-inspect-btn {
          border-radius: 999px;
          border: 1px solid rgba(255,255,255,0.14);
          background: rgba(255,255,255,0.04);
          color: rgba(255,255,255,0.86);
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.02em;
          padding: 7px 10px;
          cursor: pointer;
          transition: all var(--transition-fast);
        }
        .agent-inspect-btn:hover {
          border-color: rgba(59,130,246,0.42);
          background: rgba(59,130,246,0.14);
          color: #dbeafe;
        }
        .agent-inspect-btn:focus-visible {
          outline: 2px solid rgba(59,130,246,0.6);
          outline-offset: 2px;
        }
        .agent-detail-stack {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .agent-model {
          display: inline-flex;
          width: fit-content;
          font-size: 11px;
          color: #bfdbfe;
          background: rgba(59,130,246,0.1);
          border: 1px solid rgba(59,130,246,0.24);
          border-radius: 999px;
          padding: 4px 8px;
        }
        .agent-tools,
        .agent-decisions {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .agent-decision-item {
          font-size: 11px;
          line-height: 1.6;
          color: rgba(255,255,255,0.74);
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 10px;
          padding: 6px 8px;
        }
        .agent-metrics {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .metric-chip {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          font-size: 11px;
          color: rgba(255,255,255,0.62);
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 999px;
          padding: 5px 9px;
        }
        .agent-outputs {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .agent-output {
          background: rgba(255,255,255,0.04);
          border-radius: 14px;
          border: 1px solid rgba(255,255,255,0.06);
          padding: 10px 12px;
        }
        .agent-output-label {
          font-size: 10px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.35);
          margin-bottom: 6px;
        }
        .agent-output-value {
          margin: 0;
          white-space: pre-wrap;
          word-break: break-word;
          font-size: 11px;
          line-height: 1.6;
          color: rgba(255,255,255,0.82);
          font-family: var(--font-mono);
        }
        .agent-trace-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .agent-trace-item {
          display: flex;
          flex-direction: column;
          gap: 3px;
          padding: 10px;
          border-radius: 10px;
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.06);
        }
        .agent-trace-item strong {
          font-size: 11px;
          color: #93c5fd;
          text-transform: uppercase;
          letter-spacing: 0.06em;
        }
        .agent-trace-item span {
          font-size: 12px;
          line-height: 1.55;
          color: rgba(255,255,255,0.8);
        }
        .agent-trace-item em {
          font-size: 11px;
          color: rgba(255,255,255,0.56);
          font-style: normal;
        }
        .workflow-bottom {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
          gap: 16px;
        }
        .activity-panel,
        .review-panel {
          background: rgba(10, 14, 24, 0.88);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          padding: 18px;
        }
        .activity-title,
        .review-title {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 14px;
          font-weight: 700;
          margin-bottom: 12px;
        }
        .activity-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          max-height: 320px;
          overflow: auto;
        }
        .activity-item {
          font-size: 12px;
          line-height: 1.6;
          color: rgba(255,255,255,0.7);
          padding: 8px 10px;
          border-radius: 12px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.05);
        }
        .review-header {
          display: flex;
          justify-content: space-between;
          gap: 10px;
          align-items: center;
          margin-bottom: 14px;
        }
        .review-badge {
          font-size: 12px;
          font-weight: 700;
          padding: 7px 10px;
          border-radius: 999px;
        }
        .review-badge--pass {
          background: rgba(16,185,129,0.14);
          color: #6ee7b7;
          border: 1px solid rgba(16,185,129,0.35);
        }
        .review-badge--fail {
          background: rgba(245,158,11,0.12);
          color: #fcd34d;
          border: 1px solid rgba(245,158,11,0.35);
        }
        .review-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: 10px;
        }
        .review-item {
          border-radius: 14px;
          padding: 12px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.05);
        }
        .review-item-top {
          display: flex;
          justify-content: space-between;
          gap: 10px;
          margin-bottom: 8px;
          font-size: 12px;
        }
        .review-item p {
          font-size: 12px;
          line-height: 1.6;
          color: rgba(255,255,255,0.62);
        }
        .review-mini-list {
          display: flex;
          flex-direction: column;
          gap: 6px;
          margin-top: 8px;
        }
        .review-mini-list span {
          font-size: 11px;
          color: rgba(255,255,255,0.72);
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 10px;
          padding: 6px 8px;
        }
        .review-notes {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-top: 12px;
        }
        .review-note {
          font-size: 12px;
          color: rgba(255,255,255,0.74);
          padding: 10px 12px;
          border-radius: 12px;
          background: rgba(245,158,11,0.07);
          border: 1px solid rgba(245,158,11,0.18);
        }
        .review-note-meta {
          margin-top: 6px;
          color: rgba(255,255,255,0.58);
          font-size: 11px;
        }
        .agent-spin { animation: spin 1s linear infinite; }
        @media (max-width: 900px) {
          .agent-grid {
            grid-template-columns: 1fr;
          }
          .workflow-bottom {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </section>
  )
}
