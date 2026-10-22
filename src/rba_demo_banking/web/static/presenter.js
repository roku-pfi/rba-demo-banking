// Presenter panel (D-1): POST a scene, log what came back.
(() => {
  const log = document.getElementById('log');
  const meter = document.getElementById('load');

  const el = (tag, attrs = {}, text = '') => {
    const node = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    if (text) node.textContent = text;
    return node;
  };
  const now = () => new Date().toLocaleTimeString('es-AR', { hour12: false });

  function entry(title, lines = [], error = '') {
    const li = el('li');
    li.append(el('time', {}, now()), document.createTextNode(title));
    lines.forEach((line) => li.append(line));
    if (error) li.append(el('div', { class: 'err' }, error));
    log.prepend(li);
  }

  function attackLines(regions) {
    return regions.map((r) => {
      const div = el('div');
      const where = `${r.city}${r.egress_ip ? ' ' + r.egress_ip : ''}${r.real ? '' : ' (local)'}: `;
      div.append(document.createTextNode(where));
      if (r.error) div.append(el('span', { class: 'err' }, r.error));
      r.attempts.forEach((a, i) => {
        if (i) div.append(document.createTextNode(' · '));
        div.append(el('span', { class: `o-${a.outcome}` }, a.outcome));
      });
      return div;
    });
  }

  async function pollLoad() {
    const data = await fetch('/presenter/load').then((r) => r.json());
    meter.hidden = false;
    const set = (k, v) => { meter.querySelector(`[data-k="${k}"]`).textContent = v; };
    set('elapsed', `${data.elapsed}/${data.seconds} s`);
    set('rps', `${data.rps} req/s`);
    set('p95', `p95 ${data.p95_ms ?? '–'} ms`);
    set('errors', `${data.errors} err`);
    if (data.running) setTimeout(pollLoad, 2000);
    else entry(`Carga: ${data.sent} req, p95 ${data.p95_ms ?? '–'} ms, ${data.errors} errores`);
  }

  document.querySelectorAll('button[data-post]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (button.dataset.confirm && !confirm(button.dataset.confirm)) return;
      const label = button.closest('.row').querySelector('b').textContent;
      button.disabled = true;
      try {
        const resp = await fetch(button.dataset.post, { method: 'POST' });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) entry(label, [], data.detail || `HTTP ${resp.status}`);
        else if (data.regions) entry(label, attackLines(data.regions));
        else if (data.load) { entry(label, [], data.started ? '' : 'ya en curso'); pollLoad(); }
        else if (data.reset) entry(label, [el('div', {}, data.reset.users.length ? data.reset.users.join(', ') : 'nada que borrar')], data.reset.error || '');
        else entry(label);
      } catch (err) {
        entry(label, [], String(err));
      } finally {
        button.disabled = false;
      }
    });
  });
})();
