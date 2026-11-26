"use strict";

const $ = (selector) => document.querySelector(selector);
const transcript = $("#transcript");
const statusLine = $("#status");
const crmStatus = $("#crm-status");
const player = new Audio();
const dateFormat = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short",
});
const timeFormat = new Intl.DateTimeFormat("en-IN", {timeZone: "Asia/Kolkata", timeStyle: "short"});

let call = null;
let busy = false;
let recorder = null;
let recordingTimeout = null;
let playbackToken = 0;
let objectUrl = null;
let cancelWelcome = null;
let crmSelection = null;
let crmRequest = 0;
let continuous = false;
let discardRecording = false;
let speaking = false;
let liveMic = null;

function closeLiveMic() {
  liveMic?.close();
  liveMic = null;
}

function startLiveMic() {
  stopAudio();
  const microphone = new LiveMicrophone({
    speak: () => $("#speak-replies").checked,
    ready: () => notice("Gemini Live is listening."),
    status: message => notice(message),
    fail: message => {
      if (microphone !== liveMic) return;
      closeLiveMic();
      $("#voice-mode").value = "local";
      updateControls();
      notice(message, true);
    },
    turn: message => {
      if (message.call) renderCall(message.call);
      if (message.bookingHandoff) {
        closeLiveMic();
        $("#voice-mode").value = "local";
        continuous = true;
        updateControls();
        if ($("#speak-replies").checked) void play(call.turns.at(-1).id);
        else resumeListening();
      }
    },
  });
  liveMic = microphone;
  updateControls();
  notice("Connecting to Gemini Live…");
  void microphone.start(call.id).catch(error => microphone.events.fail(error.message));
}
player.addEventListener("ended", () => { speaking = false; resumeListening(); });
player.addEventListener("error", () => { speaking = false; continuous = false; updateControls(); });
function resumeListening() {
  if (continuous && !busy && !speaking && !recorder && call && !call.ended_at) void record();
}

function element(tag, text, cssClass) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cssClass) node.className = cssClass;
  return node;
}

function notice(text, isError = false, target = statusLine) {
  target.hidden = !text;
  target.textContent = text || "";
  target.classList.toggle("error", isError);
}

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : "Request failed (" + response.status + ").");
  }
  return response;
}

async function jsonRequest(url, options) {
  return (await request(url, options)).json();
}

function stopAudio() {
  speaking = false;
  playbackToken += 1;
  cancelWelcome?.();
  player.pause();
  player.removeAttribute("src");
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = null;
}

function playWelcome(language) {
  stopAudio();
  return new Promise((resolve) => {
    const ended = () => settle(null);
    const failed = () => settle("Welcome audio couldn't play. Select Play reply to retry.");
    const timeout = window.setTimeout(() => {
      failed();
      stopAudio();
    }, 35000);

    function settle(error) {
      if (cancelWelcome !== ended) return;
      cancelWelcome = null;
      window.clearTimeout(timeout);
      player.removeEventListener("ended", ended);
      player.removeEventListener("error", failed);
      resolve(error);
    }

    cancelWelcome = ended;
    player.addEventListener("ended", ended);
    player.addEventListener("error", failed);
    player.src = "/api/greetings/" + language + "/audio";
    player.play().catch(() => {
      if (cancelWelcome === ended) failed();
    });
  });
}

async function play(turnId) {
  stopAudio();
  const token = playbackToken;
  speaking = true;
  try {
    const response = await request("/api/turns/" + turnId + "/audio");
    const blob = await response.blob();
    if (token !== playbackToken) return;
    objectUrl = URL.createObjectURL(blob);
    player.src = objectUrl;
    await player.play();
  } catch (error) {
    if (token === playbackToken) { speaking = false; continuous = false; notice(error.message, true); updateControls(); }
  }
}

