// hooks/useGenerate.js — Custom hook for the full generate flow
import { useState, useRef, useCallback } from 'react'
import { submitGenerate, pollStatus } from '../api/client'

const POLL_INTERVAL_MS = 2000

export default function useGenerate() {
  const [jobId, setJobId]         = useState(null)
  const [status, setStatus]       = useState('idle')   // idle | pending | processing | done | failed
  const [progress, setProgress]   = useState(0)
  const [message, setMessage]     = useState('')
  const [result, setResult]       = useState(null)
  const [error, setError]         = useState(null)
  const [agents, setAgents]       = useState([])
  const [activityLog, setActivityLog] = useState([])
  const [review, setReview]       = useState(null)
  const [workflowOverview, setWorkflowOverview] = useState(null)
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
        setAgents(data.agents ?? [])
        setActivityLog(data.activity_log ?? [])
        setReview(data.review ?? null)
        setWorkflowOverview(data.workflow_overview ?? null)

        if (data.status === 'done') {
          setResult(data.result)
          setAgents(data.result?.agents ?? data.agents ?? [])
          setActivityLog(data.result?.activity_log ?? data.activity_log ?? [])
          setReview(data.result?.script?.review ?? data.review ?? null)
          setWorkflowOverview(data.result?.script?.workflow_overview ?? data.workflow_overview ?? null)
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

  const generate = useCallback(async (url, useGemini, maxSegments) => {
    setStatus('pending')
    setProgress(0)
    setMessage('Submitting job…')
    setResult(null)
    setError(null)
    setJobId(null)
    setAgents([])
    setActivityLog([])
    setReview(null)
    setWorkflowOverview(null)

    try {
      const data = await submitGenerate(url, useGemini, maxSegments)
      setJobId(data.job_id)
      setStatus('pending')
      setAgents(data.agents ?? [])
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
    setJobId(null)
    setStatus('idle')
    setProgress(0)
    setMessage('')
    setResult(null)
    setError(null)
    setAgents([])
    setActivityLog([])
    setReview(null)
    setWorkflowOverview(null)
  }, [stopPolling])

  return {
    jobId,
    status,
    progress,
    message,
    result,
    error,
    agents,
    activityLog,
    review,
    workflowOverview,
    generate,
    reset,
  }
}
