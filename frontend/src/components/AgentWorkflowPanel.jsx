import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle, Clock, Download, FileText, Loader, RefreshCw } from 'lucide-react'
import { buildExecutionConsoleLines, formatClock, retrySummary } from './consoleUtils'

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
  return serialized
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

function compactJson(value, maxLen = 420) {
  if (value == null) return ''
  if (Array.isArray(value) && value.length === 0) return ''
  if (typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0) return ''
  let text = ''
  try {
    text = typeof value === 'string' ? value : JSON.stringify(value)
  } catch {
    text = String(value)
  }
  if (!text) return ''
  if (text.length <= maxLen) return text
  return `${text.slice(0, maxLen)}...`
}

function formatStepDelta(currentTs, previousTs) {
  if (currentTs == null || previousTs == null) return 'n/a'
  const current = Number(currentTs)
  const previous = Number(previousTs)
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return 'n/a'
  return `${Math.max(0, current - previous).toFixed(1)}s`
}

function formatStepDeltaSeconds(currentTs, previousTs) {
  if (currentTs == null || previousTs == null) return null
  const current = Number(currentTs)
  const previous = Number(previousTs)
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return null
  return Number(Math.max(0, current - previous).toFixed(3))
}

function sanitizeFilePart(value) {
  return String(value || 'agent')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48)
}

function timestampSlug() {
  return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
}

function sortedEventsForAgent(traceEvents, agentKey) {
  return (traceEvents || [])
    .filter((event) => event.agent_key === agentKey)
    .sort((left, right) => Number(left.ts || 0) - Number(right.ts || 0))
}

function buildTimelineRows(agentEvents) {
  return (agentEvents || []).map((event, idx) => {
    const previousTs = idx > 0 ? agentEvents[idx - 1].ts : null
    return {
      step: idx + 1,
      ts: event.ts || null,
      time: formatClock(event.ts),
      delta_seconds_from_previous: formatStepDeltaSeconds(event.ts, previousTs),
      event_type: event.event_type || '',
      message: event.message || '',
      tools: event.tools || [],
      decision: event.decision || null,
      route_to: event.route_to || null,
      input_payload: event.input_payload ?? null,
      output_payload: event.output_payload ?? null,
      metrics: event.metrics || {},
    }
  })
}

function buildAgentAudit(agent, agentEvents) {
  return {
    key: agent.key,
    name: agent.name,
    role: agent.role,
    status: agent.status,
    progress: Number(agent.progress || 0),
    llm_model: agent.llm_model || null,
    retry_count: Number(agent.retry_count || 0),
    node_visits: Number(agent.node_visits || 0),
    event_count: Number(agent.event_count || 0),
    started_at: agent.started_at || null,
    finished_at: agent.finished_at || null,
    summary: agent.summary || '',
    branch: agent.branch || null,
    current_input: agent.current_input ?? null,
    tools_used: agent.tools_used || [],
    decisions: agent.decisions || [],
    metrics: agent.metrics || {},
    outputs: agent.outputs || [],
    timeline: buildTimelineRows(agentEvents),
  }
}

function downloadAgentAudit(agent, agentEvents) {
  const audit = {
    generated_at: new Date().toISOString(),
    agent: buildAgentAudit(agent, agentEvents),
  }

  const blob = new Blob([JSON.stringify(audit, null, 2)], { type: 'application/json' })
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = `agent-audit-${sanitizeFilePart(agent.key)}-${timestampSlug()}.json`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(href)
}

function downloadAllAgentsAudit(agents, traceEvents, workflowOverview, modelVerification, review) {
  const payload = {
    generated_at: new Date().toISOString(),
    workflow_overview: workflowOverview || {},
    model_verification: modelVerification || null,
    review: review || null,
    agent_count: (agents || []).length,
    agents: (agents || []).map((agent) => {
      const events = sortedEventsForAgent(traceEvents, agent.key)
      return buildAgentAudit(agent, events)
    }),
  }

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = `all-agents-audit-${timestampSlug()}.json`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(href)
}

