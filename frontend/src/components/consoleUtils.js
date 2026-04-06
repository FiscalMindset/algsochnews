function clockToSecondOfDay(clockText) {
  const match = String(clockText || '').match(/(\d{2}):(\d{2}):(\d{2})/)
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  const seconds = Number(match[3])
  if (![hours, minutes, seconds].every(Number.isFinite)) return null
  return hours * 3600 + minutes * 60 + seconds
}

function tsToSecondOfDay(ts) {
  const parsed = Number(ts)
  if (!Number.isFinite(parsed)) return null
  const dt = new Date(parsed * 1000)
  return dt.getHours() * 3600 + dt.getMinutes() * 60 + dt.getSeconds()
}

function runtimeLineKind(line) {
  const text = String(line || '')
  const lower = text.toLowerCase()

  if (/(traceback|exception|\[error\]|\berror:)/i.test(text)) return 'runtime-error'
  if (/(\[warning\]|\bwarning:|\bwarn\b)/i.test(text)) return 'runtime-warn'
  if (/(\[debug\]|\bdebug:)/i.test(text)) return 'runtime-debug'
  if (lower.includes('get /status/') || /http\/1\.1"\s+200\s+ok/i.test(text)) return 'runtime-http'
  if (lower.includes('scraper:')) return 'runtime-scraper'
  if (lower.includes('segmenter:')) return 'runtime-segmenter'
  if (lower.includes('narration:')) return 'runtime-narration'
  if (lower.includes('qa:')) return 'runtime-qa'
  if (lower.includes('tts:')) return 'runtime-tts'
  if (lower.includes('video_renderer:')) return 'runtime-video'
  if (lower.includes('html_frame_renderer:')) return 'runtime-html'
  if (lower.includes('main:')) return 'runtime-main'
  return 'runtime-info'
}

function runtimeSortKey(line, index) {
  const match = String(line || '').match(/(^|\[)(\d{2}:\d{2}:\d{2})(\]|\s)/)
  const sec = clockToSecondOfDay(match?.[2])
  if (sec == null) return 100000000 + index
  return sec * 1000 + index
}

function compactPayload(value, maxLen = 260) {
  if (value == null) return ''
  let rendered = ''
  if (typeof value === 'string') {
    rendered = value
  } else {
    try {
      rendered = JSON.stringify(value)
    } catch {
      rendered = String(value)
    }
  }
  if (!rendered) return ''
  if (rendered.length <= maxLen) return rendered
  return `${rendered.slice(0, maxLen)}...`
}

function agentGraphLabel(event) {
  if (event?.agent_name) return String(event.agent_name)
  const key = String(event?.agent_key || '').trim()
  if (!key) return 'system'
  return key
}

function buildGraphConsoleLines(traceEvents = []) {
  const graphLines = []
  const sorted = [...(traceEvents || [])].sort((left, right) => Number(left?.ts || 0) - Number(right?.ts || 0))

  const runPath = []
  let earliestTs = null
  sorted.forEach((event) => {
    if (earliestTs == null && Number.isFinite(Number(event?.ts))) {
      earliestTs = Number(event.ts)
    }
    if (String(event?.event_type || '') !== 'node_start') return
    const name = agentGraphLabel(event)
    if (!name) return
    if (runPath[runPath.length - 1] !== name) {
      runPath.push(name)
    }
  })

  const baseSec = earliestTs != null ? tsToSecondOfDay(earliestTs) : null
  if (runPath.length > 1) {
    graphLines.push({
      key: 'g-path',
      sortKey: baseSec != null ? baseSec * 1000 + 420 : 100001900,
      text: `[graph] path: ${runPath.join(' -> ')}`,
      kind: 'graph',
    })
  }

  const seenEdges = new Set()
  sorted.forEach((event, index) => {
    if (!event?.route_to) return
    const from = agentGraphLabel(event)
    const decision = String(event?.decision || 'route').trim()
    const to = String(event.route_to || '').trim() || 'next'
    const edgeKey = `${from}|${decision}|${to}`
    if (seenEdges.has(edgeKey)) return
    seenEdges.add(edgeKey)

    const sec = tsToSecondOfDay(event.ts)
    graphLines.push({
      key: `g-edge-${index}`,
      sortKey: sec != null ? sec * 1000 + 421 + index : 100001901 + index,
      text: `[graph] ${from} --${decision}--> ${to}`,
      kind: 'graph-route',
    })
  })

  return graphLines
}

export function formatClock(ts) {
  if (!ts) return '--:--:--'
  const parsed = Number(ts)
  if (!Number.isFinite(parsed)) return '--:--:--'
  return new Date(parsed * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function buildExecutionConsoleLines(activityLog = [], traceEvents = [], runtimeLogs = []) {
  const runtime = (runtimeLogs || []).map((line, index) => ({
    key: `r-${index}`,
    sortKey: runtimeSortKey(line, index),
    text: String(line),
    kind: runtimeLineKind(line),
  }))

  const activity = (activityLog || []).map((line, index) => {
    const parsed = clockToSecondOfDay(line)
    return {
      key: `a-${index}`,
      sortKey: parsed != null ? parsed * 1000 + 250 + index : 100001000 + index,
      text: String(line),
      kind: 'activity',
    }
  })

  const trace = []
  ;(traceEvents || []).forEach((event, index) => {
    const clock = formatClock(event.ts)
    const agent = event.agent_name || event.agent_key || 'system'
    const eventType = String(event.event_type || 'event').replace(/_/g, ' ')
    const decision = event.decision ? ` | decision=${event.decision}` : ''
    const route = event.route_to ? ` | route=${event.route_to}` : ''
    const tools = event.tools?.length ? ` | tools=${event.tools.join(', ')}` : ''
    const baseSort = tsToSecondOfDay(event.ts) ?? 100002000 + index

    trace.push({
      key: `t-${index}`,
      sortKey: baseSort * 1000 + 500,
      text: `[${clock}] ${agent} :: ${eventType} :: ${event.message || ''}${decision}${route}${tools}`,
      kind: 'trace',
    })

    const input = compactPayload(event.input_payload)
    if (input) {
      trace.push({
        key: `ti-${index}`,
        sortKey: baseSort * 1000 + 501,
        text: `  input: ${input}`,
        kind: 'trace-payload',
      })
    }

    const output = compactPayload(event.output_payload)
    if (output) {
      trace.push({
        key: `to-${index}`,
        sortKey: baseSort * 1000 + 502,
        text: `  output: ${output}`,
        kind: 'trace-payload',
      })
    }

    if (event.metrics && Object.keys(event.metrics).length > 0) {
      trace.push({
        key: `tm-${index}`,
        sortKey: baseSort * 1000 + 503,
        text: `  metrics: ${compactPayload(event.metrics)}`,
        kind: 'trace-payload',
      })
    }
  })

  const graph = buildGraphConsoleLines(traceEvents)

  return [...runtime, ...activity, ...graph, ...trace].sort((left, right) => left.sortKey - right.sortKey)
}

export function retrySummary(traceEvents = [], agents = []) {
  const retryEvents = (traceEvents || []).filter((event) => {
    const decision = String(event.decision || '').toLowerCase()
    const route = String(event.route_to || '').toLowerCase()
    return decision.includes('retry') || route.includes('retry')
  })

  const retryCount = (agents || []).reduce((acc, agent) => acc + Number(agent.retry_count || 0), 0)

  const reviewEvent = (traceEvents || [])
    .filter((event) => event.agent_key === 'review' && event.event_type === 'node_complete')
    .sort((left, right) => Number(left.ts || 0) - Number(right.ts || 0))
    .pop()

  const reviewDecision = reviewEvent?.decision || null
  const qaAverage = reviewEvent?.output_payload?.average ?? null
  const qaPassed = reviewEvent?.output_payload?.passed ?? null

  return {
    retryCount,
    retryEvents,
    reviewDecision,
    qaAverage,
    qaPassed,
  }
}
