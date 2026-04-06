import { useEffect, useMemo, useState } from 'react'
import { Captions, Check, ChevronDown, ChevronUp, Clipboard, FileText, Mic, Rows3 } from 'lucide-react'
import { resolveAssetUrl } from '../api/client.js'

function parseScreenplayBlocks(text) {
  const raw = String(text || '').replace(/\r/g, '').trim()
  if (!raw) return []

  const chunks = raw
    .split(/\n(?=Segment\s+\d+\s+\[)/g)
    .map((chunk) => chunk.trim())
    .filter(Boolean)

  if (chunks.length === 1 && !/^Segment\s+\d+\s+\[/.test(chunks[0])) {
    const plainLines = chunks[0]
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean)
    return [{ heading: 'Screenplay', rows: [], notes: plainLines }]
  }

  return chunks.map((chunk, index) => {
    const lines = chunk
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean)
    const heading = lines[0] || `Segment ${index + 1}`
    const rows = []
    const notes = []

    for (const line of lines.slice(1)) {
      const match = line.match(/^([^:]{2,40}):\s*(.*)$/)
      if (match) {
        rows.push({ label: match[1], value: match[2] })
      } else {
        notes.push(line)
      }
    }

    return { heading, rows, notes }
  })
}

function renderHighlightedJson(text) {
  const source = String(text || '')
  const output = []
  const tokenRegex = /("(?:\\.|[^"\\])*"(?=\s*:))|("(?:\\.|[^"\\])*")|\btrue\b|\bfalse\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?|[{}\[\],:]/g

  let lastIndex = 0
  let match
  let tokenIdx = 0
  while ((match = tokenRegex.exec(source)) !== null) {
    if (match.index > lastIndex) {
      output.push(source.slice(lastIndex, match.index))
    }

    const token = match[0]
    let className = 'json-token json-token--punct'
    if (token.startsWith('"')) {
      const rest = source.slice(tokenRegex.lastIndex)
      className = /^\s*:/.test(rest)
        ? 'json-token json-token--key'
        : 'json-token json-token--string'
    } else if (/^-?\d/.test(token)) {
      className = 'json-token json-token--number'
    } else if (token === 'true' || token === 'false') {
      className = 'json-token json-token--boolean'
    } else if (token === 'null') {
      className = 'json-token json-token--null'
    }

    output.push(
      <span key={`json-token-${tokenIdx}`} className={className}>
        {token}
      </span>,
    )
    tokenIdx += 1
    lastIndex = tokenRegex.lastIndex
  }

  if (lastIndex < source.length) {
    output.push(source.slice(lastIndex))
  }

  return output
}

