const el = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const byId = id => document.getElementById(id);
const content = byId("content");
const state = { token: null, user: null, page: "overview", conversation: null, messages: [], rendering: 0, chatVersion: 0, sending: null };
const staff = () => state.user?.role !== "customer";
const admin = () => state.user?.role === "admin";
const humanize = value => String(value ?? "—").replaceAll("_", " ").toLowerCase();
const button = (label, action, kind = "secondary") => {
  const control = el("button", label, kind);
  control.type = "button";
  control.addEventListener("click", () => perform(control, action));
  return control;
};
const pathId = encodeURIComponent;

function notice(message = "", error = false) {
  const box = byId("notice");
  box.textContent = message;
  box.dataset.error = String(error);
  box.hidden = !message;
}

async function perform(control, action) {
  control.disabled = true;
  notice();
  try { await action(); }
  catch (error) { notice(error.message, true); }
  finally { control.disabled = false; }
}

async function api(path, options = {}) {
  const { method = "GET", data, form = false } = options;
  const headers = {};
  if (state.token) headers.Authorization = "Bearer " + state.token;
  let body;
  if (data) {
    if (form) body = new URLSearchParams(data);
    else {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(data);
    }
  }
  const response = await fetch(path, { method, headers, body, cache: "no-store" });
  if (response.status === 204) return;
  const result = await response.json();
  if (!response.ok) {
    const detail = result.detail;
    const message = Array.isArray(detail)
      ? detail.map(item => item.msg).join(". ")
      : detail?.eligibility?.errors?.join(" ") || detail?.message || detail;
    throw new Error(typeof message === "string" ? message : "The request could not be completed.");
  }
  return result;
}

function panel(title) {
  const box = el("section", undefined, "panel");
  if (title) box.append(el("h2", title));
  return box;
}

function form(fields, label, submit) {
  const node = el("form", undefined, "forms");
  for (const spec of fields) {
    const [name, title, type = "text", optional = false] = spec;
    const labelNode = el("label", title);
    const input = el(type === "textarea" ? "textarea" : "input");
    if (input.tagName === "INPUT") input.type = type;
    input.name = name;
    input.required = !optional;
    if (type === "password") input.autocomplete = "current-password";
    if (type === "email") input.autocomplete = "username";
    if (type === "number") { input.min = "0.01"; input.step = "0.01"; }
    labelNode.append(input);
    node.append(labelNode);
  }
  const send = el("button", label, "primary");
  node.addEventListener("submit", event => {
    event.preventDefault();
    const values = Object.fromEntries([...new FormData(node)].filter(([, value]) => value !== ""));
    perform(send, () => submit(values, node));
  });
  node.append(send);
  return node;
}

function table(columns, rows, empty) {
  if (!rows.length) return el("p", empty, "muted");
  const wrapper = el("div", undefined, "table-wrap");
  const node = el("table");
  const head = el("thead");
  const header = el("tr");
  columns.forEach(column => header.append(el("th", column)));
  head.append(header);
  const body = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    for (const item of row) {
      const td = el("td");
      td.append(item instanceof Node ? item : String(item ?? "—"));
      tr.append(td);
    }
    body.append(tr);
  }
  node.append(head, body);
  wrapper.append(node);
  return wrapper;
}

function metrics(items) {
  const grid = el("div", undefined, "grid");
  for (const [label, value] of items) {
    const tile = el("div", undefined, "tile");
    tile.append(el("span", label, "muted"), el("strong", String(value ?? 0)));
    grid.append(tile);
  }
  return grid;
}

function details(container, entries) {
  const dl = el("dl");
  for (const [label, value] of entries) dl.append(el("dt", label, "muted"), el("dd", String(value ?? "—")));
  container.replaceChildren(dl);
}

function renderChrome() {
  const nav = byId("navigation");
  const session = byId("session");
  nav.replaceChildren();
  session.replaceChildren();
  if (!state.user) return;
  const tabs = staff()
    ? [["overview", "Overview"], ["returns", "Return queue"], ["refunds", "Refund queue"], ...(admin() ? [["link", "Link customer"], ["audit", "Audit history"]] : [])]
    : [["overview", "Overview"], ["orders", "Orders"], ["returns", "Returns"], ["chat", "Chat"], ["preferences", "Preferences"]];
  for (const [id, label] of tabs) {
    const tab = button(label, () => navigate(id));
    if (state.page === id) tab.setAttribute("aria-current", "page");
    nav.append(tab);
  }
  session.append(el("span", state.user.email), button("Sign out", async () => {
    Object.assign(state, { token: null, user: null, conversation: null, messages: [], page: "overview" });
    state.chatVersion += 1;
    state.sending = null;
    await navigate("overview");
  }));
}

