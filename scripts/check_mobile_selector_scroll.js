const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const APP_URL = 'http://127.0.0.1:8765';
const DEBUG_PORT = 9347;

function findFirstExisting(candidates) {
  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`http_${response.status}:${url}`);
  }
  return response.json();
}

async function waitForJson(url, tries = 60) {
  let lastError;
  for (let attempt = 0; attempt < tries; attempt += 1) {
    try {
      return await fetchJson(url);
    } catch (error) {
      lastError = error;
      await delay(100);
    }
  }
  throw lastError || new Error(`json_endpoint_unavailable:${url}`);
}

class DevToolsSession {
  constructor(webSocketDebuggerUrl) {
    this.nextId = 1;
    this.pending = new Map();
    this.socket = new WebSocket(webSocketDebuggerUrl);
    this.ready = new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, { once: true });
      this.socket.addEventListener('error', reject, { once: true });
    });
    this.socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !this.pending.has(message.id)) return;
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) {
        reject(new Error(JSON.stringify(message.error)));
      } else {
        resolve(message.result);
      }
    });
  }

  async send(method, params = {}) {
    await this.ready;
    const id = this.nextId;
    this.nextId += 1;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  close() {
    this.socket.close();
  }
}

async function evaluate(session, expression) {
  const result = await session.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(`runtime_exception:${JSON.stringify(result.exceptionDetails)}`);
  }
  return result.result.value;
}

async function waitForExpression(session, expression, errorCode, tries = 60) {
  for (let attempt = 0; attempt < tries; attempt += 1) {
    if (await evaluate(session, expression)) return;
    await delay(100);
  }
  throw new Error(errorCode);
}

function mockWindow(index) {
  const day = Math.floor(index / 5) + 1;
  const fixedHours = [5, 8, 11, 14, 17];
  const hour = fixedHours[index % fixedHours.length];
  const start = new Date(Date.UTC(2026, 4, day, hour - 1, 0, 0));
  const end = new Date(start.getTime() + 3 * 60 * 60 * 1000);
  const label = `Day ${day} ${String(hour).padStart(2, '0')}:00-${String(hour + 3).padStart(2, '0')}:00`;

  return {
    label,
    starts_at: start.toISOString(),
    ends_at: end.toISOString(),
    hours_away: index * 3,
    score: 6.2 + ((index % 4) * 0.4),
    tier: index % 5 === 0 ? 'gold' : 'green',
    reason: 'Mock clean window for mobile layout verification.',
    confidence: 'mock',
    window_practical: {
      summary: 'Mock selected-window summary.',
      confidence_label: 'Mock signal',
      indicators: [
        {
          id: 'wave_fit',
          label: 'Wave fit',
          status: 'Good fit',
          tone: 'good',
          score_0_1: 0.8,
          explanation: 'Mock readable wave fit.',
        },
        {
          id: 'wind',
          label: 'Wind',
          status: 'Clean',
          tone: 'good',
          score_0_1: 0.8,
          explanation: 'Mock clean wind.',
        },
      ],
    },
    window_technical: {
      unavailable_reason: 'mock',
    },
  };
}

async function injectMockHero(session) {
  const predictorWindows = Array.from({ length: 35 }, (_, index) => mockWindow(index));
  const topWindows = [0, 8, 16, 24, 32, 4, 12, 20, 28, 34].map(
    (index) => predictorWindows[index],
  );
  const payload = JSON.stringify({ topWindows, predictorWindows });

  await evaluate(session, `
    (() => {
      if (typeof renderUnifiedHero !== 'function') throw new Error('renderUnifiedHero_missing');
      if (typeof bindUnifiedHero !== 'function') throw new Error('bindUnifiedHero_missing');

      const payload = ${payload};
      const data = {
        unified: {
          tier: 'green',
          decision: 'go',
          decision_headline: 'GO FOR A TEST WINDOW',
          plain_summary: 'Mock summary for mobile selector verification.',
          decision_reason: 'Mock reason.',
          top_windows: payload.topWindows,
          best_window: payload.topWindows[0],
          predictor_windows: payload.predictorWindows,
        },
      };

      document.body.innerHTML = '<div class="container"><div class="cards"><div class="card" id="card-mobile-smoke"></div></div></div>';
      const card = document.getElementById('card-mobile-smoke');
      card.innerHTML = renderUnifiedHero(data);
      bindUnifiedHero(card);

      if (!document.querySelector('.hero-window-next')) throw new Error('hero_next_missing');
      if (!document.querySelector('.hero-predictor-track')) throw new Error('predictor_track_missing');
      return true;
    })()
  `);
}

