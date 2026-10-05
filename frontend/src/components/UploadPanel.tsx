// PLACEHOLDER upload form. Wei's drag-and-drop component replaces this file and keeps the
// same props: call onJobCreated(jobId) once POST /api/jobs returns.
import { useState } from 'react'
import { createJob } from '../api'

interface Props {
  onJobCreated(jobId: string): void
}

export default function UploadPanel({ onJobCreated }: Props) {
  const [reference, setReference] = useState<File | null>(null)
  const [comparison, setComparison] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!reference || !comparison) return
    setBusy(true)
    setError(null)
    try {
      onJobCreated(await createJob(reference, comparison))
    } catch (err) {
      setError(String(err))
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-xl space-y-5 rounded-xl border border-zinc-800 bg-zinc-900 p-6">
      <FileField label="Reference video" hint="The dance to match" file={reference} onChange={setReference} />
      <FileField label="Your attempt" hint="The video to score" file={comparison} onChange={setComparison} />
      {error && <p className="text-sm text-red-400">{error}</p>}
      <button
        type="submit"
        disabled={!reference || !comparison || busy}
        className="w-full rounded-lg bg-zinc-100 px-4 py-2.5 font-medium text-zinc-900 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? 'Uploading…' : 'Compare'}
      </button>
    </form>
  )
}

function FileField(props: { label: string; hint: string; file: File | null; onChange(f: File | null): void }) {
  return (
    <label className="block">
      <span className="text-sm font-medium">{props.label}</span>
      <span className="ml-2 text-sm text-zinc-500">{props.hint}</span>
      <input
        type="file"
        accept="video/*"
        onChange={(e) => props.onChange(e.target.files?.[0] ?? null)}
        className="mt-2 block w-full text-sm text-zinc-400 file:mr-3 file:rounded-md file:border-0 file:bg-zinc-800 file:px-3 file:py-1.5 file:text-zinc-100"
      />
    </label>
  )
}
