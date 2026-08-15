#!/usr/bin/env node
'use strict';

/*
 * Claude Code status hook (Windows) for the YASB `claude_code` widget.
 *
 * Claude Code invokes this at each lifecycle event with the hook payload on
 * stdin. It maintains:
 *   - ~/.claude/statusbar/state.json       — the most-recently-active session
 *     (what the bar label itself shows), picked up instantly by the widget's
 *     QFileSystemWatcher.
 *   - ~/.claude/statusbar/state.d/<id>.json — one file per live session, for
 *     the widget's session-list popup. Removed on SessionEnd.
 *
 * Usage:  node lifecycle.js <event>
 *   event ∈ start | end | prompt | pre | post | notify | permreq | stop
 *
 * Per-session shape (state.json has the same shape, no sessionId nesting):
 *   { sessionId, state: idle|thinking|tool|permission, label, cwd, project,
 *     entrypoint, termProgram, startedAt, ts }
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const STATUSBAR_DIR = path.join(os.homedir(), '.claude', 'statusbar');
const STATE_FILE = path.join(STATUSBAR_DIR, 'state.json');
const SESSIONS_DIR = path.join(STATUSBAR_DIR, 'sessions.d');
const STATE_DIR = path.join(STATUSBAR_DIR, 'state.d');

// Per-session files older than this are almost certainly orphaned by a crash
// (SessionEnd never fired to remove them) rather than a real long-lived
// session; swept on 'start' so the list doesn't accumulate garbage forever.
const STALE_SESSION_SECS = 24 * 60 * 60;

function nowSec() {
  return Math.floor(Date.now() / 1000);
}

function ensureDirs() {
  fs.mkdirSync(SESSIONS_DIR, { recursive: true });
  fs.mkdirSync(STATE_DIR, { recursive: true });
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

function stateDirFile(id) {
  return path.join(STATE_DIR, sanitizeId(id) + '.json');
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

// Drop per-session files that are clearly orphaned (crashed session, no
// SessionEnd ever fired to clean up after itself).
function sweepStaleSessions() {
  try {
    const now = nowSec();
    for (const f of fs.readdirSync(STATE_DIR)) {
      if (!f.endsWith('.json')) continue;
      const p = path.join(STATE_DIR, f);
      try {
        const data = JSON.parse(fs.readFileSync(p, 'utf8'));
        if (now - (data.ts || 0) > STALE_SESSION_SECS) fs.unlinkSync(p);
      } catch {
        try { fs.unlinkSync(p); } catch {}
      }
    }
  } catch {}
}

// Atomic write: temp file + rename. On Windows the rename can transiently fail
// with EPERM/EACCES/EBUSY when a reader holds the target; retry, then fall back
// to a direct overwrite so the displayed state never goes stale.
function writeAtomic(file, obj) {
  const data = JSON.stringify(obj);
  const tmp = file + '.' + process.pid + '.tmp';
  try {
    fs.writeFileSync(tmp, data);
  } catch {
    return;
  }
  const transient = new Set(['EPERM', 'EACCES', 'EBUSY']);
  for (let attempt = 0; attempt < 10; attempt++) {
    try {
      fs.renameSync(tmp, file);
      return;
    } catch (err) {
      if (!transient.has(err.code) || attempt === 9) break;
      sleepMs(15);
    }
  }
  try { fs.writeFileSync(file, data); } catch {}
  try { fs.unlinkSync(tmp); } catch {}
}

function readState(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return {};
  }
}

// Persists state to both state.json (the bar label's "current session") and
// state.d/<id>.json (this session's row in the list popup). Carries
// cwd/startedAt forward when a given event omits them.
function setState(sessionId, state, label, startedAt, cwd) {
  const prev = readState(STATE_FILE);
  const resolvedCwd = cwd || prev.cwd || '';
  const out = {
    sessionId: sessionId || prev.sessionId || null,
    state,
    label: label || '',
    cwd: resolvedCwd,
    project: resolvedCwd ? path.basename(resolvedCwd) : (prev.project || ''),
    entrypoint: process.env.CLAUDE_CODE_ENTRYPOINT || prev.entrypoint || '',
    termProgram: process.env.TERM_PROGRAM || prev.termProgram || '',
    startedAt: startedAt != null ? startedAt : (prev.startedAt || 0),
    ts: nowSec(),
  };
  writeAtomic(STATE_FILE, out);
  if (sessionId) writeAtomic(stateDirFile(sessionId), out);
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
      sweepStaleSessions();
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

    case 'notify': {
      // Notification fires for lots of things (including "Claude is waiting
      // for your input" idle nudges) — only a genuine permission prompt should
      // park the icon on "awaiting permission"; anything else is ignored so a
      // routine idle nudge doesn't look like Claude is blocked on you.
      const type = String(input.notification_type || input.notificationType || '').toLowerCase();
      const message = String(input.message || '').toLowerCase();
      const isPermission = type === 'permission_prompt' ||
        message.includes('permission') || message.includes('approve') || message.includes('allow');
      if (!isPermission) break;
      setState(sessionId, 'permission', '', undefined, cwd);
      break;
    }

    case 'permreq': {
      // Desktop-app permission signal; not redundant with 'notify' (CLI-only).
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
        try { fs.unlinkSync(stateDirFile(sessionId)); } catch {}
      }
      if (countSessions() === 0) setState(sessionId, 'idle', '', 0, cwd);
      break;
    }

    default:
      break;
  }
}

main();
