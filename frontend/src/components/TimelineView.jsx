// components/TimelineView.jsx
import { useRef } from 'react'

const TYPE_COLORS = {
  intro: '#EF4444',
  body:  '#3B82F6',
  outro: '#8B5CF6',
}

export default function TimelineView({ segments, totalDuration, currentTime = 0 }) {
  if (!segments || !segments.length) return null

  const pct = (s, total) => `${((s / total) * 100).toFixed(2)}%`
  const playheadLeft = pct(currentTime, totalDuration)

  function fmt(s) {
    const m = Math.floor(s / 60); const sec = Math.floor(s % 60)
    return `${m}:${sec.toString().padStart(2, '0')}`
  }

  return (
    <div className="tl-wrapper fade-up">
      <div className="tl-header">
        <span className="tl-title">Timeline</span>
        <span className="tl-dur">Total: {fmt(totalDuration)}</span>
      </div>

      <div className="tl-track">
        {segments.map((seg, i) => {
          const left  = pct(seg.start_time, totalDuration)
          const width = pct(seg.end_time - seg.start_time, totalDuration)
          const color = TYPE_COLORS[seg.segment_type] || TYPE_COLORS.body
          return (
            <div
              key={i}
              className="tl-seg"
              style={{ left, width, '--seg-color': color }}
              title={`${seg.headline} (${fmt(seg.start_time)} – ${fmt(seg.end_time)})`}
            >
              <span className="tl-seg-label">{i + 1}</span>
            </div>
          )
        })}
        {/* Playhead */}
        <div className="tl-playhead" style={{ left: playheadLeft }} />
      </div>

      {/* Timestamp markers */}
      <div className="tl-markers">
        {[0, 0.25, 0.5, 0.75, 1].map(r => (
          <span key={r} style={{ left: `${r * 100}%` }} className="tl-marker">
            {fmt(totalDuration * r)}
          </span>
        ))}
      </div>

      {/* Legend */}
      <div className="tl-legend">
        {Object.entries(TYPE_COLORS).map(([type, color]) => (
          <div key={type} className="tl-leg-item">
            <div className="tl-leg-dot" style={{ background: color }} />
            <span>{type}</span>
          </div>
        ))}
      </div>

      <style>{`
        .tl-wrapper {
          background: var(--bg-card);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-lg);
          padding: 20px 24px;
          display: flex; flex-direction: column; gap: 14px;
        }
        .tl-header { display: flex; justify-content: space-between; align-items: center; }
        .tl-title { font-size: 14px; font-weight: 700; color: rgba(255,255,255,0.8); }
        .tl-dur { font-size: 12px; font-family: var(--font-mono); color: rgba(255,255,255,0.4); }
        .tl-track {
          position: relative; height: 36px;
          background: rgba(255,255,255,0.04);
          border-radius: 8px; overflow: visible;
        }
        .tl-seg {
          position: absolute; height: 100%;
          background: var(--seg-color);
          opacity: 0.75;
          border-radius: 4px;
          border: 1px solid rgba(255,255,255,0.1);
          display: flex; align-items: center; justify-content: center;
          overflow: hidden;
          transition: opacity var(--transition-fast);
          cursor: pointer;
          box-sizing: border-box;
        }
        .tl-seg:hover { opacity: 1; z-index: 2; }
        .tl-seg-label {
          font-size: 10px; font-weight: 800; color: white;
          text-shadow: 0 1px 2px rgba(0,0,0,0.5);
        }
        .tl-playhead {
          position: absolute; top: -4px; bottom: -4px;
          width: 2px; background: white;
          border-radius: 2px;
          box-shadow: 0 0 8px white;
          pointer-events: none;
          z-index: 3;
        }
        .tl-markers {
          position: relative; height: 16px;
        }
        .tl-marker {
          position: absolute; transform: translateX(-50%);
          font-size: 10px; font-family: var(--font-mono);
          color: rgba(255,255,255,0.25);
        }
        .tl-legend {
          display: flex; gap: 16px;
        }
        .tl-leg-item {
          display: flex; align-items: center; gap: 6px;
          font-size: 11px; color: rgba(255,255,255,0.45);
          text-transform: capitalize;
        }
        .tl-leg-dot {
          width: 10px; height: 10px; border-radius: 3px;
        }
      `}</style>
    </div>
  )
}
