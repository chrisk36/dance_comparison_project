// Thin client for the FastAPI backend (CONTRACT.md section 3).
import type { JobStatus, Results } from './types'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* not JSON */
    }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

export async function createJob(reference: File, comparison: File): Promise<string> {
  const body = new FormData()
  body.append('reference', reference)
  body.append('comparison', comparison)
  const res = await fetch('/api/jobs', { method: 'POST', body })
  return (await json<{ job_id: string }>(res)).job_id
}

export async function getJob(jobId: string): Promise<JobStatus> {
  return json(await fetch(`/api/jobs/${jobId}`))
}

export async function getResults(jobId: string): Promise<Results> {
  return json(await fetch(`/api/jobs/${jobId}/results`))
}

export function mediaUrl(jobId: string, kind: 'reference' | 'comparison' | 'debug'): string {
  return `/api/jobs/${jobId}/media/${kind}`
}
