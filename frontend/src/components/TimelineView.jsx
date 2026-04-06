import { resolveAssetUrl } from '../api/client.js'

function fmt(seconds) {
  const safe = Math.max(0, Number(seconds || 0))
  const m = Math.floor(safe / 60)
  const s = Math.floor(safe % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function pct(value, total) {
  return `${((value / Math.max(total, 1)) * 100).toFixed(2)}%`
}

function getActiveSegment(segments = [], currentTime = 0) {
  return (
    segments.find((segment) => currentTime >= segment.start_time && currentTime <= segment.end_time) ||
    segments[0] ||
    null
  )
}

function markerTimes(segments = [], totalDuration = 0) {
  const times = [0, totalDuration]
  for (const segment of segments) {
    times.push(Number(segment.start_time || 0))
    times.push(Number(segment.end_time || 0))
  }

  const minGap = Math.max(totalDuration / 12, 3)
  const sorted = [...new Set(times.filter(Number.isFinite))].sort((a, b) => a - b)
  const collapsed = []
  for (const value of sorted) {
    if (!collapsed.length || value - collapsed[collapsed.length - 1] >= minGap || value === totalDuration) {
      collapsed.push(value)
    }
  }
  return collapsed
}

export default function TimelineView({ segments = [], totalDuration = 0, currentTime = 0 }) {
  if (!segments.length) return null

  const safeDuration = Math.max(Number(totalDuration || 0), Number(segments[segments.length - 1]?.end_time || 0), 1)
  const activeSegment = getActiveSegment(segments, currentTime)
  const playbackPct = Math.max(0, Math.min(100, (Number(currentTime || 0) / safeDuration) * 100))
  const markers = markerTimes(segments, safeDuration)

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
          <span>{fmt(safeDuration)} total</span>
          <span>playhead {playbackPct.toFixed(1)}%</span>
        </div>
      </div>

      <article className="timeline-live-summary">
        <div className="timeline-live-top">
          <span>Now playing</span>
          <strong>{activeSegment?.start_timecode} - {activeSegment?.end_timecode}</strong>
        </div>
        <h3>{activeSegment?.main_headline}</h3>
        <p>{activeSegment?.subheadline}</p>
        <div className="timeline-live-chips">
          <span>{activeSegment?.layout || 'layout n/a'}</span>
          <span>{activeSegment?.camera_motion || 'motion n/a'}</span>
          <span>{activeSegment?.transition || 'transition n/a'}</span>
          <span>{activeSegment?.visual_source_kind || 'visual source n/a'}</span>
        </div>
        <div className="timeline-live-note">
          {activeSegment?.control_room_cue || activeSegment?.director_note || activeSegment?.editorial_focus || 'Awaiting active direction cues.'}
        </div>
      </article>

      <div className="timeline-segment-rail">
        {segments.map((segment, index) => {
          const isActive = currentTime >= segment.start_time && currentTime <= segment.end_time
          return (
            <div
              key={`rail-${segment.segment_id}`}
              className={`timeline-segment-pill ${isActive ? 'timeline-segment-pill--active' : ''}`}
            >
              <strong>{index + 1}</strong>
              <span>{segment.main_headline}</span>
              <em>{segment.start_timecode} - {segment.end_timecode}</em>
            </div>
          )
        })}
      </div>

      <div className="timeline-track">
        {segments.map((segment) => (
          <div
            key={segment.segment_id}
            className={`timeline-bar ${currentTime >= segment.start_time && currentTime <= segment.end_time ? 'timeline-bar--active' : ''}`}
            style={{
              left: pct(segment.start_time, safeDuration),
              width: pct(segment.end_time - segment.start_time, safeDuration),
            }}
            title={`${segment.main_headline} · ${segment.start_timecode} - ${segment.end_timecode}`}
          >
            <span>{segment.segment_id}</span>
          </div>
        ))}
        <div className="timeline-playhead" style={{ left: pct(currentTime, safeDuration) }} />
      </div>

      <div className="timeline-markers">
        {markers.map((value) => (
          <span key={`marker-${value}`} style={{ left: pct(value, safeDuration) }}>{fmt(value)}</span>
        ))}
      </div>

      <div className="timeline-grid">
        {segments.map((segment, index) => {
          const isActive = currentTime >= segment.start_time && currentTime <= segment.end_time
          const frameUrl = resolveAssetUrl(segment.html_frame_url)
          const sceneImageUrl = resolveAssetUrl(segment.scene_image_url)
          return (
          <article
            key={segment.segment_id}
            className={`timeline-card ${isActive ? 'timeline-card--active' : ''}`}
          >
            <div className="timeline-card-media">
              {frameUrl ? (
                <iframe
                  src={frameUrl}
                  title={`frame-${segment.segment_id}`}
                  loading="lazy"
                  sandbox="allow-same-origin"
                  scrolling="no"
                />
              ) : sceneImageUrl ? (
                <img src={sceneImageUrl} alt={segment.main_headline} />
              ) : (
                <div className="timeline-card-fallback">{segment.top_tag}</div>
              )}
            </div>
            <div className="timeline-card-body">
              <div className="timeline-card-top">
                <span className="timeline-tag">#{index + 1} · {segment.top_tag}</span>
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
              {segment.control_room_cue && (
                <div className="timeline-detail-row">
                  <span>Control cue</span>
                  <strong>{segment.control_room_cue}</strong>
                </div>
              )}
              {frameUrl && (
                <div className="timeline-detail-row">
                  <span>HTML frame</span>
                  <strong><a href={frameUrl} target="_blank" rel="noreferrer">Open preview</a></strong>
                </div>
              )}
            </div>
          </article>
        )})}
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
        .timeline-live-summary {
          display: flex;
          flex-direction: column;
          gap: 10px;
          border-radius: 20px;
          padding: 16px 18px;
          background: linear-gradient(160deg, rgba(17,25,44,0.9), rgba(8,12,22,0.9));
          border: 1px solid rgba(59,130,246,0.22);
        }
        .timeline-live-top {
          display: flex;
          justify-content: space-between;
          gap: 10px;
          flex-wrap: wrap;
          align-items: center;
        }
        .timeline-live-top span {
          font-size: 11px;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.48);
        }
        .timeline-live-top strong {
          font-size: 14px;
          color: #dbeafe;
          font-family: var(--font-mono);
        }
        .timeline-live-summary h3 {
          font-size: 24px;
          line-height: 1.15;
        }
        .timeline-live-summary p {
          font-size: 14px;
          line-height: 1.7;
          color: rgba(255,255,255,0.7);
        }
        .timeline-live-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .timeline-live-chips span {
          font-size: 11px;
          color: rgba(255,255,255,0.74);
          border-radius: 999px;
          padding: 5px 9px;
          border: 1px solid rgba(255,255,255,0.12);
          background: rgba(255,255,255,0.05);
        }
        .timeline-live-note {
          font-size: 13px;
          line-height: 1.7;
          color: rgba(219,234,254,0.9);
          border-radius: 14px;
          padding: 10px 12px;
          background: rgba(59,130,246,0.1);
          border: 1px solid rgba(59,130,246,0.18);
        }
        .timeline-segment-rail {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 10px;
        }
        .timeline-segment-pill {
          display: flex;
          flex-direction: column;
          gap: 5px;
          border-radius: 14px;
          padding: 10px 12px;
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.08);
        }
        .timeline-segment-pill--active {
          border-color: rgba(239,68,68,0.34);
          background: rgba(239,68,68,0.08);
          box-shadow: inset 0 0 0 1px rgba(239,68,68,0.15);
        }
        .timeline-segment-pill strong {
          font-size: 11px;
          color: rgba(255,255,255,0.86);
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }
        .timeline-segment-pill span {
          font-size: 12px;
          line-height: 1.5;
          color: rgba(255,255,255,0.72);
        }
        .timeline-segment-pill em {
          font-size: 11px;
          color: rgba(255,255,255,0.5);
          font-style: normal;
          font-family: var(--font-mono);
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
        .timeline-bar span {
          overflow: hidden;
          white-space: nowrap;
          text-overflow: ellipsis;
          max-width: 100%;
          padding: 0 6px;
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
          aspect-ratio: 16 / 9;
          min-height: 0;
          overflow: hidden;
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
          .timeline-live-summary h3 {
            font-size: 20px;
          }
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
