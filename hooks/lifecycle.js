#!/usr/bin/env node
'use strict';

/*
 * Claude Code status hook (Windows) for the YASB `claude_code` widget.
 *
 * Claude Code invokes this at each lifecycle event with the hook payload on
 * stdin. It maintains a tiny state machine in ~/.claude/statusbar/state.json,
 * which the YASB widget reads instantly via a filesystem watcher.
 *
 * Usage:  node lifecycle.js <event>
 *   event ∈ start | end | prompt | pre | post | notify | stop
 *
 * state.json shape:
 *   { sessionId, state: idle|thinking|tool|permission, label, cwd, project,
 *     startedAt, ts }
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const STATUSBAR_DIR = path.join(os.homedir(), '.claude', 'statusbar');
const STATE_FILE = path.join(STATUSBAR_DIR, 'state.json');
const SESSIONS_DIR = path.join(STATUSBAR_DIR, 'sessions.d');

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
    raw = raw.replace(/^﻿/, '').trim();
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function sanitizeId(id) {
  return String(id || 'unknown').replace(/[^A-Za-z0-9._-]/g, '_').slice(0, 64) || 'unknown';
}

function sessionFile(id) {
  return path.join(SESSIONS_DIR, sanitizeId(id));
}

// Synchronous short sleep for this ephemeral hook process.
function sleepMs(ms) {
  try {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
  } catch {
    /* best-effort */
  }
}

// Remove orphaned temp files left by a failed rename in an earlier run.
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

// Atomic write: temp file + rename. On Windows the rename can transiently fail
// with EPERM/EACCES/EBUSY when a reader holds the target; retry, then fall back
// to a direct overwrite so the displayed state never goes stale.
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

// Persists state; carries cwd/startedAt forward when a given event omits them.
function setState(sessionId, state, label, startedAt, cwd) {
  const prev = readState();
  const resolvedCwd = cwd || prev.cwd || '';
  writeState({
    sessionId: sessionId || prev.sessionId || null,
    state,
    label: label || '',
    cwd: resolvedCwd,
    project: resolvedCwd ? path.basename(resolvedCwd) : (prev.project || ''),
    startedAt: startedAt != null ? startedAt : (prev.startedAt || 0),
    ts: nowSec(),
  });
}

function countSessions() {
  try {
    return fs.readdirSync(SESSIONS_DIR).length;
  } catch {
    return 0;
  }
}

function main() {
  const event = (process.argv[2] || '').toLowerCase();
  const input = readStdin();
  const sessionId = input.session_id || input.sessionId || null;
  const cwd = input.cwd || input.workingDirectory || null;

  switch (event) {
    case 'start': {
      ensureDirs();
      sweepTmp();
      if (sessionId) {
        try { fs.writeFileSync(sessionFile(sessionId), ''); } catch {}
      }
      setState(sessionId, 'idle', '', 0, cwd);
      break;
    }

    case 'prompt': {
      // A new turn begins: start the timer and show the thinking animation.
      setState(sessionId, 'thinking', '', nowSec(), cwd);
      break;
    }

    case 'pre': {
      // A tool is about to run; surface its name.
      const tool = input.tool_name || input.toolName || 'tool';
      setState(sessionId, 'tool', tool, undefined, cwd);
      break;
    }

    case 'post': {
      // Tool finished; back to thinking until the turn stops.
      setState(sessionId, 'thinking', '', undefined, cwd);
      break;
    }

    case 'permreq':
    case 'notify': {
      // Waiting on the user (permission prompt / idle notification).
      setState(sessionId, 'permission', '', undefined, cwd);
      break;
    }

    case 'stop': {
      // Turn complete: back to idle and clear the timer.
      setState(sessionId, 'idle', '', 0, cwd);
      break;
    }

    case 'end': {
      if (sessionId) {
        try { fs.unlinkSync(sessionFile(sessionId)); } catch {}
      }
      if (countSessions() === 0) setState(sessionId, 'idle', '', 0, cwd);
      break;
    }

    default:
      break;
  }
}

main();
