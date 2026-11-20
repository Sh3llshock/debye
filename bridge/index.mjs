// Debye WhatsApp bridge (demo route): a linked device on a regular WhatsApp account.
//
//   inbound : every 1:1 message → POST {BACKEND_URL}/webhooks/wweb (JSON, HMAC-signed)
//   outbound: POST /send {to_e164, text}
//             POST /send-media {to_e164, path|base64, mime, caption, ptt, filename}
//   both directions carry  X-Wweb-Signature: sha256=<hex HMAC of the raw body with WWEB_SECRET>
//
// First start prints a QR code in the terminal and writes bridge/qr.png. Scan it on the phone:
// WhatsApp → Settings → Linked Devices → Link a Device. The session is kept in bridge/auth/.
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

import makeWASocket, {
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";
import pino from "pino";
import QRCode from "qrcode";
import qrTerminal from "qrcode-terminal";

const HERE = path.dirname(fileURLToPath(import.meta.url));
loadEnv([path.join(HERE, "..", ".env"), path.join(HERE, "..", "backend", ".env")]);

const SECRET = process.env.WWEB_SECRET || "";
const PORT = Number(process.env.WWEB_BRIDGE_PORT || 3010);
const BACKEND_URL = (process.env.WWEB_BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
const AUTH_DIR = path.join(HERE, "auth");
const QR_PNG = path.join(HERE, "qr.png");
const log = pino({ level: process.env.WWEB_LOG_LEVEL || "info" });

if (!SECRET) {
  log.warn("WWEB_SECRET is empty: requests are not signed (set it in .env for the demo)");
}

let sock = null;
let ready = false;
const seen = new Set();

// ------------------------------------------------------------------ helpers
function loadEnv(files) {
  for (const f of files) {
    let text;
    try {
      text = fs.readFileSync(f, "utf8");
    } catch {
      continue;
    }
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) continue;
      const i = line.indexOf("=");
      const key = line.slice(0, i).trim();
      const value = line.slice(i + 1).trim().replace(/^["']|["']$/g, "");
      if (key && value && !process.env[key]) process.env[key] = value;
    }
  }
}

function sign(body) {
  return "sha256=" + crypto.createHmac("sha256", SECRET).update(body).digest("hex");
}

function verify(body, header) {
  if (!SECRET) return true;
  if (!header) return false;
  const want = Buffer.from(sign(body));
  const got = Buffer.from(header);
  return want.length === got.length && crypto.timingSafeEqual(want, got);
}

function jidToE164(jid) {
  const digits = String(jid || "").split("@")[0].split(":")[0];
  return /^\d{6,15}$/.test(digits) ? `+${digits}` : null;
}

function e164ToJid(e164) {
  return `${String(e164).replace(/[^\d]/g, "")}@s.whatsapp.net`;
}

// The phone-number JID of a 1:1 sender (WhatsApp may address chats by LID instead).
function senderPhoneJid(key) {
  const candidates = [key.remoteJid, key.remoteJidAlt, key.senderPn, key.participantAlt, key.participantPn];
  return candidates.find((j) => typeof j === "string" && j.endsWith("@s.whatsapp.net")) || null;
}

function unwrap(message) {
  let m = message || {};
  for (let i = 0; i < 4; i++) {
    const inner =
      m.ephemeralMessage?.message ||
      m.viewOnceMessage?.message ||
      m.viewOnceMessageV2?.message ||
      m.documentWithCaptionMessage?.message;
    if (!inner) break;
    m = inner;
  }
  return m;
}

async function postBackend(payload) {
  const body = JSON.stringify(payload);
  const r = await fetch(`${BACKEND_URL}/webhooks/wweb`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-wweb-signature": sign(body) },
    body,
  });
  if (!r.ok) log.error({ status: r.status, text: (await r.text()).slice(0, 200) }, "backend rejected message");
}

// ------------------------------------------------------------------ inbound
async function handleMessage(msg) {
  const key = msg.key || {};
  if (key.fromMe) return;
  const remote = key.remoteJid || "";
  if (remote.endsWith("@g.us") || remote === "status@broadcast" || remote.endsWith("@newsletter")) return;
  if (remote.endsWith("@broadcast")) return;
  if (!key.id || seen.has(key.id)) return;
  seen.add(key.id);
  if (seen.size > 5000) seen.delete(seen.values().next().value);

  const phoneJid = senderPhoneJid(key);
  const from = jidToE164(phoneJid);
  if (!from) {
    log.warn({ remote }, "could not resolve the sender's phone number (LID without phone); ignored");
    return;
  }
  const m = unwrap(msg.message);
  let text = m.conversation || m.extendedTextMessage?.text || null;
  const media = [];
  const mediaNode =
    (m.audioMessage && ["audioMessage", m.audioMessage]) ||
    (m.imageMessage && ["imageMessage", m.imageMessage]) ||
    (m.documentMessage && ["documentMessage", m.documentMessage]) ||
    (m.videoMessage && ["videoMessage", m.videoMessage]) ||
    null;
  if (mediaNode) {
    const [kind, node] = mediaNode;
    text = text || node.caption || null;
    try {
      const buf = await downloadMediaMessage(msg, "buffer", {}, { logger: log, reuploadRequest: sock.updateMediaMessage });
      media.push({
        base64: buf.toString("base64"),
        mime: node.mimetype || "application/octet-stream",
        filename: node.fileName || null,
        ptt: kind === "audioMessage" ? Boolean(node.ptt) : undefined,
      });
    } catch (err) {
      log.error({ err: String(err) }, "media download failed");
    }
  }
  if (!text && media.length === 0) {
    log.info({ types: Object.keys(m) }, "unsupported message type ignored");
    return;
  }
  log.info({ from, id: key.id, text: text ? text.slice(0, 60) : null, media: media.map((x) => x.mime) }, "inbound");
  await postBackend({ from_e164: from, message_id: key.id, text, media, push_name: msg.pushName || null });
}

// ------------------------------------------------------------------ WhatsApp connection
async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  let version;
  try {
    ({ version } = await fetchLatestBaileysVersion());
  } catch {
    version = undefined;
  }
  sock = makeWASocket({
    auth: state,
    version,
    logger: log.child({ level: "warn" }),
    markOnlineOnConnect: false,
    syncFullHistory: false,
  });
  sock.ev.on("creds.update", saveCreds);
  sock.ev.on("connection.update", async (u) => {
    if (u.qr) {
      qrTerminal.generate(u.qr, { small: true });
      await QRCode.toFile(QR_PNG, u.qr, { width: 480, margin: 2 });
      log.info(`QR code written to ${QR_PNG}. Scan it: WhatsApp → Settings → Linked Devices → Link a Device`);
    }
    if (u.connection === "open") {
      ready = true;
      try {
        fs.rmSync(QR_PNG, { force: true });
      } catch {}
      log.info({ me: sock.user?.id }, "WhatsApp connected");
    }
    if (u.connection === "close") {
      ready = false;
      const code = u.lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        log.error("Logged out from the phone. Delete bridge/auth and restart to link again.");
        return;
      }
      log.warn({ code }, "connection closed, reconnecting in 2 s");
      setTimeout(() => connect().catch((e) => log.error({ err: String(e) }, "reconnect failed")), 2000);
    }
  });
  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;
    for (const msg of messages) {
      try {
        await handleMessage(msg);
      } catch (err) {
        log.error({ err: String(err) }, "inbound handling failed");
      }
    }
  });
}

