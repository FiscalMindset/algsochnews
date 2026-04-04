// api/client.js — Axios wrapper for backend API
import axios from 'axios'

const api = axios.create({
  baseURL: '/',
  timeout: 15000,
})

/**
 * Submit a URL for video generation.
 * Returns { job_id }
 */
export async function submitGenerate(articleUrl, useGemini = true, maxSegments = 7) {
  const res = await api.post('/generate', {
    article_url: articleUrl,
    use_gemini: useGemini,
    max_segments: maxSegments,
  })
  return res.data
}

/**
 * Poll job status.
 * Returns { job_id, status, progress, message, result }
 */
export async function pollStatus(jobId) {
  const res = await api.get(`/status/${jobId}`)
  return res.data
}

/**
 * Fetch parsed script JSON for a completed job.
 */
export async function fetchScript(jobId) {
  const res = await api.get(`/outputs/${jobId}/script.json`)
  return res.data
}

export function videoUrl(jobId) {
  return `/outputs/${jobId}/final_video.mp4`
}
