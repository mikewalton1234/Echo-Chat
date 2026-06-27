function ecAuthExpiredResponse() {
  try { return new Response('', { status: 401, statusText: 'Unauthorized' }); } catch {}
  return { ok: false, status: 401, statusText: 'Unauthorized', json: async () => ({}), text: async () => '' };
}

function ecNetworkErrorResponse() {
  // Response(status: 0) cannot be constructed by page JS; Response.error() is
  // the browser-supported way to represent a failed/network-error response.
  try {
    if (typeof Response !== 'undefined' && typeof Response.error === 'function') return Response.error();
  } catch {}
  return { ok: false, status: 0, statusText: 'Network Error', type: 'error', json: async () => ({}), text: async () => '' };
}

async function ecReadJsonResponse(resp, fallback = null) {
  if (!resp || typeof resp.json !== 'function') return fallback;
  try {
    const data = await resp.json();
    return data === undefined ? fallback : data;
  } catch {
    return fallback;
  }
}

async function ecReadTextResponse(resp, fallback = '') {
  if (!resp || typeof resp.text !== 'function') return fallback;
  try {
    const text = await resp.text();
    return text === undefined || text === null ? fallback : String(text);
  } catch {
    return fallback;
  }
}

function ecApiErrorMessage(resp, data = null, fallback = 'Request failed') {
  if (!resp) return 'Network error: no response from server';
  const status = Number(resp.status || 0);
  if (status === 0) return 'Network error: server could not be reached';
  if (status === 401) return 'Login expired. Please sign in again.';
  if (status === 403) return 'You do not have permission to do that.';
  if (status === 404) return 'Not found.';
  if (status === 429) return 'Too many requests. Please slow down and try again.';
  const candidate = data && (data.error || data.msg || data.message || data.detail);
  if (candidate) return String(candidate);
  return `${fallback} (HTTP ${status || '?'})`;
}

async function ecReadApiJson(resp, fallback = {}) {
  return await ecReadJsonResponse(resp, fallback);
}

async function ecFetchJsonWithAuth(url, options = {}, authOptions = {}, { requireSuccess = false, fallback = 'Request failed' } = {}) {
  const resp = await fetchWithAuth(url, options, authOptions);
  const data = await ecReadApiJson(resp, {});
  const successOk = !requireSuccess || !!(data && (data.success === true || data.ok === true));
  if (!resp || !resp.ok || !successOk) {
    throw new Error(ecApiErrorMessage(resp, data, fallback));
  }
  return { resp, data };
}

async function fetchWithAuth(url, options = {}, { retryOn401 = true, useRefreshCsrf = false } = {}) {
  const opts = { credentials: "include", ...options };
  opts.headers = { ...(opts.headers || {}) };

  // If we already know the session is expired, don't keep hammering the server.
  if (typeof AUTH_EXPIRED !== "undefined" && AUTH_EXPIRED) {
    return ecAuthExpiredResponse();
  }

  // JWT cookie CSRF protection: access requests use csrf_access_token,
  // refresh uses csrf_refresh_token.
  const csrfName = useRefreshCsrf ? "csrf_refresh_token" : "csrf_access_token";
  const csrfVal = getCookie(csrfName);
  if (csrfVal && !opts.headers["X-CSRF-TOKEN"]) {
    opts.headers["X-CSRF-TOKEN"] = csrfVal;
  }

  let resp;
  try {
    resp = await fetch(url, opts);
  } catch (e) {
    // Network/server down: stay in-app, but keep quick reconnects invisible.
    if (navigator && navigator.onLine === false) {
      setConnBannerNow("offline", "📡 Offline — waiting for network…", { spinner: false, showRetry: false });
    } else {
      setConnBannerSoon("disconnected", "🔌 Connection lost — reconnecting…");
    }
    tryReconnectNow("network_error");
    return ecNetworkErrorResponse();
  }
  if (resp.status === 401 && retryOn401) {
    // Typical when the access token has expired.
    // Do a bounded refresh-with-backoff. If that fails, enter auth-expired mode
    // and stop periodic polling until the user manually retries/logs out.
    try {
      await refreshAccessTokenWithBackoff(3);
      // Refresh can rotate the access CSRF cookie, so update the header before retrying.
      try {
        const newCsrfVal = getCookie("csrf_access_token");
        if (newCsrfVal) opts.headers["X-CSRF-TOKEN"] = newCsrfVal;
      } catch {}
      try {
        resp = await fetch(url, opts);
      } catch (e) {
        if (navigator && navigator.onLine === false) {
          setConnBannerNow("offline", "📡 Offline — waiting for network…", { spinner: false, showRetry: false });
        } else {
          setConnBannerSoon("disconnected", "🔌 Connection lost — reconnecting…");
        }
        tryReconnectNow("network_error");
        return ecNetworkErrorResponse();
      }
      if (resp.status === 401) {
        // Refresh said OK but the request is still unauthorized (server-side session revoked,
        // refresh rotated in another tab/device, etc).
        enterAuthExpiredState('auth_required');
      }
    } catch {
      enterAuthExpiredState('auth_required');
    }
  }
  return resp;
}

async function xhrPostFormWithAuth(url, formData, { onProgress } = {}) {
  // XHR is used so we can show upload progress bars for server-fallback file transfers.
  const doOnce = () => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    xhr.withCredentials = true;

    const csrfVal = getCookie("csrf_access_token");
    if (csrfVal) xhr.setRequestHeader("X-CSRF-TOKEN", csrfVal);

    // If the browser/network stack wedges, XHR can appear to "do nothing".
    // Add a stall watchdog: if we see zero progress/state-change for too long,
    // abort so we can fall back to fetch().
    const TOTAL_TIMEOUT_MS = 60_000;
    const STALL_TIMEOUT_MS = 12_000;
    let lastActivity = Date.now();
    const bump = () => { lastActivity = Date.now(); };

    const stallTimer = setInterval(() => {
      if ((Date.now() - lastActivity) > STALL_TIMEOUT_MS) {
        try { xhr.abort(); } catch {}
      }
    }, 750);

    const cleanup = () => { try { clearInterval(stallTimer); } catch {} };

    if (xhr.upload && typeof onProgress === "function") {
      xhr.upload.onprogress = (ev) => {
        bump();
        try {
          if (ev.lengthComputable && ev.total > 0) onProgress(ev.loaded / ev.total);
        } catch {}
      };
    }

    xhr.onreadystatechange = () => bump();
    xhr.onerror = () => { cleanup(); reject(new Error("Network error")); };
    xhr.onabort = () => { cleanup(); reject(new Error("Upload stalled")); };
    xhr.ontimeout = () => { cleanup(); reject(new Error("Upload timeout")); };
    xhr.timeout = TOTAL_TIMEOUT_MS;

    xhr.onload = () => {
      cleanup();
      let json = null;
      try { json = JSON.parse(xhr.responseText || ""); } catch {}
      resolve({ status: xhr.status, ok: xhr.status >= 200 && xhr.status < 300, json, text: xhr.responseText });
    };

    bump();
    xhr.send(formData);
  });

  let res = await doOnce();
  if (res.status === 401) {
    // Access token likely expired; attempt refresh then retry once.
    await refreshAccessToken();
    res = await doOnce();
  }
  return res;
}

async function fetchPostFormWithAuth(url, formData) {
  const resp = await fetchWithAuth(url, {
    method: "POST",
    credentials: "include",
    body: formData,
  });
  let json = null;
  let text = "";
  try { text = await resp.text(); } catch {}
  try { json = text ? JSON.parse(text) : null; } catch {}
  return { status: resp.status, ok: resp.ok, json, text };
}
