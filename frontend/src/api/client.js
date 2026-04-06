// api/client.js — Axios wrapper for backend API
import axios from 'axios'

const RAW_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').trim()
const API_BASE_URL = RAW_API_BASE_URL.replace(/\/+$/, '')

export function getApiBaseUrl() {
  if (API_BASE_URL) return API_BASE_URL
  if (typeof window !== 'undefined' && window.location?.origin) return window.location.origin
  return '/'
}

function isAbsoluteUrl(value) {
  return /^https?:\/\//i.test(value) || /^blob:/i.test(value) || /^data:/i.test(value)
}

function normalizePath(path) {
  const value = String(path || '')
  return value.startsWith('/') ? value : `/${value}`
}

export function resolveAssetUrl(path) {
  if (!path) return ''

  const value = String(path)
  if (isAbsoluteUrl(value)) return value

  const normalizedPath = normalizePath(value)
  return API_BASE_URL ? `${API_BASE_URL}${normalizedPath}` : normalizedPath
}

const api = axios.create({
  baseURL: API_BASE_URL || '/',
  timeout: 15000,
})

/**
 * Submit a URL for video generation.
 * Returns { job_id }
 */
export async function submitGenerate(
  articleUrl,
  useGemini = true,
  maxSegments = 7,
  transitionIntensity = 'standard',
  transitionProfile = 'auto',
  deliveryMode = 'full_video'
) {
  const res = await api.post('/generate', {
    article_url: articleUrl,
    use_gemini: useGemini,
    max_segments: maxSegments,
    transition_intensity: transitionIntensity,
    transition_profile: transitionProfile,
    delivery_mode: deliveryMode,
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

export async function checkBackendHealth() {
  const res = await api.get('/health')
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
  return resolveAssetUrl(`/outputs/${jobId}/final_video.mp4`)
}

export function clientPackUrl(jobId) {
  return resolveAssetUrl(`/outputs/${jobId}/client_pack.zip`)
}
