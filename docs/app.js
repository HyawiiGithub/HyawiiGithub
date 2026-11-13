/* heatmap with hover tooltips, plus the market game. data.json comes from scripts/generate.py */

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
const CELL = 11;
const GAP = 3;

const fmt = (n) => Number(n).toLocaleString('en-US');

function parseISO(iso) {
  const parts = iso.split('-').map(Number);
  return new Date(parts[0], parts[1] - 1, parts[2]);
}

function longDate(d) {
  return d.toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  }).toLowerCase();
}

/* ---------------------------------------------------------------- heatmap */

function renderHeatmap(data) {
  const grid = document.getElementById('grid');
  const months = document.getElementById('months');
  const days = data.days;
  const first = parseISO(days[0][0]);
  const lead = first.getDay();
  const cols = Math.ceil((lead + days.length) / 7);

  grid.style.gridTemplateColumns = `repeat(${cols}, ${CELL}px)`;

  for (let i = 0; i < lead; i += 1) {
    grid.appendChild(document.createElement('span'));
  }

  let lastMonth = -1;
  const placed = new Set();

  days.forEach(([iso, count, level], index) => {
    const date = parseISO(iso);
    const col = Math.floor((lead + index) / 7);

    const cell = document.createElement('div');
    cell.className = `cell lv${level}`;
    cell.dataset.count = String(count);
    cell.dataset.date = longDate(date);
    cell.tabIndex = 0;
    grid.appendChild(cell);

    if (date.getMonth() !== lastMonth) {
      lastMonth = date.getMonth();
      if (col < cols - 1 && !placed.has(col)) {
        placed.add(col);
        const label = document.createElement('span');
        label.className = 'month';
        label.textContent = MONTHS[date.getMonth()];
        label.style.left = `${col * (CELL + GAP)}px`;
        months.appendChild(label);
      }
    }
  });

  document.getElementById('head-total').innerHTML =
    `<b>${fmt(data.total)}</b> contributions since ${MONTHS[first.getMonth()]} ${first.getFullYear()}`;

  const tip = document.getElementById('tooltip');

  function show(cell) {
    const rect = cell.getBoundingClientRect();
    const count = Number(cell.dataset.count);
    tip.innerHTML = `<strong>${fmt(count)}</strong> ${count === 1 ? 'contribution' : 'contributions'}`
      + `<span>${cell.dataset.date}</span>`;
    tip.hidden = false;
    const x = Math.min(Math.max(rect.left + rect.width / 2, 90), window.innerWidth - 90);
    tip.style.left = `${x}px`;
    tip.style.top = `${rect.top}px`;
  }

  grid.addEventListener('mouseover', (event) => {
    const cell = event.target.closest('.cell');
    if (cell) show(cell);
  });
  grid.addEventListener('focusin', (event) => {
    const cell = event.target.closest('.cell');
    if (cell) show(cell);
  });
  grid.addEventListener('mouseleave', () => { tip.hidden = true; });
  grid.addEventListener('focusout', () => { tip.hidden = true; });
  window.addEventListener('scroll', () => { tip.hidden = true; }, { passive: true });
}

function renderStripe(data) {
  const rows = [
    ['contributions', fmt(data.total)],
    ['active days', fmt(data.active_days)],
    ['current streak', `${data.current_streak}d`],
    ['busiest day', fmt(data.busiest.count)],
  ];
  document.getElementById('stripe').innerHTML = rows
    .map(([label, value]) => `<div><strong>${value}</strong><span>${label}</span></div>`)
    .join('');
}

/* --------------------------------------------------------------- net worth */

function money(n) {
  const units = [[1e12, 'T'], [1e9, 'B'], [1e6, 'M'], [1e3, 'K']];
  for (const [size, suffix] of units) {
    if (n >= size) return `$${(n / size).toFixed(2)}${suffix}`;
  }
  return `$${Math.round(n)}`;
}

