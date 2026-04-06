// hooks/useGenerate.js — Custom hook for the full generate flow
import { useState, useRef, useCallback, useEffect } from 'react'
import {
  checkBackendHealth,
  getApiBaseUrl,
  resolveAssetUrl,
  submitGenerate,
  pollStatus,
} from '../api/client'

const POLL_INTERVAL_MS = 2000
const HEALTH_PING_INTERVAL_MS = 10000
const MAX_TRANSIENT_POLL_FAILURES = 5
const OFFLINE_GRACE_MS = 90000

function backendOfflineStatusMessage() {
  return `Frontend live, backend unreachable (${getApiBaseUrl()}) - start backend on :8000; auto-checking every ${Math.round(HEALTH_PING_INTERVAL_MS / 1000)}s`
}

function isLikelyHomepageUrl(input) {
  try {
    const parsed = new URL(String(input || '').trim())
    const path = (parsed.pathname || '/').replace(/\/+$/, '') || '/'
    if (path === '/') return true
    return /^\/(home|news|latest|top|topics?|category|categories)$/i.test(path)
  } catch {
    return false
  }
}

function extractionUrlGuidance(articleUrl) {
  if (isLikelyHomepageUrl(articleUrl)) {
    return 'The submitted link looks like a homepage or section page. Open a specific story first, then paste that direct article URL.'
  }
  return 'Use a direct article URL pattern like /news/<slug>, /article/<slug>, or /YYYY/MM/<slug>. Avoid search, tag, category, and login-only pages.'
}

function normalizeFailureMessage(input, articleUrl = '') {
  const message = String(input || '').trim()
  if (!message) return 'Generation failed'

  const lower = message.toLowerCase()
  if (lower.includes('all extraction methods failed')) {
    return `Extraction failed for this URL. The page may block bots or may not contain enough article body text. ${extractionUrlGuidance(articleUrl)}`
  }

  return message
}

