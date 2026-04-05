// components/DownloadButton.jsx
import { Download, CheckCircle } from 'lucide-react'
import { useState } from 'react'

export default function DownloadButton({ videoUrl, jobId }) {
  const [downloading, setDownloading] = useState(false)
  const [done, setDone] = useState(false)

  async function handleDownload() {
    setDownloading(true)
    try {
      const res = await fetch(videoUrl)
      const blob = await res.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `algsoch_news_${jobId}.mp4`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      setDone(true)
      setTimeout(() => setDone(false), 3000)
    } catch (err) {
      console.error('Download failed:', err)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <button
      id="download-video-btn"
      className={`dl-btn ${done ? 'dl-btn--done' : ''}`}
      onClick={handleDownload}
      disabled={downloading}
    >
      {done
        ? <><CheckCircle size={18} /> Downloaded!</>
        : downloading
        ? <><span className="spinner" /> Downloading…</>
        : <><Download size={18} /> Download MP4</>
      }
      <style>{`
        .dl-btn {
          display: flex; align-items: center; gap: 10px;
          padding: 14px 28px; border-radius: var(--radius-md);
          background: rgba(16,185,129,0.15);
          border: 1px solid rgba(16,185,129,0.4);
          color: var(--accent-green);
          font-family: var(--font-sans); font-size: 14px; font-weight: 700;
          cursor: pointer;
          transition: all var(--transition-spring);
        }
        .dl-btn:hover:not(:disabled) {
          background: rgba(16,185,129,0.25);
          transform: translateY(-2px);
          box-shadow: 0 6px 24px rgba(16,185,129,0.3);
        }
        .dl-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .dl-btn--done {
          background: rgba(16,185,129,0.2);
          border-color: var(--accent-green);
        }
      `}</style>
    </button>
  )
}
