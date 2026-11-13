"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

type Job = { id: string; demo: number; state: string; error: string | null };
type Delivery = { platform: string; state: string; publish_at: string | null };

export default function Studio() {
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
          language: data.get("language"), style: data.get("style"), export_resolution: data.get("export_resolution") },
      }) });
      await refresh();
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
        image_provider: values.image_provider || null, tts_provider: values.tts_provider || null,
        story_budget_usd: budget ? Number(budget) : null,
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

  return <main>
    <header><h1>Story Video Studio</h1><a href="/classic">Provider settings and classic studio</a></header>
    <div className="connection"><label>Admin token<input type="password" autoComplete="off" value={token}
      onChange={event => {setToken(event.target.value); setJobs([]); setSelected(undefined); setPreview(""); setMetrics("");}} /></label>
      <button onClick={() => void act(refresh)}>Connect</button></div>
    <p role="alert">{error}</p>
    <div className="columns">
      <section><h2>New video</h2><form onSubmit={queue}>
        <label>Story or idea<textarea name="story" required maxLength={24000} rows={5} /></label>
        <label>Final changes<textarea name="final_changes" rows={2} /></label>
        <label>Language<input name="language" defaultValue="বাংলা" /></label>
        <label>Visual style<input name="style" defaultValue="Cinematic natural light" /></label>
        <label>Export resolution<select name="export_resolution" defaultValue="1080p">
          <option>720p</option><option>1080p</option><option>1440p</option><option value="2160p">4K</option>
        </select></label>
        <label><input name="demo" type="checkbox" defaultChecked /> Demo render</label>
        <button disabled={!token}>Queue video</button>
      </form></section>
      <section><h2>Job queue</h2><ul>{jobs.map(job => <li key={job.id}>
        <span>{job.id.slice(0, 8)} · {job.state} {job.error}</span>
        {job.state === "PENDING" && <button onClick={() => void act(async () => {
          await api("jobs/" + job.id + "/cancel", { method: "POST" }); await refresh();
        })}>Cancel</button>}
        {job.state === "READY_TO_PUBLISH" && <button onClick={() => void act(async () => {
          const file = await (await api("jobs/" + job.id + "/preview")).blob();
          setDeliveries(await (await api("jobs/" + job.id + "/deliveries")).json());
          setSelected(job); setMetrics(""); setPreview(URL.createObjectURL(file));
        })}>Preview</button>}
      </li>)}</ul>
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
      </section>
    </div>
    <section className="provider-panel"><h2>Provider defaults</h2>
      <form onSubmit={saveProviders}>
        <div className="columns">
          {[
            ["video_provider", "Video provider", "muse-video.com", "runway"],
            ["video_fallback", "Video backup", "muse-video.com", "runway"],
            ["image_provider", "Illustrations", "openai", "off"],
            ["tts_provider", "Voice provider", "openai", "elevenlabs"],
          ].map(([key, label, ...values]) => <label key={key}>{label}<select name={key}>
            <option value="">Use server settings</option>
            {values.map(value => <option key={value}>{value}</option>)}
          </select></label>)}
          <label>Estimated story budget per job (USD)<input name="story_budget_usd" type="number" min="0" step="any" /></label>
        </div>
        <button type="button" disabled={!token} onClick={event => {
          const form = event.currentTarget.form;
          void act(async () => {
            const defaults = await (await api("providers")).json() as Record<string, string | number | null>;
            for (const [key, value] of Object.entries(defaults)) {
              const field = form?.elements.namedItem(key);
              if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement) field.value = String(value ?? "");
            }
          });
        }}>Load defaults</button>
        <button disabled={!token}>Save defaults</button>
      </form>
    </section>
  </main>;
}