function createTurn(turn, allowAudio) {
  const item = element("article", undefined, "turn");
  item.dataset.role = turn.role;
  const header = element("div", undefined, "turn-header");
  header.append(element("strong", turn.role === "caller" ? "Customer" : "Assistant"));
  header.append(element("time", timeFormat.format(new Date(turn.created_at))));
  if (turn.generated_by === "llm") {
    header.append(element("span", "LLM-generated", "generation-label"));
  }
  if (turn.role === "assistant" && allowAudio) {
    const replay = element("button", "Play reply", "replay");
    replay.type = "button";
    replay.addEventListener("click", () => {
      if (!busy && !recorder && !liveMic) void play(turn.id);
    });
    header.append(replay);
  }
  const bubble = element("p", turn.text, "bubble");
  if (turn.language === "hi" || turn.language === "en") bubble.lang = turn.language;
  item.append(header, bubble);
  if (turn.sources.length) {
    const details = element("details", undefined, "sources");
    details.append(element("summary", "Retrieved sources (" + turn.sources.length + ")"));
    for (const source of turn.sources) {
      const excerpt = element("div", undefined, "source");
      const label = source.source + (source.page ? " · p. " + source.page : "");
      excerpt.append(element("strong", label), element("p", source.text));
      details.append(excerpt);
    }
    item.append(details);
  }
  return item;
}

function displayTurns(container, turns, allowAudio) {
  const items = turns.map((turn) => createTurn(turn, allowAudio));
  container.replaceChildren(...items);
}

function offerButton(text, value) {
  const button = element("button", text);
  button.type = "button";
  button.disabled = busy || Boolean(recorder);
  button.addEventListener("click", () => { void sendTurn({text: value}); });
  return button;
}

function updateControls() {
  const live = Boolean(call && !call.ended_at);
  const recording = Boolean(recorder || liveMic);
  $("#start").hidden = live;
  $("#start").disabled = busy;
  $("#end").hidden = !live;
  $("#end").disabled = busy;
  $("#record").hidden = !live;
  $("#record").disabled = busy;
  $("#record").classList.toggle("recording", recording);
  $("#record span").textContent = (continuous || liveMic) ? "Pause microphone" : "Start microphone";
  $("#text-form").hidden = !live;
  $("#text-input").disabled = busy || recording;
  $("#send").disabled = busy || recording;
  $("#language").disabled = live || busy;
  $("#voice-mode").disabled = busy || recording || (live && call.booking_active);
  $("#cloud-note").hidden = $("#voice-mode").value !== "gemini";
  const state = $("#call-state");
  state.dataset.live = String(live);
  state.dataset.recording = String(recording);
  const language = call?.language === "hi" ? "Hindi" : call?.language === "en" ? "English" : "";
  const activeLabel = language ? "In conversation · " + language : "In conversation";
  const label = recording ? "Listening" : busy ? "Working…" : live ? activeLabel : call ? "Ended" : "Ready";
  state.replaceChildren(element("span"), document.createTextNode(label));

  const options = $("#booking-options");
  options.replaceChildren();
  if (live && call.options.length) {
    call.options.forEach((option) => options.append(offerButton(option.value + ". " + option.label, option.value)));
  }
  if (live && call.awaiting_confirmation) {
    options.append(offerButton("Confirm booking", "yes"), offerButton("Cancel", "cancel"));
  }
  options.hidden = options.childElementCount === 0;
}

function setBusy(value) {
  busy = value;
  updateControls();
}

function renderCall(nextCall) {
  call = nextCall;
  if (call.ended_at) {
    sessionStorage.removeItem("showroom-call");
  } else {
    sessionStorage.setItem("showroom-call", call.id);
  }
  displayTurns(transcript, call.turns, true);
  transcript.scrollTop = transcript.scrollHeight;

  const confirmed = $("#confirmed");
  confirmed.hidden = call.bookings.length === 0;
  if (call.bookings.length) {
    const last = call.bookings.at(-1);
    confirmed.textContent = "Confirmed · " + last.reference + " · " + last.vehicle + " · " + dateFormat.format(new Date(last.slot)) + " IST";
  }
  updateControls();
}

async function start(language, playGreeting = false) {
  if (busy || (call && !call.ended_at)) return false;
  setBusy(true);
  const voiceMode = $("#voice-mode").value;
  const greetingLanguage = voiceMode === "gemini" && language === "auto" ? "en" : language;
  const opening = playGreeting && $("#speak-replies").checked ? playWelcome(greetingLanguage) : null;
  notice("Starting conversation…");
  try {
    const created = await jsonRequest("/api/calls", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({language, voice_mode: voiceMode}),
    });
    renderCall(created);
    if (opening) {
      notice("Welcome audio…");
      const playbackError = await opening;
      notice(playbackError, Boolean(playbackError));
    } else {
      notice("");
    }
    return true;
  } catch (error) {
    if (opening) stopAudio();
    notice(error.message, true);
    return false;
  } finally {
    setBusy(false);
  }
}