function setupWorth(data) {
  const canvas = document.getElementById('worthChart');
  const ctx = canvas.getContext('2d');
  const tip = document.getElementById('tooltip');
  const per = data.per_commit || 1000000;

  let running = 0;
  const points = data.days.map(([iso, count]) => {
    running += count;
    return { value: running * per, label: longDate(parseISO(iso)) };
  });
  const peak = points[points.length - 1].value || 1;

  document.getElementById('worth-value').textContent = money(data.net_worth);
  document.getElementById('worth-meta').innerHTML = `<b>${fmt(data.total)}</b> commits`;
  document.getElementById('worth-sub').innerHTML =
    `${fmt(data.net_worth)}<br>since ${MONTHS[parseISO(data.days[0][0]).getMonth()]} ${parseISO(data.days[0][0]).getFullYear()}`;

  let hover = -1;

  function draw() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 560;
    const h = canvas.clientHeight || 132;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const padTop = 10;
    const padBottom = 6;
    const x = (i) => (i / (points.length - 1)) * (w - 2) + 1;
    const y = (v) => (h - padBottom) - (v / peak) * (h - padBottom - padTop);

    ctx.strokeStyle = 'rgba(255,255,255,.05)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 2; i += 1) {
      const gy = padTop + (h - padTop - padBottom) * (i / 2);
      ctx.beginPath();
      ctx.moveTo(0, gy);
      ctx.lineTo(w, gy);
      ctx.stroke();
    }

    ctx.beginPath();
    points.forEach((p, i) => {
      if (i === 0) ctx.moveTo(x(i), y(p.value));
      else ctx.lineTo(x(i), y(p.value));
    });
    ctx.strokeStyle = '#a78bfa';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.stroke();

    ctx.lineTo(w, h);
    ctx.lineTo(x(0), h);
    ctx.closePath();
    const fill = ctx.createLinearGradient(0, padTop, 0, h);
    fill.addColorStop(0, 'rgba(167,139,250,.42)');
    fill.addColorStop(1, 'rgba(167,139,250,0)');
    ctx.fillStyle = fill;
    ctx.fill();

    const index = hover >= 0 ? hover : points.length - 1;
    const hx = x(index);
    const hy = y(points[index].value);
    if (hover >= 0) {
      ctx.strokeStyle = 'rgba(255,255,255,.22)';
      ctx.beginPath();
      ctx.moveTo(hx, 0);
      ctx.lineTo(hx, h);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(hx, hy, 3.2, 0, Math.PI * 2);
    ctx.fillStyle = '#c9b8ff';
    ctx.fill();
  }

  function indexFrom(clientX) {
    const rect = canvas.getBoundingClientRect();
    const ratio = (clientX - rect.left) / rect.width;
    return Math.max(0, Math.min(points.length - 1, Math.round(ratio * (points.length - 1))));
  }

  canvas.addEventListener('mousemove', (event) => {
    hover = indexFrom(event.clientX);
    draw();
    const rect = canvas.getBoundingClientRect();
    const point = points[hover];
    tip.innerHTML = `<strong>${money(point.value)}</strong><span>${point.label}</span>`;
    tip.hidden = false;
    const px = rect.left + (hover / (points.length - 1)) * rect.width;
    tip.style.left = `${Math.min(Math.max(px, 90), window.innerWidth - 90)}px`;
    tip.style.top = `${rect.top + 30}px`;
  });

  canvas.addEventListener('mouseleave', () => {
    hover = -1;
    tip.hidden = true;
    draw();
  });

  window.addEventListener('resize', draw);
  draw();
}

/* ------------------------------------------------------------------- game */

