// hooks/useGenerate.js — Custom hook for the full generate flow
import { useState, useRef, useCallback } from 'react'
import { submitGenerate, pollStatus } from '../api/client'

const POLL_INTERVAL_MS = 2000

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
  const pollRef                   = useRef(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const startPolling = useCallback((id) => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const data = await pollStatus(id)
        setProgress(data.progress ?? 0)
        setMessage(data.message ?? '')
        setStatus(data.status)
        setPreviewVideoUrl(data.preview_video_url ?? null)
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
        setError(err.message)
        stopPolling()
      }
    }, POLL_INTERVAL_MS)
  }, [stopPolling])

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
      const data = await submitGenerate(url, useGemini, maxSegments, transitionIntensity, transitionProfile)
      setJobId(data.job_id)
      setStatus('pending')
      setAgents(data.agents ?? [])
      setTraceEvents(data.trace_events ?? [])
      setWorkflowOverview(data.workflow_overview ?? null)
      startPolling(data.job_id)
    } catch (err) {
      const msg = err.response?.data?.detail || err.message
      setError(msg)
      setStatus('failed')
    }
  }, [startPolling])

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
  }, [stopPolling])

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
    generate,
    reset,
  }
}
