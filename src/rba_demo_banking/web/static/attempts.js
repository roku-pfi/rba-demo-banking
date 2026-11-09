// "Alguien intentó ingresar a tu cuenta" while the person is signed in: the
// bank asks the IdP every few seconds (contracts 0.22.0). Shown until
// dismissed or the password is changed.
(() => {
  const box = document.getElementById("attempts");
  if (!box) return;
  const where = document.getElementById("attempts-where");
  const COUNTRY = (() => {
    try { return new Intl.DisplayNames(["es"], { type: "region" }); } catch { return null; }
  })();
  const WHEN = new Intl.DateTimeFormat("es-AR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  let newest = null;

  function render(attempts) {
    if (!attempts.length) { box.hidden = true; return; }
    const a = attempts[0];
    newest = a.occurred_at;
    const place = a.country ? (COUNTRY?.of(a.country) ?? a.country) : "un lugar desconocido";
    const how = a.stopped_by === "passkey" ? "le pedimos tu passkey" : "lo bloqueamos";
    const more = attempts.length > 1 ? ` y ${attempts.length - 1} más` : "";
    where.textContent = `Desde ${place}, ${WHEN.format(new Date(a.occurred_at))}: ${how}${more}. Si no fuiste vos, cambiá tu contraseña.`;
    box.hidden = false;
  }

  async function poll() {
    try {
      const resp = await fetch("/attempts", { credentials: "same-origin" });
      if (resp.status === 200) render((await resp.json()).attempts || []);
    } catch { /* offline: try again later */ }
  }

  document.getElementById("attempts-ok").addEventListener("click", async () => {
    box.hidden = true;
    if (!newest) return;
    const body = new URLSearchParams({ up_to: newest });
    try { await fetch("/attempts/seen", { method: "POST", body, credentials: "same-origin" }); } catch {}
  });

  poll();
  setInterval(() => { if (document.visibilityState === "visible") poll(); }, 10000);
})();
