"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

type Job = { id: string; demo: number; state: string; error: string | null };
type Delivery = { platform: string; state: string; publish_at: string | null };

export default function Studio() {
  const [view, setView] = useState<"queue" | "create" | "providers">("queue");
  const [filter, setFilter] = useState("all");
  const [report, setReport] = useState("");
  const [usage, setUsage] = useState<{host: string; requests: number; failures: number; average_ms: number; reported_tokens: number | null; last_success: boolean | null; last_observed_at: string | null}[]>([]);
  const [connected, setConnected] = useState(false);
  const [token, setToken] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Job>();
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [preview, setPreview] = useState("");
  const [metrics, setMetrics] = useState("");

  const api = useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch("/api/" + path, {
      ...init, headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : "Request failed (" + response.status + ")");
    }
    return response;
  }, [token]);

  async function act(action: () => Promise<void>) {
    try { setError(""); await action(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Request failed"); }
  }

  const refresh = useCallback(async () => {
    setJobs(await (await api("jobs")).json());
    setConnected(true);
    if (selected) setDeliveries(await (await api("jobs/" + selected.id + "/deliveries")).json());
  }, [api, selected]);

  useEffect(() => {
    if (!token) return;
    const timer = window.setInterval(() => void act(refresh), 5000);
    return () => window.clearInterval(timer);
  }, [token, refresh]);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  function queue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    void act(async () => {
      await api("jobs", { method: "POST", body: JSON.stringify({
        demo: data.get("demo") === "on",
        brief: { story: data.get("story"), final_changes: data.get("final_changes"),
          language: data.get("language"), style: data.get("style"),
          resolution: data.get("resolution"), export_resolution: data.get("export_resolution"),
          scene_count: Number(data.get("scene_count")), seconds_per_scene: Number(data.get("seconds_per_scene")),
          audio: data.get("audio") === "on", burn_captions: data.get("burn_captions") === "on",
          made_for_kids: data.get("made_for_kids") === "on",
          synthetic_disclosure: data.get("synthetic_disclosure") === "on" },
      }) });
      await refresh();
      setView("queue");
      setFilter("all");
    });
  }

  function saveProviders(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const values = Object.fromEntries(form);
    const budget = String(form.get("story_budget_usd"));
    void act(async () => {
      await api("providers", { method: "PUT", body: JSON.stringify({
        video_provider: values.video_provider || null, video_fallback: values.video_fallback || null,
        runway_video_model: values.runway_video_model || null,
        image_provider: values.image_provider || null, tts_provider: values.tts_provider || null,
        story_budget_usd: budget ? Number(budget) : null,
        ...Object.fromEntries(["image_model", "tts_model", "tts_voice", "tts_fallback_model", "tts_fallback_voice"]
          .map(name => [name, String(values[name] ?? "").trim() || null])),
        story_routing: values.story_routing ? JSON.parse(String(values.story_routing)) : null,
      }) });
    });
  }

  function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const data = new FormData(event.currentTarget);
    const schedule = String(data.get("schedule"));
    const publicUpload = data.get("public") === "on";
    if (publicUpload && !window.confirm("Request public publication?")) return;
    void act(async () => {
      await api("jobs/" + selected.id + "/deliveries", { method: "POST", body: JSON.stringify({
        platform: data.get("platform"), public: publicUpload,
        publish_at: schedule ? new Date(schedule).toISOString() : null,
      }) });
      await refresh();
    });
  }

  const visibleJobs = jobs.filter(job => filter === "all" || job.state === filter);
  const nav = [["queue", "Production"], ["create", "New video"], ["providers", "Providers"]] as const;

  return <div className="workspace">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark" aria-hidden="true">▶</span> Story Video Studio</div>
      <nav aria-label="Workspace">
        {nav.map(([key, label]) => <button key={key} aria-current={view === key ? "page" : undefined}
          onClick={() => setView(key)}>{label}</button>)}
      </nav>
      <span className="connection-indicator" data-connected={connected}>{connected ? "Connected" : "Offline"}</span>
    </aside>
    <main>
    <header><h1>{nav.find(([key]) => key === view)?.[1]}</h1>
      {view === "queue" && <button onClick={() => setView("create")}>New video</button>}
    </header>
    <form className="connection" onSubmit={event => {event.preventDefault(); void act(refresh);}}>
      <label>Admin token<input type="password" autoComplete="off" value={token}
        onChange={event => {
          setToken(event.target.value); setConnected(false); setJobs([]); setSelected(undefined);
          setPreview(""); setMetrics(""); setDeliveries([]); setUsage([]); setReport("");
        }} /></label>
      <button className="secondary" disabled={!token}>{connected ? "Refresh" : "Connect"}</button>
    </form>
    <p role="alert">{error}</p>
    {view === "queue" && <dl className="stats" aria-label="Recent jobs">
      {[
        ["Queued", jobs.filter(job => job.state === "PENDING").length],
        ["Processing", jobs.filter(job => ["RUNNING", "RENDERING"].includes(job.state)).length],
        ["Ready", jobs.filter(job => job.state === "READY_TO_PUBLISH").length],
        ["Failed", jobs.filter(job => job.state === "FAILED").length],
      ].map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}
    </dl>}
    <div className="studio-content">
      <section id="create" hidden={view !== "create"}><h2>Video brief</h2><form onSubmit={queue}>
        <label>Story or idea<textarea name="story" required maxLength={24000} rows={5} /></label>
        <label>Final changes<textarea name="final_changes" maxLength={6000} rows={2} /></label>
        <label>Language<input name="language" defaultValue="বাংলা" /></label>
        <label>Visual style<input name="style" defaultValue="Cinematic natural light" /></label>
        <div className="field-grid">
        <label>Source resolution<select name="resolution" defaultValue="1080p">
          <option>720p</option><option>1080p</option>
        </select></label>
        <label>Export resolution<select name="export_resolution" defaultValue="1080p">
          <option>720p</option><option>1080p</option><option>1440p</option><option value="2160p">4K</option>
        </select></label>
        <label>Scenes<input type="number" name="scene_count" min={1} max={5} defaultValue={3} required /></label>
        <label>Seconds per scene<input type="number" name="seconds_per_scene" min={4} max={12} defaultValue={6} required /></label>
        </div>
        <div className="field-grid">
          <label><input name="audio" type="checkbox" defaultChecked /> Source audio</label>
          <label><input name="burn_captions" type="checkbox" defaultChecked /> Burn captions</label>
          <label><input name="made_for_kids" type="checkbox" /> Made for kids</label>
          <label><input name="synthetic_disclosure" type="checkbox" /> Disclose synthetic media</label>
        </div>
        <label><input name="demo" type="checkbox" defaultChecked /> Demo render</label>
        <button disabled={!connected}>Queue video</button>
      </form></section>
      <section id="queue" hidden={view !== "queue"}><div className="section-heading">
        <h2>Recent jobs</h2>
        <label className="queue-filter">Status<select value={filter} onChange={event => setFilter(event.target.value)}>
          <option value="all">All jobs</option><option value="PENDING">Queued</option>
          <option value="RUNNING">Writing</option><option value="RENDERING">Rendering</option>
          <option value="READY_TO_PUBLISH">Ready</option><option value="FAILED">Failed</option>
          <option value="CANCELLED">Cancelled</option>
        </select></label></div>
        {!visibleJobs.length && <p className="empty-state">{connected ? "No jobs match this filter." : "Connect to view your jobs."}</p>}
        <ul>{visibleJobs.map(job => <li key={job.id}>
        <div><span className="job-id">{job.id.slice(0, 8)}</span>{" · "}
          <span className="state" data-state={job.state}>{job.state.toLowerCase().replaceAll("_", " ")}</span>
          {job.error && <div className="error-detail">{job.error}</div>}
        </div>
        {job.state === "FAILED" && <button onClick={() => void act(async () => {
          await api("jobs/" + job.id + "/recover", { method: "POST" }); await refresh();
        })}>Recover</button>}
        {job.state === "PENDING" && <button onClick={() => void act(async () => {
          await api("jobs/" + job.id + "/cancel", { method: "POST" }); await refresh();
        })}>Cancel</button>}
        {job.state === "READY_TO_PUBLISH" && <button onClick={() => void act(async () => {
          const file = await (await api("jobs/" + job.id + "/preview")).blob();
          setDeliveries(await (await api("jobs/" + job.id + "/deliveries")).json());
          setSelected(job); setMetrics(""); setPreview(URL.createObjectURL(file));
        })}>Preview</button>}
      </li>)}</ul>
      </section>
    </div>
    {selected && view === "queue" && <section className="preview-panel" aria-labelledby="preview-title">
      <div className="section-heading"><h2 id="preview-title">Preview and publishing</h2>
        <button className="secondary" onClick={() => {setSelected(undefined); setPreview(""); setDeliveries([]); setMetrics("");}}>Close preview</button>
      </div>
      {preview && <video controls src={preview} />}
      {selected && !selected.demo && <form onSubmit={publish}>
        <label>Platform<select name="platform"><option>youtube</option><option>facebook</option></select></label>
        <label>Upload time (optional)<input name="schedule" type="datetime-local" /></label>
        <label><input name="public" type="checkbox" /> Request public publication</label>
        <button>Schedule upload</button>
      </form>}
      <ul>{deliveries.map(delivery => <li key={delivery.platform}>{delivery.platform} · {delivery.state}
        {delivery.publish_at && " · " + new Date(delivery.publish_at).toLocaleString()}
        {delivery.state === "SUBMITTED" && <button onClick={() => void act(async () => {
          const data = await (await api("jobs/" + selected?.id + "/analytics/" + delivery.platform)).json();
          setMetrics(Object.entries(data).map(([key, value]) => key + " " + value).join(" · ") || "No metrics returned");
        })}>Metrics</button>}
      </li>)}</ul><p aria-live="polite">{metrics}</p>
    </section>}
    <section id="providers" className="provider-panel" hidden={view !== "providers"}><h2>Provider defaults</h2>
      <button className="secondary" disabled={!connected} onClick={() => void act(async () => {
        setUsage(await (await api("provider-usage")).json());
      })}>Load request history</button>
      <button className="secondary" disabled={!connected} onClick={() => void act(async () => {
        const result = await (await api("provider-health/openai")).json();
        setReport("OpenAI connection · " + result.status + (result.latency_ms == null ? "" : " · " + result.latency_ms + " ms"));
      })}>Test OpenAI connection</button>
      <button className="secondary" disabled={!connected} onClick={() => void act(async () => {
        const result = await (await api("provider-costs/openai")).json() as {
          scope: string; start: string; end: string; totals: Record<string, string>;
        };
        const totals = Object.entries(result.totals).map(([currency, value]) => currency + " " + value).join(" · ");
        setReport("OpenAI " + result.scope + " costs since " + result.start.slice(0, 10) +
          " UTC · " + (totals || "No costs reported"));
      })}>Read OpenAI costs</button>
      <button className="secondary" disabled={!connected} onClick={() => void act(async () => {
        const result = await (await api("provider-health/elevenlabs")).json() as {
          status: string; characters_used?: number; character_limit?: number;
          current_overage?: {amount: string; currency: string};
        };
        const usage = result.characters_used == null ? "" :
          " · " + result.characters_used.toLocaleString() + " / " + result.character_limit?.toLocaleString() + " characters";
        const overage = result.current_overage;
        setReport("ElevenLabs · " + result.status + usage +
          (overage ? " · Current overage " + overage.currency + " " + overage.amount : ""));
      })}>Check ElevenLabs subscription</button>
      {report && <p role="status">{report}</p>}
      {usage.length > 0 && <ul aria-label="Provider request history">{usage.map(row => <li key={row.host}>
        <strong>{row.host}</strong>
        <span>{row.requests} requests · {row.failures} failed · {row.average_ms} ms average</span>
        <span>{row.last_observed_at ? (row.last_success ? "Last request succeeded" : "Last request failed") + " · " +
          new Date(row.last_observed_at).toLocaleString() : "Last request time unavailable"}</span>
        <span>{row.reported_tokens ?? "Unavailable"} reported tokens</span>
      </li>)}</ul>}
      <form onSubmit={saveProviders}>
        <div className="field-grid">
          {[
            ["video_provider", "Video provider", "muse-video.com", "runway"],
            ["video_fallback", "Video backup", "muse-video.com", "runway"],
            ["runway_video_model", "Runway model", "gen4.5", "kling3.0_standard", "kling3.0_pro"],
            ["image_provider", "Illustrations", "openai", "vertex", "off"],
            ["tts_provider", "Voice provider", "openai", "elevenlabs"],
          ].map(([key, label, ...values]) => <label key={key}>{label}<select name={key}>
            <option value="">Use server settings</option>
            {values.map(value => <option key={value}>{value}</option>)}
          </select></label>)}
          {[
            ["image_model", "Illustration model"], ["tts_model", "Voice model"],
            ["tts_voice", "Voice ID"], ["tts_fallback_model", "Backup voice model"],
            ["tts_fallback_voice", "Backup voice ID"],
          ].map(([key, label]) => <label key={key}>{label}
            <input name={key} maxLength={200} placeholder="Use server settings" />
          </label>)}
          <label>Estimated story budget per job (USD)<input name="story_budget_usd" type="number" min="0" step="any" /></label>
        </div>
        <label>Story routing JSON<textarea name="story_routing" rows={9}
          placeholder="Leave blank to use the server configuration" spellCheck={false} /></label>
        <button type="button" disabled={!token} onClick={event => {
          const form = event.currentTarget.form;
          void act(async () => {
            const defaults = await (await api("providers")).json() as Record<string, unknown>;
            for (const [key, value] of Object.entries(defaults)) {
              const field = form?.elements.namedItem(key);
              if (field instanceof HTMLTextAreaElement) field.value = value ? JSON.stringify(value, null, 2) : "";
              if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement) field.value = String(value ?? "");
            }
          });
        }}>Load defaults</button>
        <button disabled={!token}>Save defaults</button>
      </form>
    </section>
  </main></div>;
}