export default function useGenerate() {
  const [articleUrl, setArticleUrl] = useState('')
  const [previewVideoUrl, setPreviewVideoUrl] = useState(null)
  const [jobId, setJobId]         = useState(null)
  const [status, setStatus]       = useState('idle')   // idle | pending | processing | done | failed
  const [progress, setProgress]   = useState(0)
  const [message, setMessage]     = useState('')
  const [result, setResult]       = useState(null)
  const [error, setError]         = useState(null)
  const [agents, setAgents]       = useState([])
  const [activityLog, setActivityLog] = useState([])
  const [traceEvents, setTraceEvents] = useState([])
  const [runtimeLogs, setRuntimeLogs] = useState([])
  const [review, setReview]       = useState(null)
  const [workflowOverview, setWorkflowOverview] = useState(null)
  const [modelVerification, setModelVerification] = useState(null)
  const [backendStatus, setBackendStatus] = useState('unknown')
  const [backendStatusMessage, setBackendStatusMessage] = useState(`API target: ${getApiBaseUrl()}`)
  const pollRef                   = useRef(null)
  const pollFailureRef            = useRef(0)
  const pollInFlightRef           = useRef(false)
  const offlineSinceRef           = useRef(null)
  const healthRef                 = useRef(null)
  const statusRef                 = useRef('idle')
  const backendStatusRef          = useRef('unknown')
  const articleUrlRef             = useRef('')

  const setBackendState = useCallback((nextStatus, nextMessage, options = {}) => {
    const { announceRecovery = false } = options
    const previous = backendStatusRef.current
    backendStatusRef.current = nextStatus
    setBackendStatus(nextStatus)
    setBackendStatusMessage(nextMessage)

    if (announceRecovery && previous !== 'online') {
      setMessage('Backend is live now. You can start generation.')
      setStatus((prev) => (prev === 'failed' ? 'idle' : prev))
      setError((prev) => {
        if (!prev) return prev
        const lower = String(prev).toLowerCase()
        if (
          lower.includes('network') ||
          lower.includes('backend') ||
          lower.includes('offline') ||
          lower.includes('unreachable') ||
          lower.includes('connection')
        ) {
          return null
        }
        return prev
      })
    }
  }, [])

  useEffect(() => {
    statusRef.current = status
  }, [status])

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    pollInFlightRef.current = false
  }, [])

  const checkBackend = useCallback(async (options = {}) => {
    const { warmupRetries = 1, announceRecovery = false } = options
    const attempts = Math.max(1, Number(warmupRetries || 1))

    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      setBackendState(
        'checking',
        `Checking backend health (${getApiBaseUrl()}) ${attempts > 1 ? `attempt ${attempt}/${attempts}` : ''}`,
      )

      try {
        await checkBackendHealth()
        setBackendState('online', `Backend live (${getApiBaseUrl()})`, { announceRecovery })
        return
      } catch (err) {
        if (attempt < attempts) {
          setBackendState(
            'degraded',
            `Backend waking up (${attempt}/${attempts}) - retrying in 2s...`,
          )
          await new Promise((resolve) => setTimeout(resolve, 2000))
          continue
        }
        setBackendState(
          'offline',
          backendOfflineStatusMessage(),
        )
        throw err
      }
    }
  }, [setBackendState])

  const startHealthHeartbeat = useCallback(() => {
    if (healthRef.current) {
      clearInterval(healthRef.current)
      healthRef.current = null
    }

    const tick = async () => {
      // Polling loop already tracks liveness while a job is running.
      if (statusRef.current === 'pending' || statusRef.current === 'processing') return

      try {
        await checkBackendHealth()
        setBackendState('online', `Backend live (${getApiBaseUrl()})`, { announceRecovery: true })
      } catch {
        setBackendState(
          'offline',
            backendOfflineStatusMessage(),
        )
      }
    }

    tick()
    healthRef.current = setInterval(tick, HEALTH_PING_INTERVAL_MS)
  }, [setBackendState])

  useEffect(() => {
    startHealthHeartbeat()
    return () => {
      stopPolling()
      if (healthRef.current) {
        clearInterval(healthRef.current)
        healthRef.current = null
      }
    }
  }, [startHealthHeartbeat, stopPolling])

  const startPolling = useCallback((id) => {
    stopPolling()
    pollFailureRef.current = 0
    pollRef.current = setInterval(async () => {
      if (pollInFlightRef.current) return
      pollInFlightRef.current = true
      try {
        const data = await pollStatus(id)
        pollFailureRef.current = 0
        offlineSinceRef.current = null
        setBackendState('online', `Backend live (${getApiBaseUrl()})`)
        setProgress(data.progress ?? 0)
        setMessage(data.message ?? '')
        setStatus(data.status)
        setPreviewVideoUrl(data.preview_video_url ? resolveAssetUrl(data.preview_video_url) : null)
        setAgents(data.agents ?? [])
        setActivityLog(data.activity_log ?? [])
        setTraceEvents(data.trace_events ?? [])
        setRuntimeLogs(data.runtime_logs ?? [])
        setReview(data.review ?? null)
        setWorkflowOverview(data.workflow_overview ?? null)
        setModelVerification(data.model_verification ?? null)

        if (data.status === 'done') {
          setResult(data.result)
          setAgents(data.result?.agents ?? data.agents ?? [])
          setActivityLog(data.result?.activity_log ?? data.activity_log ?? [])
          setTraceEvents(data.result?.trace_events ?? data.trace_events ?? [])
          setRuntimeLogs(data.result?.runtime_logs ?? data.runtime_logs ?? [])
          setReview(data.result?.script?.review ?? data.review ?? null)
          setWorkflowOverview(data.result?.script?.workflow_overview ?? data.workflow_overview ?? null)
          setModelVerification(data.result?.model_verification ?? data.model_verification ?? null)
          stopPolling()
        } else if (data.status === 'failed') {
          setBackendState('online', `Backend live (${getApiBaseUrl()}) - job completed with a workflow failure`)
          setError(normalizeFailureMessage(data.message, articleUrlRef.current))
          stopPolling()
        }
      } catch (err) {
        pollFailureRef.current += 1
        const failures = pollFailureRef.current

        if (failures <= MAX_TRANSIENT_POLL_FAILURES) {
          setBackendState('degraded', `Backend unstable (${failures}/${MAX_TRANSIENT_POLL_FAILURES}) - retrying status check...`)
          setMessage(`Transient network issue while polling status (${failures}/${MAX_TRANSIENT_POLL_FAILURES}). Retrying...`)
          pollInFlightRef.current = false
          return
        }

        let backendStillAlive = false
        try {
          await checkBackendHealth()
          backendStillAlive = true
        } catch {
          backendStillAlive = false
        }

        if (backendStillAlive) {
          pollFailureRef.current = 0
          offlineSinceRef.current = null
          setBackendState('online', `Backend live (${getApiBaseUrl()}) - connection recovered`)
          setMessage('Recovered connection to backend. Continuing generation...')
          pollInFlightRef.current = false
          return
        }

        if (!offlineSinceRef.current) {
          offlineSinceRef.current = Date.now()
        }

        const offlineMs = Date.now() - Number(offlineSinceRef.current || 0)
        const remainingMs = Math.max(0, OFFLINE_GRACE_MS - offlineMs)
        const remainingSeconds = Math.ceil(remainingMs / 1000)

        if (offlineMs < OFFLINE_GRACE_MS) {
          setBackendState(
            'degraded',
            `Connection interrupted (${getApiBaseUrl()}) - reconnecting... (${remainingSeconds}s grace)`,
          )
          setMessage('Connection dropped while generation is running. Retrying automatically...')
          pollInFlightRef.current = false
          return
        }

        setBackendState(
          'offline',
          backendOfflineStatusMessage(),
        )
        setError('Lost connection to backend for too long during generation. The run may still be processing on the server; refresh status in a moment or retry.')
        setStatus('failed')
        stopPolling()
      } finally {
        pollInFlightRef.current = false
      }
    }, POLL_INTERVAL_MS)
  }, [setBackendState, stopPolling])

  const generate = useCallback(async (
    url,
    useGemini,
    maxSegments,
    transitionIntensity = 'standard',
    transitionProfile = 'auto',
    deliveryMode = 'full_video',
  ) => {
    const normalizedUrl = url.trim()
    const normalizedDeliveryMode = deliveryMode === 'editorial_only' ? 'editorial_only' : 'full_video'
    articleUrlRef.current = normalizedUrl
    setArticleUrl(normalizedUrl)
    setStatus('pending')
    setProgress(0)
    setMessage('Submitting job…')
    setResult(null)
    setError(null)
    setPreviewVideoUrl(null)
    setJobId(null)
    setAgents([])
    setActivityLog([])
    setTraceEvents([])
    setRuntimeLogs([])
    setReview(null)
    setWorkflowOverview(null)
    setModelVerification(null)

    try {
      await checkBackend({ warmupRetries: 3 })
      const data = await submitGenerate(
        normalizedUrl,
        useGemini,
        maxSegments,
        transitionIntensity,
        transitionProfile,
        normalizedDeliveryMode,
      )
      setBackendState('online', `Backend live (${getApiBaseUrl()}) - job accepted`)
      setJobId(data.job_id)
      setStatus('pending')
      setAgents(data.agents ?? [])
      setTraceEvents(data.trace_events ?? [])
      setWorkflowOverview(
        data.workflow_overview
          ? {
              ...data.workflow_overview,
              delivery_mode: normalizedDeliveryMode,
              video_required: normalizedDeliveryMode === 'full_video',
            }
          : {
              delivery_mode: normalizedDeliveryMode,
              video_required: normalizedDeliveryMode === 'full_video',
            },
      )
      startPolling(data.job_id)
    } catch (err) {
      if (!err.response) {
        setBackendState(
          'offline',
          backendOfflineStatusMessage(),
        )
        setError(`Frontend is live, but backend is offline at ${getApiBaseUrl()}. Start backend on :8000 and retry.`)
        setStatus('failed')
        return
      }
      const detail = err.response?.data?.detail
      const msg =
        detail === 'Method Not Allowed'
          ? 'Backend endpoint requires POST. Please generate from the app UI, not by opening /generate in browser.'
          : normalizeFailureMessage(detail || err.message, normalizedUrl)
      setBackendState('online', `Backend live (${getApiBaseUrl()}) - request reached backend`)
      setError(msg)
      setStatus('failed')
    }
  }, [checkBackend, setBackendState, startPolling])

  const reset = useCallback(() => {
    stopPolling()
    setArticleUrl('')
    articleUrlRef.current = ''
    setJobId(null)
    offlineSinceRef.current = null
    setStatus('idle')
    setProgress(0)
    setMessage('')
    setResult(null)
    setError(null)
    setPreviewVideoUrl(null)
    setAgents([])
    setActivityLog([])
    setTraceEvents([])
    setRuntimeLogs([])
    setReview(null)
    setWorkflowOverview(null)
    setModelVerification(null)
    setBackendState('unknown', `API target: ${getApiBaseUrl()}`)
  }, [setBackendState, stopPolling])

  return {
    articleUrl,
    previewVideoUrl,
    jobId,
    status,
    progress,
    message,
    result,
    error,
    agents,
    activityLog,
    traceEvents,
    runtimeLogs,
    review,
    workflowOverview,
    modelVerification,
    backendStatus,
    backendStatusMessage,
    generate,
    reset,
  }
}
