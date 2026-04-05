function fmt(seconds) {
  const safe = Math.max(0, Number(seconds || 0))
  const m = Math.floor(safe / 60)
  const s = Math.floor(safe % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function pct(value, total) {
  return `${((value / Math.max(total, 1)) * 100).toFixed(2)}%`
}

export default function TimelineView({ segments = [], totalDuration = 0, currentTime = 0 }) {
  if (!segments.length) return null

  return (
    <section className="timeline-shell fade-up">
      <div className="timeline-head">
        <div>
          <p className="timeline-kicker">Broadcast rundown</p>
          <h2>Segment Timeline</h2>
          <div className="timeline-owners">
            <span>Timeline owner: Visual Packaging Agent</span>
            <span>Playback owner: Video Generation Agent</span>
          </div>
        </div>
        <div className="timeline-meta">
          <span>{segments.length} segments</span>
          <span>{fmt(totalDuration)} total</span>
        </div>
      </div>

      <div className="timeline-track">
        {segments.map((segment) => (
          <div
            key={segment.segment_id}
            className={`timeline-bar ${currentTime >= segment.start_time && currentTime <= segment.end_time ? 'timeline-bar--active' : ''}`}
            style={{
              left: pct(segment.start_time, totalDuration),
              width: pct(segment.end_time - segment.start_time, totalDuration),
            }}
            title={`${segment.main_headline} · ${segment.start_timecode} - ${segment.end_timecode}`}
          >
            <span>{segment.segment_id}</span>
          </div>
        ))}
        <div className="timeline-playhead" style={{ left: pct(currentTime, totalDuration) }} />
      </div>

      <div className="timeline-markers">
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
          <span key={ratio} style={{ left: `${ratio * 100}%` }}>{fmt(totalDuration * ratio)}</span>
        ))}
      </div>

      <div className="timeline-grid">
        {segments.map((segment) => (
          <article
            key={segment.segment_id}
            className={`timeline-card ${currentTime >= segment.start_time && currentTime <= segment.end_time ? 'timeline-card--active' : ''}`}
          >
            <div className="timeline-card-media">
              {segment.html_frame_url ? (
                <iframe
                  src={segment.html_frame_url}
                  title={`frame-${segment.segment_id}`}
                  loading="lazy"
                  sandbox="allow-same-origin"
                />
              ) : segment.scene_image_url ? (
                <img src={segment.scene_image_url} alt={segment.main_headline} />
              ) : (
                <div className="timeline-card-fallback">{segment.top_tag}</div>
              )}
            </div>
            <div className="timeline-card-body">
              <div className="timeline-card-top">
                <span className="timeline-tag">{segment.top_tag}</span>
                <span className="timeline-time">{segment.start_timecode} - {segment.end_timecode}</span>
              </div>
              <h3>{segment.main_headline}</h3>
              <p className="timeline-subheadline">{segment.subheadline}</p>
              <div className="timeline-detail-row">
                <span>Layout</span>
                <strong>{segment.layout}</strong>
              </div>
              <div className="timeline-detail-row">
                <span>Lower third</span>
                <strong>{segment.lower_third}</strong>
              </div>
              <div className="timeline-detail-row">
                <span>Motion</span>
                <strong>{segment.camera_motion}</strong>
              </div>
              <div className="timeline-detail-row">
                <span>Transition</span>
                <strong>{segment.transition}</strong>
              </div>
              <div className="timeline-detail-row">
                <span>Timeline owner</span>
                <strong>Visual Packaging Agent</strong>
              </div>
              <div className="timeline-detail-row">
                <span>Render owner</span>
                <strong>Video Generation Agent</strong>
              </div>
              <div className="timeline-detail-row">
                <span>Right panel</span>
                <strong>{segment.right_panel}</strong>
              </div>
              {segment.html_frame_url && (
                <div className="timeline-detail-row">
                  <span>HTML frame</span>
                  <strong><a href={segment.html_frame_url} target="_blank" rel="noreferrer">Open preview</a></strong>
                </div>
              )}
            </div>
          </article>
        ))}
      </div>

      <style>{`
        .timeline-shell {
          display: flex;
          flex-direction: column;
          gap: 18px;
        }
        .timeline-head {
          display: flex;
          justify-content: space-between;
          align-items: end;
          gap: 16px;
          flex-wrap: wrap;
        }
        .timeline-kicker {
          font-size: 11px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.42);
          margin-bottom: 6px;
        }
        .timeline-head h2 {
          font-size: 24px;
        }
        .timeline-owners {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 10px;
        }
        .timeline-owners span {
          font-size: 11px;
          color: rgba(255,255,255,0.74);
          background: rgba(59,130,246,0.12);
          border: 1px solid rgba(59,130,246,0.24);
          border-radius: 999px;
          padding: 5px 9px;
        }
        .timeline-meta {
          display: flex;
          gap: 10px;
          flex-wrap: wrap;
        }
        .timeline-meta span {
          font-size: 12px;
          color: rgba(255,255,255,0.68);
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 999px;
          padding: 6px 10px;
        }
        .timeline-track {
          position: relative;
          height: 42px;
          border-radius: 18px;
          background: linear-gradient(180deg, rgba(12,16,28,0.95), rgba(7,10,18,0.95));
          border: 1px solid rgba(255,255,255,0.08);
          overflow: hidden;
        }
        .timeline-bar {
          position: absolute;
          top: 6px;
          bottom: 6px;
          border-radius: 12px;
          background: linear-gradient(90deg, rgba(59,130,246,0.9), rgba(14,165,233,0.9));
          display: flex;
          align-items: center;
          justify-content: center;
          color: white;
          font-size: 11px;
          font-weight: 800;
          border: 1px solid rgba(255,255,255,0.18);
          min-width: 34px;
        }
        .timeline-bar--active {
          background: linear-gradient(90deg, rgba(239,68,68,0.92), rgba(251,191,36,0.92));
        }
        .timeline-playhead {
          position: absolute;
          top: 0;
          bottom: 0;
          width: 2px;
          transform: translateX(-50%);
          background: white;
          box-shadow: 0 0 14px rgba(255,255,255,0.95);
        }
        .timeline-markers {
          position: relative;
          height: 14px;
        }
        .timeline-markers span {
          position: absolute;
          transform: translateX(-50%);
          font-size: 11px;
          color: rgba(255,255,255,0.35);
          font-family: var(--font-mono);
        }
        .timeline-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 14px;
        }
        .timeline-card {
          display: grid;
          grid-template-columns: 210px minmax(0, 1fr);
          background: rgba(10,14,24,0.9);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 20px;
          overflow: hidden;
          box-shadow: 0 16px 40px rgba(0,0,0,0.22);
        }
        .timeline-card--active {
          border-color: rgba(239,68,68,0.26);
          box-shadow: 0 20px 48px rgba(239,68,68,0.14);
        }
        .timeline-card-media {
          background: rgba(255,255,255,0.04);
          min-height: 170px;
        }
        .timeline-card-media img {
          width: 100%;
          height: 100%;
          object-fit: cover;
          display: block;
        }
        .timeline-card-media iframe {
          width: 100%;
          height: 100%;
          border: none;
          display: block;
          background: rgba(8,12,18,0.8);
        }
        .timeline-card a {
          color: #93c5fd;
          text-decoration: underline;
        }
        .timeline-card-fallback {
          height: 100%;
          display: grid;
          place-items: center;
          color: rgba(255,255,255,0.84);
          font-size: 20px;
          font-weight: 800;
          background: linear-gradient(135deg, rgba(59,130,246,0.22), rgba(239,68,68,0.18));
        }
        .timeline-card-body {
          padding: 16px 18px;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .timeline-card-top {
          display: flex;
          justify-content: space-between;
          gap: 10px;
          flex-wrap: wrap;
        }
        .timeline-tag {
          font-size: 11px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: #fca5a5;
          background: rgba(239,68,68,0.12);
          border: 1px solid rgba(239,68,68,0.26);
          border-radius: 999px;
          padding: 5px 8px;
        }
        .timeline-time {
          font-size: 11px;
          color: rgba(255,255,255,0.4);
          font-family: var(--font-mono);
        }
        .timeline-card h3 {
          font-size: 18px;
          line-height: 1.3;
        }
        .timeline-subheadline {
          color: rgba(255,255,255,0.56);
          line-height: 1.6;
          font-size: 13px;
        }
        .timeline-detail-row {
          display: grid;
          grid-template-columns: 90px minmax(0, 1fr);
          gap: 10px;
          font-size: 12px;
          line-height: 1.55;
        }
        .timeline-detail-row span {
          color: rgba(255,255,255,0.34);
          text-transform: uppercase;
          letter-spacing: 0.08em;
          font-size: 10px;
        }
        .timeline-detail-row strong {
          color: rgba(255,255,255,0.82);
          font-weight: 600;
        }
        @media (max-width: 980px) {
          .timeline-grid {
            grid-template-columns: 1fr;
          }
        }
        @media (max-width: 720px) {
          .timeline-card {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </section>
  )
}
