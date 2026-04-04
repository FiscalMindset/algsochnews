import { useMemo, useState } from 'react'
import { Captions, ChevronDown, ChevronUp, FileText, Mic, Rows3 } from 'lucide-react'

function SegmentCard({ segment, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)

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

export default function ScriptPreview({ script }) {
  const [viewMode, setViewMode] = useState('screenplay')
  const jsonPreview = useMemo(() => JSON.stringify(script, null, 2), [script])

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
        <div className="preview-toggle">
          <button
            type="button"
            className={`json-toggle ${viewMode === 'screenplay' ? 'json-toggle--active' : ''}`}
            onClick={() => setViewMode('screenplay')}
          >
            Screenplay
          </button>
          <button
            type="button"
            className={`json-toggle ${viewMode === 'json' ? 'json-toggle--active' : ''}`}
            onClick={() => setViewMode('json')}
          >
            JSON
          </button>
        </div>
      </div>

      <div className="script-shell-meta">
        <span>Article URL: {script.article_url}</span>
        <span>Runtime: {script.video_duration_sec}s</span>
        <span>QA: {(script.qa_score * 100).toFixed(0)}%</span>
        <span>Extractor: {script.article?.extraction_method}</span>
      </div>

      {viewMode === 'screenplay' ? (
        <>
          <div className="screenplay-block">
            <div className="script-block-title">Human-readable screenplay</div>
            <pre>{script.screenplay_text}</pre>
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
        </>
      ) : (
        <div className="json-block">
          <div className="script-block-title">Structured JSON</div>
          <pre>{jsonPreview}</pre>
        </div>
      )}

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
        .json-toggle {
          border: 1px solid rgba(59,130,246,0.3);
          background: rgba(59,130,246,0.1);
          color: #bfdbfe;
          border-radius: 999px;
          padding: 10px 14px;
          cursor: pointer;
          font-weight: 700;
        }
        .preview-toggle {
          display: inline-flex;
          gap: 8px;
          flex-wrap: wrap;
        }
        .json-toggle--active {
          background: rgba(239,68,68,0.14);
          border-color: rgba(239,68,68,0.34);
          color: #fecaca;
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
        .script-block-title {
          font-size: 12px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.34);
          margin-bottom: 12px;
        }
        .script-block-title--with-icon {
          display: inline-flex;
          align-items: center;
          gap: 8px;
        }
        .screenplay-block pre,
        .json-block pre {
          margin: 0;
          white-space: pre-wrap;
          word-break: break-word;
          font-size: 12px;
          line-height: 1.7;
          color: rgba(255,255,255,0.82);
          font-family: var(--font-mono);
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
        @media (max-width: 860px) {
          .script-side-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </section>
  )
}