async function end() {
  if (!call || call.ended_at || busy) return;
  closeLiveMic();
  continuous = false;
  discardRecording = true;
  stopRecording();
  stopAudio();
  setBusy(true);
  try {
    renderCall(await jsonRequest("/api/calls/" + call.id + "/end", {method: "POST"}));
    notice("Conversation saved to CRM.");
  } catch (error) {
    notice(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function sendTurn({text, audio}) {
  if (!call || call.ended_at || busy || liveMic) return;
  stopAudio();
  setBusy(true);
  notice(audio ? "Transcribing and preparing a reply…" : "Preparing a reply…");
  const form = new FormData();
  if (audio) {
    const extension = audio.type.includes("ogg") ? "ogg" : audio.type.includes("mp4") ? "mp4" : "webm";
    form.append("audio", audio, "microphone." + extension);
  } else {
    form.append("text", text);
  }
  try {
    const response = await jsonRequest("/api/calls/" + call.id + "/turn", {method: "POST", body: form});
    renderCall(response.call);
    notice(response.notice);
    if ($("#speak-replies").checked) await play(call.turns.at(-1).id);
  } catch (error) {
    notice(error.message, true);
    continuous = false;
    if (text) $("#text-input").value = text;
  } finally {
    setBusy(false);
    resumeListening();
  }
}

function stopRecording() {
  if (recorder && recorder.state !== "inactive") recorder.stop();
}

async function record() {
  if (busy || !call || call.ended_at) return;
  if (recorder) {
    stopRecording();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    notice("Microphone recording is unavailable. Open this page on localhost in Edge or Chrome, or type your reply.", true);
    return;
  }
  stopAudio();
  setBusy(true);
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio: {
      echoCancellation: true, noiseSuppression: true, channelCount: 1,
    }});
    discardRecording = false;
    const context = new AudioContext();
    await context.resume();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    let heardSpeech = false;
    let voicedFrames = 0;
    let lastVoice = performance.now();
    const detector = setInterval(() => {
      analyser.getFloatTimeDomainData(samples);
      let energy = 0;
      for (const sample of samples) energy += sample * sample;
      if (Math.sqrt(energy / samples.length) > 0.018) {
        voicedFrames += 1;
        heardSpeech = voicedFrames >= 3;
        lastVoice = performance.now();
      }
      if (heardSpeech && performance.now() - lastVoice > 1000) stopRecording();
    }, 80);
    const chunks = [];
    const currentRecorder = new MediaRecorder(stream);
    currentRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) chunks.push(event.data);
    });
    currentRecorder.addEventListener("error", () => {
      notice("The microphone stopped unexpectedly. Try recording again.", true);
    });
    currentRecorder.addEventListener("stop", () => {
      clearTimeout(recordingTimeout);
      clearInterval(detector);
      source.disconnect();
      void context.close();
      stream.getTracks().forEach((track) => track.stop());
      recorder = null;
      updateControls();
      if (discardRecording || !heardSpeech) {
        discardRecording = false;
        resumeListening();
        return;
      }
      if (!chunks.length) {
        notice("The microphone recording was empty.", true);
        return;
      }
      void sendTurn({audio: new Blob(chunks, {type: currentRecorder.mimeType})});
    });
    currentRecorder.start();
    recorder = currentRecorder;
    recordingTimeout = setTimeout(stopRecording, 25000);
    notice("Listening. Select Stop and send when you’re done.");
  } catch (error) {
    stream?.getTracks().forEach((track) => track.stop());
    continuous = false;
    notice("Microphone access failed. Check your browser permission or type your reply.", true);
  } finally {
    setBusy(false);
  }
}

async function showCall(callId) {
  const sequence = ++crmRequest;
  if (!$("#customer-dialog").open) $("#customer-dialog").showModal();
  $("#call-details").replaceChildren(element("p", "Loading conversation…", "empty-message"));
  crmSelection = callId;
  for (const row of $("#call-list").querySelectorAll("button")) {
    row.setAttribute("aria-pressed", String(row.dataset.id === callId));
  }
  try {
    const record = await jsonRequest("/api/calls/" + callId);
    if (sequence !== crmRequest) return;
    const summary = element("div", undefined, "call-summary");
    summary.append(element("h3", record.ended_at ? "Summary" : "Conversation in progress"));
    summary.append(element("p", record.summary || "Transcript so far. End the conversation to save its summary."));
    if (record.bookings.length) {
      const bookings = element("ul");
      for (const entry of record.bookings) {
        bookings.append(element("li", entry.reference + " · " + entry.vehicle + " · " +
          dateFormat.format(new Date(entry.slot)) + " IST · " + entry.customer + " · " + entry.phone));
      }
      summary.append(bookings);
    }
    const detailTranscript = element("div", undefined, "transcript");
    displayTurns(detailTranscript, record.turns, false);
    $("#call-details").replaceChildren(summary, detailTranscript);
    notice("", false, crmStatus);
  } catch (error) {
    if (sequence === crmRequest) $("#call-details").replaceChildren(element("p", error.message, "empty-message"));
  }
}

const calendarDateFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
});
function dateKey(value) {
  const parts = Object.fromEntries(calendarDateFormat.formatToParts(new Date(value)).map(part => [part.type, part.value]));
  return parts.year + "-" + parts.month + "-" + parts.day;
}
let selectedDate = dateKey(new Date());
let calendarMonth = selectedDate.slice(0, 7);
let calendarBookings = [];
let crmRefreshSequence = 0;

function renderCalendar() {
  const [year, month] = calendarMonth.split("-").map(Number);
  const first = new Date(Date.UTC(year, month - 1, 1));
  $("#calendar-title").textContent = new Intl.DateTimeFormat("en-IN", {month: "long", year: "numeric", timeZone: "UTC"}).format(first);
  const cells = [];
  const offset = (first.getUTCDay() + 6) % 7;
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const today = dateKey(new Date());
  const total = Math.ceil((days + offset) / 7) * 7;
  for (let index = 0; index < total; index++) {
    const date = new Date(Date.UTC(year, month - 1, index - offset + 1));
    const key = date.toISOString().slice(0, 10);
    const entries = calendarBookings.filter(booking => dateKey(booking.slot) === key);
    const cell = element("div", undefined, "calendar-cell");
    cell.classList.toggle("outside-month", key.slice(0, 7) !== calendarMonth);
    cell.classList.toggle("selected-date", selectedDate === key);
    const button = element("button", String(date.getUTCDate()), "date-number");
    button.type = "button";
    button.setAttribute("aria-pressed", String(selectedDate === key));
    button.setAttribute("aria-label", key + ", " + entries.length + " bookings");
    if (key === today) button.setAttribute("aria-current", "date");
    const selectDay = () => { selectedDate = key; renderCalendar(); };
    button.addEventListener("click", selectDay);
    cell.addEventListener("click", event => { if (event.target === cell) selectDay(); });
    cell.append(button);
    for (const booking of entries) {
      const chip = element("button", undefined, "calendar-event");
      chip.type = "button";
      chip.append(element("span", timeFormat.format(new Date(booking.slot))), element("strong", booking.customer), element("small", booking.vehicle));
      chip.addEventListener("click", () => {
        selectedDate = key;
        renderCalendar();
        void showCall(booking.call_id);
      });
      cell.append(chip);
    }
    cells.push(cell);
  }
  $("#calendar-days").replaceChildren(...cells);
  $("#booking-day-title").textContent = new Intl.DateTimeFormat("en-IN", {day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Kolkata"}).format(new Date(selectedDate + "T12:00:00+05:30"));
  const appointments = calendarBookings.filter(booking => dateKey(booking.slot) === selectedDate);
  const rows = appointments.map(booking => {
    const row = element("article", undefined, "appointment");
    const person = element("button", booking.customer, "customer-link");
    person.type = "button";
    person.addEventListener("click", async () => {
      await showCall(booking.call_id);
      $("#detail-heading").focus();

    });
    row.append(element("time", timeFormat.format(new Date(booking.slot))), person,
      element("p", booking.vehicle), element("small", booking.reference + " · " + booking.phone));
    return row;
  });
  $("#day-bookings").replaceChildren(...(rows.length ? rows : [element("p", "No test drives booked for this date.", "empty-message")]));
}
function moveCalendarMonth(delta) {
  const [year, month] = calendarMonth.split("-").map(Number);
  const next = new Date(Date.UTC(year, month - 1 + delta, 1));
  calendarMonth = next.getUTCFullYear() + "-" + String(next.getUTCMonth() + 1).padStart(2, "0");
  selectedDate = calendarMonth + "-01";
  renderCalendar();
}
$("#close-customer").addEventListener("click", () => { ++crmRequest; $("#customer-dialog").close(); });
$("#calendar-prev").addEventListener("click", () => moveCalendarMonth(-1));
$("#calendar-next").addEventListener("click", () => moveCalendarMonth(1));
$("#calendar-today").addEventListener("click", () => {
  selectedDate = dateKey(new Date()); calendarMonth = selectedDate.slice(0, 7); renderCalendar();
});

async function refreshCRM() {
  const sequence = ++crmRefreshSequence;
  renderCalendar();
  notice("Loading conversations and bookings…", false, crmStatus);
  try {
    const [calls, bookings] = await Promise.all([jsonRequest("/api/calls"), jsonRequest("/api/bookings")]);
    if (sequence !== crmRefreshSequence) return;
    calendarBookings = bookings;
    renderCalendar();
    const rows = calls.map((entry) => {
      const button = element("button");
      button.type = "button";
      button.dataset.id = entry.id;
      button.setAttribute("aria-pressed", String(entry.id === crmSelection));
      const time = dateFormat.format(new Date(entry.started_at));
      const language = entry.language === "hi" ? "Hindi" : entry.language === "en" ? "English" : "Language undecided";
      const outcome = entry.booking_count ? " · Booked" : "";
      button.append(element("strong", time + " IST"), element("small", language + (entry.ended_at ? " · Ended" : " · Active") + outcome));
      button.addEventListener("click", () => { void showCall(entry.id); });
      return button;
    });
    $("#call-list").replaceChildren(...(rows.length ? rows : [element("div", "No saved conversations yet.", "empty-message")]));
    notice("", false, crmStatus);

  } catch (error) {
    notice(error.message, true, crmStatus);
  }
}

$("#start").addEventListener("click", () => {
  void start($("#language").value, true);
});
$("#end").addEventListener("click", () => { void end(); });
$("#voice-mode").addEventListener("change", updateControls);
$("#record").addEventListener("click", () => {
  if ($("#voice-mode").value === "gemini") {
    if (liveMic) {
      closeLiveMic();
      notice("Microphone paused.");
      updateControls();
    } else if (call.booking_active) {
      $("#voice-mode").value = "local";
      updateControls();
      notice("This booking continues in local mode.");
    } else {
      startLiveMic();
    }
    return;
  }
  continuous = !continuous;
  if (!continuous) { discardRecording = true; stopRecording(); }
  else void record();
  updateControls();
});
$("#refresh").addEventListener("click", () => { void refreshCRM(); });
$("#speak-replies").addEventListener("change", (event) => {
  if (!event.target.checked) { stopAudio(); liveMic?.clearAudio(); }
});
$("#text-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("#text-input").value.trim();
  if (!text) return;
  $("#text-input").value = "";
  void sendTurn({text});
});
for (const example of document.querySelectorAll("[data-example]")) {
  example.addEventListener("click", async () => {
    if (busy || recorder || liveMic) return;
    if (!call || call.ended_at) {
      const started = await start($("#language").value);
      if (!started) return;
    }
    $("#text-input").value = example.dataset.example;
    $("#text-input").focus();
  });
}
for (const button of document.querySelectorAll("[data-view]")) {
  button.addEventListener("click", () => {
    for (const item of document.querySelectorAll("[data-view]")) {
      if (item === button) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    }
    const isCRM = button.dataset.view === "crm";
    $("#conversation-view").hidden = isCRM;
    $("#crm-view").hidden = !isCRM;
    if (isCRM) void refreshCRM();
  });
}

function serviceStatus(selector, name, status) {
  const state = $(selector);
  if (state.dataset.model !== status) {
    state.dataset.model = status;
    state.replaceChildren(element("span"), document.createTextNode(name + " " + status));
  }
}

async function updateServiceStatus() {
  const status = await jsonRequest("/api/status").catch(() => ({}));
  serviceStatus("#model-state", "LFM3", status.llm || "offline");
  serviceStatus("#rag-state", "RAG", status.rag || "offline");
}

void updateServiceStatus();
window.setInterval(updateServiceStatus, 5000);

const activeCall = sessionStorage.getItem("showroom-call");
if (activeCall) {
  setBusy(true);
  jsonRequest("/api/calls/" + encodeURIComponent(activeCall))
    .then(renderCall)
    .catch(() => sessionStorage.removeItem("showroom-call"))
    .finally(() => setBusy(false));
} else {
  updateControls();
}
