/**
 * Electron main process — spawns Python backend, creates window (PRD B.1 / C.7).
 * Phase 11: health watchdog + multi-restart recovery with renderer toast.
 */
const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

const BACKEND_HOST = '127.0.0.1';
const BACKEND_PORT = 8765;
const HEALTH_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}/health`;
const VITE_DEV_URL = 'http://127.0.0.1:5173';

const isDev = process.argv.includes('--dev') || !app.isPackaged;

let mainWindow = null;
let backendProc = null;
let backendRestartAttempts = 0;
const MAX_BACKEND_RESTARTS = 5;
const HEALTH_POLL_MS = 4000;
let healthTimer = null;
let consecutiveHealthFails = 0;
const HEALTH_FAILS_BEFORE_RESTART = 3;

function repoRoot() {
  return path.resolve(__dirname, '..');
}

function notifyRenderer(channel, payload) {
  try {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send(channel, payload);
    }
  } catch (err) {
    console.error('[ipc] notify failed', err);
  }
}

function resolveBackendCommand() {
  if (app.isPackaged) {
    const exeName =
      process.platform === 'win32' ? 'studsat-backend.exe' : 'studsat-backend';
    const packed = path.join(process.resourcesPath, 'backend', exeName);
    return { command: packed, args: [], cwd: path.dirname(packed) };
  }

  const backendDir = path.join(repoRoot(), 'backend');
  // Prefer venv python if present
  const venvPy =
    process.platform === 'win32'
      ? path.join(backendDir, '.venv', 'Scripts', 'python.exe')
      : path.join(backendDir, '.venv', 'bin', 'python');
  const fs = require('fs');
  const py =
    process.env.STUDSAT_PYTHON ||
    (fs.existsSync(venvPy)
      ? venvPy
      : process.platform === 'win32'
        ? 'python'
        : 'python3');
  return {
    command: py,
    args: ['-m', 'app.main'],
    cwd: backendDir,
  };
}

function backendEnv() {
  const env = { ...process.env, PYTHONUNBUFFERED: '1' };
  if (app.isPackaged) {
    // Packaged layout: resources/{backend,frontend,tiles}
    env.STUDSAT_TILES_DIR = path.join(process.resourcesPath, 'tiles');
    env.STUDSAT_LOGS_DIR = path.join(app.getPath('userData'), 'logs');
  } else {
    env.STUDSAT_TILES_DIR =
      process.env.STUDSAT_TILES_DIR || path.join(repoRoot(), 'tiles');
    env.STUDSAT_LOGS_DIR =
      process.env.STUDSAT_LOGS_DIR || path.join(repoRoot(), 'logs');
  }
  return env;
}

function spawnBackend() {
  if (backendProc) {
    return;
  }

  const { command, args, cwd } = resolveBackendCommand();
  console.log(`[backend] spawning: ${command} ${args.join(' ')} (cwd=${cwd})`);

  try {
    backendProc = spawn(command, args, {
      cwd,
      env: backendEnv(),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
  } catch (err) {
    console.error('[backend] spawn threw', err);
    notifyRenderer('studsat:backend-status', {
      state: 'err',
      message: `Backend spawn failed: ${err.message}`,
    });
    return;
  }

  backendProc.stdout?.on('data', (buf) => {
    console.log(`[backend] ${buf.toString().trimEnd()}`);
  });
  backendProc.stderr?.on('data', (buf) => {
    console.error(`[backend:err] ${buf.toString().trimEnd()}`);
  });

  backendProc.on('error', (err) => {
    console.error('[backend] process error', err);
    notifyRenderer('studsat:backend-status', {
      state: 'err',
      message: `Backend process error: ${err.message}`,
    });
  });

  backendProc.on('exit', (code, signal) => {
    console.warn(`[backend] exited code=${code} signal=${signal}`);
    backendProc = null;
    if (!app.isQuitting && backendRestartAttempts < MAX_BACKEND_RESTARTS) {
      backendRestartAttempts += 1;
      console.log(
        `[backend] restart attempt ${backendRestartAttempts}/${MAX_BACKEND_RESTARTS}`
      );
      notifyRenderer('studsat:backend-status', {
        state: 'restarting',
        message: `Backend crashed — restart ${backendRestartAttempts}/${MAX_BACKEND_RESTARTS}`,
        attempt: backendRestartAttempts,
      });
      setTimeout(spawnBackend, 1000);
    } else if (!app.isQuitting) {
      notifyRenderer('studsat:backend-status', {
        state: 'err',
        message: 'Backend failed repeatedly — restart the app',
      });
    }
  });
}

function killBackend() {
  app.isQuitting = true;
  stopHealthWatchdog();
  if (!backendProc) return;
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(backendProc.pid), '/f', '/t']);
    } else {
      backendProc.kill('SIGTERM');
    }
  } catch (err) {
    console.error('[backend] kill failed', err);
  }
  backendProc = null;
}

function probeHealth() {
  return new Promise((resolve) => {
    const req = http.get(HEALTH_URL, (res) => {
      let body = '';
      res.on('data', (c) => {
        body += c;
      });
      res.on('end', () => {
        resolve({ ok: res.statusCode === 200, body, status: res.statusCode });
      });
    });
    req.on('error', () => resolve({ ok: false, body: '', status: 0 }));
    req.setTimeout(1500, () => {
      req.destroy();
      resolve({ ok: false, body: '', status: 0 });
    });
  });
}

function waitForHealth(timeoutMs = 20000, intervalMs = 250) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tryOnce = async () => {
      const r = await probeHealth();
      if (r.ok) {
        resolve(r.body);
        return;
      }
      if (Date.now() - start > timeoutMs) {
        reject(new Error(`Backend health check timed out after ${timeoutMs}ms`));
        return;
      }
      setTimeout(tryOnce, intervalMs);
    };
    tryOnce();
  });
}

function startHealthWatchdog() {
  stopHealthWatchdog();
  healthTimer = setInterval(async () => {
    if (app.isQuitting) return;
    const r = await probeHealth();
    if (r.ok) {
      if (consecutiveHealthFails > 0) {
        notifyRenderer('studsat:backend-status', {
          state: 'ok',
          message: 'Backend recovered',
        });
      }
      consecutiveHealthFails = 0;
      // Successful health means process is alive — allow future crash restarts
      if (backendProc) {
        backendRestartAttempts = 0;
      }
      return;
    }
    consecutiveHealthFails += 1;
    console.warn(
      `[backend] health fail ${consecutiveHealthFails}/${HEALTH_FAILS_BEFORE_RESTART}`
    );
    if (consecutiveHealthFails >= HEALTH_FAILS_BEFORE_RESTART) {
      consecutiveHealthFails = 0;
      if (backendRestartAttempts < MAX_BACKEND_RESTARTS) {
        notifyRenderer('studsat:backend-status', {
          state: 'restarting',
          message: 'Backend unresponsive — restarting…',
        });
        // Force kill stuck process if any
        if (backendProc) {
          try {
            if (process.platform === 'win32') {
              spawn('taskkill', ['/pid', String(backendProc.pid), '/f', '/t']);
            } else {
              backendProc.kill('SIGKILL');
            }
          } catch (_) {
            /* ignore */
          }
          backendProc = null;
        }
        backendRestartAttempts += 1;
        spawnBackend();
      } else {
        notifyRenderer('studsat:backend-status', {
          state: 'err',
          message: 'Backend offline',
        });
      }
    }
  }, HEALTH_POLL_MS);
}

function stopHealthWatchdog() {
  if (healthTimer) {
    clearInterval(healthTimer);
    healthTimer = null;
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: 'STUDSAT Ground Station',
    backgroundColor: '#0b0f14',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  if (isDev) {
    mainWindow.loadURL(VITE_DEV_URL).catch(() => {
      mainWindow.loadURL(
        `data:text/html,<h2 style="font-family:sans-serif;color:#eee;background:#111;padding:2rem">` +
          `Start Vite first: <code>cd frontend && npm run dev</code></h2>`
      );
    });
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    const indexHtml = app.isPackaged
      ? path.join(process.resourcesPath, 'frontend', 'index.html')
      : path.join(repoRoot(), 'frontend', 'dist', 'index.html');
    mainWindow.loadFile(indexHtml);
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// Renderer can request a manual backend restart (Settings / recovery)
ipcMain.handle('studsat:restart-backend', async () => {
  if (app.isQuitting) return { ok: false };
  backendRestartAttempts = 0;
  if (backendProc) {
    try {
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', String(backendProc.pid), '/f', '/t']);
      } else {
        backendProc.kill('SIGTERM');
      }
    } catch (_) {
      /* ignore */
    }
    backendProc = null;
  }
  spawnBackend();
  try {
    await waitForHealth(15000);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

app.whenReady().then(async () => {
  spawnBackend();
  try {
    const body = await waitForHealth();
    console.log('[backend] healthy:', body);
    backendRestartAttempts = 0;
  } catch (err) {
    console.error('[backend] health failed:', err.message);
  }
  createWindow();
  startHealthWatchdog();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  killBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  killBackend();
});
