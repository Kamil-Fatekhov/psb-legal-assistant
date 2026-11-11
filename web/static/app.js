// Юридический ассистент ПСБ — клиент веб-чата.
// Вся разметка строится через DOM API и textContent: текст пользователя,
// модели и документов никогда не вставляется как HTML.
"use strict";

(() => {
  const REQUEST_TIMEOUT_MS = 120000;
  const MAX_HISTORY = 20;
  const STORAGE_KEY = "psb-legal-chat-v1";

  const STATUS_LABELS = {
    answered: "Ответ подтверждён источниками",
    partial: "Частичный ответ",
    insufficient: "Недостаточно данных в базе",
    clarification_needed: "Нужно уточнение",
    declined: "Вне рамок ассистента",
  };

  const $ = (id) => document.getElementById(id);
  const els = {
    log: $("log"),
    empty: $("empty"),
    form: $("composer"),
    input: $("question"),
    send: $("send"),
    newChat: $("new-chat"),
    modeNote: $("mode-note"),
    panel: $("source-panel"),
    placeholder: $("source-placeholder"),
    view: $("source-view"),
    collection: $("doc-collection"),
    title: $("doc-title"),
    meta: $("doc-meta"),
    body: $("doc-body"),
    docId: $("doc-id"),
    copy: $("source-copy"),
    link: $("source-link"),
    close: $("source-close"),
    back: $("source-back"),
    toast: $("toast"),
  };

  // Диалог: user {role, text} | assistant {role, answer} | error {role:"error", ...}
  let messages = [];
  let pending = false;
  let currentSource = null;
  let lastTrigger = null;

  // ---------- Утилиты ----------

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function splitTitle(raw) {
    // ID документа у A: «папка__имя файла». Показываем папку отдельно.
    const parts = String(raw || "").split("__");
    const name = parts.pop() || "Документ";
    return { collection: parts.join(" / "), name };
  }

  function formatDate(iso) {
    if (!iso) return null;
    const [y, m, d] = iso.split("-");
    return `${d}.${m}.${y}`;
  }

  function isNarrow() {
    return window.matchMedia("(max-width: 899px)").matches;
  }

  function answerToText(answer) {
    // Текст ответа ассистента для history. Ядро не считает его доказательством.
    const parts = [];
    if (answer.note) parts.push(answer.note);
    answer.findings.forEach((f) => parts.push(f.text));
    if (answer.clarifying_question) parts.push(answer.clarifying_question);
    return parts.join("\n");
  }

  function buildHistory(upTo) {
    const history = [];
    for (const m of messages.slice(0, upTo)) {
      // Вопрос без ответа (сбой) и сообщения об ошибке в историю не идут.
      if (m.role === "user" && !m.failed) history.push({ role: "user", text: m.text });
      else if (m.role === "assistant") history.push({ role: "assistant", text: answerToText(m.answer) });
    }
    return history.slice(-MAX_HISTORY);
  }

  function save() {
    try {
      const keep = messages.filter((m) => m.role !== "error" && !(m.role === "user" && m.failed));
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(keep));
    } catch (_) { /* хранилище недоступно — диалог живёт до перезагрузки */ }
  }

  function restore() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) {
        messages = parsed.filter((m) => m && (m.role === "user" || (m.role === "assistant" && m.answer)));
      }
    } catch (_) {
      messages = [];
    }
  }

  let toastTimer = null;
  function toast(text) {
    els.toast.textContent = text;
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { els.toast.hidden = true; }, 2200);
  }

  async function copyText(text, done) {
    try {
      await navigator.clipboard.writeText(text);
      toast(done);
    } catch (_) {
      toast("Не удалось скопировать: браузер запретил доступ к буферу обмена");
    }
  }

  // ---------- API ----------

  class ApiError extends Error {
    constructor(status, code, message, requestId) {
      super(message);
      this.status = status;
      this.code = code;
      this.requestId = requestId;
    }
  }

  async function api(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    let response;
    try {
      response = await fetch(path, {
        ...options,
        signal: controller.signal,
        headers: { Accept: "application/json", ...(options.headers || {}) },
      });
    } catch (err) {
      const timeout = err && err.name === "AbortError";
      throw new ApiError(0, timeout ? "timeout" : "network",
        timeout ? "Ассистент не ответил за 2 минуты." : "Нет связи с сервером. Проверьте, что он запущен.", null);
    } finally {
      clearTimeout(timer);
    }
    let data = null;
    try { data = await response.json(); } catch (_) { /* тело не JSON */ }
    if (!response.ok) {
      const e = (data && data.error) || {};
      throw new ApiError(response.status, e.code || "http_" + response.status,
        e.message || `Сервер вернул ошибку ${response.status}.`,
        (data && data.request_id) || response.headers.get("X-Request-ID"));
    }
    return data;
  }

  // ---------- Отрисовка диалога ----------

  function render() {
    els.log.querySelectorAll(".msg").forEach((n) => n.remove());
    els.empty.hidden = messages.length > 0 || pending;
    messages.forEach((m) => els.log.appendChild(renderMessage(m)));
    if (pending) els.log.appendChild(renderThinking());
    els.log.scrollTop = els.log.scrollHeight;
  }

  function renderMessage(m) {
    if (m.role === "user") {
      const node = el("div", "msg msg-user");
      node.appendChild(el("p", "msg-text", m.text));
      return node;
    }
    if (m.role === "error") return renderError(m);
    return renderAnswer(m.answer);
  }

  function renderThinking() {
    const node = el("div", "msg msg-assistant status-declined");
    const row = el("div", "thinking");
    const dots = el("span", "thinking-dots");
    dots.setAttribute("aria-hidden", "true");
    dots.append(el("span"), el("span"), el("span"));
    row.append(dots, el("span", null, "Ищу положения в базе и проверяю ссылки…"));
    node.appendChild(row);
    return node;
  }

  function renderAnswer(answer) {
    const status = STATUS_LABELS[answer.status] ? answer.status : "declined";
    const node = el("div", `msg msg-assistant status-${status}`);
    node.appendChild(el("p", "status-line", STATUS_LABELS[status]));

    // Номера сносок — в порядке первого упоминания, как в списке sources.
    const numbers = new Map();
    const refs = new Map();
    (answer.sources || []).forEach((s) => refs.set(s.fragment_id, s));
    answer.findings.forEach((f) => f.source_ids.forEach((id) => {
      if (!numbers.has(id)) numbers.set(id, numbers.size + 1);
    }));

    if (answer.findings.length) {
      const list = el("ul", "findings");
      answer.findings.forEach((finding) => {
        const li = el("li", "finding");
        li.appendChild(el("span", "finding-text", finding.text));
        finding.source_ids.forEach((id) => li.appendChild(citeButton(id, numbers.get(id), refs.get(id))));
        list.appendChild(li);
      });
      node.appendChild(list);
    }

    if (answer.note) node.appendChild(el("p", "note", answer.note));

    if (answer.clarifying_question) {
      const block = el("div", "block block-question");
      block.appendChild(el("p", "block-title", "Вопрос ассистента"));
      block.appendChild(el("p", null, answer.clarifying_question));
      node.appendChild(block);
    }

    if (answer.missing && answer.missing.length) {
      const block = el("div", "block block-missing");
      block.appendChild(el("p", "block-title", "Чего не хватает в базе"));
      const ul = el("ul");
      answer.missing.forEach((item) => ul.appendChild(el("li", null, item)));
      block.appendChild(ul);
      node.appendChild(block);
    }

    if (numbers.size) {
      const list = el("ol", "sources-list");
      list.setAttribute("aria-label", "Источники");
      numbers.forEach((n, id) => {
        const ref = refs.get(id) || { fragment_id: id, found: false };
        const li = el("li");
        const btn = el("button", "source-ref");
        btn.type = "button";
        btn.dataset.fragmentId = id;
        btn.appendChild(el("span", "source-num", `[${n}]`));
        const label = el("span");
        if (ref.found) {
          const t = splitTitle(ref.title);
          label.appendChild(el("span", "source-title", t.name));
          label.appendChild(el("span", "source-sub", ref.point || ""));
          btn.addEventListener("click", () => openSource(id, btn));
        } else {
          btn.disabled = true;
          label.appendChild(el("span", "source-title", "Источник не найден в каталоге"));
          label.appendChild(el("span", "source-sub", id));
        }
        btn.appendChild(label);
        li.appendChild(btn);
        list.appendChild(li);
      });
      node.appendChild(list);
    }
    return node;
  }

  function citeButton(id, n, ref) {
    const btn = el("button", "cite", String(n));
    btn.type = "button";
    btn.dataset.fragmentId = id;
    if (ref && ref.found) {
      const t = splitTitle(ref.title);
      btn.title = `${t.name}${ref.point ? ", " + ref.point : ""}`;
      btn.setAttribute("aria-label", `Источник ${n}: ${btn.title}`);
      btn.addEventListener("click", () => openSource(id, btn));
    } else {
      btn.classList.add("is-missing");
      btn.title = "Источник не найден в каталоге";
      btn.setAttribute("aria-label", `Источник ${n} не найден в каталоге`);
    }
    return btn;
  }

  function renderError(m) {
    const node = el("div", "msg msg-assistant status-error");
    node.appendChild(el("p", "status-line", m.title));
    node.appendChild(el("p", "note", m.text));
    if (m.retry && !pending) {
      const row = el("div", "retry-row");
      const btn = el("button", "btn btn-quiet", "Повторить запрос");
      btn.type = "button";
      btn.addEventListener("click", () => retry(m));
      row.appendChild(btn);
      node.appendChild(row);
    }
    if (m.requestId) node.appendChild(el("p", "meta-id", `Код запроса: ${m.requestId}`));
    return node;
  }

  function describeError(err) {
    if (err.status === 503 && err.code === "dependency_unavailable") {
      return { title: "Сервис временно недоступен", text: "Поиск или языковая модель сейчас не отвечают. Вопрос сохранён — повторите запрос через минуту.", retry: true };
    }
    if (err.status === 503) return { title: "Ассистент не готов", text: err.message, retry: true };
    if (err.status === 422) return { title: "Запрос не принят", text: err.message, retry: false };
    if (err.status === 502) return { title: "Ответ не прошёл проверку", text: err.message, retry: true };
    if (err.status === 0) return { title: "Нет ответа от сервера", text: err.message, retry: true };
    return { title: "Ошибка сервера", text: err.message, retry: true };
  }

  // ---------- Отправка ----------

  function setPending(value) {
    pending = value;
    els.send.disabled = value;
    els.input.setAttribute("aria-busy", String(value));
  }

  async function ask(user) {
    const payload = { question: user.text, history: buildHistory(messages.indexOf(user)) };
    setPending(true);
    render();
    let reply;
    try {
      const answer = await api("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      user.failed = false;
      reply = { role: "assistant", answer };
      els.input.placeholder = answer.status === "clarification_needed"
        ? "Ответьте на уточняющий вопрос"
        : "Задайте вопрос по документам базы";
    } catch (err) {
      user.failed = true;
      reply = { role: "error", ...describeError(err), requestId: err.requestId, user };
    } finally {
      // Ответ встаёт сразу после своего вопроса, даже если это повтор старого запроса.
      const at = messages.indexOf(user);
      if (reply) messages.splice(at < 0 ? messages.length : at + 1, 0, reply);
      setPending(false);
      save();
      render();
      els.input.focus();
    }
  }

  function submit(text) {
    const question = (text ?? els.input.value).trim();
    if (!question || pending) return;
    const user = { role: "user", text: question };
    messages.push(user);
    els.input.value = "";
    autosize();
    ask(user);
  }

  function retry(error) {
    if (pending) return;
    const at = messages.indexOf(error);
    if (at < 0) return;
    messages.splice(at, 1);
    if (messages.includes(error.user)) ask(error.user);
  }

  function autosize() {
    els.input.style.height = "auto";
    els.input.style.height = Math.min(els.input.scrollHeight + 2, 200) + "px";
  }

  // ---------- Источник ----------

  function markActive(id) {
    document.querySelectorAll(".cite.is-active, .source-ref.is-active")
      .forEach((n) => n.classList.remove("is-active"));
    if (!id) return;
    document.querySelectorAll(".cite, .source-ref").forEach((n) => {
      if (n.dataset.fragmentId === id) n.classList.add("is-active");
    });
  }

  function renderClauses(container, text, fragmentClass) {
    const lines = String(text).split(/\n+/).map((l) => l.trim()).filter(Boolean);
    const clauseRe = /^(\d+(?:\.\d+)*\.?)\s+(.+)$/;
    lines.forEach((line) => {
      const match = clauseRe.exec(line);
      let node;
      if (match) {
        node = el("p", "clause");
        node.appendChild(el("span", "clause-num", match[1]));
        node.appendChild(el("span", "clause-text", match[2]));
        // Заголовок раздела «3. Арендная плата…» без точки внутри номера
        if (/^\d+\.?$/.test(match[1]) && match[2].length < 90 && !/[.;:]$/.test(match[2])) {
          node.classList.add("clause-heading");
        }
      } else {
        node = el("p", "clause-plain", line);
      }
      if (fragmentClass) node.classList.add(fragmentClass);
      container.appendChild(node);
    });
  }

  function renderDocument(source) {
    const t = splitTitle(source.title);
    els.collection.textContent = t.collection;
    els.collection.hidden = !t.collection;
    els.title.textContent = t.name;

    els.meta.replaceChildren();
    const addMeta = (label, value) => {
      if (!value) return;
      els.meta.append(el("dt", null, label), el("dd", null, value));
    };
    addMeta("Положение", source.point);
    addMeta("Редакция", source.revision_id === "base" ? "основная" : source.revision_id);
    const from = formatDate(source.effective_from);
    const to = formatDate(source.effective_to);
    if (from || to) addMeta("Действует", `${from ? "с " + from : ""}${from && to ? " " : ""}${to ? "до " + to : ""}`);

    els.body.replaceChildren();
    const ctx = source.context_text || "";
    const pos = ctx && source.text && ctx !== source.text ? ctx.indexOf(source.text) : -1;
    if (pos >= 0) {
      // Контекст шире фрагмента: показываем его целиком, фрагмент — выделенным.
      els.body.classList.add("is-context");
      renderClauses(els.body, ctx.slice(0, pos));
      renderClauses(els.body, source.text, "is-fragment");
      renderClauses(els.body, ctx.slice(pos + source.text.length));
    } else {
      els.body.classList.remove("is-context");
      renderClauses(els.body, source.text);
    }
    els.docId.textContent = source.fragment_id;
  }

  function showPanel() {
    els.placeholder.hidden = true;
    els.view.hidden = false;
    els.panel.classList.add("is-open");
  }

  async function openSource(id, trigger, { fromHash = false } = {}) {
    lastTrigger = trigger || null;
    currentSource = null;
    showPanel();
    markActive(id);
    els.collection.hidden = true;
    els.title.textContent = "Загрузка источника…";
    els.meta.replaceChildren();
    els.body.replaceChildren();
    els.docId.textContent = id;
    if (!fromHash) {
      history.replaceState(null, "", "#source=" + encodeURIComponent(id));
    }
    try {
      const source = await api("/api/sources/" + encodeURIComponent(id));
      currentSource = source;
      renderDocument(source);
    } catch (err) {
      els.title.textContent = "Источник не открылся";
      const msg = err.status === 404
        ? "Фрагмента с таким ID нет в каталоге. Возможно, база была пересобрана после ответа."
        : err.message;
      els.body.replaceChildren(el("p", "doc-error", msg));
    }
    els.panel.scrollTop = 0;
    els.title.focus({ preventScroll: true });
  }

  function closeSource() {
    els.panel.classList.remove("is-open");
    els.view.hidden = true;
    els.placeholder.hidden = false;
    currentSource = null;
    markActive(null);
    history.replaceState(null, "", location.pathname + location.search);
    if (lastTrigger && document.body.contains(lastTrigger)) lastTrigger.focus();
    else els.input.focus();
  }

  function openFromHash() {
    const match = /^#source=(.+)$/.exec(location.hash);
    if (!match) return;
    let id;
    try { id = decodeURIComponent(match[1]); } catch (_) { return; }
    openSource(id, null, { fromHash: true });
  }

  // ---------- События ----------

  els.form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submit();
    }
  });
  els.input.addEventListener("input", autosize);

  document.querySelectorAll(".example").forEach((btn) => {
    btn.addEventListener("click", () => submit(btn.textContent));
  });

  els.newChat.addEventListener("click", () => {
    if (pending) return;
    messages = [];
    save();
    closeSource();
    els.input.placeholder = "Задайте вопрос по документам базы";
    render();
    els.input.focus();
  });

  els.close.addEventListener("click", closeSource);
  els.back.addEventListener("click", closeSource);
  els.copy.addEventListener("click", () => {
    if (currentSource) copyText(currentSource.text, "Текст фрагмента скопирован");
  });
  els.link.addEventListener("click", () => {
    if (currentSource) copyText(location.href, "Ссылка на источник скопирована");
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && els.panel.classList.contains("is-open") && isNarrow()) closeSource();
  });
  window.addEventListener("hashchange", openFromHash);

  // ---------- Старт ----------

  restore();
  render();
  openFromHash();
  api("/api/health")
    .then((h) => { if (h && h.mode === "mock") els.modeNote.hidden = false; })
    .catch(() => { /* статус покажет первая ошибка запроса */ });
  if (!isNarrow()) els.input.focus();
})();