function setupGame() {
  const canvas = document.getElementById('chart');
  const ctx = canvas.getContext('2d');
  const overlay = document.getElementById('overlay');
  const result = document.getElementById('result');
  const startBtn = document.getElementById('start');
  const buyBtn = document.getElementById('buy');
  const sellBtn = document.getElementById('sell');
  const hud = document.getElementById('hud');
  const hint = document.getElementById('hint');

  const START_CASH = 1000;
  const ROUND_MS = 30000;
  const TICK_MS = 110;
  const KEEP = 160;

  let price = 100;
  let history = [price];
  let cash = START_CASH;
  let lots = 0;
  let running = false;
  let startedAt = 0;
  let lastTick = 0;
  let left = ROUND_MS;
  let timer = 0;
  let best = Number(localStorage.getItem('ticker-best') || 0);

  const value = () => cash + lots * price;

  function draw() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 600;
    const h = canvas.clientHeight || 230;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const pad = 18;
    ctx.strokeStyle = 'rgba(255,255,255,.06)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i += 1) {
      const gy = pad + (h - pad * 2) * (i / 3);
      ctx.beginPath();
      ctx.moveTo(0, gy);
      ctx.lineTo(w, gy);
      ctx.stroke();
    }

    const min = Math.min(...history);
    const max = Math.max(...history);
    const span = max - min || 1;
    const x = (i) => (i / (KEEP - 1)) * w;
    const y = (v) => pad + (1 - (v - min) / span) * (h - pad * 2);
    const offset = KEEP - history.length;

    ctx.beginPath();
    history.forEach((v, i) => {
      const px = x(i + offset);
      const py = y(v);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.strokeStyle = '#d4a94e';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.stroke();

    ctx.lineTo(w, h);
    ctx.lineTo(x(offset), h);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, pad, 0, h);
    grad.addColorStop(0, 'rgba(196,18,46,.35)');
    grad.addColorStop(1, 'rgba(196,18,46,0)');
    ctx.fillStyle = grad;
    ctx.fill();

    const lx = x(KEEP - 1);
    const ly = y(history[history.length - 1]);
    ctx.beginPath();
    ctx.arc(lx, ly, 6, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(196,18,46,.35)';
    ctx.fill();
    ctx.beginPath();
    ctx.arc(lx, ly, 3.2, 0, Math.PI * 2);
    ctx.fillStyle = '#ff4d67';
    ctx.fill();
  }

  function updateHud() {
    hud.innerHTML = [
      `price <b>${price.toFixed(1)}</b>`,
      `gold <b>${Math.round(cash)}</b>`,
      `lots <b>${lots}</b>`,
      `value <b>${Math.round(value())}</b>`,
      `<span class="${left < 5000 ? 'warn' : ''}">${Math.max(0, Math.ceil(left / 1000))}s</span>`,
    ].join('');
  }

  function step() {
    const noise = (Math.random() - 0.47) * 5.5;
    const pull = (100 - price) * 0.006;
    price = Math.max(15, Math.min(280, price + noise + pull));
    history.push(price);
    if (history.length > KEEP) history.shift();
  }

  // a timer, not rAF: rAF stops completely in a background tab and the round
  // would sit at 30s forever
  function loop() {
    if (!running) return;
    const now = performance.now();
    left = ROUND_MS - (now - startedAt);
    while (now - lastTick >= TICK_MS) {
      lastTick += TICK_MS;
      step();
    }
    if (left <= 0) {
      finish();
      return;
    }
    draw();
    updateHud();
  }

  function start() {
    clearInterval(timer);
    price = 100;
    history = [price];
    cash = START_CASH;
    lots = 0;
    left = ROUND_MS;
    result.innerHTML = '';
    overlay.classList.add('hidden');
    hint.textContent = 'buy the dips, sell the peaks';
    draw();
    updateHud();
    running = true;
    startedAt = performance.now();
    lastTick = startedAt;
    timer = setInterval(loop, 33);
  }

  function finish() {
    running = false;
    clearInterval(timer);
    left = 0;
    const profit = Math.round(value() - START_CASH);
    if (profit > best) {
      best = profit;
      localStorage.setItem('ticker-best', String(best));
    }
    const sign = profit >= 0 ? '+' : '';
    result.innerHTML = `<strong class="${profit >= 0 ? 'up' : 'down'}">${sign}${fmt(profit)} gold</strong>`
      + `<span>${profit >= 0 ? 'the market respected you' : 'the market took it'}</span>`
      + `<em>best run ${best >= 0 ? '+' : ''}${fmt(best)}</em>`;
    startBtn.textContent = 'go again';
    overlay.classList.remove('hidden');
    draw();
    updateHud();
  }

  function buy() {
    if (!running) return;
    if (cash < price) {
      hint.textContent = 'not enough gold for that';
      return;
    }
    cash -= price;
    lots += 1;
    hint.textContent = `bought 1 lot at ${price.toFixed(1)}`;
    updateHud();
  }

  function sell() {
    if (!running) return;
    if (!lots) {
      hint.textContent = 'nothing to sell yet';
      return;
    }
    cash += lots * price;
    hint.textContent = `sold ${lots} ${lots === 1 ? 'lot' : 'lots'} at ${price.toFixed(1)}`;
    lots = 0;
    updateHud();
  }

  startBtn.addEventListener('click', start);
  buyBtn.addEventListener('click', buy);
  sellBtn.addEventListener('click', sell);

  window.addEventListener('keydown', (event) => {
    if (event.key === 'b' || event.key === 'B') buy();
    if (event.key === 's' || event.key === 'S') sell();
  });

  window.addEventListener('resize', draw);

  draw();
  updateHud();
}

/* ------------------------------------------------------------------- boot */

async function boot() {
  try {
    const response = await fetch('data.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`http ${response.status}`);
    const data = await response.json();
    renderHeatmap(data);
    renderStripe(data);
    setupWorth(data);
  } catch (error) {
    document.getElementById('head-total').textContent = `could not load data.json (${error.message})`;
  }
  setupGame();
}

boot();
