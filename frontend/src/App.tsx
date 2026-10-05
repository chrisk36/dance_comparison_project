import { useEffect, useState } from 'react'
import { getJob, getResults, mediaUrl } from './api'
import ComparisonPlayer from './components/ComparisonPlayer/ComparisonPlayer'
import UploadPanel from './components/UploadPanel'
import type { JobStatus, Results } from './types'

const STATUS_LABEL: Record<JobStatus['status'], string> = {
  queued: 'Queued',
  aligning: 'Aligning audio',
  pose: 'Tracking dancers',
  scoring: 'Scoring',
  done: 'Done',
  error: 'Failed',
}

// The job id lives in the URL (?job=…) so a reload or shared link reopens the results.
function jobFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get('job')
}

export default function App() {
  const [jobId, setJobId] = useState<string | null>(jobFromUrl)
  const [status, setStatus] = useState<JobStatus | null>(null)
  const [results, setResults] = useState<Results | null>(null)
  const [error, setError] = useState<string | null>(null)

  function startJob(id: string) {
    window.history.pushState(null, '', `?job=${id}`)
    setJobId(id)
  }

  function reset() {
    window.history.pushState(null, '', window.location.pathname)
    setJobId(null)
    setStatus(null)
    setResults(null)
    setError(null)
  }

  // Poll the job until it is done, then load results.
  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const s = await getJob(jobId)
        if (cancelled) return
        setStatus(s)
        if (s.status === 'done') setResults(await getResults(jobId))
        else if (s.status === 'error') setError(s.error ?? 'Analysis failed')
        else timer = window.setTimeout(poll, 800)
      } catch (err) {
        if (!cancelled) setError(String(err))
      }
    }
    poll()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [jobId])

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-8 flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Dance Sync</h1>
        {jobId && (
          <button onClick={reset} className="text-sm text-zinc-400 hover:text-zinc-100">
            New comparison
          </button>
        )}
      </header>

      {!jobId && <UploadPanel onJobCreated={startJob} />}

      {jobId && error && (
        <div className="rounded-lg border border-red-900 bg-red-950/50 p-4 text-sm text-red-300">{error}</div>
      )}

      {jobId && !error && !results && (
        <div className="mx-auto max-w-md space-y-2 pt-16 text-center">
          <p className="text-sm text-zinc-300">{status ? STATUS_LABEL[status.status] : 'Starting'}…</p>
          <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800">
            <div className="h-full bg-zinc-100 transition-all" style={{ width: `${100 * (status?.progress ?? 0)}%` }} />
          </div>
        </div>
      )}

      {jobId && results && (
        <ComparisonPlayer
          results={results}
          referenceUrl={mediaUrl(jobId, 'reference')}
          comparisonUrl={mediaUrl(jobId, 'comparison')}
        />
      )}
    </div>
  )
}