function title(name, description) {
  byId("heading").replaceChildren(el("h1", name), el("p", description, "muted"));
}

async function navigate(page) {
  const renderId = ++state.rendering;
  state.page = page;
  renderChrome();
  notice();
  const view = el("div");
  content.replaceChildren(view);
  try {
    if (!state.user) signIn(view);
    else await views[page](view);
  } catch (error) {
    if (renderId === state.rendering) notice(error.message, true);
  }
}

function signIn(view) {
  title("Support workspace", "Sign in to manage orders, returns, and support conversations.");
  const section = panel("Sign in");
  section.classList.add("narrow");
  const login = async data => {
    const result = await api("/auth/login", { method: "POST", data: { username: data.email, password: data.password }, form: true });
    state.token = result.access_token;
    try {
      state.user = await api("/auth/me");
    } catch (error) {
      state.token = null;
      throw error;
    }
    await navigate("overview");
  };
  section.append(form([["email", "Email", "email"], ["password", "Password", "password"]], "Sign in", login));
  const register = panel("New customer");
  register.classList.add("narrow");
  register.append(form([["full_name", "Name", "text", true], ["email", "Email", "email"], ["password", "Password", "password"]], "Create account", async data => {
    await api("/auth/register", { method: "POST", data });
    await login(data);
  }));
  view.append(section, register);
}

async function overview(view) {
  if (staff()) {
    title("Support overview", "Track the work moving through your support desk.");
    const data = await api("/staff/analytics");
    view.append(metrics([
      ["Open return reviews", data.returns.pending_review],
      ["Returns", data.returns.total_requests],
      ["Refunds", data.refunds.total_refunds],
      ["Conversations", data.chat.conversations],
    ]));
    const summary = panel("Return activity");
    summary.append(table(["Status", "Requests"], Object.entries(data.returns.status_wise_count).map(([key, value]) => [humanize(key), value]), "No return activity."));
    view.append(summary);
    return;
  }
  title("Your support desk", "Find your orders, request a return, or ask for help.");
  const profile = panel("Your account");
  profile.append(el("p", state.user.customer_unique_id ? "Your order profile is linked." : "Ask support to verify and link your order profile.", "muted"));
  const data = el("div", undefined, "details");
  details(data, [["Account ID", state.user.user_id], ["Email", state.user.email]]);
  profile.append(data);
  view.append(profile);
}

async function orders(view) {
  title("Your orders", "See delivery status, payment totals, and purchased items.");
  const result = await api("/customers/me/orders");
  const box = panel("Order history");
  const summary = el("div", undefined, "details");
  summary.setAttribute("aria-live", "polite");
  box.append(table(["Order", "Status", "Delivered", "Details"], result.orders.orders.map(order => [
    order.order_id, el("span", humanize(order.order_status), "pill"), order.order_delivered_customer_date,
    button("View", async () => {
      const { order_details: orderData } = await api("/orders/" + pathId(order.order_id));
      details(summary, [["Order", order.order_id], ["Paid", `${orderData.currency} ${orderData.summary.total_paid}`], ["Items", orderData.summary.total_items]]);
    }),
  ]), "There are no orders on this profile."), summary);
  view.append(box);
}