// ------------------------------------------------------------------ outbound HTTP API
function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function reply(res, status, obj) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(obj));
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") return reply(res, 200, { ready, me: sock?.user?.id || null });
    if (req.method !== "POST" || !["/send", "/send-media"].includes(req.url)) return reply(res, 404, { error: "not found" });
    const raw = await readBody(req);
    if (!verify(raw, req.headers["x-wweb-signature"])) return reply(res, 401, { error: "bad signature" });
    if (!ready) return reply(res, 503, { error: "WhatsApp not connected (scan the QR code)" });
    const b = JSON.parse(raw || "{}");
    if (!b.to_e164) return reply(res, 400, { error: "to_e164 missing" });
    const jid = e164ToJid(b.to_e164);
    let content;
    if (req.url === "/send") {
      content = { text: String(b.text || "") };
    } else {
      const buf = b.base64 ? Buffer.from(b.base64, "base64") : fs.readFileSync(b.path);
      const mime = b.mime || "application/octet-stream";
      if (mime.startsWith("audio/")) content = { audio: buf, mimetype: b.ptt ? "audio/ogg; codecs=opus" : mime, ptt: Boolean(b.ptt) };
      else if (mime.startsWith("image/")) content = { image: buf, mimetype: mime, caption: b.caption || undefined };
      else content = { document: buf, mimetype: mime, fileName: b.filename || "file", caption: b.caption || undefined };
    }
    const sent = await sock.sendMessage(jid, content);
    log.info({ to: b.to_e164, id: sent?.key?.id, kind: req.url }, "sent");
    return reply(res, 200, { ok: true, id: sent?.key?.id || null });
  } catch (err) {
    log.error({ err: String(err) }, "send failed");
    return reply(res, 500, { error: String(err) });
  }
});

server.listen(PORT, "127.0.0.1", () => log.info(`bridge API on http://127.0.0.1:${PORT}, backend ${BACKEND_URL}`));
connect().catch((e) => {
  log.error({ err: String(e) }, "start failed");
  process.exit(1);
});
