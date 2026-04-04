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

        if (data.status === 'done') {
          setResult(data.result)
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

    try {
      const data = await submitGenerate(url, useGemini, maxSegments)
      setJobId(data.job_id)
      setStatus('pending')
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
  }, [stopPolling])

  return { jobId, status, progress, message, result, error, generate, reset }
}
