function showUnlockModal() {
  // End users do not manage private-message key state manually. Private
  // messages become ready from the login password kept in this browser tab.
  // If that tab secret is missing, the user signs out and signs back in.
  try {
    toast("Private messages refresh after you sign out and sign back in.", "info", 4200);
  } catch {}
  return Promise.resolve(false);
}

async function ensurePrivateKeyUnlocked() {
  if (!HAS_WEBCRYPTO) throw new Error(`E2EE requires HTTPS (or http://localhost / http://127.0.0.1). Current origin: ${window.location.origin}`);
  if (window.myPrivateCryptoKey) return window.myPrivateCryptoKey;

  // Private messages become ready using the login password captured in
  // sessionStorage. There is intentionally no end-user key-state UI.
  const ok = await tryAutoUnlockPrivateMessages("");
  if (ok && window.myPrivateCryptoKey) return window.myPrivateCryptoKey;

  throw new Error("Private messages are not ready in this tab. Sign out and sign back in to refresh private messages.");
}
