"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchBatch, fetchErrors, requestUpload } from "@/lib/api";
import {
  readableError, STATUS_LABEL, TERMINAL_STATUSES, validateFile,
  type BatchResponse, type RowError,
} from "@/lib/contracts";
import { StorageError, fileFingerprint, uploadToStorage } from "@/lib/upload";

const MAX_BYTES = Number(process.env.NEXT_PUBLIC_CSV_MAX_BYTES ?? 10_000_000);
const PAGE_SIZE = 20;
const MAX_POLLS = 90;
const PENDING_KEY = "loan-upload-pending-v1";
const DEMO_AVAILABLE = process.env.NEXT_PUBLIC_ENABLE_DEMO_UPLOAD === "1";

type Pending = { fingerprint: string; key: string; batchId?: string };
type Phase = "idle" | "ready" | "requesting" | "uploading" | "waiting" | "complete" | "error";

function readPending(): Pending | null {
  try {
    const value = sessionStorage.getItem(PENDING_KEY);
    return value ? JSON.parse(value) as Pending : null;
  } catch { return null; }
}

function savePending(value: Pending) {
  sessionStorage.setItem(PENDING_KEY, JSON.stringify(value));
}

function fileSize(size: number) {
  if (size < 1_000) return "< 1 KB";
  return size < 1_000_000 ? `${Math.round(size / 1_000)} KB` : `${(size / 1_000_000).toFixed(2)} MB`;
}

