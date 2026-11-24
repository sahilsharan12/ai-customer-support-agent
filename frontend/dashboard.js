const el = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const byId = id => document.getElementById(id);
const content = byId("content");
const state = { token: null, user: null, page: "sign-in", conversation: null, messages: [], rendering: 0, chatVersion: 0, sending: null };
const staff = () => ["support_agent", "admin"].includes(state.user?.role);
const admin = () => state.user?.role === "admin";
const humanize = value => String(value ?? "—").replaceAll("_", " ").toLowerCase();
const displayDate = value => {
  if (!value) return "—";
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? value + "T00:00:00" : value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleDateString(undefined, { dateStyle: "medium" });
};
const roleNames = { customer: "Customer", support_agent: "Support agent", admin: "Administrator" };
const navIcons = { overview: "▦", orders: "▤", returns: "↶", refunds: "↔", cases: "◇", chat: "◉", preferences: "⚙", link: "⊕", audit: "≡", system: "◫" };
const button = (label, action, kind = "secondary") => {
  const control = el("button", label, kind);
  control.type = "button";
  control.addEventListener("click", () => perform(control, action));
  return control;
};
const pathId = encodeURIComponent;
const money = (amount, currency = "BRL") => amount == null ? "—" : currency + " " + Number(amount).toFixed(2);
const caseNames = { REFUND_REVIEW: "Refund review", ORDER_CANCELLATION: "Order cancellation", ACCOUNT_CHANGE: "Account change", LOW_CONFIDENCE: "Support review" };
const returnStates = ["PENDING_REVIEW", "APPROVED", "REJECTED", "PROCESSING", "COMPLETED", "CANCELLED"];

function statusPill(status, label = humanize(status)) {
  const pill = el("span", label, "pill");
  if (["DELIVERED", "APPROVED", "COMPLETED", "PROCESSED", "SUCCESS", "READY"].includes(status?.toUpperCase())) pill.dataset.tone = "success";
  if (["PENDING", "PENDING_REVIEW", "UNDER_REVIEW", "PROCESSING"].includes(status)) pill.dataset.tone = "pending";
  if (["REJECTED", "CANCELLED", "FAILED", "DEGRADED"].includes(status)) pill.dataset.tone = "error";
  return pill;
}

function statusFilter(values, selected, change, includeAll = true) {
  const label = el("label", "Status");
  const select = el("select");
  select.setAttribute("aria-label", "Status");
  for (const value of includeAll ? ["", ...values] : values) {
    const option = el("option", value ? humanize(value) : "All statuses");
    option.value = value;
    select.append(option);
  }
  select.value = selected || "";
  select.addEventListener("change", () => perform(select, () => change(select.value)));
  label.append(select);
  const wrapper = el("div", undefined, "filters");
  wrapper.append(label);
  return wrapper;
}

function pager({ offset, count, limit, total }, load) {
  const wrapper = el("div", undefined, "actions pager");
  const previous = button("Previous", () => load(Math.max(0, offset - limit)));
  const next = button("Next", () => load(offset + limit));
  previous.disabled = offset === 0;
  next.disabled = total != null ? offset + count >= total : count < limit;
  if (!count && offset === 0) return wrapper;
  const range = count ? (offset + 1) + "–" + (offset + count) : "No more records";
  wrapper.append(el("span", total != null && count ? range + " of " + total : range), previous, next);
  return wrapper;
}

function quickLinks(titleText, links) {
  const box = panel(titleText);
  const choices = el("div", undefined, "quick-links");
  for (const [label, target, params] of links) {
    const link = button(label, () => navigate(target, params));
    const arrow = el("span", "→");
    arrow.setAttribute("aria-hidden", "true");
    link.append(arrow);
    choices.append(link);
  }
  box.append(choices);
  return box;
}

