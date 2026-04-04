// components/ScriptPreview.jsx
import { useState } from 'react'
import { FileText, ChevronDown, ChevronUp, Mic, Clock } from 'lucide-react'

function fmt(s) {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

const TYPE_COLORS = {
  intro: { bg: 'rgba(239,68,68,0.12)', border: 'rgba(239,68,68,0.35)', text: '#EF4444', label: 'INTRO' },
  body:  { bg: 'rgba(59,130,246,0.08)', border: 'rgba(59,130,246,0.25)', text: '#3B82F6', label: 'BODY'  },
  outro: { bg: 'rgba(139,92,246,0.1)', border: 'rgba(139,92,246,0.3)', text: '#8B5CF6', label: 'OUTRO' },
}

function SegmentCard({ segment, index }) {
  const [open, setOpen] = useState(index === 0)
  const colors = TYPE_COLORS[segment.segment_type] || TYPE_COLORS.body

  return (
    <div className="seg-card" style={{ '--seg-border': colors.border, '--seg-bg': colors.bg }}>
      <div className="seg-header" onClick={() => setOpen(o => !o)}>
        <div className="seg-meta">
          <span className="seg-badge" style={{ color: colors.text, borderColor: colors.border, background: colors.bg }}>
            {colors.label}
          </span>
          <span className="seg-num">#{index + 1}</span>
          <span className="seg-headline">{segment.headline}</span>
        </div>
        <div className="seg-time">
          <Clock size={12} />
          <span>{fmt(segment.start_time)} – {fmt(segment.end_time)}</span>
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </div>

      {open && (
        <div className="seg-body fade-up">
          <div className="seg-section">
            <div className="seg-section-label">
              <Mic size={12} /> Narration
            </div>
            <p className="seg-narration">{segment.narration}</p>
          </div>
          <div className="seg-section">
            <div className="seg-section-label">
              <FileText size={12} /> Source text
            </div>
            <p className="seg-source-text">{segment.text || segment.narration}</p>
          </div>
          {segment.visual_prompt && (
            <div className="seg-prompt">
              <span className="seg-prompt-tag">🎨 Visual</span>
              <span>{segment.visual_prompt}</span>
            </div>
          )}
        </div>
      )}

      <style>{`
        .seg-card {
          border: 1px solid var(--seg-border);
          background: var(--seg-bg);
          border-radius: var(--radius-md);
          overflow: hidden;
          transition: box-shadow var(--transition-base);
        }
        .seg-card:hover { box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
        .seg-header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 14px 18px; cursor: pointer; gap: 12px;
        }
        .seg-meta { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
        .seg-badge {
          font-size: 10px; font-weight: 800; letter-spacing: 0.1em;
          padding: 3px 8px; border-radius: 4px; border: 1px solid;
          flex-shrink: 0;
        }
        .seg-num { font-family: var(--font-mono); font-size: 12px; color: rgba(255,255,255,0.3); flex-shrink: 0; }
        .seg-headline {
          font-size: 14px; font-weight: 600; color: rgba(255,255,255,0.85);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .seg-time {
          display: flex; align-items: center; gap: 5px;
          font-size: 12px; color: rgba(255,255,255,0.35); flex-shrink: 0;
          font-family: var(--font-mono);
        }
        .seg-body { padding: 0 18px 18px; display: flex; flex-direction: column; gap: 14px; }
        .seg-section { display: flex; flex-direction: column; gap: 6px; }
        .seg-section-label {
          display: flex; align-items: center; gap: 5px;
          font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
          text-transform: uppercase; color: rgba(255,255,255,0.3);
        }
        .seg-narration {
          font-size: 13px; line-height: 1.7; color: rgba(255,255,255,0.8);
          background: rgba(0,0,0,0.2); border-radius: 8px;
          padding: 10px 14px; border-left: 3px solid rgba(59,130,246,0.5);
        }
        .seg-source-text {
          font-size: 12px; line-height: 1.7; color: rgba(255,255,255,0.45);
          font-family: var(--font-mono);
        }
        .seg-prompt {
          display: flex; gap: 8px; align-items: flex-start;
          font-size: 11px; color: rgba(255,255,255,0.35); font-style: italic;
          background: rgba(255,255,255,0.03); border-radius: 6px;
          padding: 8px 12px;
        }
        .seg-prompt-tag { flex-shrink: 0; }
      `}</style>
    </div>
  )
}

export default function ScriptPreview({ script }) {
  if (!script) return null
  const { segments, overall_headline, article, qa_score } = script

  return (
    <div className="sp-wrapper fade-up">
      <div className="sp-header">
        <div className="sp-title-row">
          <FileText size={18} className="sp-icon" />
          <h2 className="sp-title">Script Preview</h2>
          <div className="qa-badge" title={`QA Score: ${(qa_score * 100).toFixed(0)}%`}>
            QA {(qa_score * 100).toFixed(0)}%
          </div>
        </div>
        <div className="sp-meta-row">
          <span className="sp-overall-hl">{overall_headline}</span>
        </div>
        <div className="sp-article-meta">
          <span>📰 {article?.source_domain}</span>
          {article?.authors?.length > 0 && <span>✍️ {article.authors.join(', ')}</span>}
          <span>📊 {article?.word_count} words</span>
          <span>🔬 via {article?.extraction_method}</span>
        </div>
      </div>

      <div className="sp-segments">
        {segments.map((seg, i) => (
          <SegmentCard key={i} segment={seg} index={i} />
        ))}
      </div>

      <style>{`
        .sp-wrapper { display: flex; flex-direction: column; gap: 20px; }
        .sp-header {
          glass: var(--bg-glass);
          background: var(--bg-card);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-lg);
          padding: 22px 24px;
          display: flex; flex-direction: column; gap: 12px;
        }
        .sp-title-row { display: flex; align-items: center; gap: 10px; }
        .sp-icon { color: var(--accent-blue); }
        .sp-title { font-size: 17px; font-weight: 700; flex: 1; }
        .qa-badge {
          font-size: 11px; font-weight: 700; padding: 4px 10px;
          border-radius: var(--radius-full);
          background: rgba(16,185,129,0.15); color: var(--accent-green);
          border: 1px solid rgba(16,185,129,0.3);
        }
        .sp-meta-row {}
        .sp-overall-hl {
          font-size: 20px; font-weight: 800;
          background: var(--gradient-primary);
          -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }
        .sp-article-meta {
          display: flex; flex-wrap: wrap; gap: 14px;
          font-size: 12px; color: rgba(255,255,255,0.4);
        }
        .sp-segments { display: flex; flex-direction: column; gap: 10px; }
      `}</style>
    </div>
  )
}