export function UploadConsole() {
  const inputRef = useRef<HTMLInputElement>(null);
  const busyRef = useRef(false);
  const [file, setFile] = useState<File | null>(null);
  const [demoMode, setDemoMode] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [batch, setBatch] = useState<BatchResponse | null>(null);
  const [watch, setWatch] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [rows, setRows] = useState<RowError[]>([]);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("batch");
    if (id && /^[0-9a-f-]{36}$/i.test(id)) {
      const timer = setTimeout(() => {
        setBatchId(id);
        setPhase("waiting");
        setWatch(true);
      }, 0);
      return () => clearTimeout(timer);
    }
  }, []);

  useEffect(() => {
    if (!watch || !batchId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let polls = 0;
    let failures = 0;
    const poll = async () => {
      if (cancelled) return;
      try {
        const next = await fetchBatch(batchId);
        if (cancelled) return;
        setBatch(next);
        setMessage(null);
        failures = 0;
        if (TERMINAL_STATUSES.has(next.status)) {
          setPhase("complete");
          setWatch(false);
          sessionStorage.removeItem(PENDING_KEY);
          return;
        }
        setPhase("waiting");
      } catch (error) {
        if (cancelled) return;
        failures += 1;
        if (failures >= 3) {
          setPhase("error");
          setMessage(error instanceof Error ? error.message : "Unable to refresh status.");
          setWatch(false);
          return;
        }
      }
      polls += 1;
      if (polls >= MAX_POLLS) {
        setMessage("Processing is still underway. Automatic checks paused; refresh the status when ready.");
        setWatch(false);
        return;
      }
      timer = setTimeout(poll, failures ? Math.min(8_000, 2_000 * failures) : 2_500);
    };
    void poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [batchId, watch, refreshToken]);

  useEffect(() => {
    if (!batchId || !batch?.rejected_rows) return;
    let cancelled = false;
    fetchErrors(batchId, offset, PAGE_SIZE).then((response) => {
      if (!cancelled) setRows(response.errors);
    }).catch(() => {
      if (!cancelled) setMessage("Row details are temporarily unavailable. Refresh to try again.");
    });
    return () => { cancelled = true; };
  }, [batchId, batch?.rejected_rows, offset]);

  const choose = useCallback((next: File | null) => {
    if (next) window.history.replaceState(null, "", window.location.pathname);
    setFile(next);
    setBatch(null);
    setBatchId(null);
    setWatch(false);
    setProgress(0);
    setOffset(0);
    setRows([]);
    if (!next) { setPhase("idle"); setMessage(null); return; }
    const problem = validateFile(next, MAX_BYTES);
    setPhase(problem ? "error" : "ready");
    setMessage(problem);
  }, []);

  const submit = async () => {
    if (busyRef.current || !file) return;
    const problem = validateFile(file, MAX_BYTES);
    if (problem) { setMessage(problem); setPhase("error"); return; }
    busyRef.current = true;
    setMessage(null);
    setProgress(0);
    setPhase("requesting");
    try {
      const contentFingerprint = `${file.name}:${file.size}:${await fileFingerprint(file)}:${demoMode}`;
      const prior = readPending();
      const current: Pending = prior?.fingerprint === contentFingerprint
        ? prior : { fingerprint: contentFingerprint, key: crypto.randomUUID() };
      savePending(current);
      const presign = await requestUpload(file, current.key, demoMode);
      const updated = { ...current, batchId: presign.batch_id };
      savePending(updated);
      setBatchId(presign.batch_id);
      window.history.replaceState(null, "", `?batch=${encodeURIComponent(presign.batch_id)}`);
      setPhase("uploading");
      await uploadToStorage(file, presign.upload, setProgress);
      setPhase("waiting");
      setWatch(true);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409 && batchId) {
        setWatch(true);
        setMessage("This upload is already being processed. Showing its latest status.");
        setPhase("waiting");
      } else {
        setPhase("error");
        setMessage(error instanceof StorageError || error instanceof ApiError
          ? error.message : "Something went wrong. Retry without creating a second batch.");
      }
    } finally { busyRef.current = false; }
  };

  const refresh = () => {
    if (!batchId) return;
    setMessage(null);
    setPhase("waiting");
    setWatch(true);
    setRefreshToken((value) => value + 1);
  };

  const reset = () => {
    sessionStorage.removeItem(PENDING_KEY);
    window.history.replaceState(null, "", window.location.pathname);
    if (inputRef.current) inputRef.current.value = "";
    choose(null);
  };

  const active = phase === "requesting" || phase === "uploading";
  const currentStep = phase === "idle" || phase === "ready" || phase === "error" && !batchId ? 0
    : phase === "requesting" || phase === "uploading" ? 1 : 2;

  return <main className="loan-page">
    <header className="site-header">
      <a href="#" className="wordmark" aria-label="Credora home"><span className="brand-symbol" aria-hidden="true">✳</span> CREDORA</a>
      <nav aria-label="Main navigation"><a href="#how-it-works">How it works</a><a href="#csv-guidance">Data guide</a><a className="nav-action" href="#workspace">Open workspace <span aria-hidden="true">↗</span></a></nav>
    </header>

    <div className="editorial-shell">
      <section className="editorial-hero" aria-labelledby="hero-title">
        <div><p className="eyebrow">A clearer starting point</p><h1 id="hero-title">Better information.<br /><span>Better possibilities.</span></h1></div>
        <p className="hero-description">Turn applicant data into a clearer picture of potential loan eligibility. Thoughtful matching starts with getting the details right.</p>
      </section>

      <section className="feature-banner" aria-labelledby="feature-title">
        <div className="feature-copy"><p className="eyebrow">From data to direction</p><h2 id="feature-title">A little clarity.<br />A world of possibility.</h2><p>One CSV. A structured review.<br />Your next step, made simpler.</p><a href="#workspace" className="dark-link">Start with your data <span aria-hidden="true">↗</span></a></div>
        <svg className="branch-art" viewBox="0 0 480 370" fill="none" aria-hidden="true">
          <path d="M210 375C220 280 240 178 312 42M233 268C186 225 150 210 105 193M253 208C300 198 348 154 382 115M277 143C246 102 220 82 186 67" stroke="#373e2d" strokeWidth="3" />
          <path d="M231 279C175 286 138 256 141 222C184 209 223 235 231 279Z" fill="#7b8763"/>
          <path d="M242 245C285 268 333 239 334 201C295 188 254 209 242 245Z" fill="#b76b4e"/>
          <path d="M259 195C214 198 185 161 195 130C233 128 261 157 259 195Z" fill="#515f46"/>
          <path d="M279 143C320 161 360 135 359 101C320 95 286 113 279 143Z" fill="#9ca285"/>
          <path d="M303 77C278 48 290 15 319 7C338 33 327 64 303 77Z" fill="#b76b4e"/>
          <path d="M179 225C153 183 113 172 87 191C98 224 140 241 179 225Z" fill="#c4aa72"/>
          <path d="M219 102C215 67 188 43 164 55C164 83 187 102 219 102Z" fill="#7b8763"/>
          <path d="M346 156C349 118 376 94 403 102C404 135 375 157 346 156Z" fill="#d0a375"/>
          <path d="M144 221L217 268M263 235L321 209M206 142L251 184M298 137L348 111M305 68L315 22" stroke="#eee9d8" strokeWidth="1.2"/>
          <circle cx="365" cy="245" r="4" fill="#b76b4e"/><circle cx="144" cy="103" r="3" fill="#7b8763"/>
          <path d="M351 55l5-9 5 9-5 9-5-9Z" fill="#444735"/>
        </svg>
        <span className="banner-caption">Built on details. Designed for possibilities.</span>
      </section>

      <section id="how-it-works" className="process-section" aria-labelledby="process-title">
        <div className="section-heading"><h2 id="process-title">A simple path forward</h2><span>01 — 03</span></div>
        <div className="process-grid">
          {[ ["01", "Bring your data", "Start with a CSV of applicant profiles. One person per row, six essential fields.", "CSV intake"], ["02", "Make every row count", "Review validation feedback and see which records are ready for matching.", "Data validation"], ["03", "Explore the possibilities", "Validated profiles move on to eligibility matching. Potential matches are never guarantees.", "Eligibility review"] ].map(([number, title, description, label]) => <article key={number} className="process-card"><span className="card-number">{number}</span><h3>{title}</h3><p>{description}</p><div className="card-caption">{label}<span aria-hidden="true">↗</span></div></article>)}
        </div>
      </section>

      <div id="workspace" className="workspace">
      <div className="workspace-heading"><div><p className="eyebrow">Your workspace</p><h2>Upload applicant data</h2></div><p>Start with a CSV. Follow validation as it happens,<br className="desktop-break" /> then review the results in one place.</p></div>
      <ol aria-label="Upload stages" className="mb-8 grid grid-cols-3 gap-2 text-xs sm:gap-3 sm:text-sm">
        {["Choose CSV", "Transfer file", "Review results"].map((label, index) =>
          <li key={label} className={`rounded-lg border px-3 py-3 font-medium sm:px-4 ${index <= currentStep ? "border-teal-200 bg-teal-50 text-teal-900" : "border-slate-200 bg-white text-slate-500"}`}>
            <span className="mr-2 text-xs opacity-70">0{index + 1}</span>{label}
          </li>)}
      </ol>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(260px,1fr)]">
        <section aria-labelledby="upload-title" className="upload-panel rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-8">
          <div className="mb-6 flex items-center justify-between gap-3">
            <div><h2 id="upload-title" className="text-lg font-semibold text-slate-900">CSV upload</h2><p className="mt-1 text-sm text-slate-500">Maximum {fileSize(MAX_BYTES)} · UTF-8 CSV</p></div>
            {file && <button type="button" onClick={reset} className="text-sm font-semibold text-teal-700 underline-offset-4 hover:underline">Start over</button>}
          </div>

          <div onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()}
               onDragLeave={(event) => { event.preventDefault(); setDragging(false); }}
               onDrop={(event) => { event.preventDefault(); setDragging(false); if (!active) choose(event.dataTransfer.files[0] ?? null); }}
               className={`drop-zone rounded-xl border-2 border-dashed px-5 py-11 text-center transition-colors ${dragging ? "border-teal-600 bg-teal-50" : "border-slate-300 bg-slate-50/60"}`}>
            <div aria-hidden="true" className="mx-auto mb-4 grid size-12 place-items-center rounded-xl bg-white text-2xl text-teal-700 shadow-sm">↑</div>
            <p className="font-semibold text-slate-900">Drag a CSV here, or choose a file</p>
            <p className="mt-1 text-sm text-slate-500">Your file stays on your device until you select Upload CSV.</p>
            <label htmlFor="csv-file" className="mt-5 inline-flex cursor-pointer items-center rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 shadow-sm hover:border-teal-500 hover:text-teal-800">Browse files</label>
            <input ref={inputRef} id="csv-file" type="file" accept=".csv,text/csv" className="sr-only" disabled={active}
                   onChange={(event) => choose(event.target.files?.[0] ?? null)} aria-describedby="csv-guidance" />
          </div>

          {file && <div className="mt-4 flex items-center justify-between gap-4 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm" data-testid="selected-file">
            <span className="min-w-0 truncate font-medium text-slate-800">{file.name}</span><span className="shrink-0 text-slate-500">{fileSize(file.size)}</span>
          </div>}

          {DEMO_AVAILABLE && <label className="mt-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
            <input type="checkbox" checked={demoMode} disabled={active} onChange={(event) => setDemoMode(event.target.checked)} className="mt-1" />
            <span>Local synthetic demonstration only. Results are not real lender offers; notifications remain mock-only.</span>
          </label>}

          {message && <div role="alert" className="mt-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">{message}</div>}

          {(phase === "uploading" || progress > 0 && phase !== "idle") && <div className="mt-6" aria-live="polite">
            <div className="mb-2 flex justify-between text-sm"><span className="font-medium text-slate-700">Direct upload</span><span className="font-semibold text-teal-800">{progress}%</span></div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label="CSV upload progress">
              <div className="h-full rounded-full bg-teal-700 transition-[width] duration-150" style={{ width: `${progress}%` }} />
            </div>
          </div>}

          <div className="mt-6 flex flex-wrap gap-3">
            <button type="button" onClick={() => void submit()} disabled={!file || active || phase === "waiting" || phase === "complete"}
                    className="rounded-lg bg-teal-700 px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50">
              {active ? "Uploading…" : phase === "error" && file ? "Retry upload" : "Upload CSV"}
            </button>
            {batchId && <button type="button" onClick={refresh} disabled={active || watch} className="rounded-lg border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 hover:border-teal-500 disabled:opacity-50">Refresh status</button>}
          </div>
        </section>

        <aside id="csv-guidance" aria-labelledby="format-title" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
          <p className="mb-2 text-xs font-bold uppercase tracking-[0.15em] text-teal-700">Before you begin</p>
          <h2 id="format-title" className="text-lg font-semibold text-slate-900">CSV format</h2>
          <p className="mt-3 text-sm leading-6 text-slate-600">One applicant per row. Include these six column names in the header; order can vary.</p>
          <code className="mt-4 block break-all rounded-lg bg-slate-50 p-4 text-xs leading-6 text-slate-700">user_id, email, monthly_income, credit_score, employment_status, age</code>
          <ul className="mt-5 space-y-3 text-sm leading-6 text-slate-600">
            <li><span className="font-semibold text-slate-800">Optional:</span> name is ignored and is not stored.</li>
            <li>Income has no assumed currency; unknown currency cannot satisfy a currency-specific rule.</li>
            <li>Invalid rows are reported without displaying applicant values.</li>
          </ul>
        </aside>
      </div>

      {batchId && <section aria-labelledby="results-title" className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><p className="text-xs font-bold uppercase tracking-[0.15em] text-teal-700">Batch progress</p><h2 id="results-title" className="mt-2 text-xl font-semibold text-slate-900">Processing summary</h2></div>
          <span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${batch?.status === "rejected" || batch?.status === "failed" || batch?.status === "match_failed" ? "bg-red-50 text-red-800" : batch?.status === "processed_with_errors" ? "bg-amber-50 text-amber-900" : "bg-teal-50 text-teal-900"}`} role="status" aria-live="polite">
            {batch ? STATUS_LABEL[batch.status] ?? batch.status : "Checking status"}
          </span>
        </div>
        <p className="mt-3 break-all text-xs text-slate-500">Batch ID: <code data-testid="batch-id">{batchId}</code></p>
        {batch ? <>
          <div className="mt-6 grid grid-cols-3 gap-3">
            {[ ["Total rows", batch.total_rows], ["Accepted", batch.accepted_rows], ["Rejected", batch.rejected_rows] ].map(([label, value]) =>
              <div key={label} className="rounded-lg border border-slate-200 bg-slate-50 p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{value}</p></div>)}
          </div>
          {(batch.status === "uploaded" || batch.status === "processing" || batch.status === "matching") && <p className="mt-4 text-sm text-slate-600" aria-live="polite">{batch.status === "uploaded" && progress === 100 ? "File transferred. Waiting for the ingestion worker to begin." : "The latest status is from the backend. This page checks again automatically for a limited time."}</p>}
          {batch.status === "processed" && <p className="mt-4 text-sm text-slate-600">Ingestion is complete. Downstream matching may continue; use Refresh status for a later update.</p>}
          {batch.status === "processed_with_errors" && <p className="mt-4 text-sm text-slate-600">Valid rows were saved. Review the rejected rows below, then correct and upload a new file if needed.</p>}
          {(batch.status === "rejected" || batch.status === "failed" || batch.status === "match_failed") && <p className="mt-4 text-sm text-red-800">This batch could not complete. Check the validation details or logs, then retry with a corrected file.</p>}
          {typeof batch.errors.code === "string" && <p className="mt-3 text-sm text-red-800">File error: {readableError(batch.errors.code).reason}</p>}
          <p className="mt-3 text-xs text-slate-500">Processing duration is not supplied by the upload API.</p>
        </> : <p className="mt-5 text-sm text-slate-500">Waiting for the first backend status response…</p>}

        {batch && batch.rejected_rows > 0 && <div className="mt-8 border-t border-slate-200 pt-6">
          <h3 className="text-base font-semibold text-slate-900">Validation results</h3>
          <p className="mt-1 text-sm text-slate-600">{batch.rejected_rows} rejected {batch.rejected_rows === 1 ? "row" : "rows"}. Applicant values are intentionally hidden.</p>
          {rows.length === 0 ? <p className="mt-4 text-sm text-slate-500">Loading row details or no details were returned for this page.</p> :
            <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[480px] text-left text-sm"><thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500"><tr><th scope="col" className="py-3 pr-4">Row</th><th scope="col" className="py-3 pr-4">Field</th><th scope="col" className="py-3">Reason</th></tr></thead><tbody>
              {rows.flatMap((item) => item.codes.map((code) => { const info = readableError(code); return <tr key={`${item.row}-${code}`} className="border-b border-slate-100"><td className="py-3 pr-4 font-medium">{item.row}</td><td className="py-3 pr-4"><code>{info.field}</code></td><td className="py-3 text-slate-600">{info.reason}</td></tr>; }))}
            </tbody></table></div>}
          <div className="mt-4 flex items-center justify-between gap-3 text-sm">
            <span className="text-slate-500">Rows {offset + 1}–{Math.min(offset + PAGE_SIZE, batch.rejected_rows)} of {batch.rejected_rows}</span>
            <div className="flex gap-2"><button type="button" disabled={offset === 0} onClick={() => { setRows([]); setOffset(Math.max(0, offset - PAGE_SIZE)); }} className="rounded border border-slate-300 px-3 py-2 disabled:opacity-40">Previous</button><button type="button" disabled={offset + PAGE_SIZE >= batch.rejected_rows} onClick={() => { setRows([]); setOffset(offset + PAGE_SIZE); }} className="rounded border border-slate-300 px-3 py-2 disabled:opacity-40">Next</button></div>
          </div>
        </div>}
      </section>}
      <p className="mt-8 text-center text-xs text-slate-500">These are potential matches, not guaranteed loan approvals.</p>
      </div>
    </div>
    <footer className="site-footer"><div><p className="footer-brand">CREDORA<span aria-hidden="true">✳</span></p><p>Clarity at every step.</p></div><div className="footer-links"><a href="#workspace">Upload data ↗</a><a href="#csv-guidance">CSV guide ↗</a><span>Built for informed decisions.</span></div></footer>
  </main>;
}