function notice(message = "", error = false) {
  const box = byId(state.user ? "notice" : "auth-notice");
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
  const { method = "GET", data, form = false, accept = [] } = options;
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
  const result = await response.json().catch(() => ({}));
  if (!response.ok && !accept.includes(response.status)) {
    if (response.status === 401 && headers.Authorization && headers.Authorization === "Bearer " + state.token && state.user) {
      resetSession();
      await navigate("sign-in");
      notice("Your session expired. Sign in to continue.", true);
      throw new Error("Your session expired. Sign in to continue.");
    }
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
    const [name, title, type = "text", optional = false, attrs = {}] = spec;
    const labelNode = el("label", title);
    const input = el(type === "textarea" ? "textarea" : "input");
    if (input.tagName === "INPUT") input.type = type;
    input.name = name;
    input.required = !optional;
    if (type === "password") input.autocomplete = "current-password";
    if (type === "email") input.autocomplete = "username";
    if (type === "number") { input.min = "0.01"; input.step = "0.01"; }
    Object.assign(input, attrs);
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
  if (!rows.length) return el("p", empty, "empty");
  const wrapper = el("div", undefined, "table-wrap");
  const node = el("table");
  const head = el("thead");
  const header = el("tr");
  for (const column of columns) {
    const heading = el("th", column);
    heading.scope = "col";
    if (!column) heading.setAttribute("aria-label", "Actions");
    header.append(heading);
  }
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
  byId("workspace").hidden = !state.user;
  byId("auth-screen").hidden = !!state.user;
  if (!state.user) return;
  byId("workspace-label").textContent = staff() ? "Staff workspace" : "Customer workspace";
  const tabs = staff()
    ? [["overview", "Overview"], ["cases", "Review queue"], ["returns", "Return queue"], ["refunds", "Refund queue"], ...(admin() ? [["link", "Link customer"], ["audit", "Audit history"], ["system", "System activity"]] : [])]
    : [["overview", "Overview"], ["orders", "Orders"], ["returns", "Returns"], ["cases", "My cases"], ["chat", "Chat"], ["preferences", "Preferences"]];
  for (const [id, label] of tabs) {
    const tab = button(label, () => navigate(id));
    const icon = el("span", navIcons[id], "nav-icon");
    icon.setAttribute("aria-hidden", "true");
    tab.prepend(icon);
    if (state.page === id) tab.setAttribute("aria-current", "page");
    nav.append(tab);
  }
  const account = el("div", undefined, "account");
  const initials = el("span", state.user.email.slice(0, 1).toUpperCase(), "avatar");
  initials.setAttribute("aria-hidden", "true");
  const info = el("span", undefined, "account-label");
  info.append(el("span", state.user.email), el("small", roleNames[state.user.role]));
  account.append(initials, info);
  session.append(account, button("Sign out", () => {
    resetSession();
    return navigate("sign-in");
  }));
}

function resetSession() {
  Object.assign(state, { token: null, user: null, conversation: null, messages: [], sending: null });
  state.chatVersion += 1;
}

function title(name, description) {
  document.title = name + " · Support Desk";
  byId("heading").replaceChildren(el("h1", name), el("p", description, "muted"));
}

async function navigate(page, params = {}) {
  const renderId = ++state.rendering;
  state.page = page;
  renderChrome();
  notice();
  if (!state.user) {
    renderAuth(page === "register");
    return;
  }
  const view = el("div");
  content.replaceChildren(view);
  const loading = el("p", "Loading…", "panel loading");
  view.append(loading);
  try {
    await views[page](view, params);
  } catch (error) {
    if (renderId === state.rendering) {
      notice(error.message, true);
      if (view.childElementCount === 1) {
        const retry = panel("Couldn't load this page");
        retry.append(button("Try again", () => navigate(page, params)));
        view.append(retry);
      }
    }
  } finally {
    loading.remove();
  }
}

async function signIn(data) {
  const result = await api("/auth/login", { method: "POST", data: { username: data.email, password: data.password }, form: true });
  state.token = result.access_token;
  try {
    state.user = await api("/auth/me");
  } catch (error) {
    state.token = null;
    throw error;
  }
  await navigate("overview");
}

function renderAuth(register) {
  document.title = (register ? "Create an account" : "Sign in") + " · Support Desk";
  const section = el("section", undefined, "auth-form");
  section.append(
    el("h2", register ? "Create a customer account" : "Sign in"),
    el("p", register ? "Use your email to get started with order support." : "Use your account email to open your workspace.", "muted"),
  );
  const fields = [
    ["email", "Email", "email", false, { maxLength: 254, placeholder: "you@example.com" }],
    ["password", "Password", "password", false, { autocomplete: register ? "new-password" : "current-password" }],
  ];
  const switcher = el("p", undefined, "auth-switch");
  if (register) {
    const registration = form([
      ["full_name", "Name", "text", true, { autocomplete: "name", maxLength: 120 }],
      ...fields,
    ], "Create account", async data => {
      await api("/auth/register", { method: "POST", data });
      await signIn(data);
    });
    registration.elements.password.minLength = 8;
    section.append(registration);
    switcher.append("Already have an account?", button("Back to sign in", () => navigate("sign-in"), "text-button"));
  } else {
    section.append(form(fields, "Sign in", signIn));
    switcher.append("New customer?", button("Create customer account", () => navigate("register"), "text-button"));
  }
  section.append(switcher);
  byId("auth-panel").replaceChildren(section);
}

async function overview(view) {
  if (staff()) {
    title("Support overview", "Track the work moving through your support desk.");
    const [data, { cases: queue }] = await Promise.all([api("/staff/analytics"), api("/staff/support-cases?limit=5")]);
    view.append(metrics([
      ["Open return reviews", data.returns.pending_review],
      ["Returns", data.returns.total_requests],
      ["Refunds", data.refunds.total_refunds],
      ["Conversations", data.chat.conversations],
    ]));
    const split = el("div", undefined, "columns");
    const summary = panel("Recent review cases");
    summary.append(table(["Case", "Order", "Status"], queue.map(item => [
      button(caseNames[item.kind] || humanize(item.kind), () => navigate("cases"), "text-button"),
      item.order_id, statusPill(item.status),
    ]), "The review queue is clear."));
    split.append(summary, quickLinks("Go to a queue", [
      ["Review support cases", "cases"], ["Review returns", "returns", { status: "PENDING_REVIEW" }],
      ["Manage refunds", "refunds"], ...(admin() ? [["View audit history", "audit"]] : []),
    ]));
    view.append(split);
    return;
  }
  title("Your support desk", "Find your orders, request a return, or ask for help.");
  if (state.user.customer_unique_id) {
    const [orderData, returnData, caseData] = await Promise.all([
      api("/customers/me/orders?limit=1"), api("/customers/me/returns?limit=1"), api("/customers/me/support-cases"),
    ]);
    view.append(metrics([
      ["Orders", orderData.orders.total_orders],
      ["Return requests", returnData.total_returns],
      ["Recent open cases", caseData.cases.filter(item => item.status === "PENDING").length],
    ]));
  }
  const profile = panel("Your account");
  profile.append(el("p", state.user.customer_unique_id ? "Your order profile is linked." : "Ask support to verify and link your order profile.", "muted"));
  const data = el("div", undefined, "details");
  details(data, [["Account ID", state.user.user_id], ["Email", state.user.email]]);
  profile.append(data);
  const split = el("div", undefined, "columns");
  split.append(quickLinks("How can we help?", [
    ["Ask support", "chat"], ["Track an order", "orders"], ["View returns", "returns"], ["Check a support case", "cases"],
  ]), profile);
  view.append(split);
}

async function orders(view, { offset = 0 }) {
  title("Your orders", "See delivery status, payment totals, and purchased items.");
  if (!state.user.customer_unique_id) {
    const box = panel("Link your order profile");
    box.append(el("p", "Ask support to verify your account and link it to your order profile.", "muted"));
    box.append(button("View account ID", () => navigate("overview")));
    view.append(box);
    return;
  }
  const limit = 15;
  const result = await api("/customers/me/orders?limit=" + limit + "&offset=" + offset);
  const box = panel("Order history");
  const summary = el("div", undefined, "details");
  summary.setAttribute("aria-live", "polite");
  const rows = result.orders.orders;
  box.append(table(["Order ID", "Status", "Delivered", ""], rows.map(order => [
    order.order_id, statusPill(order.order_status), displayDate(order.order_delivered_customer_date),
    button("View", async () => {
      const { order_details: orderData } = await api("/orders/" + pathId(order.order_id));
      details(summary, [
        ["Order ID", order.order_id], ["Paid", money(orderData.summary.total_paid, orderData.currency)],
        ["Delivered", displayDate(orderData.order.order_delivered_customer_date)],
        ["Estimated delivery", displayDate(orderData.order.order_estimated_delivery_date)],
      ]);
      summary.prepend(el("h3", "Order details"));
      summary.append(table(["Item", "Price"], orderData.products.map(item => [
        item.product_category_name_english || item.product_category_name || item.product_id,
        money(item.price, orderData.currency),
      ]), "No item details are available."));
      summary.append(button("Request return", () => navigate("returns", { orderId: order.order_id })));
    }),
  ]), "There are no orders on this profile."), pager({
    offset, count: rows.length, limit, total: result.orders.total_orders,
  }, next => navigate("orders", { offset: next })), summary);
  view.append(box);
}

async function returns(view, { status = "", offset = 0, orderId = "" }) {
  const isStaff = staff();
  title(isStaff ? "Return queue" : "Your returns", isStaff ? "Review requests and open the refund workflow." : "Submit a return and check its progress.");
  if (!isStaff && !state.user.customer_unique_id) {
    const box = panel("Link your order profile");
    box.append(el("p", "Ask support to link your verified order profile before submitting a return.", "muted"));
    box.append(button("View account ID", () => navigate("overview")));
    view.append(box);
    return;
  }
  if (!isStaff) {
    const newReturn = panel("Request a return");
    newReturn.append(form([
      ["order_id", "Order ID", "text", false, { value: orderId, maxLength: 100 }],
      ["reason", "Reason", "text", false, { minLength: 3, maxLength: 500 }],
      ["evidence_reference", "Evidence reference (optional)", "text", true, { maxLength: 500 }],
    ], "Submit return", async data => {
      const result = await api("/returns", { method: "POST", data });
      await navigate("returns");
      notice(result.message);
    }));
    view.append(newReturn);
  }

  const limit = 15;
  const data = await api(isStaff
    ? "/returns" + (status ? "?status=" + pathId(status) : "")
    : "/customers/me/returns?limit=" + limit + "&offset=" + offset);
  const box = panel(isStaff ? "Requests" : "Return history");
  if (isStaff) box.append(statusFilter(returnStates, status, next => navigate("returns", { status: next })));
  const detail = el("div", undefined, "details");
  detail.setAttribute("aria-live", "polite");
  const rows = data.return_requests;
  box.append(table(["Order ID", "Status", "Reason", ""], rows.map(row => [
    row.order_id, statusPill(row.status), row.reason,
    button("Open return", () => showReturn(detail, row.request_id, { status, offset })),
  ]), "There are no return requests for this view."));
  if (!isStaff) box.append(pager({ offset, count: rows.length, limit, total: data.total_returns }, next => navigate("returns", { offset: next })));
  box.append(detail);
  view.append(box);
}

async function showReturn(node, id, params) {
  const base = "/returns/" + pathId(id);
  const { return_request: item, refund_record: refund } = await api(base);
  const actions = el("div", undefined, "actions");
  const update = (label, endpoint, payload, success, target = "returns") => button(label, async () => {
    await api(base + endpoint, { method: "POST", data: payload });
    await navigate(target, target === "returns" ? params : {});
    notice(success);
  }, endpoint === "/cancel" || payload?.decision === "REJECTED" ? "danger" : "secondary");
  details(node, [
    ["Request ID", item.request_id], ["Order ID", item.order_id], ["Status", humanize(item.status)],
    ["Reason", item.reason], ["Submitted", displayDate(item.created_at)], ["Evidence", item.evidence_reference],
    ["Refund", refund ? humanize(refund.status) : "No refund record"],
  ]);
  node.prepend(el("h3", "Return details"));
  if (item.status === "PENDING_REVIEW") {
    if (staff()) {
      actions.append(
        update("Approve return", "/review", { decision: "APPROVED" }, "Return approved."),
        update("Reject return", "/review", { decision: "REJECTED" }, "Return rejected."),
      );
    } else {
      actions.append(update("Cancel request", "/cancel", undefined, "Return request cancelled."));
    }
  }
  if (staff() && refund) {
    actions.append(button("View refund", () => navigate("refunds", { refundId: refund.refund_id })));
  } else if (staff() && item.status === "APPROVED") {
    actions.append(update("Create refund record", "/refund", undefined, "Refund record created.", "refunds"));
  }
  node.append(actions);
}

async function refunds(view, { status = "", refundId } = {}) {
  title("Refund queue", "Record receipt and inspection, then review eligible refunds.");
  const { refunds: rows, demo_refunds_enabled: demoEnabled } = await api("/refunds" + (status ? "?status=" + pathId(status) : ""));
  const box = panel("Refund records");
  const detail = el("div", undefined, "details");
  detail.setAttribute("aria-live", "polite");
  box.append(statusFilter(["UNDER_REVIEW", "APPROVED", "REJECTED", "PROCESSING", "COMPLETED"], status, next => navigate("refunds", { status: next })));
  box.append(table(["Return request", "Status", "Amount", ""], rows.map(row => [
    row.return_request_id, statusPill(row.status), money(row.approved_amount, row.currency),
    button("Open refund", () => showRefund(detail, row.refund_id, demoEnabled, status)),
  ]), "There are no refund records for this status."), detail);
  view.append(box);
  if (refundId) await showRefund(detail, refundId, demoEnabled, status);
}

async function showRefund(node, id, demoEnabled, status) {
  const base = "/refunds/" + pathId(id);
  const [{ refund }, { attempts }] = await Promise.all([api(base), api(base + "/attempts?limit=10")]);
  const send = async (endpoint, data, success) => {
    await api(base + endpoint, { method: "POST", data });
    await navigate("refunds", { status, refundId: id });
    notice(success);
  };
  details(node, [
    ["Refund ID", refund.refund_id], ["Status", humanize(refund.status)],
    ["Amount", money(refund.approved_amount, refund.currency)],
    ["Receipt", refund.product_received ? "Recorded" : "Pending"],
    ["Inspection", refund.inspected ? (refund.inspection_passed ? "Passed" : "Failed") : "Pending"],
    ...(refund.processing_mode ? [["Processing mode", humanize(refund.processing_mode)]] : []),
  ]);
  node.prepend(el("h3", "Refund details"));
  if (refund.status === "UNDER_REVIEW" && !refund.product_received) {
    node.append(button("Record receipt", () => send("/receive", undefined, "Receipt recorded."), "primary"));
  } else if (refund.status === "UNDER_REVIEW" && !refund.inspected) {
    const inspection = form([["inspection_notes", "Inspection notes", "textarea", false, { minLength: 3 }]], "Save inspection", data =>
      send("/inspect", { inspection_notes: data.inspection_notes, inspection_passed: data.inspection_result === "passed" }, "Inspection recorded."));
    const label = el("label", "Inspection result");
    const choice = el("select");
    choice.name = "inspection_result";
    choice.setAttribute("aria-label", "Inspection result");
    for (const value of ["passed", "failed"]) {
      const option = el("option", value === "passed" ? "Passed" : "Failed");
      option.value = value;
      choice.append(option);
    }
    label.append(choice);
    inspection.prepend(label);
    node.append(inspection);
  } else if (refund.status === "UNDER_REVIEW" && admin()) {
    if (refund.inspection_passed) {
      node.append(form([["approved_amount", "Refund amount (BRL)", "number"]], "Approve refund", data =>
        send("/review", { decision: "APPROVED", approved_amount: Number(data.approved_amount) }, "Refund approved.")));
    } else {
      node.append(button("Reject refund", () => send("/review", { decision: "REJECTED" }, "Refund rejected."), "danger"));
    }
  } else if (refund.status === "UNDER_REVIEW") {
    node.append(el("p", "Awaiting administrator review.", "muted"));
  } else if (refund.status === "APPROVED" && admin()) {
    if (demoEnabled) {
      node.append(form([["transaction_id", "Demo transaction reference"]], "Record demo payment", data =>
        send("/process", { ...data, payment_gateway_confirmed: true }, "Demo payment recorded.")));
    } else {
      node.append(el("p", "Demo payment processing is disabled for this server.", "muted"));
    }
  }
  if (attempts.length) {
    const history = el("div", undefined, "details");
    history.append(el("h3", "Processing attempts"), table(["Status", "Date", "Reason"], attempts.map(item => [
      statusPill(item.attempt_status), displayDate(item.attempted_at), item.failure_reason,
    ])));
    node.append(history);
  }
}

async function cases(view, { status = "PENDING", offset = 0, caseId } = {}) {
  const isStaff = staff();
  title(isStaff ? "Review queue" : "My support cases",
    isStaff ? "Review requests handed off by the assistant." : "See which of your requests are with the support team.");
  const limit = isStaff ? 20 : 100;
  const { cases: rows } = await api(isStaff
    ? "/staff/support-cases?status=" + pathId(status) + "&limit=" + limit + "&offset=" + offset
    : "/customers/me/support-cases?limit=" + limit);
  const box = panel(isStaff ? "Cases" : "Recent cases");
  const detail = el("div", undefined, "details");
  detail.setAttribute("aria-live", "polite");
  if (isStaff) box.append(statusFilter(["PENDING", "APPROVED", "REJECTED"], status, next => navigate("cases", { status: next }), false));
  box.append(table(["Case", "Order ID", "Opened", "Status", ""], rows.map(item => [
    caseNames[item.kind] || humanize(item.kind), item.order_id, displayDate(item.created_at),
    statusPill(item.status), button("Open case", () => showCase(detail, item, { status, offset })),
  ]), "There are no cases for this view."));
  if (isStaff) box.append(pager({ offset, count: rows.length, limit }, next => navigate("cases", { status, offset: next })));
  box.append(detail);
  view.append(box);
  const selected = caseId && rows.find(item => item.case_id === caseId);
  if (selected) showCase(detail, selected, { status, offset });
}

function showCase(node, item, params) {
  details(node, [
    ["Case ID", item.case_id], ["Type", caseNames[item.kind] || humanize(item.kind)], ["Order ID", item.order_id],
    ["Status", humanize(item.status)], ["Opened", displayDate(item.created_at)],
    ...(item.decided_at ? [["Decision date", displayDate(item.decided_at)]] : []),
  ]);
  node.prepend(el("h3", "Case details"));
  if (staff()) {
    const transcript = el("div", undefined, "details");
    const actions = el("div", undefined, "actions");
    actions.append(button("Read conversation", async () => {
      const { messages } = await api("/conversation/" + pathId(item.conversation_id) + "?limit=100");
      transcript.replaceChildren(el("h3", "Conversation"), ...messages.map(message =>
        el("p", (message.role === "user" ? "Customer: " : "Assistant: ") + message.content, "case-message")));
    }));
    if (item.status === "PENDING" && (admin() || item.kind === "LOW_CONFIDENCE")) {
      for (const decision of ["APPROVED", "REJECTED"]) {
        actions.append(button(decision === "APPROVED" ? "Approve case" : "Reject case", async () => {
          await api("/staff/support-cases/" + pathId(item.case_id) + "/decision", { method: "POST", data: { decision } });
          await navigate("cases", { status: params.status, offset: 0 });
          notice("Case decision recorded.");
        }, decision === "APPROVED" ? "primary" : "danger"));
      }
    } else if (item.status === "PENDING") {
      node.append(el("p", "An administrator must decide this case.", "muted"));
    }
    node.append(actions, transcript);
  } else {
    node.append(button("Open related chat", () => navigate("chat", { conversationId: item.conversation_id })));
  }
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

async function audit(view, { offset = 0, action = "", requestId = "" } = {}) {
  title("Audit history", "Review the latest return and refund events.");
  const limit = 20;
  const query = new URLSearchParams({ offset, limit });
  if (action) query.set("action", action);
  if (requestId) query.set("request_id", requestId);
  const result = await api("/audit-logs?" + query);
  const box = panel("Recent events");
  const filters = form([
    ["action", "Action", "text", true, { value: action, placeholder: "e.g. RETURN_CREATED" }],
    ["request_id", "Return request ID", "text", true, { value: requestId }],
  ], "Apply filters", data => navigate("audit", { action: data.action?.trim().toUpperCase(), requestId: data.request_id?.trim() }));
  filters.classList.add("actions", "forms-inline");
  filters.append(button("Clear", () => navigate("audit"), "text-button"));
  box.append(filters, table(["Action", "Actor", "Return request", "Date"], result.logs.map(log => [
    humanize(log.action), log.performed_by, log.request_id, displayDate(log.created_at),
  ]), "There are no audit events for these filters."), pager(
    { offset, count: result.logs.length, limit },
    next => navigate("audit", { offset: next, action, requestId }),
  ));
  view.append(box);
}

async function system(view) {
  title("System activity", "Check service readiness and current backend metrics.");
  const [health, data] = await Promise.all([api("/ready", { accept: [503] }), api("/admin/metrics")]);
  const assistant = data.assistant || {};
  const status = panel("Readiness");
  const checks = el("div", undefined, "actions");
  checks.append(
    statusPill(health.status, health.status === "ready" ? "Service ready" : "Service degraded"),
    statusPill(health.checks.orders ? "READY" : "DEGRADED", health.checks.orders ? "Orders available" : "Orders unavailable"),
    statusPill(health.checks.ollama ? "READY" : "DEGRADED", health.checks.ollama ? "Ollama available" : "Ollama unavailable"),
  );
  status.append(checks);
  const requests = panel("API activity");
  requests.append(table(["Method", "Route", "HTTP status", "Requests", "Mean latency"], data.requests.map(item => [
    item.method, item.route, item.status, item.count, item.mean_ms + " ms",
  ]), "There is no request activity yet."));
  view.append(metrics([
    ["Chat turns", assistant.turns], ["Tool calls", assistant.tool_calls],
    ["Review escalations", assistant.escalated_turns],
  ]), status, requests);
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
    state.messages.push(
      { text: result.customer_message, user: true },
      { text: result.assistant_response, sources: result.policy_sources, case: result.support_case },
    );
  } finally {
    if (state.sending === submission) state.sending = null;
  }
}

async function chat(view, { conversationId } = {}) {
  title("Support chat", "Ask about orders, delivery, and return policies.");
  const layout = el("div", undefined, "columns chat-layout");
  const box = panel();
  const log = el("div", undefined, "chat-log");
  log.setAttribute("role", "log");
  const historyList = el("div", undefined, "conversation-list");
  function draw() {
    log.replaceChildren();
    if (!state.messages.length) {
      log.append(el("h2", "How can we help?"));
      const suggestions = el("div", undefined, "actions");
      for (const suggestion of ["What is the return window?", "How do refunds work?"]) {
        suggestions.append(button(suggestion, () => {
          composer.elements.message.value = suggestion;
          composer.elements.message.focus();
        }));
      }
      log.append(suggestions);
    }
    for (const message of state.messages) {
      const bubble = el("div", message.text, message.user ? "bubble customer" : "bubble");
      if (message.sources?.length) bubble.append(el("small", "Sources · " + message.sources.join(", ")));
      if (message.case?.case_id) {
        bubble.append(el("br"), button("View support case", () => navigate("cases", { caseId: message.case.case_id }), "text-button"));
      }
      log.append(bubble);
    }
    const latest = state.messages.at(-1);
    if (latest && !latest.user) {
      const returnDraft = latest.text.endsWith("Reply 'confirm' to submit this return request.");
      const cancellationDraft = latest.text.endsWith("Reply 'confirm' to send this cancellation request to staff.");
      if (returnDraft || cancellationDraft) {
        const confirm = button(returnDraft ? "Confirm return request" : "Confirm cancellation request", async () => {
          await sendChat("confirm");
          draw();
        }, "primary");
        const controls = el("div", undefined, "actions");
        controls.append(confirm);
        log.append(controls);
      }
    }
    log.scrollTop = log.scrollHeight;
  }
  async function openConversation(id) {
    const version = ++state.chatVersion;
    const base = "/conversation/" + pathId(id);
    let result = await api(base + "?limit=50");
    if (result.total_messages > 50) result = await api(base + "?limit=50&offset=" + (result.total_messages - 50));
    if (version !== state.chatVersion) return;
    state.conversation = id;
    state.messages = result.messages.map(message => ({ text: message.content, user: message.role === "user" }));
    draw();
  }
  async function loadHistory() {
    const { conversations } = await api("/customers/me/conversations");
    historyList.replaceChildren();
    if (!conversations.length) historyList.append(el("p", "New chats appear here.", "muted"));
    for (const item of conversations) {
      const entry = button("Open conversation", () => openConversation(item.conversation_id));
      const date = el("small", displayDate(item.created_at));
      date.setAttribute("aria-hidden", "true");
      entry.append(date);
      historyList.append(entry);
    }
  }
  const composer = form([["message", "Message", "textarea"]], "Send message", async (data, node) => {
    const startedNew = !state.conversation;
    await sendChat(data.message);
    node.reset();
    draw();
    if (startedNew) await loadHistory();
  });
  composer.elements.message.maxLength = 2000;
  composer.elements.message.placeholder = "Ask a question or enter an order ID";
  const controls = el("div", undefined, "actions chat-actions");
  controls.append(
    button("New chat", async () => {
      state.chatVersion += 1;
      state.messages = [];
      state.conversation = null;
      draw();
      composer.elements.message.focus();
    }),
    button("Dictate", () => dictate(composer.elements.message)),
    button("Read reply", () => readReply()),
  );
  draw();
  box.append(controls, log, composer);
  const history = panel("Recent conversations");
  history.append(historyList);
  layout.append(box, history);
  view.append(layout);
  await loadHistory();
  if (conversationId) await openConversation(conversationId);
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

const views = { overview, orders, returns, refunds, cases, link, audit, system, preferences, chat };
byId("workspace-home").addEventListener("click", () => navigate("overview"));
navigate("sign-in");
