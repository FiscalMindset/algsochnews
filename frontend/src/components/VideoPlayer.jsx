// components/VideoPlayer.jsx
import { useRef, useState } from 'react'
import { Play, Pause, Volume2, VolumeX, Maximize2 } from 'lucide-react'

export default function VideoPlayer({ videoUrl, title }) {
  const videoRef = useRef(null)
  const [playing, setPlaying]   = useState(false)
  const [muted, setMuted]       = useState(false)
  const [progress, setProgress] = useState(0)
  const [duration, setDuration] = useState(0)
  const [hover, setHover]       = useState(false)

  function togglePlay() {
    if (!videoRef.current) return
    if (playing) { videoRef.current.pause() } else { videoRef.current.play() }
    setPlaying(p => !p)
  }

  function handleTimeUpdate() {
    const v = videoRef.current
    if (!v) return
    setProgress((v.currentTime / v.duration) * 100 || 0)
  }

  function handleSeek(e) {
    const v = videoRef.current
    if (!v) return
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = (e.clientX - rect.left) / rect.width
    v.currentTime = ratio * v.duration
  }

  function fmt(s) {
    const m = Math.floor(s / 60)
    const sec = Math.floor(s % 60)
    return `${m}:${sec.toString().padStart(2, '0')}`
  }

  function handleFullscreen() {
    if (videoRef.current?.requestFullscreen) videoRef.current.requestFullscreen()
  }

  return (
    <div
      className={`vp-wrapper fade-up ${hover ? 'vp-hover' : ''}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {/* Breaking news ticker above video */}
      <div className="vp-ticker">
        <div className="vp-ticker-badge">● BREAKING</div>
        <div className="vp-ticker-track">
          <span className="ticker-text">{title} &nbsp;&nbsp;&nbsp; {title} &nbsp;&nbsp;&nbsp; {title}</span>
        </div>
      </div>

      <div className="vp-video-wrap" onClick={togglePlay}>
        <video
          ref={videoRef}
          id="news-video-player"
          src={videoUrl}
          className="vp-video"
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetadata={e => setDuration(e.target.duration)}
          onEnded={() => setPlaying(false)}
          muted={muted}
          playsInline
        />

        {/* Play overlay */}
        {!playing && (
          <div className="vp-play-overlay">
            <div className="vp-play-btn">
              <Play size={32} fill="white" />
            </div>
          </div>
        )}
      </div>

      {/* Controls bar */}
      <div className={`vp-controls ${hover || !playing ? 'vp-controls--visible' : ''}`}>
        <div className="vp-seek" onClick={handleSeek}>
          <div className="vp-seek-fill" style={{ width: `${progress}%` }} />
          <div className="vp-seek-thumb" style={{ left: `${progress}%` }} />
        </div>

        <div className="vp-ctrl-row">
          <button id="vp-play-pause" className="vp-ctrl-btn" onClick={togglePlay}>
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </button>
          <button id="vp-mute" className="vp-ctrl-btn" onClick={() => {
            setMuted(m => !m)
            if (videoRef.current) videoRef.current.muted = !muted
          }}>
            {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
          </button>
          <span className="vp-time">
            {fmt(videoRef.current?.currentTime || 0)} / {fmt(duration)}
          </span>
          <div style={{ flex: 1 }} />
          <span className="vp-live-badge">● AI GENERATED</span>
          <button id="vp-fullscreen" className="vp-ctrl-btn" onClick={handleFullscreen}>
            <Maximize2 size={18} />
          </button>
        </div>
      </div>

      <style>{`
        .vp-wrapper {
          border-radius: var(--radius-lg); overflow: hidden;
          background: #000;
          border: 1px solid var(--border-subtle);
          box-shadow: var(--shadow-card), 0 0 60px rgba(59,130,246,0.08);
          position: relative;
          transition: box-shadow var(--transition-base);
        }
        .vp-hover { box-shadow: var(--shadow-glow), var(--shadow-card); }
        .vp-ticker {
          display: flex; align-items: center; overflow: hidden;
          background: #0A0A1A; height: 36px;
          border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .vp-ticker-badge {
          background: var(--gradient-ticker); color: white;
          font-size: 11px; font-weight: 800; letter-spacing: 0.1em;
          padding: 0 16px; height: 100%;
          display: flex; align-items: center; white-space: nowrap;
          flex-shrink: 0;
        }
        .vp-ticker-track {
          flex: 1; overflow: hidden; position: relative; height: 100%;
          display: flex; align-items: center;
          padding-left: 12px;
        }
        .ticker-text { color: rgba(255,220,50,0.9); font-size: 12px; font-weight: 500; }
        .vp-video-wrap { position: relative; cursor: pointer; background: #000; }
        .vp-video { width: 100%; display: block; aspect-ratio: 16/9; object-fit: cover; }
        .vp-play-overlay {
          position: absolute; inset: 0;
          display: flex; align-items: center; justify-content: center;
          background: rgba(0,0,0,0.3);
          transition: opacity var(--transition-fast);
        }
        .vp-play-btn {
          width: 72px; height: 72px; border-radius: 50%;
          background: rgba(59,130,246,0.85);
          display: flex; align-items: center; justify-content: center;
          box-shadow: 0 0 0 12px rgba(59,130,246,0.2), var(--shadow-button);
          transition: transform var(--transition-spring);
        }
        .vp-play-btn:hover { transform: scale(1.08); }
        .vp-controls {
          background: linear-gradient(to top, rgba(0,0,0,0.95) 0%, transparent 100%);
          padding: 20px 16px 14px;
          display: flex; flex-direction: column; gap: 10px;
          opacity: 0; transition: opacity var(--transition-base);
        }
        .vp-controls--visible { opacity: 1; }
        .vp-seek {
          height: 4px; border-radius: 2px;
          background: rgba(255,255,255,0.15); cursor: pointer;
          position: relative;
        }
        .vp-seek-fill {
          height: 100%; background: var(--accent-blue);
          border-radius: 2px; transition: width 0.1s linear;
        }
        .vp-seek-thumb {
          position: absolute; top: 50%; transform: translate(-50%, -50%);
          width: 12px; height: 12px; border-radius: 50%;
          background: white; box-shadow: 0 0 6px rgba(59,130,246,0.8);
          transition: left 0.1s linear;
        }
        .vp-ctrl-row {
          display: flex; align-items: center; gap: 12px;
        }
        .vp-ctrl-btn {
          background: none; border: none; cursor: pointer;
          color: rgba(255,255,255,0.8); padding: 4px;
          border-radius: 4px; transition: all var(--transition-fast);
          display: flex; align-items: center;
        }
        .vp-ctrl-btn:hover { color: var(--accent-blue); background: rgba(59,130,246,0.1); }
        .vp-time {
          font-family: var(--font-mono); font-size: 12px;
          color: rgba(255,255,255,0.5);
        }
        .vp-live-badge {
          font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
          color: var(--accent-blue); padding: 3px 8px;
          border: 1px solid rgba(59,130,246,0.4); border-radius: 4px;
          background: rgba(59,130,246,0.1);
        }
      `}</style>
    </div>
  )
}
