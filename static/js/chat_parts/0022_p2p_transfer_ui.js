function appendP2pTransferUI(winEl, who, meta, { mode = "outgoing", ts } = {}) {
  const log = winEl?._ym?.log;
  if (!log) return { setProgress() {}, setStatus() {}, remove() {}, disableActions() {}, onAccept() {}, onDecline() {}, onCancel() {} };

  const card = document.createElement("span");
  card.className = "ym-xferCard";

  const row = document.createElement("span");
  row.className = "ym-xferRow";

  const icon = document.createElement("span");
  icon.textContent = "📎";

  const name = document.createElement("span");
  name.className = "ym-fileName";
  name.textContent = String(meta?.name || "file");

  const size = document.createElement("span");
  size.className = "ym-fileMeta";
  size.textContent = humanBytes(Number(meta?.size || 0) || 0);

  const badge = document.createElement("span");
  badge.className = "ym-fileBadge";
  badge.textContent = "P2P";

  row.appendChild(icon);
  row.appendChild(name);
  row.appendChild(size);
  row.appendChild(badge);

  const status = document.createElement("div");
  status.className = "ym-xferStatus";
  status.textContent = (mode === "incoming") ? "Incoming file…" : "Preparing…";

  const bar = document.createElement("div");
  bar.className = "ym-xferBar";
  const fill = document.createElement("span");
  fill.className = "ym-xferFill";
  bar.appendChild(fill);

  const actions = document.createElement("div");
  actions.className = "ym-xferActions";

  const btnAccept = document.createElement("button");
  btnAccept.type = "button";
  btnAccept.className = "ym-xferBtn";
  btnAccept.textContent = "Accept";

  const btnDecline = document.createElement("button");
  btnDecline.type = "button";
  btnDecline.className = "ym-xferBtn danger";
  btnDecline.textContent = "Decline";

  const btnCancel = document.createElement("button");
  btnCancel.type = "button";
  btnCancel.className = "ym-xferBtn danger";
  btnCancel.textContent = "Cancel";

  if (mode === "incoming") {
    actions.appendChild(btnAccept);
    actions.appendChild(btnDecline);
  } else {
    actions.appendChild(btnCancel);
  }

  card.appendChild(row);
  card.appendChild(status);
  card.appendChild(bar);
  if (actions.childElementCount) card.appendChild(actions);

  const item = appendGenericMessageItem(log, who, card, { ts, kind: "transfer" });
  scheduleScrollLogToBottom(log);

  let _onAccept = null;
  let _onDecline = null;
  let _onCancel = null;

  btnAccept.onclick = () => _onAccept && _onAccept();
  btnDecline.onclick = () => _onDecline && _onDecline();
  btnCancel.onclick = () => _onCancel && _onCancel();

  return {
    setProgress(r) {
      const ratio = Math.max(0, Math.min(1, Number(r) || 0));
      fill.style.width = `${Math.round(ratio * 100)}%`;
    },
    setStatus(s) {
      status.textContent = String(s || "");
    },
    remove() {
      try { item?.remove(); } catch {}
    },
    disableActions() {
      btnAccept.disabled = true;
      btnDecline.disabled = true;
      btnCancel.disabled = true;
    },
    onAccept(fn) { _onAccept = fn; },
    onDecline(fn) { _onDecline = fn; },
    onCancel(fn) { _onCancel = fn; },
    setBadge(text) {
      badge.textContent = String(text || "").slice(0, 6) || "";
    },
  };
}
