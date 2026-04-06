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
  const healthRef                 = useRef(null)
  const statusRef                 = useRef('idle')
  const backendStatusRef          = useRef('unknown')

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
          `Backend unreachable (${getApiBaseUrl()}) - auto-checking every ${Math.round(HEALTH_PING_INTERVAL_MS / 1000)}s`,
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
          `Backend unreachable (${getApiBaseUrl()}) - auto-checking every ${Math.round(HEALTH_PING_INTERVAL_MS / 1000)}s`,
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
          setError(data.message || 'Generation failed')
          stopPolling()
        }
      } catch (err) {
        pollFailureRef.current += 1
        const failures = pollFailureRef.current

        if (failures <= 3) {
          setBackendState('degraded', `Backend unstable (${failures}/3) - retrying status check...`)
          setMessage(`Transient network issue while polling status (${failures}/3). Retrying...`)
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
          setBackendState('online', `Backend live (${getApiBaseUrl()}) - connection recovered`)
          setMessage('Recovered connection to backend. Continuing generation...')
          pollInFlightRef.current = false
          return
        }

        setBackendState(
          'offline',
          `Backend unreachable (${getApiBaseUrl()}) - auto-checking every ${Math.round(HEALTH_PING_INTERVAL_MS / 1000)}s`,
        )
        setError('Lost connection to backend during generation. We will keep checking and show when backend is live again.')
        setStatus('failed')
        stopPolling()
      } finally {
        pollInFlightRef.current = false
      }
    }, POLL_INTERVAL_MS)
  }, [setBackendState, stopPolling])

  const generate = useCallback(async (url, useGemini, maxSegments, transitionIntensity = 'standard', transitionProfile = 'auto') => {
    setArticleUrl(url.trim())
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
      const data = await submitGenerate(url, useGemini, maxSegments, transitionIntensity, transitionProfile)
      setJobId(data.job_id)
      setStatus('pending')
      setAgents(data.agents ?? [])
      setTraceEvents(data.trace_events ?? [])
      setWorkflowOverview(data.workflow_overview ?? null)
      startPolling(data.job_id)
    } catch (err) {
      if (!err.response) {
        setBackendState(
          'offline',
          `Backend request failed (${getApiBaseUrl()}) - auto-checking every ${Math.round(HEALTH_PING_INTERVAL_MS / 1000)}s`,
        )
        setError('Backend is offline or waking up (Render free tier). Waiting for backend to come live...')
        setStatus('failed')
        return
      }
      const detail = err.response?.data?.detail
      const msg =
        detail === 'Method Not Allowed'
          ? 'Backend endpoint requires POST. Please generate from the app UI, not by opening /generate in browser.'
          : detail || err.message
      setError(msg)
      setStatus('failed')
    }
  }, [checkBackend, setBackendState, startPolling])

  const reset = useCallback(() => {
    stopPolling()
    setArticleUrl('')
    setJobId(null)
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
