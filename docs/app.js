/* heatmap tooltips, the market history chart, the tape and the game. data.json comes from scripts/generate.py */

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
const DAY_MS = 86400000;
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

function money(n) {
  const units = [[1e12, 'T'], [1e9, 'B'], [1e6, 'M'], [1e3, 'K']];
  for (const [size, suffix] of units) {
    if (n >= size) return `$${(n / size).toFixed(2)}${suffix}`;
  }
  return `$${Math.round(n)}`;
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

function setupWorth(data) {
  const canvas = document.getElementById('worthChart');
  const ctx = canvas.getContext('2d');
  const tip = document.getElementById('tooltip');
  const start = parseISO(data.history.start);
  const values = data.history.values;
  const points = values.map((value, index) => ({
    value,
    date: new Date(start.getTime() + index * DAY_MS),
  }));

  const lowValue = Math.min(...values);
  const highValue = Math.max(...values);
  const lowLog = Math.log(lowValue);
  const spread = (Math.log(highValue) - lowLog) || 1;

  document.getElementById('worth-value').textContent = money(data.net_worth);
  document.getElementById('worth-sub').innerHTML =
    `${fmt(data.net_worth)}<br>since jan 2020`;
  const pct = data.change_pct || 0;
  document.getElementById('worth-meta').innerHTML =
    `<span class="${pct >= 0 ? 'up' : 'down'}">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}% today</span>`
    + `<span>${fmt(data.total)} commits</span>`;

  let hover = -1;

  function draw() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = canvas.clientWidth || 560;
    const h = canvas.clientHeight || 150;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.font = '9px "SF Mono", Menlo, Consolas, monospace';

    const padTop = 10;
    const padBottom = 18;
    const x = (i) => (i / (points.length - 1)) * (w - 2) + 1;
    const y = (v) => (h - padBottom) - ((Math.log(v) - lowLog) / spread) * (h - padBottom - padTop);

    for (let exp = Math.floor(Math.log10(lowValue)); exp <= Math.ceil(Math.log10(highValue)); exp += 1) {
      const level = Math.pow(10, exp);
      if (level < lowValue || level > highValue) continue;
      const gy = y(level);
      ctx.strokeStyle = 'rgba(255,255,255,.05)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, gy);
      ctx.lineTo(w, gy);
      ctx.stroke();
      ctx.fillStyle = 'rgba(139,139,150,.75)';
      ctx.fillText(money(level), 2, gy - 3);
    }

    const endTime = points[points.length - 1].date.getTime();
    for (let year = start.getFullYear() + 1; year <= points[points.length - 1].date.getFullYear(); year += 1) {
      const mark = Date.UTC(year, 0, 1);
      const index = Math.round((mark - start.getTime()) / DAY_MS);
      if (index <= 0 || index >= points.length || mark > endTime) continue;
      const gx = x(index);
      ctx.strokeStyle = 'rgba(255,255,255,.05)';
      ctx.beginPath();
      ctx.moveTo(gx, padTop);
      ctx.lineTo(gx, h - padBottom);
      ctx.stroke();
      ctx.fillStyle = 'rgba(139,139,150,.75)';
      ctx.textAlign = 'center';
      ctx.fillText(String(year), gx, h - 5);
      ctx.textAlign = 'left';
    }

    ctx.beginPath();
    points.forEach((p, i) => {
      if (i === 0) ctx.moveTo(x(i), y(p.value));
      else ctx.lineTo(x(i), y(p.value));
    });
    ctx.strokeStyle = '#a78bfa';
    ctx.lineWidth = 1.4;
    ctx.lineJoin = 'round';
    ctx.stroke();

    ctx.lineTo(w, h);
    ctx.lineTo(x(0), h);
    ctx.closePath();
    const fill = ctx.createLinearGradient(0, padTop, 0, h);
    fill.addColorStop(0, 'rgba(167,139,250,.34)');
    fill.addColorStop(1, 'rgba(167,139,250,0)');
    ctx.fillStyle = fill;
    ctx.fill();

    const index = hover >= 0 ? hover : points.length - 1;
    const hx = x(index);
    const hy = y(points[index].value);
    if (hover >= 0) {
      ctx.strokeStyle = 'rgba(255,255,255,.25)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(hx, padTop);
      ctx.lineTo(hx, h - padBottom);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(hx, hy, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#c9b8ff';
    ctx.fill();
  }

  canvas.addEventListener('mousemove', (event) => {
    const rect = canvas.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    hover = Math.max(0, Math.min(points.length - 1, Math.round(ratio * (points.length - 1))));
    draw();

    const point = points[hover];
    tip.innerHTML = `<strong>${money(point.value)}</strong><span>${longDate(point.date)}</span>`;
    tip.hidden = false;
    const px = rect.left + (hover / (points.length - 1)) * rect.width;
    tip.style.left = `${Math.min(Math.max(px, 92), window.innerWidth - 92)}px`;
    tip.style.top = `${rect.top + 34}px`;
  });

  canvas.addEventListener('mouseleave', () => {
    hover = -1;
    tip.hidden = true;
    draw();
  });

  window.addEventListener('resize', draw);
  draw();
}

/* -------------------------------------------------------------------- tape */

function setupTape() {
  const track = document.getElementById('tape-track');
  if (!track) return;
  const rows = [
    ['HYW', 2.14], ['AHD', 4.63], ['CRN', -1.28], ['VNG', 0.74],
    ['JVS', 12.41], ['DMW', -3.19], ['FLS', 1.86], ['USSR', -0.42],
  ];

  const render = () => {
    track.innerHTML = rows.map(([name, pct]) => {
      const up = pct >= 0;
      return `<span class="tick"><b>${name}</b>`
        + `<span class="${up ? 'up' : 'down'}">${up ? '+' : ''}${pct.toFixed(2)}%</span></span>`;
    }).join('');
  };

  render();
  setInterval(() => {
    rows.forEach((row) => {
      row[1] = Math.max(-18, Math.min(18, row[1] + (Math.random() - 0.5) * 0.9));
    });
    render();
  }, 2600);
}

/* -------------------------------------------------------------------- game */

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
    ctx.strokeStyle = '#a78bfa';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.stroke();

    ctx.lineTo(w, h);
    ctx.lineTo(x(offset), h);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, pad, 0, h);
    grad.addColorStop(0, 'rgba(167,139,250,.34)');
    grad.addColorStop(1, 'rgba(167,139,250,0)');
    ctx.fillStyle = grad;
    ctx.fill();

    const lx = x(KEEP - 1);
    const ly = y(history[history.length - 1]);
    ctx.beginPath();
    ctx.arc(lx, ly, 6, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(167,139,250,.28)';
    ctx.fill();
    ctx.beginPath();
    ctx.arc(lx, ly, 3.2, 0, Math.PI * 2);
    ctx.fillStyle = '#c9b8ff';
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
  setupTape();
  setupGame();
}

boot();