async function returns(view) {
  title(staff() ? "Return queue" : "Your returns", staff() ? "Review eligible requests and open the refund workflow." : "Submit a return and check its progress.");
  if (!staff() && state.user.customer_unique_id) {
    const newReturn = panel("Request a return");
    newReturn.append(form([["order_id", "Order ID"], ["reason", "Reason"], ["evidence_reference", "Evidence reference", "text", true]], "Submit return", async data => {
      const result = await api("/returns", { method: "POST", data });
      await navigate("returns");
      notice(result.message);
    }));
    view.append(newReturn);
  }
  const data = await api(staff() ? "/returns" : "/customers/me/returns");
  const box = panel(staff() ? "Requests" : "Return history");
  const rows = data.return_requests || data.returns;
  box.append(table(["Order", "Status", "Reason", "Actions"], rows.map(row => {
    const actions = el("div", undefined, "actions");
    const request = "/returns/" + pathId(row.request_id);
    const update = (label, endpoint, payload) => button(label, async () => {
      await api(request + endpoint, { method: "POST", data: payload });
      await navigate("returns");
      notice(label + " completed.");
    });
    if (row.status === "PENDING_REVIEW") {
      if (staff()) {
        actions.append(update("Approve", "/review", { decision: "APPROVED" }), update("Reject", "/review", { decision: "REJECTED" }));
      } else actions.append(update("Cancel", "/cancel"));
    }
    if (staff() && row.status === "APPROVED") actions.append(update("Open refund", "/refund"));
    if (row.refund) actions.append(el("span", "Refund " + humanize(row.refund.status), "pill"));
    return [row.order_id, el("span", humanize(row.status), "pill"), row.reason, actions];
  }), "There are no return requests."));
  view.append(box);
}

async function refunds(view) {
  title("Refund queue", "Record receipt and inspection before administrative review.");
  const { refunds: rows, demo_refunds_enabled: demoEnabled } = await api("/refunds");
  const box = panel("Refund records");
  const detail = el("div", undefined, "details");
  box.append(table(["Return request", "Status", "Amount", "Actions"], rows.map(row => [
    row.return_request_id, el("span", humanize(row.status), "pill"),
    row.approved_amount == null ? "—" : `${row.currency} ${row.approved_amount}`,
    button("Open", () => showRefund(detail, row.refund_id, demoEnabled)),
  ]), "There are no refund records."), detail);
  view.append(box);
}

async function showRefund(node, id, demoEnabled) {
  const base = "/refunds/" + pathId(id);
  const { refund } = await api(base);
  const send = async (endpoint, data) => {
    await api(base + endpoint, { method: "POST", data });
    await navigate("refunds");
    notice("Refund record updated.");
  };
  node.replaceChildren(el("h2", "Refund details"), el("p", "Status " + humanize(refund.status), "muted"));
  if (refund.status === "UNDER_REVIEW" && !refund.product_received) {
    node.append(button("Record receipt", () => send("/receive")));
  } else if (refund.status === "UNDER_REVIEW" && !refund.inspected) {
    const inspection = form([["inspection_notes", "Inspection notes"]], "Record passed inspection",
      data => send("/inspect", { ...data, inspection_passed: true }));
    const failed = form([["inspection_notes", "Failed inspection notes"]], "Record failed inspection",
      data => send("/inspect", { ...data, inspection_passed: false }));
    node.append(inspection, failed);
  } else if (refund.status === "UNDER_REVIEW" && admin()) {
    if (refund.inspection_passed) {
      node.append(form([["approved_amount", "Refund amount", "number"]], "Approve refund",
        data => send("/review", { decision: "APPROVED", approved_amount: Number(data.approved_amount) })));
    } else {
      node.append(button("Reject refund", () => send("/review", { decision: "REJECTED" })));
    }
  } else if (refund.status === "APPROVED" && admin() && demoEnabled) {
    node.append(form([["transaction_id", "Demo transaction reference"]], "Record demo payment",
      data => send("/process", { ...data, payment_gateway_confirmed: true })));
  }
  if (refund.processing_mode) node.append(el("p", "Processing mode " + refund.processing_mode, "muted"));
}

async function link(view) {
  title("Link customer", "Verify profile ownership before linking it to a customer account.");
  const box = panel("Link an order profile");
  box.classList.add("narrow");
  box.append(form([["user_id", "Customer account ID"], ["customer_unique_id", "Order profile ID"]], "Link profile", async (data, node) => {
    await api("/admin/customers/" + pathId(data.user_id) + "/order-profile", {
      method: "PUT", data: { customer_unique_id: data.customer_unique_id },
    });
    node.reset();
    notice("Order profile linked.");
  }));
  view.append(box);
}

async function audit(view) {
  title("Audit history", "Review the latest return and refund events.");
  const result = await api("/audit-logs?limit=50");
  const box = panel("Recent events");
  box.append(table(["Action", "Actor", "Time"], result.logs.map(log => [humanize(log.action), log.performed_by, log.created_at]), "There are no audit events."));
  view.append(box);
}

