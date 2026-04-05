import { Captions, Clapperboard, Radio, Rows3 } from 'lucide-react'

function getActiveSegment(segments = [], currentTime = 0) {
  return (
    segments.find((segment) => currentTime >= segment.start_time && currentTime <= segment.end_time) ||
    segments[0] ||
    null
  )
}

function getActiveCue(script, currentTime) {
  const cues = script?.live_transcript || []
  return (
    cues.find((cue) => currentTime >= cue.start_time && currentTime <= cue.end_time) ||
    cues[0] ||
    null
  )
}

export default function LiveControlRoom({ script, currentTime = 0 }) {
  if (!script?.segments?.length) return null

  const activeSegment = getActiveSegment(script.segments, currentTime)
  const activeCue = getActiveCue(script, currentTime)
  const visibleCues = (script.live_transcript || []).filter((cue) => cue.segment_id === activeSegment?.segment_id)

  return (
    <section className="control-room fade-up">
      <div className="control-room-head">
        <div>
          <p className="control-room-kicker">Live production desk</p>
          <h2>Control Room</h2>
          <div className="control-room-owners">
            <span>Timeline: Visual Packaging Agent</span>
            <span>Render: Video Generation Agent</span>
            <span>Editorial: News Editor Agent</span>
          </div>
        </div>
        <div className="control-room-time">
          <span>Now Playing</span>
          <strong>{activeSegment?.start_timecode} - {activeSegment?.end_timecode}</strong>
        </div>
      </div>

      <div className="control-room-grid">
        <article className="control-card control-card--primary">
          <div className="control-card-label"><Radio size={14} /> Active segment</div>
          <div className="control-live-tag">{activeSegment?.top_tag}</div>
          <h3>{activeSegment?.main_headline}</h3>
          <p className="control-subheadline">{activeSegment?.subheadline}</p>
          <div className="control-chip-row">
            <span>{activeSegment?.layout}</span>
            <span>{activeSegment?.camera_motion}</span>
            <span>{activeSegment?.transition}</span>
          </div>
          <p className="control-note">{activeSegment?.control_room_cue}</p>
          <p className="control-director">{activeSegment?.director_note}</p>
        </article>

        <article className="control-card">
          <div className="control-card-label"><Clapperboard size={14} /> On-screen package</div>
          <div className="control-stat"><span>Lower third</span><strong>{activeSegment?.lower_third}</strong></div>
          <div className="control-stat"><span>Ticker</span><strong>{activeSegment?.ticker_text}</strong></div>
          <div className="control-stat"><span>Visual source</span><strong>{activeSegment?.visual_source_kind}</strong></div>
          <div className="control-stat"><span>Focus</span><strong>{activeSegment?.editorial_focus}</strong></div>
        </article>

        <article className="control-card">
          <div className="control-card-label"><Captions size={14} /> Live transcript</div>
          <div className="control-transcript-live">{activeCue?.text || activeSegment?.anchor_narration}</div>
          <div className="control-transcript-list">
            {visibleCues.map((cue) => (
              <div
                key={cue.id}
                className={`control-transcript-item ${activeCue?.id === cue.id ? 'control-transcript-item--active' : ''}`}
              >
                <span>{cue.start_timecode}</span>
                <p>{cue.text}</p>
              </div>
            ))}
          </div>
        </article>

        <article className="control-card">
          <div className="control-card-label"><Rows3 size={14} /> Rundown</div>
          <div className="control-rundown-list">
            {(script.rundown || []).map((item) => (
              <div
                key={item.segment_id}
                className={`control-rundown-item ${item.segment_id === activeSegment?.segment_id ? 'control-rundown-item--active' : ''}`}
              >
                <div>
                  <strong>{item.slug}</strong>
                  <p>{item.start_timecode} - {item.end_timecode}</p>
                </div>
                <span>{item.camera_motion}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="control-card">
          <div className="control-card-label"><Rows3 size={14} /> Desk ownership</div>
          <div className="control-owner-list">
            <div className="control-owner-item"><span>Timeline desk</span><strong>Visual Packaging Agent</strong></div>
            <div className="control-owner-item"><span>Graphics + transitions</span><strong>Visual Packaging Agent</strong></div>
            <div className="control-owner-item"><span>Transcript alignment</span><strong>Video Generation Agent</strong></div>
            <div className="control-owner-item"><span>Final render</span><strong>Video Generation Agent</strong></div>
          </div>
        </article>
      </div>

      <style>{`
        .control-room {
          display: flex;
          flex-direction: column;
          gap: 18px;
        }
        .control-room-head {
          display: flex;
          justify-content: space-between;
          gap: 16px;
          align-items: end;
          flex-wrap: wrap;
        }
        .control-room-kicker {
          font-size: 11px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.42);
          margin-bottom: 6px;
        }
        .control-room-head h2 {
          font-size: 24px;
        }
        .control-room-owners {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 10px;
        }
        .control-room-owners span {
          font-size: 11px;
          color: rgba(255,255,255,0.72);
          background: rgba(59,130,246,0.12);
          border: 1px solid rgba(59,130,246,0.22);
          border-radius: 999px;
          padding: 5px 9px;
        }
        .control-room-time {
          display: flex;
          flex-direction: column;
          gap: 4px;
          align-items: flex-end;
          color: rgba(255,255,255,0.62);
          font-size: 12px;
        }
        .control-room-time strong {
          font-size: 18px;
          color: white;
          font-family: var(--font-mono);
        }
        .control-room-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 14px;
        }
        .control-card {
          background: rgba(10,14,24,0.92);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 22px;
          padding: 18px;
          display: flex;
          flex-direction: column;
          gap: 12px;
          box-shadow: 0 16px 40px rgba(0,0,0,0.2);
        }
        .control-card--primary {
          background: linear-gradient(180deg, rgba(14,22,42,0.96), rgba(10,14,24,0.96));
          border-color: rgba(59,130,246,0.2);
        }
        .control-card-label {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          font-size: 10px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.36);
        }
        .control-live-tag {
          width: fit-content;
          border-radius: 999px;
          padding: 6px 10px;
          font-size: 11px;
          font-weight: 800;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: #fecaca;
          background: rgba(239,68,68,0.14);
          border: 1px solid rgba(239,68,68,0.28);
        }
        .control-card h3 {
          font-size: 26px;
          line-height: 1.1;
        }
        .control-subheadline {
          color: rgba(255,255,255,0.62);
          font-size: 14px;
          line-height: 1.7;
        }
        .control-chip-row {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }
        .control-chip-row span {
          font-size: 11px;
          color: rgba(255,255,255,0.74);
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 999px;
          padding: 5px 8px;
        }
        .control-note {
          color: rgba(255,255,255,0.86);
          line-height: 1.7;
          font-size: 13px;
        }
        .control-director {
          color: #bfdbfe;
          line-height: 1.7;
          font-size: 13px;
          background: rgba(59,130,246,0.1);
          border: 1px solid rgba(59,130,246,0.18);
          border-radius: 14px;
          padding: 10px 12px;
        }
        .control-stat {
          display: grid;
          grid-template-columns: 110px minmax(0, 1fr);
          gap: 10px;
          align-items: start;
        }
        .control-stat span {
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.34);
        }
        .control-stat strong {
          font-size: 13px;
          line-height: 1.6;
          color: rgba(255,255,255,0.84);
        }
        .control-transcript-live {
          font-size: 18px;
          line-height: 1.55;
          color: rgba(255,255,255,0.94);
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 16px;
          padding: 14px;
        }
        .control-transcript-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .control-transcript-item {
          display: grid;
          grid-template-columns: 52px minmax(0, 1fr);
          gap: 10px;
          padding: 10px 12px;
          border-radius: 14px;
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.05);
        }
        .control-transcript-item--active {
          border-color: rgba(59,130,246,0.24);
          background: rgba(59,130,246,0.08);
        }
        .control-transcript-item span {
          font-size: 11px;
          color: rgba(255,255,255,0.4);
          font-family: var(--font-mono);
        }
        .control-transcript-item p {
          font-size: 13px;
          line-height: 1.6;
          color: rgba(255,255,255,0.82);
        }
        .control-rundown-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .control-rundown-item {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: center;
          padding: 12px 14px;
          border-radius: 14px;
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.05);
        }
        .control-rundown-item--active {
          border-color: rgba(16,185,129,0.26);
          background: rgba(16,185,129,0.08);
        }
        .control-rundown-item strong {
          display: block;
          font-size: 13px;
          color: rgba(255,255,255,0.88);
          margin-bottom: 4px;
        }
        .control-rundown-item p {
          font-size: 11px;
          color: rgba(255,255,255,0.4);
          font-family: var(--font-mono);
        }
        .control-rundown-item span {
          flex-shrink: 0;
          font-size: 11px;
          color: #bfdbfe;
          background: rgba(59,130,246,0.1);
          border: 1px solid rgba(59,130,246,0.2);
          border-radius: 999px;
          padding: 5px 8px;
        }
        .control-owner-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .control-owner-item {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: center;
          padding: 10px 12px;
          border-radius: 12px;
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.06);
        }
        .control-owner-item span {
          font-size: 11px;
          color: rgba(255,255,255,0.45);
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }
        .control-owner-item strong {
          font-size: 12px;
          color: rgba(255,255,255,0.9);
        }
        @media (max-width: 980px) {
          .control-room-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </section>
  )
}