async function measure(session, label) {
  return evaluate(session, `
    (() => {
      const track = document.querySelector('.hero-predictor-track');
      const selected = document.querySelector('.hero-predictor-bar[aria-pressed="true"]');
      const active = document.activeElement;
      return {
        label: ${JSON.stringify(label)},
        innerWidth: window.innerWidth,
        scrollX: window.scrollX,
        documentWidth: document.documentElement.scrollWidth,
        bodyWidth: document.body.scrollWidth,
        activeClass: active ? active.className : '',
        selectedText: selected ? selected.innerText.replace(/\\s+/g, ' ').trim() : '',
        trackScrollLeft: track ? Math.round(track.scrollLeft) : null,
        trackClientWidth: track ? track.clientWidth : null,
        trackScrollWidth: track ? track.scrollWidth : null,
      };
    })()
  `);
}

async function clickHeroNext(session, times) {
  for (let index = 0; index < times; index += 1) {
    await evaluate(session, `
      (() => {
        const button = document.querySelector('.hero-window-next');
        if (!button) throw new Error('hero_next_missing');
        if (button.disabled) throw new Error('hero_next_disabled');
        button.click();
        return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      })()
    `);
  }
}

async function removeProfile(profileDir) {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    try {
      fs.rmSync(profileDir, { recursive: true, force: true });
      return;
    } catch (error) {
      await delay(150);
    }
  }
  console.warn(`mobile_scroll_check_profile_cleanup_warning:${profileDir}`);
}

async function main() {
  const browserPath = findFirstExisting([
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  ]);

  if (!browserPath) {
    throw new Error('mobile_scroll_check_browser_missing');
  }

  await waitForJson(`${APP_URL}/api/spots`, 10).catch((error) => {
    throw new Error(`mobile_scroll_check_server_missing:${error.message}`);
  });

  const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lineup-mobile-scroll-'));
  const browser = spawn(browserPath, [
    '--headless=new',
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${profileDir}`,
    '--disable-gpu',
    '--force-device-scale-factor=1',
    '--no-first-run',
    '--no-default-browser-check',
    '--window-size=390,844',
    'about:blank',
  ], { stdio: 'ignore' });

  let session;
  try {
    await waitForJson(`http://127.0.0.1:${DEBUG_PORT}/json/version`);
    const target = await fetchJson(`http://127.0.0.1:${DEBUG_PORT}/json/new?about:blank`, {
      method: 'PUT',
    });

    session = new DevToolsSession(target.webSocketDebuggerUrl);
    await session.send('Runtime.enable');
    await session.send('Page.enable');
    await session.send('Emulation.setDeviceMetricsOverride', {
      width: 390,
      height: 844,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await session.send('Page.navigate', { url: APP_URL });
    await waitForExpression(
      session,
      'document.readyState === "complete" && typeof renderUnifiedHero === "function" && typeof bindUnifiedHero === "function"',
      'mobile_scroll_check_app_not_ready',
    );

    await injectMockHero(session);
    await waitForExpression(
      session,
      'Boolean(document.querySelector(".hero-window-next") && document.querySelector(".hero-predictor-track"))',
      'mobile_scroll_check_mock_render_failed',
    );

    const before = await measure(session, 'before');
    if (before.innerWidth > 500) {
      throw new Error(`mobile_viewport_not_applied:${before.innerWidth}`);
    }

    await clickHeroNext(session, 4);
    const after = await measure(session, 'after');

    console.log(JSON.stringify({ before, after }, null, 2));

    if (after.scrollX !== 0) {
      throw new Error(`root_scroll_x_changed:${after.scrollX}`);
    }

    if (after.documentWidth > after.innerWidth + 2) {
      throw new Error(`document_width_overflow:${after.documentWidth}:${after.innerWidth}`);
    }

    if (after.activeClass !== 'hero-window-carousel') {
      throw new Error(`hero_focus_lost:${after.activeClass}`);
    }
  } finally {
    if (session) session.close();
    browser.kill();
    await removeProfile(profileDir);
  }
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
