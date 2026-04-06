import { useMemo, useRef, useState } from 'react'
import {
  Captions,
  Check,
  Clipboard,
  FileJson,
  Maximize2,
  Pause,
  Play,
  ScrollText,
  Volume2,
  VolumeX,
} from 'lucide-react'
import { resolveAssetUrl } from '../api/client.js'

function formatTime(seconds) {
  const safe = Math.max(0, Number(seconds || 0))
  const mins = Math.floor(safe / 60)
  const secs = Math.floor(safe % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function buildTranscriptText(cues = []) {
  return cues
    .map((cue) => `${cue.start_timecode || formatTime(cue.start_time)} ${cue.text || ''}`.trim())
    .join('\n')
}

export default function VideoPlayer({
  videoUrl,
  title,
  script = null,
  activeSegment = null,
  onProgress,
  llmEnhanced = false,
}) {
  const videoRef = useRef(null)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [progress, setProgress] = useState(0)
  const [duration, setDuration] = useState(0)
  const [hover, setHover] = useState(false)
  const [playbackTime, setPlaybackTime] = useState(0)
  const [panelMode, setPanelMode] = useState(null)
  const [showCaptions, setShowCaptions] = useState(true)
  const [copyState, setCopyState] = useState('')

  const transcriptCues = script?.live_transcript || []
  const screenplayText = script?.screenplay_text || ''
  const jsonText = useMemo(() => (script ? JSON.stringify(script, null, 2) : ''), [script])
  const resolvedVideoUrl = useMemo(() => resolveAssetUrl(videoUrl), [videoUrl])

  const activeCue = useMemo(() => {
    if (!transcriptCues.length) return null
    const current = transcriptCues.find(
      (cue) => playbackTime >= cue.start_time && playbackTime <= cue.end_time,
    )
    if (current) return current

    // Briefly hold the previous cue to avoid pre-showing the next line.
    for (let i = transcriptCues.length - 1; i >= 0; i -= 1) {
      const cue = transcriptCues[i]
      if (playbackTime >= cue.start_time) {
        if (playbackTime - cue.end_time <= 0.25) return cue
        break
      }
    }

    return null
  }, [transcriptCues, playbackTime])

  const transcriptPanelCues = useMemo(() => {
    if (!transcriptCues.length) return []
    if (!activeSegment) return transcriptCues.slice(0, 16)
    const scoped = transcriptCues.filter((cue) => cue.segment_id === activeSegment.segment_id)
    return scoped.length ? scoped : transcriptCues.slice(0, 16)
  }, [transcriptCues, activeSegment])

  const panelTitle =
    panelMode === 'transcript'
      ? 'Live transcript'
      : panelMode === 'screenplay'
        ? 'Screenplay'
        : panelMode === 'json'
          ? 'Structured JSON'
          : ''

  const panelText = panelMode === 'screenplay' ? screenplayText : panelMode === 'json' ? jsonText : ''

  const tickerLabel = activeSegment?.top_tag || 'BREAKING'
  const tickerText = activeSegment?.ticker_text || activeSegment?.main_headline || title

  function togglePlay() {
    const player = videoRef.current
    if (!player) return
    if (playing) {
      player.pause()
    } else {
      player.play()
    }
    setPlaying((prev) => !prev)
  }

  function handleTimeUpdate() {
    const player = videoRef.current
    if (!player) return
    const pct = (player.currentTime / player.duration) * 100
    setProgress(Number.isFinite(pct) ? pct : 0)
    setPlaybackTime(player.currentTime || 0)
    onProgress?.(player.currentTime, player.duration)
  }

  function handleSeek(event) {
    const player = videoRef.current
    if (!player) return
    const rect = event.currentTarget.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
    player.currentTime = ratio * player.duration
  }

  function handleFullscreen() {
    if (videoRef.current?.requestFullscreen) videoRef.current.requestFullscreen()
  }

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

  return (
    <div
      className={`vp-wrapper fade-up ${hover ? 'vp-hover' : ''}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div className="vp-ticker">
        <div className="vp-ticker-badge">● {tickerLabel}</div>
        <div className="vp-ticker-track">
          <span className="ticker-text">{tickerText} &nbsp;&nbsp;&nbsp; {tickerText} &nbsp;&nbsp;&nbsp; {tickerText}</span>
        </div>
      </div>

      <div className="vp-video-wrap" onClick={togglePlay}>
        <video
          ref={videoRef}
          id="news-video-player"
          src={resolvedVideoUrl}
          className="vp-video"
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetadata={(event) => setDuration(event.target.duration || 0)}
          onEnded={() => setPlaying(false)}
          muted={muted}
          playsInline
        />

        {showCaptions && activeCue?.text && (
          <div className="vp-caption-overlay" aria-live="polite">
            <p>{activeCue.text}</p>
          </div>
        )}

        {!playing && (
          <div className="vp-play-overlay">
            <div className="vp-play-btn">
              <Play size={32} fill="white" />
            </div>
          </div>
        )}
      </div>

      <div className={`vp-controls ${hover || !playing ? 'vp-controls--visible' : ''}`}>
        {activeSegment && (
          <div className="vp-now-playing">
            <span>{activeSegment.start_timecode} - {activeSegment.end_timecode}</span>
            <strong>{activeSegment.lower_third || activeSegment.main_headline}</strong>
          </div>
        )}

        <div className="vp-seek" onClick={handleSeek}>
          <div className="vp-seek-fill" style={{ width: `${progress}%` }} />
          <div className="vp-seek-thumb" style={{ left: `${progress}%` }} />
        </div>

        <div className="vp-ctrl-row">
          <button id="vp-play-pause" className="vp-ctrl-btn" onClick={togglePlay}>
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </button>

          <button
            id="vp-mute"
            className="vp-ctrl-btn"
            onClick={() => {
              setMuted((prev) => !prev)
              if (videoRef.current) videoRef.current.muted = !muted
            }}
          >
            {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
          </button>

          <span className="vp-time">
            {formatTime(playbackTime)} / {formatTime(duration)}
          </span>

          <div className="vp-ctrl-spacer" />

          <span className="vp-live-badge">● {llmEnhanced ? 'LLM EDIT ASSISTED' : 'AUTOMATED NEWS PACKAGE'}</span>

          <button id="vp-fullscreen" className="vp-ctrl-btn" onClick={handleFullscreen}>
            <Maximize2 size={18} />
          </button>
        </div>

        <div className="vp-action-row">
          <button
            type="button"
            className={`vp-action-btn ${panelMode === 'transcript' ? 'vp-action-btn--active' : ''}`}
            onClick={() => setPanelMode((value) => (value === 'transcript' ? null : 'transcript'))}
          >
            <ScrollText size={14} /> Transcript
          </button>

          <button
            type="button"
            className={`vp-action-btn ${panelMode === 'screenplay' ? 'vp-action-btn--active' : ''}`}
            onClick={() => setPanelMode((value) => (value === 'screenplay' ? null : 'screenplay'))}
          >
            <ScrollText size={14} /> Screenplay
          </button>

          <button
            type="button"
            className={`vp-action-btn ${panelMode === 'json' ? 'vp-action-btn--active' : ''}`}
            onClick={() => setPanelMode((value) => (value === 'json' ? null : 'json'))}
          >
            <FileJson size={14} /> JSON
          </button>

          <button
            type="button"
            className={`vp-action-btn ${showCaptions ? 'vp-action-btn--active' : ''}`}
            onClick={() => setShowCaptions((value) => !value)}
          >
            <Captions size={14} /> {showCaptions ? 'Captions on' : 'Captions off'}
          </button>

          {panelMode && (
            <button
              type="button"
              className="vp-action-btn"
              onClick={() => {
                if (panelMode === 'transcript') {
                  copyText(buildTranscriptText(transcriptPanelCues), 'Transcript copied')
                  return
                }
                copyText(panelText, panelMode === 'json' ? 'JSON copied' : 'Screenplay copied')
              }}
            >
              {copyState ? <Check size={14} /> : <Clipboard size={14} />} Copy
            </button>
          )}

          {copyState && <span className="vp-copy-state">{copyState}</span>}
        </div>
      </div>

      {panelMode && (
        <div className="vp-panel">
          <div className="vp-panel-head">
            <strong>{panelTitle}</strong>
            {panelMode === 'transcript' ? (
              <span>{transcriptPanelCues.length} cues</span>
            ) : (
              <span>{panelMode === 'json' ? 'Structured payload' : 'Human-readable script'}</span>
            )}
          </div>

          {panelMode === 'transcript' ? (
            <div className="vp-transcript-list">
              {transcriptPanelCues.map((cue) => (
                <div
                  key={cue.id}
                  className={`vp-transcript-item ${activeCue?.id === cue.id ? 'vp-transcript-item--active' : ''}`}
                >
                  <span>{cue.start_timecode || formatTime(cue.start_time)}</span>
                  <p>{cue.text}</p>
                </div>
              ))}
            </div>
          ) : (
            <pre className="vp-panel-pre">{panelText || 'No content available for this run.'}</pre>
          )}
        </div>
      )}

      <style>{`
        .vp-wrapper {
          border-radius: var(--radius-lg);
          overflow: hidden;
          background: #000;
          border: 1px solid var(--border-subtle);
          box-shadow: var(--shadow-card), 0 0 60px rgba(59,130,246,0.08);
          position: relative;
          transition: box-shadow var(--transition-base);
        }
        .vp-hover {
          box-shadow: var(--shadow-glow), var(--shadow-card);
        }
        .vp-ticker {
          display: flex;
          align-items: center;
          overflow: hidden;
          background: #0a0a1a;
          height: 36px;
          border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .vp-ticker-badge {
          background: var(--gradient-ticker);
          color: white;
          font-size: 11px;
          font-weight: 800;
          letter-spacing: 0.1em;
          padding: 0 16px;
          height: 100%;
          display: flex;
          align-items: center;
          white-space: nowrap;
          flex-shrink: 0;
        }
        .vp-ticker-track {
          flex: 1;
          overflow: hidden;
          position: relative;
          height: 100%;
          display: flex;
          align-items: center;
          padding-left: 12px;
        }
        .ticker-text {
          color: rgba(255,220,50,0.9);
          font-size: 12px;
          font-weight: 500;
          white-space: nowrap;
        }
        .vp-video-wrap {
          position: relative;
          cursor: pointer;
          background: #000;
        }
        .vp-video {
          width: 100%;
          display: block;
          aspect-ratio: 16/9;
          object-fit: cover;
        }
        .vp-caption-overlay {
          position: absolute;
          left: 0;
          right: 0;
          bottom: 18px;
          display: flex;
          justify-content: center;
          pointer-events: none;
          padding: 0 16px;
        }
        .vp-caption-overlay p {
          margin: 0;
          width: fit-content;
          max-width: 94%;
          font-size: clamp(14px, 2.1vw, 20px);
          line-height: 1.45;
          color: #f8fafc;
          text-align: center;
          background: rgba(2,6,23,0.72);
          border: 1px solid rgba(255,255,255,0.22);
          border-radius: 10px;
          padding: 8px 12px;
          text-wrap: pretty;
          overflow-wrap: anywhere;
          text-shadow: 0 1px 2px rgba(0,0,0,0.45);
        }
        .vp-play-overlay {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          background: rgba(0,0,0,0.3);
          transition: opacity var(--transition-fast);
        }
        .vp-play-btn {
          width: 72px;
          height: 72px;
          border-radius: 50%;
          background: rgba(59,130,246,0.85);
          display: flex;
          align-items: center;
          justify-content: center;
          box-shadow: 0 0 0 12px rgba(59,130,246,0.2), var(--shadow-button);
          transition: transform var(--transition-spring);
        }
        .vp-play-btn:hover {
          transform: scale(1.08);
        }
        .vp-controls {
          background: linear-gradient(to top, rgba(0,0,0,0.95) 0%, transparent 100%);
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 10px;
          opacity: 0;
          transition: opacity var(--transition-base);
        }
        .vp-controls--visible {
          opacity: 1;
        }
        .vp-now-playing {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: center;
          flex-wrap: wrap;
          font-size: 12px;
          color: rgba(255,255,255,0.68);
        }
        .vp-now-playing span {
          font-family: var(--font-mono);
        }
        .vp-now-playing strong {
          color: white;
          font-size: 13px;
          line-height: 1.5;
          overflow-wrap: anywhere;
        }
        .vp-seek {
          height: 4px;
          border-radius: 2px;
          background: rgba(255,255,255,0.15);
          cursor: pointer;
          position: relative;
        }
        .vp-seek-fill {
          height: 100%;
          background: var(--accent-blue);
          border-radius: 2px;
          transition: width 0.1s linear;
        }
        .vp-seek-thumb {
          position: absolute;
          top: 50%;
          transform: translate(-50%, -50%);
          width: 12px;
          height: 12px;
          border-radius: 50%;
          background: white;
          box-shadow: 0 0 6px rgba(59,130,246,0.8);
          transition: left 0.1s linear;
        }
        .vp-ctrl-row {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
        }
        .vp-ctrl-btn {
          background: none;
          border: none;
          cursor: pointer;
          color: rgba(255,255,255,0.8);
          padding: 4px;
          border-radius: 4px;
          transition: all var(--transition-fast);
          display: flex;
          align-items: center;
        }
        .vp-ctrl-btn:hover {
          color: var(--accent-blue);
          background: rgba(59,130,246,0.1);
        }
        .vp-time {
          font-family: var(--font-mono);
          font-size: 12px;
          color: rgba(255,255,255,0.58);
        }
        .vp-ctrl-spacer {
          flex: 1;
        }
        .vp-live-badge {
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.1em;
          color: var(--accent-blue);
          padding: 3px 8px;
          border: 1px solid rgba(59,130,246,0.4);
          border-radius: 4px;
          background: rgba(59,130,246,0.1);
        }
        .vp-action-row {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }
        .vp-action-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          border: 1px solid rgba(255,255,255,0.16);
          background: rgba(255,255,255,0.06);
          color: rgba(255,255,255,0.82);
          border-radius: 999px;
          padding: 6px 10px;
          font-size: 11px;
          font-weight: 700;
          cursor: pointer;
          transition: all var(--transition-fast);
        }
        .vp-action-btn--active,
        .vp-action-btn:hover {
          border-color: rgba(59,130,246,0.42);
          background: rgba(59,130,246,0.14);
          color: #dbeafe;
        }
        .vp-copy-state {
          font-size: 11px;
          color: #86efac;
          background: rgba(34,197,94,0.12);
          border: 1px solid rgba(34,197,94,0.3);
          border-radius: 999px;
          padding: 5px 9px;
        }
        .vp-panel {
          border-top: 1px solid rgba(255,255,255,0.08);
          background: rgba(4,7,13,0.92);
          padding: 12px 14px 14px;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .vp-panel-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          flex-wrap: wrap;
        }
        .vp-panel-head strong {
          font-size: 12px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.82);
        }
        .vp-panel-head span {
          font-size: 11px;
          color: rgba(255,255,255,0.58);
        }
        .vp-panel-pre {
          margin: 0;
          max-height: 240px;
          overflow: auto;
          white-space: pre-wrap;
          word-break: break-word;
          font-size: 12px;
          line-height: 1.6;
          color: rgba(255,255,255,0.84);
          font-family: var(--font-mono);
          background: rgba(255,255,255,0.03);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 10px;
          padding: 10px;
        }
        .vp-transcript-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          max-height: 240px;
          overflow: auto;
          padding-right: 4px;
        }
        .vp-transcript-item {
          display: grid;
          grid-template-columns: 52px minmax(0, 1fr);
          gap: 10px;
          padding: 8px 10px;
          border-radius: 10px;
          border: 1px solid rgba(255,255,255,0.08);
          background: rgba(255,255,255,0.03);
        }
        .vp-transcript-item--active {
          border-color: rgba(59,130,246,0.35);
          background: rgba(59,130,246,0.12);
        }
        .vp-transcript-item span {
          font-size: 11px;
          font-family: var(--font-mono);
          color: rgba(255,255,255,0.48);
        }
        .vp-transcript-item p {
          margin: 0;
          font-size: 12px;
          line-height: 1.6;
          color: rgba(255,255,255,0.82);
          overflow-wrap: anywhere;
        }
        @media (max-width: 780px) {
          .vp-controls {
            padding: 12px;
          }
          .vp-live-badge {
            letter-spacing: 0.05em;
          }
          .vp-caption-overlay {
            bottom: 12px;
          }
        }
      `}</style>
    </div>
  )
}
