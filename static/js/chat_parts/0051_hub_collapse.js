// Collapsible desktop hub
(function () {
  const STORAGE_KEY = "ec_hub_collapsed";

  function getAppRoot() {
    return document.getElementById("appRoot") || document.body;
  }

  function isMobileShell(root) {
    return !!(root && root.classList && root.classList.contains("is-mobile-shell"));
  }

  function setHubCollapsed(collapsed, persist = true) {
    const root = getAppRoot();
    const dock = document.getElementById("ecDock");
    const btn = document.getElementById("btnHubCollapse");
    const icon = btn ? btn.querySelector(".dockCollapseIcon") : null;
    const next = !!collapsed && !isMobileShell(root);

    if (root && root.classList) {
      root.classList.toggle("is-hub-collapsed", next);
    }
    if (dock) {
      dock.classList.toggle("is-collapsed", next);
      dock.setAttribute("aria-hidden", next ? "true" : "false");
    }
    if (btn) {
      btn.setAttribute("aria-expanded", next ? "false" : "true");
      btn.setAttribute("title", next ? "Expand hub" : "Collapse hub");
      btn.setAttribute("aria-label", next ? "Expand hub" : "Collapse hub");
    }
    if (icon) {
      icon.textContent = "›";
    }

    if (next && typeof closeDockRailPanel === "function") {
      try { closeDockRailPanel(); } catch {}
    }

    if (persist) {
      try { localStorage.setItem(STORAGE_KEY, next ? "1" : "0"); } catch {}
    }
  }

  function bindHubCollapse() {
    const root = getAppRoot();
    const btn = document.getElementById("btnHubCollapse");
    if (!btn || btn.dataset.bound === "1") return;

    btn.dataset.bound = "1";
    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      const collapsed = !(root && root.classList && root.classList.contains("is-hub-collapsed"));
      setHubCollapsed(collapsed, true);
    });

    let saved = "0";
    try { saved = localStorage.getItem(STORAGE_KEY) || "0"; } catch {}
    setHubCollapsed(saved === "1", false);
  }

  document.addEventListener("DOMContentLoaded", bindHubCollapse);

  window.ecSetHubCollapsed = setHubCollapsed;
  window.ecToggleHubCollapsed = function () {
    const root = getAppRoot();
    setHubCollapsed(!(root && root.classList && root.classList.contains("is-hub-collapsed")), true);
  };
})();
