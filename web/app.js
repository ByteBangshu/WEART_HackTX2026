"use strict";
const $ = id => document.getElementById(id);
let csrf = "", current = null, stream = null, config = null, latestCreated = 0, locked = true;
const terminal = new Set(["COMPLETE","COMPLETE_ORG_ONLY","RETAKE","REJECTED_CARD_TYPE","FAILED","CANCELLED","EXPIRED"]);
function node(tag, text, cls) { const el = document.createElement(tag); if (text) el.textContent = text; if (cls) el.className = cls; return el; }
function notice(text) { $("notice").textContent = text; }
async function api(path, options = {}) {
  const headers = { ...options.headers };
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && path !== "/v1/session") lock();
    throw new Error(typeof body.detail === "string" ? body.detail : "Request could not be completed.");
  }
  return response.status === 204 ? null : response.json();
}
function lock() { locked = true; csrf = ""; if (stream) stream.close(); current = null; clearBrief(); if (!$("login").open) $("login").showModal(); $("logout").hidden = true; }
function clearBrief() { $("result").hidden = true; $("empty").hidden = false; $("brief-content").replaceChildren(); $("confidence").hidden = true; $("correction").reset(); }
async function unlock() {
  config = await api("/v1/session"); csrf = config.csrf; locked = false;
  $("login").close(); $("pin").value = ""; $("logout").hidden = false;
  $("mode").textContent = config.provider === "mock" ? "OFFLINE DEMO" : "LIVE · STANDARD MODE";
  $("demo").hidden = config.provider !== "mock"; $("scenario").disabled = config.provider !== "mock";
  $("ttl").textContent = config.ttl_minutes;
  notice(config.provider === "mock" ? "Demo workspace · All names, organizations, and source pages are fictional. Images are not read by AI in this mode." : "Live mode · Public professional sources only. Results may be inaccurate. Images are sent to Meta for processing.");
  await refreshJobs(true);
}
$("login").addEventListener("cancel", e => e.preventDefault());
$("login-form").addEventListener("submit", async e => { e.preventDefault(); try { const result = await api("/v1/session", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({pin:$("pin").value})}); csrf = result.csrf; $("login-error").textContent = ""; await unlock(); } catch (err) { $("login-error").textContent = err.message; } });
$("logout").onclick = () => action(async () => { await api("/v1/session",{method:"DELETE"}); lock(); });
$("theme").onclick = () => { document.body.classList.toggle("dark"); localStorage.setItem("weart-theme",document.body.classList.contains("dark") ? "dark" : "light"); };
if (localStorage.getItem("weart-theme") === "dark") document.body.classList.add("dark");
async function action(fn) { try { await fn(); } catch (err) { notice(err.message); } }
$("demo").onclick = () => action(async () => { const job = await api("/v1/demo?scenario=" + $("scenario").value, {method:"POST"}); watch(job.job_id); });
$("upload").onclick = $("rescan").onclick = () => $("file").click();
$("file").onchange = () => action(async () => { const file = $("file").files[0]; if (!file) return; if (file.size > 3000000) throw new Error("Choose a JPEG smaller than 3 MB."); const id = crypto.randomUUID(); const job = await api("/v1/captures", {method:"POST",headers:{"Content-Type":"image/jpeg","X-Capture-ID":id},body:file}); $("file").value=""; watch(job.job_id); });
function watch(id) {
  if (stream) stream.close(); current = id; clearBrief();
  $("empty").hidden = true; $("result").hidden = false;
  $("timeline").textContent = "Connecting to capture…";
  stream = new EventSource(`/v1/jobs/${id}/events`);
  stream.addEventListener("progress", e => { if (id !== current) return; render(JSON.parse(e.data)); });
  stream.addEventListener("forgotten", () => { stream.close(); current = null; clearBrief(); notice("This briefing was forgotten or expired."); });
  stream.onerror = () => { if (current === id) action(async () => { const result = await api(`/v1/jobs/${id}`); render(result); }); };
}
function cite(target, ids, evidence) {
  for (const id of ids) { const e = evidence.find(x => x.id === id); if (!e) continue; const a = node("a",`[${id.slice(1)}]`,"source-link"); try { const url = new URL(e.url); if (url.protocol !== "https:") continue; a.href = url.href; } catch { continue; } a.target="_blank"; a.rel="noopener noreferrer"; a.title=e.title; target.append(a); }
}
function label(parent,text) { parent.append(node("p",text,"section-label")); }
function render(job) {
  $("empty").hidden = true; $("result").hidden = false;
  $("timeline").replaceChildren(node("strong",job.message),node("span",`${job.state.replaceAll("_"," ")} · ${job.elapsed_seconds}s${job.mock ? " · simulated" : ""}`));
  const done=terminal.has(job.state); if (done && stream) stream.close();
  $("cancel").hidden=done; $("wrong").hidden=!job.brief; $("confirm").hidden=job.state!=="AWAITING_CONFIRMATION";
  $("correction").hidden=!job.extraction || ["RETAKE","CANCELLED","REJECTED_CARD_TYPE"].includes(job.state);
  if (job.extraction && !$("correction").contains(document.activeElement)) { $("person-name").value=job.extraction.name.normalized; $("person-org").value=job.extraction.organization.normalized; }
  const box=$("brief-content"); box.replaceChildren();
  const cardConfidence=job.classification?` · Card: ${job.classification.card_type} (${Math.round(job.classification.confidence*100)}% confidence)`:"";
  if (!job.brief) { $("confidence").hidden=!job.classification; if(job.classification)$("confidence").textContent=cardConfidence.slice(3); return; }
  const b=job.brief, evidence=job.evidence;
  $("confidence").hidden=false; $("confidence").textContent=(job.mock ? "DEMO · " : "") + ({high:"High match",medium:"Medium match",organization_only:"Organization only"}[b.confidence]) + cardConfidence;
  const title=node("h2",b.headline.text); cite(title,b.headline.source_ids,evidence); box.append(title);
  if (b.summary.length) { label(box,"Who they are"); for (const c of b.summary) { const p=node("p",c.text,"claim"); cite(p,c.source_ids,evidence); box.append(p); } }
  if (b.interests.length) { label(box,"What they work on"); const chips=node("div",null,"chips"); for (const c of b.interests) { const chip=node("div",c.text,"chip"); cite(chip,c.source_ids,evidence); chips.append(chip); } box.append(chips); }
  if (b.starters.length) { label(box,"A place to start"); for (const starter of b.starters) { const card=node("article",null,"starter"),head=node("div",null,"starter-head"),text=node("p",starter.text),copy=node("button","Copy"); cite(text,starter.source_ids,evidence); copy.type="button"; copy.setAttribute("aria-label","Copy conversation starter"); copy.onclick=()=>action(async()=>{await navigator.clipboard.writeText(starter.text);copy.textContent="Copied";setTimeout(()=>copy.textContent="Copy",1800);}); head.append(text,copy);card.append(head); const details=node("details");details.append(node("summary","Why this works"),node("p",starter.why));card.append(details);box.append(card); } }
  if (b.organization_snapshot) { label(box,"Organization snapshot"); const p=node("p",b.organization_snapshot.text,"claim");cite(p,b.organization_snapshot.source_ids,evidence);box.append(p); }
  for (const text of b.caveats) box.append(node("p",text,"caveat"));
  if (b.could_not_verify.length) box.append(node("p","Could not verify: " + b.could_not_verify.join("; "),"caveat"));
  if (evidence.length) { const details=node("details",null,"sources");details.append(node("summary",`${evidence.length} sources${job.mock ? " · fictional fixtures" : ""}`));const list=node("ol");for(const e of evidence){ const item=node("li"),link=node("a",e.title);link.href=e.url;link.target="_blank";link.rel="noopener noreferrer";item.append(link,node("div",`${e.publisher} · ${e.date || "Date unavailable"}`,"small"));list.append(item);}details.append(list);box.append(details); }
}
$("correction").onsubmit=e=>{e.preventDefault();action(async()=>{await api(`/v1/jobs/${current}/extraction`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:$("person-name").value,organization:$("person-org").value})});watch(current);});};
$("confirm").onclick=()=>action(async()=>{await api(`/v1/jobs/${current}/confirm`,{method:"POST"});});
$("wrong").onclick=()=>action(async()=>{await api(`/v1/jobs/${current}/next-candidate`,{method:"POST"});watch(current);});
$("cancel").onclick=()=>action(async()=>{await api(`/v1/jobs/${current}/cancel`,{method:"POST"});});
$("forget").onclick=()=>action(async()=>{const id=current;if(stream)stream.close();await api(`/v1/jobs/${id}`,{method:"DELETE"});current=null;clearBrief();await refreshJobs(false);});
$("purge").onclick=()=>action(async()=>{await api("/v1/purge",{method:"POST"});if(stream)stream.close();current=null;clearBrief();await refreshJobs(false);notice("All briefings and research cache entries were forgotten.");});
$("pair").onclick=()=>action(async()=>{const result=await api("/v1/devices/pair-code",{method:"POST"});$("pair-code").textContent=`${result.code} — expires in 5 minutes`;});
$("kill").onclick=()=>action(async()=>{const result=await api("/v1/kill-switch",{method:"POST"});notice(result.paused ? "New captures paused. Active jobs cancelled." : "Captures resumed.");});
async function refreshJobs(auto=true) { if(locked)return;const jobs=await api("/v1/jobs");$("recent").replaceChildren();if(!jobs.length)$("recent").append(node("p","No captures yet.","small"));for(const j of jobs.slice().reverse().slice(0,5)){const button=node("button",`${new Date(j.created_at*1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})} · ${j.state.replaceAll("_"," ")}`,"recent-item");button.onclick=()=>watch(j.id);$("recent").append(button);}if(current&&!jobs.some(j=>j.id===current)){if(stream)stream.close();current=null;clearBrief();}const newest=jobs.at(-1);if(auto&&newest&&newest.created_at>latestCreated){latestCreated=newest.created_at;if(newest.id!==current)watch(newest.id);} }
setInterval(()=>{if(!locked)action(()=>refreshJobs());},5000);
unlock().catch(lock);
if("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(()=>{});