function complianceCheck(key, label, passed, detail, status = '') {
  const resolvedStatus = status || (passed ? 'pass' : 'fail')
  return {
    key,
    label,
    passed: Boolean(passed),
    status: resolvedStatus,
    detail,
  }
}

function deriveComplianceReport(workflowOverview, review, agents) {
  const backendReport = workflowOverview?.compliance_report
  if (backendReport?.checks?.length) return backendReport

  const sequentialPath = workflowOverview?.sequential_path || []
  const parallelTasks = workflowOverview?.parallel_stage?.tasks || []
  const conditionalEdges = workflowOverview?.conditional_edges || []
  const hardFailures = review?.hard_failures || []
  const qaAverage = Number(review?.overall_average || 0)

  const checks = [
    complianceCheck(
      'langgraph_workflow',
      'LangGraph workflow',
      workflowOverview?.engine === 'langgraph',
      `engine=${workflowOverview?.engine || 'n/a'}`,
    ),
    complianceCheck(
      'sequential_flow',
      'Sequential flow',
      sequentialPath.length >= 4,
      `steps=${sequentialPath.length}`,
    ),
    complianceCheck(
      'parallel_step',
      'Parallel stage',
      parallelTasks.length >= 2,
      `tasks=${parallelTasks.length}`,
    ),
    complianceCheck(
      'conditional_edges',
      'Conditional routing',
      conditionalEdges.length >= 3,
      `edges=${conditionalEdges.length}`,
    ),
    complianceCheck(
      'qa_gate',
      'QA gate (avg>=4)',
      review ? review.passed && qaAverage >= 4 && hardFailures.length === 0 : false,
      review
        ? `avg=${qaAverage.toFixed(2)}; hard_failures=${hardFailures.length}`
        : 'Waiting for QA review',
      review ? '' : 'pending',
    ),
    complianceCheck(
      'targeted_retry',
      'Targeted retry readiness',
      Array.isArray(review?.weak_segments) || (agents || []).length > 0,
      review
        ? `weak_segments=${review?.weak_segments?.length || 0}`
        : 'Tracking weak segments once QA runs',
      review ? '' : 'pending',
    ),
  ]

  const passCount = checks.filter((check) => check.passed).length
  return {
    generated_at: new Date().toISOString(),
    overall_status: passCount === checks.length ? 'pass' : 'needs_attention',
    pass_count: passCount,
    total_count: checks.length,
    checks,
  }
}

function CompliancePanel({ workflowOverview, review, agents = [] }) {
  const report = useMemo(
    () => deriveComplianceReport(workflowOverview, review, agents),
    [workflowOverview, review, agents],
  )
  if (!report?.checks?.length) return null

  const statusClass = report.overall_status === 'pass' ? 'pass' : 'needs_attention'

  return (
    <section className="workflow-map compliance-panel">
      <div className="workflow-map-title">Client compliance</div>
      <div className="compliance-topline">
        <span className={`compliance-status compliance-status--${statusClass}`}>
          {statusClass === 'pass' ? 'All checks passing' : 'Needs attention'}
        </span>
        <span className="compliance-score">{report.pass_count}/{report.total_count} checks</span>
      </div>
      <div className="compliance-grid">
        {report.checks.map((check) => (
          <article key={check.key} className="compliance-card">
            <div className="compliance-card-top">
              <strong>{check.label}</strong>
              <span className={`compliance-pill compliance-pill--${check.status}`}>
                {check.status === 'pending' ? 'pending' : check.status === 'pass' ? 'pass' : 'fail'}
              </span>
            </div>
            <p>{check.detail}</p>
          </article>
        ))}
      </div>
    </section>
  )
}