function SegmentCard({ segment, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const frameUrl = resolveAssetUrl(segment?.html_frame_url)

  return (
    <article className="script-card">
      <button className="script-card-head" onClick={() => setOpen((value) => !value)} type="button">
        <div className="script-card-title">
          <span className="script-chip">{segment.top_tag}</span>
          <div>
            <strong>{segment.main_headline}</strong>
            <p>{segment.subheadline}</p>
          </div>
        </div>
        <div className="script-card-time">
          <span>{segment.start_timecode} - {segment.end_timecode}</span>
          {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </button>

      {open && (
        <div className="script-card-body">
          <div className="script-card-grid">
            <div className="script-card-panel">
              <div className="script-card-label"><Mic size={13} /> Anchor narration</div>
              <p>{segment.anchor_narration}</p>
            </div>
            <div className="script-card-panel">
              <div className="script-card-label">Layout package</div>
              <p><strong>Layout:</strong> {segment.layout}</p>
              <p><strong>Left panel:</strong> {segment.left_panel}</p>
              <p><strong>Right panel:</strong> {segment.right_panel}</p>
              <p><strong>Lower third:</strong> {segment.lower_third}</p>
              <p><strong>Camera motion:</strong> {segment.camera_motion}</p>
              <p><strong>Transition:</strong> {segment.transition}</p>
              {frameUrl && (
                <p>
                  <strong>HTML frame:</strong>{' '}
                  <a href={frameUrl} target="_blank" rel="noreferrer">Open frame preview</a>
                </p>
              )}
            </div>
            <div className="script-card-panel">
              <div className="script-card-label">Source grounding</div>
              <p>{segment.source_excerpt}</p>
              {segment.factual_points?.length > 0 && (
                <div className="factual-list">
                  {segment.factual_points.map((fact, index) => (
                    <span key={index} className="fact-chip">{fact}</span>
                  ))}
                </div>
              )}
            </div>
            <div className="script-card-panel">
              <div className="script-card-label">Packaging rationale</div>
              <p><strong>Headline:</strong> {segment.headline_reason}</p>
              <p><strong>Visual:</strong> {segment.visual_rationale}</p>
              <p><strong>Control room:</strong> {segment.control_room_cue}</p>
              {segment.ai_support_visual_prompt && <p><strong>AI support prompt:</strong> {segment.ai_support_visual_prompt}</p>}
            </div>
          </div>

          {frameUrl && (
            <div className="script-frame-preview">
              <div className="script-card-label">HTML frame preview</div>
              <iframe
                src={frameUrl}
                title={`frame-${segment.segment_id}`}
                loading="lazy"
                sandbox="allow-same-origin"
                scrolling="no"
              />
            </div>
          )}
        </div>
      )}

      <style>{`
        .script-card {
          border-radius: 18px;
          overflow: hidden;
          background: rgba(10, 14, 24, 0.9);
          border: 1px solid rgba(255,255,255,0.08);
        }
        .script-card-head {
          width: 100%;
          background: none;
          border: none;
          color: inherit;
          text-align: left;
          padding: 16px 18px;
          display: flex;
          justify-content: space-between;
          gap: 14px;
          cursor: pointer;
        }
        .script-card-title {
          display: flex;
          gap: 12px;
          align-items: start;
          min-width: 0;
        }
        .script-chip {
          flex-shrink: 0;
          font-size: 11px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: #fca5a5;
          border: 1px solid rgba(239,68,68,0.3);
          background: rgba(239,68,68,0.12);
          padding: 5px 9px;
          border-radius: 999px;
        }
        .script-card-title strong {
          display: block;
          font-size: 17px;
          line-height: 1.35;
          margin-bottom: 4px;
        }
        .script-card-title p {
          color: rgba(255,255,255,0.54);
          font-size: 13px;
          line-height: 1.6;
        }
        .script-card-time {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-shrink: 0;
          color: rgba(255,255,255,0.44);
          font-family: var(--font-mono);
          font-size: 12px;
        }
        .script-card-body {
          padding: 0 18px 18px;
        }
        .script-card-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 12px;
        }
        .script-card-panel {
          border-radius: 14px;
          padding: 14px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.05);
          display: flex;
          flex-direction: column;
          gap: 8px;
          font-size: 13px;
          line-height: 1.65;
          color: rgba(255,255,255,0.82);
        }
        .script-card a {
          color: #93c5fd;
          text-decoration: underline;
        }
        .script-frame-preview {
          margin-top: 12px;
          border-radius: 14px;
          padding: 12px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.05);
        }
        .script-frame-preview iframe {
          width: 100%;
          height: auto;
          min-height: 220px;
          aspect-ratio: 16 / 9;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 12px;
          background: rgba(8,12,18,0.8);
          margin-top: 8px;
        }
        .script-card-label {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 10px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.34);
        }
        .factual-list {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .fact-chip {
          font-size: 11px;
          color: rgba(255,255,255,0.76);
          background: rgba(59,130,246,0.12);
          border: 1px solid rgba(59,130,246,0.24);
          border-radius: 999px;
          padding: 4px 8px;
        }
        @media (max-width: 860px) {
          .script-card-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </article>
  )
}

export default function ScriptPreview({ script, requestedView = null }) {
  const [viewMode, setViewMode] = useState('screenplay')
  const [copyState, setCopyState] = useState('')
  const [readerSize, setReaderSize] = useState('medium')
  const [readerFocus, setReaderFocus] = useState(false)
  const showJson = viewMode === 'json'
  const jsonPreview = useMemo(() => JSON.stringify(script, null, 2), [script])
  const highlightedJson = useMemo(() => renderHighlightedJson(jsonPreview), [jsonPreview])
  const screenplayBlocks = useMemo(
    () => parseScreenplayBlocks(script?.screenplay_text || ''),
    [script?.screenplay_text],
  )

  useEffect(() => {
    if (requestedView === 'json' || requestedView === 'screenplay') {
      setViewMode(requestedView)
      setCopyState('')
    }
  }, [requestedView])

  async function copyText(text, label) {
    if (!text) return

    let copied = false
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
        copied = true
      }
    } catch {
      copied = false
    }

    if (!copied) {
      try {
        const temp = document.createElement('textarea')
        temp.value = text
        temp.setAttribute('readonly', 'true')
        temp.style.position = 'absolute'
        temp.style.left = '-9999px'
        document.body.appendChild(temp)
        temp.select()
        copied = document.execCommand('copy')
        document.body.removeChild(temp)
      } catch {
        copied = false
      }
    }

    if (copied) {
      setCopyState(label)
      window.setTimeout(() => setCopyState(''), 1400)
    }
  }

  if (!script) return null

  return (
    <section className="script-shell fade-up">
      <div className="script-shell-head">
        <div className="script-shell-title">
          <FileText size={18} />
          <div>
            <p className="script-kicker">Structured output</p>
            <h2>{script.source_title}</h2>
          </div>
        </div>
        <div className="script-head-actions">
          <span className="view-indicator">Showing: {showJson ? 'JSON' : 'Screenplay'}</span>
        </div>
      </div>

      <div className="script-shell-meta">
        <span>Article URL: {script.article_url}</span>
        <span>Runtime: {script.video_duration_sec}s</span>
        <span>QA: {(script.qa_score * 100).toFixed(0)}%</span>
        <span>Extractor: {script.article?.extraction_method}</span>
        <span>Model: {script.model_verification?.selected_model || 'n/a'}</span>
      </div>

      {script.route_history?.length > 0 && (
        <div className="script-shell-meta">
          <span>Route: {script.route_history.join(' -> ')}</span>
        </div>
      )}

      {!!script.article?.extraction_attempts?.length && (
        <div className="screenplay-block">
          <div className="script-block-title">Extraction attempts</div>
          <div className="extraction-attempts">
            {script.article.extraction_attempts.map((attempt, idx) => (
              <div key={`${attempt.method}-${idx}`} className="extraction-attempt">
                <div className="attempt-head">
                  <strong>{attempt.method}</strong>
                  <span className={`attempt-status attempt-status--${attempt.status}`}>{attempt.status}</span>
                </div>
                <p>{attempt.reason}</p>
                {attempt.status === 'failed' && (
                  <p className="attempt-note">Non-blocking: fallback extractor output was used for the final package.</p>
                )}
                {attempt.preview_excerpt && <p><em>{attempt.preview_excerpt}</em></p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {script.render_review && (
        <div className="screenplay-block">
          <div className="script-block-title">Render quality review</div>
          <div className="script-shell-meta">
            <span>Verdict: {script.render_review.verdict}</span>
            <span>Score: {script.render_review.overall_score}/5</span>
            <span>Status: {script.render_review.passed ? 'pass' : 'review'}</span>
          </div>
          {script.render_review.summary && <p className="render-summary">{script.render_review.summary}</p>}
          {script.render_review.issues?.length > 0 && (
            <div className="render-list">
              {script.render_review.issues.map((issue, index) => (
                <div key={`render-issue-${index}`} className="render-item render-item--issue">{issue}</div>
              ))}
            </div>
          )}
          {script.render_review.recommendations?.length > 0 && (
            <div className="render-list">
              {script.render_review.recommendations.map((rec, index) => (
                <div key={`render-rec-${index}`} className="render-item render-item--rec">{rec}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {showJson && (
        <div id="script-json-block" className="json-block">
          <div className="script-block-head">
            <div className="script-block-title">Structured JSON (screenplay remains visible below)</div>
            <button
              type="button"
              className="block-copy-btn"
              onClick={() => copyText(jsonPreview, 'JSON copied')}
            >
              {copyState === 'JSON copied' ? <Check size={13} /> : <Clipboard size={13} />}
              {copyState === 'JSON copied' ? 'JSON copied' : 'Copy JSON'}
            </button>
          </div>
          <pre className="json-reader"><code>{highlightedJson}</code></pre>
        </div>
      )}

      <div id="script-screenplay-block" className="screenplay-block">
        <div className="script-block-head">
          <div className="script-block-title">Human-readable screenplay</div>
          <div className="screenplay-tools">
            <div className="reader-size-group">
              <button
                type="button"
                className={`reader-size-btn ${readerSize === 'small' ? 'reader-size-btn--active' : ''}`}
                onClick={() => setReaderSize('small')}
              >
                A-
              </button>
              <button
                type="button"
                className={`reader-size-btn ${readerSize === 'medium' ? 'reader-size-btn--active' : ''}`}
                onClick={() => setReaderSize('medium')}
              >
                A
              </button>
              <button
                type="button"
                className={`reader-size-btn ${readerSize === 'large' ? 'reader-size-btn--active' : ''}`}
                onClick={() => setReaderSize('large')}
              >
                A+
              </button>
            </div>
            <button
              type="button"
              className={`reader-focus-btn ${readerFocus ? 'reader-focus-btn--active' : ''}`}
              onClick={() => setReaderFocus((value) => !value)}
            >
              {readerFocus ? 'Exit focus' : 'Focus mode'}
            </button>
            <button
              type="button"
              className="block-copy-btn"
              onClick={() => copyText(script.screenplay_text, 'Screenplay copied')}
            >
              {copyState === 'Screenplay copied' ? <Check size={13} /> : <Clipboard size={13} />}
              {copyState === 'Screenplay copied' ? 'Screenplay copied' : 'Copy screenplay'}
            </button>
          </div>
        </div>
        <div className={`screenplay-reader screenplay-reader--${readerSize} ${readerFocus ? 'screenplay-reader--focus' : ''}`}>
          {screenplayBlocks.length ? screenplayBlocks.map((block, index) => (
            <article key={`block-${index}`} className="screenplay-segment">
              <header className="screenplay-segment-head">
                <span className="screenplay-segment-no">{index + 1}</span>
                <h3>{block.heading}</h3>
              </header>

              {!!block.rows?.length && (
                <div className="screenplay-segment-grid">
                  {block.rows.map((row, rowIndex) => (
                    <div key={`row-${index}-${rowIndex}`} className="screenplay-segment-row">
                      <span>{row.label}</span>
                      <p>{row.value || '—'}</p>
                    </div>
                  ))}
                </div>
              )}

              {!!block.notes?.length && (
                <div className="screenplay-segment-notes">
                  {block.notes.map((line, lineIndex) => (
                    <p key={`note-${index}-${lineIndex}`}>{line}</p>
                  ))}
                </div>
              )}
            </article>
          )) : (
            <p className="screenplay-empty">No screenplay text available.</p>
          )}
        </div>
      </div>

      <div className="script-side-grid">
        <div className="screenplay-block">
          <div className="script-block-title script-block-title--with-icon">
            <Rows3 size={14} /> Editorial rundown
          </div>
          <div className="rundown-list">
            {(script.rundown || []).map((item) => (
              <div key={item.segment_id} className="rundown-item">
                <strong>{item.slug}</strong>
                <p>{item.start_timecode} - {item.end_timecode}</p>
                <span>{item.lower_third}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="screenplay-block">
          <div className="script-block-title script-block-title--with-icon">
            <Captions size={14} /> Live transcript cues
          </div>
          <div className="transcript-list">
            {(script.live_transcript || []).map((cue) => (
              <div key={cue.id} className="transcript-item">
                <span>{cue.start_timecode}</span>
                <p>{cue.text}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="script-card-list">
        {script.segments.map((segment, index) => (
          <SegmentCard
            key={segment.segment_id ?? index}
            segment={segment}
            defaultOpen={index === 0}
          />
        ))}
      </div>

      <style>{`
        .script-shell {
          display: flex;
          flex-direction: column;
          gap: 18px;
        }
        .script-shell-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          flex-wrap: wrap;
        }
        .script-shell-title {
          display: flex;
          gap: 12px;
          align-items: center;
        }
        .script-kicker {
          font-size: 11px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.42);
          margin-bottom: 4px;
        }
        .script-shell-title h2 {
          font-size: 24px;
          line-height: 1.2;
        }
        .script-head-actions {
          display: inline-flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
        }
        .view-indicator {
          font-size: 11px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.58);
          border: 1px solid rgba(255,255,255,0.1);
          background: rgba(255,255,255,0.04);
          border-radius: 999px;
          padding: 9px 12px;
        }
        .script-block-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          flex-wrap: wrap;
          margin-bottom: 12px;
        }
        .script-block-title {
          font-size: 12px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.34);
          margin: 0;
        }
        .screenplay-tools {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }
        .reader-size-group {
          display: inline-flex;
          border: 1px solid rgba(255,255,255,0.14);
          border-radius: 999px;
          background: rgba(255,255,255,0.05);
          overflow: hidden;
        }
        .reader-size-btn,
        .reader-focus-btn,
        .block-copy-btn {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          border-radius: 999px;
          padding: 8px 12px;
          cursor: pointer;
          font-weight: 700;
          font-size: 11px;
          border: 1px solid rgba(255,255,255,0.14);
          background: rgba(255,255,255,0.06);
          color: rgba(255,255,255,0.88);
          transition: all 0.2s ease;
        }
        .reader-size-btn {
          border: none;
          border-right: 1px solid rgba(255,255,255,0.14);
          border-radius: 0;
          min-width: 40px;
          justify-content: center;
          background: transparent;
          padding: 8px 10px;
        }
        .reader-size-btn:last-child {
          border-right: none;
        }
        .reader-size-btn--active {
          background: rgba(59,130,246,0.24);
          color: #dbeafe;
        }
        .reader-focus-btn {
          border-color: rgba(99,102,241,0.38);
          background: rgba(99,102,241,0.12);
          color: #c7d2fe;
        }
        .reader-focus-btn--active {
          background: rgba(99,102,241,0.24);
          border-color: rgba(99,102,241,0.6);
          color: #e0e7ff;
        }
        .block-copy-btn {
          border: 1px solid rgba(16,185,129,0.38);
          background: rgba(16,185,129,0.12);
          color: #bbf7d0;
        }
        .block-copy-btn:hover {
          border-color: rgba(16,185,129,0.58);
          background: rgba(16,185,129,0.2);
        }
        .reader-focus-btn:hover,
        .reader-size-btn:hover {
          background: rgba(255,255,255,0.14);
        }
        .script-shell-meta {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
        }
        .script-shell-meta span {
          font-size: 12px;
          color: rgba(255,255,255,0.64);
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 999px;
          padding: 6px 10px;
        }
        .screenplay-block,
        .json-block {
          background: rgba(10, 14, 24, 0.88);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          padding: 18px;
        }
        .script-block-title--with-icon {
          display: inline-flex;
          align-items: center;
          gap: 8px;
        }
        .json-reader {
          margin: 0;
          white-space: pre-wrap;
          word-break: break-word;
          font-size: 12px;
          line-height: 1.7;
          color: rgba(255,255,255,0.82);
          font-family: var(--font-mono);
          max-height: 420px;
          overflow: auto;
          border-radius: 14px;
          border: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.03);
          padding: 12px;
        }
        .json-reader code {
          font-family: var(--font-mono);
        }
        .json-token--key {
          color: #93c5fd;
          font-weight: 700;
        }
        .json-token--string {
          color: #86efac;
        }
        .json-token--number {
          color: #fca5a5;
        }
        .json-token--boolean {
          color: #c4b5fd;
          font-weight: 700;
        }
        .json-token--null {
          color: #fbbf24;
          font-weight: 700;
        }
        .json-token--punct {
          color: rgba(255,255,255,0.62);
        }
        .screenplay-reader {
          border-radius: 16px;
          border: 1px solid rgba(255,255,255,0.1);
          background:
            linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02)),
            repeating-linear-gradient(
              to bottom,
              transparent,
              transparent 36px,
              rgba(255,255,255,0.04) 36px,
              rgba(255,255,255,0.04) 37px
            );
          padding: 16px;
          max-height: 520px;
          overflow: auto;
        }
        .screenplay-reader--focus {
          max-width: 960px;
          margin: 0 auto;
          background:
            linear-gradient(180deg, rgba(99,102,241,0.08), rgba(16,185,129,0.04)),
            rgba(7,11,20,0.92);
        }
        .screenplay-reader--small .screenplay-segment-head h3,
        .screenplay-reader--small .screenplay-segment-row p,
        .screenplay-reader--small .screenplay-segment-notes p {
          font-size: 14px;
          line-height: 1.7;
        }
        .screenplay-reader--medium .screenplay-segment-head h3,
        .screenplay-reader--medium .screenplay-segment-row p,
        .screenplay-reader--medium .screenplay-segment-notes p {
          font-size: 15px;
          line-height: 1.85;
        }
        .screenplay-reader--large .screenplay-segment-head h3,
        .screenplay-reader--large .screenplay-segment-row p,
        .screenplay-reader--large .screenplay-segment-notes p {
          font-size: 17px;
          line-height: 2;
        }
        .screenplay-segment {
          border-radius: 14px;
          border: 1px solid rgba(255,255,255,0.1);
          background: rgba(8,12,22,0.58);
          padding: 12px;
          margin: 0 0 10px;
        }
        .screenplay-segment:last-child {
          margin-bottom: 0;
        }
        .screenplay-segment-head {
          display: grid;
          grid-template-columns: 44px minmax(0, 1fr);
          gap: 10px;
          align-items: start;
          margin: 0 0 10px;
        }
        .screenplay-segment-head h3 {
          margin: 0;
          font-size: 14px;
          line-height: 1.45;
          color: rgba(245,247,255,0.96);
          font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Palatino, serif;
        }
        .screenplay-segment-no {
          font-family: var(--font-mono);
          font-size: 11px;
          color: rgba(255,255,255,0.56);
          border-right: 1px solid rgba(255,255,255,0.12);
          padding-right: 8px;
          text-align: right;
          line-height: 1.6;
          user-select: none;
        }
        .screenplay-segment-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
          gap: 8px;
        }
        .screenplay-segment-row {
          border-radius: 10px;
          border: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.04);
          padding: 8px 9px;
          min-width: 0;
        }
        .screenplay-segment-row span {
          display: inline-block;
          font-size: 10px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: rgba(255,255,255,0.52);
          margin-bottom: 4px;
        }
        .screenplay-segment-row p {
          margin: 0;
          color: rgba(245,247,255,0.9);
          font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Palatino, serif;
          overflow-wrap: anywhere;
        }
        .screenplay-segment-notes {
          margin-top: 8px;
          display: grid;
          gap: 7px;
        }
        .screenplay-segment-notes p {
          margin: 0;
          border-radius: 9px;
          border: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.03);
          padding: 8px 9px;
          color: rgba(245,247,255,0.86);
          font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Palatino, serif;
          overflow-wrap: anywhere;
        }
        .screenplay-empty {
          margin: 0;
          color: rgba(255,255,255,0.6);
          font-size: 13px;
          font-style: italic;
        }
        .script-card-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .script-side-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 14px;
        }
        .rundown-list,
        .transcript-list {
          display: flex;
          flex-direction: column;
          gap: 10px;
          max-height: 340px;
          overflow: auto;
          padding-right: 6px;
        }
        .rundown-item,
        .transcript-item {
          display: grid;
          gap: 6px;
          padding: 12px 14px;
          border-radius: 14px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.06);
        }
        .rundown-item strong {
          font-size: 14px;
          color: rgba(255,255,255,0.9);
        }
        .rundown-item p,
        .transcript-item span {
          font-family: var(--font-mono);
          font-size: 11px;
          color: rgba(255,255,255,0.42);
        }
        .rundown-item span,
        .transcript-item p {
          font-size: 13px;
          line-height: 1.6;
          color: rgba(255,255,255,0.76);
        }
        .extraction-attempts {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 10px;
        }
        .extraction-attempt {
          border-radius: 14px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.06);
          padding: 12px;
          display: grid;
          gap: 6px;
          font-size: 12px;
          line-height: 1.6;
          color: rgba(255,255,255,0.78);
          min-width: 0;
        }
        .attempt-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          flex-wrap: wrap;
        }
        .extraction-attempt strong,
        .extraction-attempt p,
        .extraction-attempt em {
          overflow-wrap: anywhere;
          word-break: break-word;
        }
        .attempt-status {
          display: inline-flex;
          width: fit-content;
          max-width: 100%;
          font-size: 10px;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          border-radius: 999px;
          padding: 4px 8px;
          border: 1px solid rgba(255,255,255,0.12);
          white-space: normal;
        }
        .attempt-status--accepted {
          color: #6ee7b7;
          border-color: rgba(16,185,129,0.45);
          background: rgba(16,185,129,0.12);
        }
        .attempt-status--failed {
          color: #fca5a5;
          border-color: rgba(239,68,68,0.45);
          background: rgba(239,68,68,0.12);
        }
        .attempt-note {
          color: #bfdbfe;
          background: rgba(59,130,246,0.12);
          border: 1px solid rgba(59,130,246,0.24);
          border-radius: 10px;
          padding: 6px 8px;
          font-size: 11px;
          line-height: 1.55;
        }
        .render-summary {
          margin: 12px 0 0;
          color: rgba(255,255,255,0.8);
          font-size: 13px;
          line-height: 1.65;
        }
        .render-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-top: 12px;
        }
        .render-item {
          font-size: 12px;
          line-height: 1.6;
          border-radius: 10px;
          padding: 8px 10px;
          overflow-wrap: anywhere;
        }
        .render-item--issue {
          color: #fecaca;
          border: 1px solid rgba(239,68,68,0.3);
          background: rgba(239,68,68,0.1);
        }
        .render-item--rec {
          color: #dbeafe;
          border: 1px solid rgba(59,130,246,0.24);
          background: rgba(59,130,246,0.1);
        }
        @media (max-width: 860px) {
          .script-block-head {
            align-items: flex-start;
          }
          .screenplay-tools {
            width: 100%;
          }
          .reader-focus-btn,
          .block-copy-btn {
            flex: 1;
            justify-content: center;
          }
          .screenplay-segment-head {
            grid-template-columns: 34px minmax(0, 1fr);
          }
          .screenplay-segment-grid {
            grid-template-columns: 1fr;
          }
          .script-side-grid {
            grid-template-columns: 1fr;
          }
          .extraction-attempts {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </section>
  )
}
