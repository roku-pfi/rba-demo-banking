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
  const DEVICE = { desktop: "computadora", mobile: "celular", tablet: "tablet" };
  const more = document.getElementById("attempts-more");
  const details = document.getElementById("attempts-details");
  let newest = null;

  // "Chrome en Windows · computadora", as a bank lists a sign-in.
  function device(a) {
    const what = [a.browser, a.os].filter(Boolean).join(" en ");
    const kind = DEVICE[a.device_type] ?? null;
    return [what, kind].filter(Boolean).join(" · ") || "Desconocido";
  }

  function fillDetails(attempts) {
    const body = details.querySelector("tbody");
    body.replaceChildren(...attempts.slice(0, 5).map((a) => {
      const row = document.createElement("tr");
      const place = a.country ? (COUNTRY?.of(a.country) ?? a.country) : "Desconocido";
      for (const text of [WHEN.format(new Date(a.occurred_at)), place, device(a), a.ip_address || "—"]) {
        const cell = document.createElement("td");
        cell.textContent = text;
        row.append(cell);
      }
      return row;
    }));
  }

  more.addEventListener("click", () => {
    const open = details.hidden;
    details.hidden = !open;
    more.setAttribute("aria-expanded", String(open));
    more.textContent = open ? "Ocultar detalles" : "Ver detalles";
  });

  function render(attempts) {
    if (!attempts.length) { box.hidden = true; return; }
    const a = attempts[0];
    newest = a.occurred_at;
    // Where and when, never how it was stopped: the owner needs to know to
    // change the password, not which control the attacker ran into.
    const place = a.country ? (COUNTRY?.of(a.country) ?? a.country) : "un lugar desconocido";
    const others = attempts.length > 1 ? ` (y ${attempts.length - 1} más)` : "";
    where.textContent = `Detectamos un ingreso sospechoso desde ${place}, ${WHEN.format(new Date(a.occurred_at))}${others}. Te recomendamos cambiar tu contraseña.`;
    fillDetails(attempts);
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