async function preferences(view) {
  title("Reply preferences", "Your saved style applies to future support chats.");
  const result = await api("/customers/me/preferences");
  const box = panel("Reply style");
  box.append(el("p", result.reply_style ? humanize(result.reply_style) : "Default"));
  const chatWith = message => async () => {
    await sendChat(message);
    await navigate("preferences");
  };
  const actions = el("div", undefined, "actions");
  actions.append(
    button("Prefer concise replies", chatWith("Remember that I prefer concise replies")),
    button("Prefer detailed replies", chatWith("Remember that I prefer detailed replies")),
    button("Clear preference", async () => {
      await api("/customers/me/preferences", { method: "DELETE" });
      await navigate("preferences");
    }),
  );
  box.append(actions);
  view.append(box);
}

async function sendChat(message) {
  if (state.sending) throw new Error("Wait for the current reply before sending another message.");
  const submission = Symbol();
  state.sending = submission;
  const version = state.chatVersion;
  const payload = { message, ...(state.conversation ? { conversation_id: state.conversation } : {}) };
  try {
    const result = await api("/chat", { method: "POST", data: payload });
    if (version !== state.chatVersion) return;
    state.conversation = result.conversation_id;
    state.messages.push({ text: message, user: true }, { text: result.assistant_response, sources: result.policy_sources });
  } finally {
    if (state.sending === submission) state.sending = null;
  }
}

async function chat(view) {
  title("Support chat", "Ask about orders, delivery, and return policies.");
  const box = panel();
  const log = el("div", undefined, "chat-log");
  log.setAttribute("role", "log");
  function draw() {
    log.replaceChildren();
    if (!state.messages.length) log.append(el("p", "Start by asking how to return an order.", "muted"));
    for (const message of state.messages) {
      const bubble = el("div", message.text, message.user ? "bubble customer" : "bubble");
      if (message.sources?.length) bubble.append(el("small", "Sources · " + message.sources.join(", ")));
      log.append(bubble);
    }
    log.scrollTop = log.scrollHeight;
  }
  draw();
  const composer = form([["message", "Message", "textarea"]], "Send message", async (data, node) => {
    await sendChat(data.message);
    node.reset();
    draw();
  });
  const controls = el("div", undefined, "actions");
  controls.append(
    button("New chat", async () => {
      state.chatVersion += 1;
      state.messages = [];
      state.conversation = null;
      draw();
    }),
    button("Dictate", () => dictate(composer.elements.message)),
    button("Read reply", () => readReply()),
  );
  box.append(log, controls, composer);
  view.append(box);
  const { conversations } = await api("/customers/me/conversations");
  if (conversations.length) {
    const history = panel("Recent conversations");
    history.append(table(["Started", "Conversation"], conversations.map(item => [
      item.created_at, button("Open conversation", async () => {
        const version = ++state.chatVersion;
        const result = await api("/conversations/" + pathId(item.conversation_id));
        if (version !== state.chatVersion) return;
        state.conversation = item.conversation_id;
        state.messages = result.messages.map(message => ({ text: message.content, user: message.role === "user" }));
        draw();
      }),
    ]), ""));
    view.append(history);
  }
}

async function dictate(input) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) throw new Error("This browser does not support dictation.");
  const speech = new Recognition();
  if (!("processLocally" in speech)) throw new Error("On-device dictation is unavailable in this browser.");
  speech.processLocally = true;
  speech.lang = navigator.language;
  speech.onresult = event => { input.value = event.results[0][0].transcript; input.focus(); notice("Dictation ready. Review the text before sending."); };
  speech.onerror = event => notice("Dictation could not start: " + event.error, true);
  speech.start();
}

function readReply() {
  const last = state.messages.findLast(message => !message.user);
  if (!last) throw new Error("There is no reply to read.");
  const voice = window.speechSynthesis?.getVoices().find(item => item.localService && item.lang.startsWith("en"));
  if (!voice) throw new Error("An on-device English voice is unavailable in this browser.");
  const utterance = new SpeechSynthesisUtterance(last.text);
  utterance.voice = voice;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

const views = { overview, orders, returns, refunds, link, audit, preferences, chat };
navigate("overview");
