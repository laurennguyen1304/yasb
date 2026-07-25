#!/usr/bin/env node
'use strict';

/*
 * Claude Status Bar (Windows) — lifecycle hook.
 *
 * Claude Code invokes this script at each lifecycle event and passes the hook
 * payload as JSON on stdin. We translate events into a tiny state machine and
 * write ~/.claude/statusbar/state.json, which the tray app polls. Active
 * sessions are tracked as files under sessions.d/ so the tray app knows when to
 * self-quit.
 *
 * Usage:  node lifecycle.js <event>
 *   event ∈ start | end | prompt | pre | post | notify | permreq | stop
 *
 * Must stay in sync with the C# reader (AppPaths.cs / StatusState.cs).
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

const STATUSBAR_DIR = path.join(os.homedir(), '.claude', 'statusbar');
const STATE_FILE = path.join(STATUSBAR_DIR, 'state.json');
const SESSIONS_DIR = path.join(STATUSBAR_DIR, 'sessions.d');
// The published tray exe sits next to this hooks/ folder: <root>/ClaudeStatusBar.exe
const APP_EXE = process.env.CLAUDE_STATUSBAR_EXE ||
  path.join(__dirname, '..', 'ClaudeStatusBar.exe');

const EXE_NAME = 'ClaudeStatusBar.exe';

function nowSec() {
  return Math.floor(Date.now() / 1000);
}

function ensureDirs() {
  fs.mkdirSync(SESSIONS_DIR, { recursive: true });
}

function readStdin() {
  try {
    let raw = fs.readFileSync(0, 'utf8');
    if (!raw) return {};
    // Strip a UTF-8 BOM if present and surrounding whitespace.
    raw = raw.replace(/^﻿/, '').trim();
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function sanitizeId(id) {
  return String(id || 'unknown')
    .replace(/[^A-Za-z0-9._-]/g, '_')
    .slice(0, 64) || 'unknown';
}

function sessionFile(id) {
  return path.join(SESSIONS_DIR, sanitizeId(id));
}

// Synchronous short sleep for this ephemeral hook process (no event loop work
// to yield to). Falls back to no delay if SharedArrayBuffer is unavailable.
function sleepMs(ms) {
  try {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
  } catch {
    /* best-effort */
  }
}

// Remove orphaned temp files left behind by a failed rename in an earlier run.
// Only sweeps files older than 5s so a sibling hook's in-flight temp is safe.
function sweepTmp() {
  try {
    const now = Date.now();
    for (const f of fs.readdirSync(STATUSBAR_DIR)) {
      if (!f.startsWith('state.json.') || !f.endsWith('.tmp')) continue;
      const p = path.join(STATUSBAR_DIR, f);
      try {
        if (now - fs.statSync(p).mtimeMs > 5000) fs.unlinkSync(p);
      } catch {}
    }
  } catch {}
}

// Atomic write: temp file + rename, so the poller never sees a half-written
// file. On Windows the rename can transiently fail with EPERM/EACCES/EBUSY when
// a reader (the status bar, antivirus) has the target open; retry briefly, then
// fall back to a direct overwrite so the displayed state never goes stale.
function writeState(obj) {
  ensureDirs();
  const data = JSON.stringify(obj);
  const tmp = STATE_FILE + '.' + process.pid + '.tmp';
  try {
    fs.writeFileSync(tmp, data);
  } catch {
    return;
  }
  const transient = new Set(['EPERM', 'EACCES', 'EBUSY']);
  for (let attempt = 0; attempt < 10; attempt++) {
    try {
      fs.renameSync(tmp, STATE_FILE);
      return;
    } catch (err) {
      if (!transient.has(err.code) || attempt === 9) break;
      sleepMs(15);
    }
  }
  // Rename kept failing: write directly and drop the temp file.
  try { fs.writeFileSync(STATE_FILE, data); } catch {}
  try { fs.unlinkSync(tmp); } catch {}
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch {
    return {};
  }
}

function setState(sessionId, state, label, startedAt) {
  const prev = readState();
  writeState({
    sessionId: sessionId || prev.sessionId || null,
    state,
    label: label || '',
    startedAt: startedAt != null ? startedAt : (prev.startedAt || 0),
    ts: nowSec(),
  });
}

function isAppRunning() {
  try {
    const out = spawnSync('tasklist', ['/FI', `IMAGENAME eq ${EXE_NAME}`, '/NH'], {
      encoding: 'utf8',
      windowsHide: true,
    });
    return (out.stdout || '').includes(EXE_NAME);
  } catch {
    return false;
  }
}

function launchApp() {
  try {
    if (!fs.existsSync(APP_EXE)) return;
    const child = spawn(APP_EXE, [], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
    });
    child.unref();
  } catch {
    /* best-effort launch; the app's single-instance mutex handles dupes */
  }
}

function countSessions() {
  try {
    return fs.readdirSync(SESSIONS_DIR).length;
  } catch {
    return 0;
  }
}

function clearSessions() {
  try {
    for (const f of fs.readdirSync(SESSIONS_DIR)) {
      try { fs.unlinkSync(path.join(SESSIONS_DIR, f)); } catch {}
    }
  } catch {}
}

function main() {
  const event = (process.argv[2] || '').toLowerCase();
  const input = readStdin();
  const sessionId = input.session_id || input.sessionId || null;

  switch (event) {
    case 'start': {
      ensureDirs();
      sweepTmp();
      // If the app isn't running, any leftover session files are stale (e.g.
      // after a crash); clear them so the app doesn't think work is ongoing.
      if (!isAppRunning()) clearSessions();
      if (sessionId) {
        try { fs.writeFileSync(sessionFile(sessionId), ''); } catch {}
      }
      setState(sessionId, 'idle', '', 0);
      launchApp();
      break;
    }

    case 'prompt': {
      // A new turn begins: start the timer and show the thinking animation.
      setState(sessionId, 'thinking', '', nowSec());
      break;
    }

    case 'pre': {
      // A tool is about to run; surface its name.
      const tool = input.tool_name || input.toolName || 'tool';
      setState(sessionId, 'tool', tool, undefined);
      break;
    }

    case 'post': {
      // Tool finished; back to thinking until the turn stops.
      setState(sessionId, 'thinking', '', undefined);
      break;
    }

    case 'permreq':
    case 'notify': {
      // Waiting on the user (permission prompt / idle notification).
      setState(sessionId, 'permission', '', undefined);
      break;
    }

    case 'stop': {
      // Turn complete: back to idle and clear the timer.
      setState(sessionId, 'idle', '', 0);
      break;
    }

    case 'end': {
      if (sessionId) {
        try { fs.unlinkSync(sessionFile(sessionId)); } catch {}
      }
      // If that was the last session, mark idle so a lingering app shows rest.
      if (countSessions() === 0) setState(sessionId, 'idle', '', 0);
      break;
    }

    default:
      // Unknown event: do nothing rather than corrupt state.
      break;
  }
}

main();
