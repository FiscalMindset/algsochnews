// components/URLInput.jsx
import { useState } from 'react'
import { Link, AlertCircle } from 'lucide-react'

const PLACEHOLDER_URLS = [
  'https://www.bbc.com/news/world-...',
  'https://techcrunch.com/2024/...',
  'https://www.reuters.com/...',
]

function isValidUrl(str) {
  try {
    const u = new URL(str)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}

export default function URLInput({
  onSubmit,
  disabled,
  backendStatus = 'unknown',
  backendStatusMessage = '',
}) {
  const [url, setUrl]         = useState('')
  const [touched, setTouched] = useState(false)
  const [useGemini, setUseGemini]       = useState(true)
  const [maxSegments, setMaxSegments]   = useState(7)
  const [transitionIntensity, setTransitionIntensity] = useState('standard')
  const [transitionProfile, setTransitionProfile] = useState('auto')
  const [deliveryMode, setDeliveryMode] = useState('full_video')
  const [showAdvanced, setShowAdvanced] = useState(false)

  const valid   = isValidUrl(url)
  const invalid = touched && url.length > 0 && !valid

  const backendLabelByState = {
    unknown: 'Backend status unknown',
    checking: 'Checking backend...',
    online: 'Backend live',
    degraded: 'Backend unstable',
    offline: 'Backend offline',
  }
  const backendClassByState = {
    unknown: 'backend-pill--unknown',
    checking: 'backend-pill--checking',
    online: 'backend-pill--online',
    degraded: 'backend-pill--degraded',
    offline: 'backend-pill--offline',
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (!valid || disabled) return
    onSubmit(url.trim(), useGemini, maxSegments, transitionIntensity, transitionProfile, deliveryMode)
  }

  return (
    <div className="url-input-wrapper fade-up">
      <div className="url-input-label">
        <span className="live-dot" />
        <span>Enter news article URL</span>
        <span className={`backend-pill ${backendClassByState[backendStatus] || backendClassByState.unknown}`}>
          {backendLabelByState[backendStatus] || backendLabelByState.unknown}
        </span>
      </div>

      {!!backendStatusMessage && <div className="backend-note">{backendStatusMessage}</div>}

      <form onSubmit={handleSubmit} className="url-form">
        <div className={`url-field ${invalid ? 'url-field--error' : ''} ${valid && touched ? 'url-field--valid' : ''}`}>
          <Link size={18} className="url-icon" />
          <input
            id="article-url-input"
            type="url"
            value={url}
            onChange={e => { setUrl(e.target.value); setTouched(true) }}
            onBlur={() => setTouched(true)}
            placeholder="https://www.bbc.com/news/..."
            disabled={disabled}
            autoComplete="url"
            spellCheck={false}
            className="url-input"
          />
          {url.length > 0 && (
            <button
              type="button"
              className="url-clear"
              onClick={() => { setUrl(''); setTouched(false) }}
              aria-label="Clear URL"
            >✕</button>
          )}
        </div>

        {invalid && (
          <div className="url-error">
            <AlertCircle size={13} />
            <span>Please enter a valid http(s) URL</span>
          </div>
        )}

        {/* Advanced settings toggle */}
        <div className="advanced-toggle" onClick={() => setShowAdvanced(s => !s)}>
          <span>{showAdvanced ? '▲' : '▼'} Advanced settings</span>
        </div>

        {showAdvanced && (
          <div className="advanced-panel fade-up">
            <label className="adv-row">
              <span>Use Gemini editorial refinement</span>
              <div
                id="gemini-toggle"
                className={`toggle ${useGemini ? 'toggle--on' : ''}`}
                onClick={() => setUseGemini(g => !g)}
                role="switch"
                aria-checked={useGemini}
              >
                <div className="toggle-thumb" />
              </div>
            </label>
            <label className="adv-row">
              <span>Max segments: <b>{maxSegments}</b></span>
              <input
                id="max-segments-slider"
                type="range"
                min={3}
                max={12}
                value={maxSegments}
                onChange={e => setMaxSegments(Number(e.target.value))}
                className="segment-slider"
              />
            </label>

            <label className="adv-row adv-row--stack">
              <span>Transition intensity</span>
              <select
                id="transition-intensity-select"
                value={transitionIntensity}
                onChange={e => setTransitionIntensity(e.target.value)}
                className="transition-select"
              >
                <option value="subtle">Subtle</option>
                <option value="standard">Standard</option>
                <option value="dramatic">Dramatic</option>
              </select>
            </label>

            <label className="adv-row adv-row--stack">
              <span>Story transition grammar</span>
              <select
                id="transition-profile-select"
                value={transitionProfile}
                onChange={e => setTransitionProfile(e.target.value)}
                className="transition-select"
              >
                <option value="auto">Auto detect</option>
                <option value="general">General</option>
                <option value="crisis">Crisis</option>
                <option value="politics">Politics</option>
                <option value="sports">Sports</option>
              </select>
            </label>

            <label className="adv-row adv-row--stack">
              <span>Delivery mode</span>
              <select
                id="delivery-mode-select"
                value={deliveryMode}
                onChange={e => setDeliveryMode(e.target.value)}
                className="transition-select"
              >
                <option value="full_video">Full video (script + mp4)</option>
                <option value="editorial_only">Editorial only (no mp4)</option>
              </select>
            </label>
          </div>
        )}

        <button
          id="generate-btn"
          type="submit"
          disabled={!valid || disabled}
          className="generate-btn"
        >
          {disabled ? (
            <>
              <span className="spinner" />
              <span>Generating…</span>
            </>
          ) : (
            <>
              <span className="btn-icon">⚡</span>
              <span>{deliveryMode === 'editorial_only' ? 'Generate Editorial Package' : 'Generate Video'}</span>
            </>
          )}
        </button>
      </form>

      <style>{`
        .url-input-wrapper { width: 100%; }
        .url-input-label {
          display: flex; align-items: center; gap: 10px;
          font-size: 13px; font-weight: 600; letter-spacing: 0.08em;
          text-transform: uppercase; color: rgba(255,255,255,0.5);
          margin-bottom: 12px;
          flex-wrap: wrap;
        }
        .backend-pill {
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          border-radius: 999px;
          padding: 4px 8px;
          border: 1px solid rgba(148,163,184,0.35);
          background: rgba(148,163,184,0.14);
          color: rgba(226,232,240,0.95);
          max-width: 100%;
        }
        .backend-pill--unknown {
          border-color: rgba(148,163,184,0.35);
          background: rgba(148,163,184,0.14);
          color: rgba(226,232,240,0.95);
        }
        .backend-pill--checking {
          border-color: rgba(59,130,246,0.4);
          background: rgba(59,130,246,0.14);
          color: #dbeafe;
        }
        .backend-pill--online {
          border-color: rgba(16,185,129,0.42);
          background: rgba(16,185,129,0.14);
          color: #bbf7d0;
        }
        .backend-pill--degraded {
          border-color: rgba(245,158,11,0.45);
          background: rgba(245,158,11,0.15);
          color: #fde68a;
        }
        .backend-pill--offline {
          border-color: rgba(239,68,68,0.45);
          background: rgba(239,68,68,0.15);
          color: #fecaca;
        }
        .backend-note {
          font-size: 11px;
          color: rgba(255,255,255,0.52);
          font-family: var(--font-mono);
          margin-top: 4px;
          margin-bottom: 10px;
          line-height: 1.55;
          overflow-wrap: anywhere;
        }
        .url-form { display: flex; flex-direction: column; gap: 14px; margin-top: 2px; }
        .url-field {
          display: flex; align-items: center; gap: 12px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: var(--radius-md);
          padding: 14px 18px;
          transition: border-color var(--transition-base), box-shadow var(--transition-base);
        }
        .url-field:focus-within {
          border-color: var(--accent-blue);
          box-shadow: 0 0 0 3px rgba(59,130,246,0.18);
        }
        .url-field--error { border-color: var(--accent-red) !important; }
        .url-field--valid { border-color: rgba(16,185,129,0.5); }
        .url-icon { color: rgba(255,255,255,0.3); flex-shrink: 0; }
        .url-input {
          flex: 1; border: none; outline: none;
          background: transparent; color: rgba(255,255,255,0.9);
          font-family: var(--font-mono); font-size: 14px;
        }
        .url-input::placeholder { color: rgba(255,255,255,0.25); }
        .url-input:disabled { opacity: 0.5; }
        .url-clear {
          background: none; border: none; cursor: pointer;
          color: rgba(255,255,255,0.3); font-size: 14px;
          padding: 2px 6px; border-radius: 4px;
          transition: all var(--transition-fast);
        }
        .url-clear:hover { color: var(--accent-red); background: rgba(239,68,68,0.1); }
        .url-error {
          display: flex; align-items: center; gap: 6px;
          font-size: 12px; color: var(--accent-red);
        }
        .advanced-toggle {
          font-size: 12px; color: rgba(255,255,255,0.4); cursor: pointer;
          text-align: right;
          transition: color var(--transition-fast);
        }
        .advanced-toggle:hover { color: var(--accent-blue); }
        .advanced-panel {
          background: rgba(255,255,255,0.03);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-md);
          padding: 16px 20px;
          display: flex; flex-direction: column; gap: 14px;
        }
        .adv-row {
          display: flex; align-items: center; justify-content: space-between;
          font-size: 13px; color: rgba(255,255,255,0.7); cursor: pointer;
        }
        .adv-row--stack {
          align-items: flex-start;
          flex-direction: column;
          gap: 8px;
        }
        .transition-select {
          width: 100%;
          border: 1px solid rgba(255,255,255,0.16);
          border-radius: 10px;
          background: rgba(255,255,255,0.05);
          color: rgba(255,255,255,0.9);
          padding: 8px 10px;
          font-size: 13px;
          outline: none;
        }
        .transition-select:focus {
          border-color: var(--accent-blue);
          box-shadow: 0 0 0 2px rgba(59,130,246,0.2);
        }
        .transition-select option {
          background: #0c1220;
          color: #f8fafc;
        }
        .toggle {
          width: 44px; height: 24px; border-radius: 12px;
          background: rgba(255,255,255,0.1); cursor: pointer;
          position: relative; transition: background 0.3s ease;
        }
        .toggle--on { background: var(--accent-blue); }
        .toggle-thumb {
          position: absolute; top: 3px; left: 3px;
          width: 18px; height: 18px; border-radius: 50%;
          background: white; transition: transform 0.3s ease;
          box-shadow: 0 1px 4px rgba(0,0,0,0.3);
        }
        .toggle--on .toggle-thumb { transform: translateX(20px); }
        .segment-slider {
          width: 120px; accent-color: var(--accent-blue); cursor: pointer;
        }
        .generate-btn {
          display: flex; align-items: center; justify-content: center; gap: 10px;
          padding: 16px 32px; border-radius: var(--radius-md);
          background: var(--gradient-button);
          border: none; cursor: pointer; color: white;
          font-family: var(--font-sans); font-size: 15px; font-weight: 700;
          letter-spacing: 0.04em;
          transition: all var(--transition-spring);
          box-shadow: var(--shadow-button);
          position: relative; overflow: hidden;
        }
        .generate-btn::after {
          content: ''; position: absolute; inset: 0;
          background: linear-gradient(135deg, rgba(255,255,255,0.15) 0%, transparent 60%);
          pointer-events: none;
        }
        .generate-btn:hover:not(:disabled) {
          transform: translateY(-2px);
          box-shadow: 0 8px 30px rgba(59,130,246,0.55);
        }
        .generate-btn:active:not(:disabled) { transform: translateY(0); }
        .generate-btn:disabled {
          opacity: 0.7; cursor: not-allowed;
          background: rgba(255,255,255,0.08);
          box-shadow: none;
        }
        .btn-icon { font-size: 18px; }

        @media (max-width: 760px) {
          .url-input-label {
            gap: 8px;
            margin-bottom: 8px;
          }
          .backend-pill {
            flex-basis: 100%;
            width: fit-content;
          }
          .backend-note {
            margin-top: 2px;
            margin-bottom: 12px;
          }
          .url-field {
            padding: 12px 14px;
          }
          .url-input {
            font-size: 13px;
          }
        }
      `}</style>
    </div>
  )
}