function AgentCard({ agent, index, traceEvents = [] }) {
  const [showDetails, setShowDetails] = useState(agent.status !== 'pending')

  useEffect(() => {
    if ((agent.status === 'running' || agent.status === 'done' || agent.status === 'failed') && !showDetails) {
      setShowDetails(true)
    }
  }, [agent.status, agent.event_count, showDetails])

  const agentEvents = useMemo(
    () => sortedEventsForAgent(traceEvents, agent.key),
    [traceEvents, agent.key],
  )
  const duration = formatDuration(agent.started_at, agent.finished_at)
  const routeCount = agentEvents.filter((event) => Boolean(event.route_to)).length
  const latestDecision = [...agentEvents].reverse().find((event) => event.decision)?.decision || 'none'
  const latestRoute = [...agentEvents].reverse().find((event) => event.route_to)?.route_to || 'none'
  const auditStats = [
    { label: 'events', value: agent.event_count || 0 },
    { label: 'node visits', value: agent.node_visits || 0 },
    { label: 'tools', value: agent.tools_used?.length || 0 },
    { label: 'outputs', value: agent.outputs?.length || 0 },
    { label: 'decisions', value: agent.decisions?.length || 0 },
    { label: 'routes', value: routeCount },
  ]

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

      <div className="agent-audit-grid">
        {auditStats.map((stat) => (
          <div key={`${agent.key}-${stat.label}`} className="agent-audit-item">
            <span>{stat.label}</span>
            <strong>{stat.value}</strong>
          </div>
        ))}
      </div>

      <div className="agent-lifecycle-summary">
        <span>start: {formatClock(agent.started_at)}</span>
        <span>end: {formatClock(agent.finished_at)}</span>
        <span>duration: {duration}</span>
        <span>last decision: {latestDecision}</span>
        <span>last route: {latestRoute}</span>
      </div>

      <div className="agent-card-actions">
        <button
          type="button"
          className="agent-inspect-btn"
          onClick={() => setShowDetails((value) => !value)}
        >
          {agent.status === 'running'
            ? 'Live lifecycle (auto-open)'
            : showDetails
              ? 'Hide how this worked'
              : 'How this worked'}
        </button>
        <button
          type="button"
          className="agent-download-btn"
          onClick={() => downloadAgentAudit(agent, agentEvents)}
        >
          <Download size={12} /> Download audit JSON
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
              {agent.decisions.map((decision, idx) => (
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
                {agentEvents.map((event, idx) => {
                  const previousTs = idx > 0 ? agentEvents[idx - 1].ts : null
                  const inputPreview = compactJson(event.input_payload, 360)
                  const outputPreview = compactJson(event.output_payload, 360)
                  const metricsPreview = compactJson(event.metrics, 240)

                  return (
                    <div key={`${agent.key}-trace-${event.ts}-${idx}`} className="agent-trace-item">
                      <strong>Step {idx + 1}: {formatEventType(event.event_type)}</strong>
                      <span>{event.message}</span>
                      <em>time: {formatClock(event.ts)} | delta: {formatStepDelta(event.ts, previousTs)}</em>
                      {event.tools?.length > 0 && <em>tools: {event.tools.join(', ')}</em>}
                      {event.decision && <em>decision: {event.decision}</em>}
                      {event.route_to && <em>route: {event.route_to}</em>}
                      {inputPreview && <pre className="agent-trace-payload">input: {inputPreview}</pre>}
                      {outputPreview && <pre className="agent-trace-payload">output: {outputPreview}</pre>}
                      {metricsPreview && <pre className="agent-trace-payload">metrics: {metricsPreview}</pre>}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          <div className="agent-outputs">
            {(agent.outputs || []).map((output, idx) => (
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

function ExecutionConsole({ activityLog = [], traceEvents = [], runtimeLogs = [] }) {
  const lines = useMemo(
    () => buildExecutionConsoleLines(activityLog, traceEvents, runtimeLogs),
    [activityLog, traceEvents, runtimeLogs],
  )
  if (!lines.length) return null

  return (
    <section className="terminal-console">
      <div className="terminal-console-head">Execution Console (Full Stream)</div>
      <div className="terminal-console-body">
        {lines.map((line) => (
          <div key={line.key} className={`terminal-line terminal-line--${line.kind}`}>
            {line.text}
          </div>
        ))}
      </div>
    </section>
  )
}

function ExtractionPanel({ agents = [] }) {
  const [showFullPreview, setShowFullPreview] = useState(false)
  const [showAllAttempts, setShowAllAttempts] = useState(false)
  const extractionAgent = agents.find((agent) => agent.key === 'extraction')
  if (!extractionAgent) return null

  const outputs = extractionAgent.outputs || []
  const candidates = outputs.find((item) => item.label === 'Candidates')?.value || []
  const extractedPreview = outputs.find((item) => item.label === 'Extracted preview')?.value
  const attempts = outputs.find((item) => item.label === 'Extractor attempts')?.value || []
  const selectedCandidate = candidates.find((candidate) => candidate.status === 'accepted') || candidates[0] || null
  const previewText = String(extractedPreview || '')
  const previewLimit = 560
  const previewBody = showFullPreview || previewText.length <= previewLimit
    ? previewText
    : `${previewText.slice(0, previewLimit)}...`
  const visibleAttempts = showAllAttempts ? attempts : attempts.slice(0, 3)

  return (
    <section className="review-panel">
      <div className="review-header">
        <div className="review-title">
          <FileText size={16} />
          <span>Extraction transparency</span>
        </div>
      </div>

      {selectedCandidate && (
        <div className="review-note review-note--neutral">
          <strong>Selected candidate:</strong> {selectedCandidate.method} | score {selectedCandidate.score || 0} |
          {' '}words {selectedCandidate.word_count || 0} | attempts {attempts.length || candidates.length}
        </div>
      )}

      {extractedPreview && (
        <div className="review-note review-note--preview">
          <strong>Selected extraction preview:</strong>
          <div className="review-preview-shell">
            <p className="review-preview-text">{previewBody}</p>
          </div>
          {previewText.length > previewLimit && (
            <button type="button" className="review-toggle-btn" onClick={() => setShowFullPreview((value) => !value)}>
              {showFullPreview ? 'Show shorter preview' : 'Show full preview'}
            </button>
          )}
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
          {visibleAttempts.map((attempt, idx) => (
            <div key={`${attempt.method}-${idx}`} className="review-note">
              <strong>{attempt.method}</strong>: {attempt.status} · {attempt.reason}
              {attempt.selector_used && <div className="review-note-meta">selector: {attempt.selector_used}</div>}
              {attempt.dom_tags?.length > 0 && <div className="review-note-meta">tags: {attempt.dom_tags.join(', ')}</div>}
            </div>
          ))}
          {attempts.length > 3 && (
            <button type="button" className="review-toggle-btn" onClick={() => setShowAllAttempts((value) => !value)}>
              {showAllAttempts ? 'Show fewer attempts' : `Show all attempts (${attempts.length})`}
            </button>
          )}
        </div>
      )}
    </section>
  )
}

function ReviewPanel({ review }) {
  if (!review) return null
  const breakdownEntries = Object.entries(review.score_breakdown || {})
  const strongest = breakdownEntries.length
    ? [...breakdownEntries].sort((left, right) => Number(right[1] || 0) - Number(left[1] || 0))[0]
    : null
  const weakest = breakdownEntries.length
    ? [...breakdownEntries].sort((left, right) => Number(left[1] || 0) - Number(right[1] || 0))[0]
    : null

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

      <div className="review-facts">
        <div className="review-fact"><span>criteria</span><strong>{review.criteria?.length || 0}</strong></div>
        <div className="review-fact"><span>segments checked</span><strong>{review.segment_diagnostics?.length || 0}</strong></div>
        <div className="review-fact"><span>weak segments</span><strong>{review.weak_segments?.length || 0}</strong></div>
        {strongest && <div className="review-fact"><span>strongest</span><strong>{strongest[0].replace(/_/g, ' ')}</strong></div>}
        {weakest && <div className="review-fact"><span>needs work</span><strong>{weakest[0].replace(/_/g, ' ')}</strong></div>}
      </div>

      {review.score_explanation && (
        <div className="review-note review-note--qa-summary">{review.score_explanation}</div>
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

export default function AgentWorkflowPanel({
  agents = [],
  activityLog = [],
  traceEvents = [],
  runtimeLogs = [],
  review = null,
  workflowOverview = null,
  modelVerification = null,
}) {
  if (!agents.length && !activityLog.length && !traceEvents.length && !review && !workflowOverview) return null

  const {
    retryCount,
    retryEvents,
    reviewDecision,
    qaAverage,
    qaPassed,
  } = useMemo(() => retrySummary(traceEvents, agents), [traceEvents, agents])

  return (
    <section className="workflow-panel fade-up">
      <div className="workflow-header">
        <div>
          <p className="workflow-kicker">Visible orchestration</p>
          <h2>Agent Workflow</h2>
        </div>
        <div className="workflow-header-right">
          <p className="workflow-sub">Extraction, editorial, packaging, QA, and video generation are surfaced so the client can inspect the work, not just the final answer.</p>
        </div>
      </div>

      {!!agents.length && (
        <div className="workflow-actions-row">
          <button
            type="button"
            className="workflow-download-btn"
            onClick={() => downloadAllAgentsAudit(agents, traceEvents, workflowOverview, modelVerification, review)}
          >
            <Download size={13} /> Download all agents audit (live)
          </button>
          <span className="workflow-actions-hint">Available during processing. Exports current progress instantly.</span>
        </div>
      )}

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
      <CompliancePanel workflowOverview={workflowOverview} review={review} agents={agents} />

      {(reviewDecision || retryCount > 0) && (
        <section className="workflow-map">
          <div className="workflow-map-title">Retry visibility</div>
          <div className="workflow-parallel">
            <strong>Retries executed:</strong> <span>{retryCount}</span>
          </div>
          {reviewDecision && (
            <div className="workflow-parallel">
              <strong>Decision:</strong>
              <span>
                {reviewDecision}
                {qaAverage != null ? ` | qa=${Number(qaAverage).toFixed(2)}` : ''}
                {qaPassed != null ? ` | passed=${String(qaPassed)}` : ''}
              </span>
            </div>
          )}
          {retryEvents.length > 0 && (
            <div className="workflow-edges">
              {retryEvents.slice(-8).map((event, idx) => (
                <span key={`wf-retry-${idx}-${event.ts}`} className="workflow-edge">
                  {formatClock(event.ts)} {event.agent_name || event.agent_key}: {event.decision || event.route_to}
                </span>
              ))}
            </div>
          )}
          {retryCount === 0 && reviewDecision === 'finalize' && (
            <div className="workflow-parallel">
              <span>No retry executed: QA finalized on first pass.</span>
            </div>
          )}
        </section>
      )}

      <ExecutionConsole activityLog={activityLog} traceEvents={traceEvents} runtimeLogs={runtimeLogs} />

      <div className="agent-grid">
        {agents.map((agent, index) => (
          <AgentCard key={agent.key} agent={agent} index={index} traceEvents={traceEvents} />
        ))}
      </div>

      <div className="workflow-bottom">
        <ExtractionPanel agents={agents} />
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
        .workflow-header-right {
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 6px;
          max-width: 560px;
          min-width: 0;
        }
        .workflow-actions-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          flex-wrap: wrap;
          border-radius: 14px;
          border: 1px solid rgba(59,130,246,0.2);
          background: linear-gradient(180deg, rgba(59,130,246,0.1), rgba(59,130,246,0.05));
          padding: 10px 12px;
        }
        .workflow-actions-hint {
          font-size: 11px;
          line-height: 1.5;
          color: rgba(219,234,254,0.84);
          overflow-wrap: anywhere;
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
          max-width: 560px;
          color: rgba(255,255,255,0.55);
          font-size: 13px;
          line-height: 1.7;
          text-align: right;
          overflow-wrap: anywhere;
        }
        .workflow-download-btn {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          border-radius: 999px;
          border: 1px solid rgba(59,130,246,0.36);
          background: rgba(59,130,246,0.14);
          color: #dbeafe;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.02em;
          padding: 8px 12px;
          cursor: pointer;
          transition: all var(--transition-fast);
        }
        .workflow-download-btn:hover {
          border-color: rgba(59,130,246,0.56);
          background: rgba(59,130,246,0.22);
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
        .compliance-panel {
          gap: 12px;
        }
        .compliance-topline {
          display: flex;
          align-items: center;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: 10px;
        }
        .compliance-status {
          display: inline-flex;
          align-items: center;
          border-radius: 999px;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.02em;
          padding: 6px 10px;
        }
        .compliance-status--pass {
          color: #bbf7d0;
          border: 1px solid rgba(16,185,129,0.34);
          background: rgba(16,185,129,0.12);
        }
        .compliance-status--needs_attention {
          color: #fde68a;
          border: 1px solid rgba(245,158,11,0.34);
          background: rgba(245,158,11,0.12);
        }
        .compliance-score {
          font-size: 12px;
          color: rgba(255,255,255,0.68);
        }
        .compliance-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: 10px;
        }
        .compliance-card {
          border-radius: 14px;
          border: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.04);
          padding: 10px 12px;
          display: flex;
          flex-direction: column;
          gap: 8px;
          min-width: 0;
        }
        .compliance-card-top {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
        }
        .compliance-card-top strong {
          font-size: 12px;
          color: rgba(255,255,255,0.9);
        }
        .compliance-pill {
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          border-radius: 999px;
          padding: 4px 8px;
          font-weight: 700;
        }
        .compliance-pill--pass {
          color: #86efac;
          border: 1px solid rgba(16,185,129,0.35);
          background: rgba(16,185,129,0.12);
        }
        .compliance-pill--fail {
          color: #fca5a5;
          border: 1px solid rgba(239,68,68,0.38);
          background: rgba(239,68,68,0.12);
        }
        .compliance-pill--pending {
          color: #bfdbfe;
          border: 1px solid rgba(59,130,246,0.36);
          background: rgba(59,130,246,0.12);
        }
        .compliance-card p {
          margin: 0;
          font-size: 11px;
          line-height: 1.6;
          color: rgba(255,255,255,0.66);
          overflow-wrap: anywhere;
        }
        .terminal-console {
          border-radius: 20px;
          border: 1px solid rgba(255,255,255,0.12);
          background: rgba(3, 7, 16, 0.92);
          overflow: hidden;
        }
        .terminal-console-head {
          padding: 10px 14px;
          font-size: 11px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.58);
          background: rgba(255,255,255,0.05);
          border-bottom: 1px solid rgba(255,255,255,0.08);
        }
        .terminal-console-body {
          max-height: 360px;
          overflow: auto;
          padding: 12px 14px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .terminal-line {
          font-family: var(--font-mono);
          font-size: 11px;
          line-height: 1.55;
          color: rgba(255,255,255,0.82);
          white-space: pre-wrap;
          overflow-wrap: anywhere;
        }
        .terminal-line--trace {
          color: #bfdbfe;
        }
        .terminal-line--graph {
          color: #fde68a;
        }
        .terminal-line--graph-route {
          color: #fcd34d;
        }
        .terminal-line--trace-payload {
          color: #dbeafe;
        }
        .terminal-line--activity {
          color: rgba(165, 180, 252, 0.92);
        }
        .terminal-line--runtime-info,
        .terminal-line--runtime-main {
          color: rgba(220, 252, 231, 0.9);
        }
        .terminal-line--runtime-http {
          color: rgba(148, 163, 184, 0.8);
        }
        .terminal-line--runtime-debug {
          color: rgba(134, 239, 172, 0.88);
        }
        .terminal-line--runtime-warn {
          color: #fde68a;
        }
        .terminal-line--runtime-error {
          color: #fca5a5;
        }
        .terminal-line--runtime-scraper {
          color: #fcd34d;
        }
        .terminal-line--runtime-segmenter {
          color: #c4b5fd;
        }
        .terminal-line--runtime-narration {
          color: #93c5fd;
        }
        .terminal-line--runtime-qa {
          color: #fdba74;
        }
        .terminal-line--runtime-tts {
          color: #86efac;
        }
        .terminal-line--runtime-video,
        .terminal-line--runtime-html {
          color: rgba(220, 252, 231, 0.9);
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
        .agent-download-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          border-radius: 999px;
          border: 1px solid rgba(16,185,129,0.36);
          background: rgba(16,185,129,0.12);
          color: #bbf7d0;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.02em;
          padding: 7px 10px;
          cursor: pointer;
          transition: all var(--transition-fast);
        }
        .agent-download-btn:hover {
          border-color: rgba(16,185,129,0.56);
          background: rgba(16,185,129,0.18);
          color: #dcfce7;
        }
        .agent-download-btn:focus-visible {
          outline: 2px solid rgba(16,185,129,0.5);
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
          gap: 20px;
          align-items: start;
        }
        .activity-panel,
        .review-panel {
          background: rgba(10, 14, 24, 0.88);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          padding: 18px;
          min-width: 0;
          overflow: hidden;
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
          flex-wrap: wrap;
          margin-bottom: 14px;
        }
        .review-facts {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 8px;
          margin-bottom: 12px;
        }
        .review-fact {
          display: grid;
          gap: 4px;
          border-radius: 10px;
          border: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.04);
          padding: 8px 10px;
          min-width: 0;
        }
        .review-fact span {
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: rgba(255,255,255,0.5);
        }
        .review-fact strong {
          font-size: 12px;
          color: rgba(255,255,255,0.86);
          overflow-wrap: anywhere;
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
          grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
          gap: 10px;
          margin-top: 8px;
        }
        .review-item {
          border-radius: 14px;
          padding: 12px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.05);
          min-width: 0;
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
          overflow-wrap: anywhere;
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
          margin: 0;
          overflow-wrap: anywhere;
          white-space: normal;
        }
        .review-note--neutral {
          background: rgba(59,130,246,0.08);
          border-color: rgba(59,130,246,0.25);
          color: rgba(219,234,254,0.9);
          margin-bottom: 12px;
        }
        .review-note--preview {
          background: rgba(16,185,129,0.08);
          border-color: rgba(16,185,129,0.2);
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-bottom: 14px;
        }
        .review-note--qa-summary {
          background: rgba(245,158,11,0.1);
          border-color: rgba(245,158,11,0.24);
        }
        .review-preview-shell {
          border-radius: 10px;
          border: 1px solid rgba(16,185,129,0.24);
          background: rgba(15,23,42,0.52);
          padding: 10px 12px;
          max-height: 240px;
          overflow: auto;
          min-width: 0;
        }
        .review-preview-text {
          margin: 0;
          color: rgba(255,255,255,0.8);
          line-height: 1.7;
          overflow-wrap: anywhere;
          white-space: pre-wrap;
        }
        .review-toggle-btn {
          margin-top: 8px;
          border: 1px solid rgba(255,255,255,0.16);
          border-radius: 999px;
          background: rgba(255,255,255,0.05);
          color: rgba(255,255,255,0.85);
          padding: 6px 10px;
          font-size: 11px;
          font-weight: 700;
          cursor: pointer;
          width: fit-content;
        }
        .review-note-meta {
          margin-top: 6px;
          color: rgba(255,255,255,0.58);
          font-size: 11px;
          overflow-wrap: anywhere;
        }
        .agent-audit-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
          gap: 8px;
        }
        .agent-audit-item {
          border-radius: 10px;
          border: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.04);
          padding: 7px 9px;
          display: grid;
          gap: 4px;
          min-width: 0;
        }
        .agent-audit-item span {
          font-size: 10px;
          color: rgba(255,255,255,0.48);
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }
        .agent-audit-item strong {
          font-size: 12px;
          color: rgba(255,255,255,0.88);
          overflow-wrap: anywhere;
        }
        .agent-trace-payload {
          margin: 0;
          white-space: pre-wrap;
          word-break: break-word;
          overflow-wrap: anywhere;
          border-radius: 8px;
          border: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.04);
          padding: 7px 8px;
          font-size: 11px;
          line-height: 1.6;
          color: rgba(255,255,255,0.74);
          font-family: var(--font-mono);
        }
        .agent-spin { animation: spin 1s linear infinite; }
        @media (max-width: 1180px) {
          .workflow-bottom {
            grid-template-columns: 1fr;
          }
        }
        @media (max-width: 900px) {
          .workflow-header-right {
            align-items: flex-start;
            max-width: 100%;
          }
          .workflow-sub {
            text-align: left;
          }
          .workflow-actions-row {
            align-items: flex-start;
          }
        }
        @media (max-width: 760px) {
          .review-grid {
            grid-template-columns: 1fr;
          }
          .review-facts {
            grid-template-columns: 1fr 1fr;
          }
        }
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
