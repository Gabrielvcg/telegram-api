import { copyFileSync, existsSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";

const distDir = process.env.OPENCLAW_DIST_DIR || "/app/dist";

const deliveryFunctionReplacement = `async function sendTelegramText(bot, chatId, text, runtime, opts) {
\tconst messageParams = buildTelegramSendParams({
\t\treplyToMessageId: opts?.replyToMessageId,
\t\treplyQuoteMessageId: opts?.replyQuoteMessageId,
\t\treplyQuoteText: opts?.replyQuoteText,
\t\treplyQuotePosition: opts?.replyQuotePosition,
\t\treplyQuoteEntities: opts?.replyQuoteEntities,
\t\tthread: opts?.thread,
\t\tsilent: opts?.silent
\t});
\tif (!text.trim()) throw new Error("Message must be non-empty for Telegram sends");
\tconst res = await sendTelegramWithThreadFallback({
\t\toperation: "sendMessage",
\t\truntime,
\t\tthread: opts?.thread,
\t\trequestParams: messageParams,
\t\tremoveNativeQuoteParam: removeTelegramNativeQuoteParam,
\t\tsend: (effectiveParams) => bot.api.sendMessage(chatId, text, {
\t\t\t...(opts?.replyMarkup ? { reply_markup: opts.replyMarkup } : {}),
\t\t\t...effectiveParams
\t\t})
\t});
\truntime.log?.("telegram sendMessage ok chat=" + chatId + " message=" + res.message_id);
\treturn res.message_id;
}
//#endregion
//#region extensions/telegram/src/bot/reply-threading.ts`;

const sendTextChunkReplacement = `const sendTelegramTextChunk = async (chunk, params) => {
\t\t\tconst messageParams = {
\t\t\t\t...params,
\t\t\t\t...(opts.silent === true ? { disable_notification: true } : {})
\t\t\t};
\t\t\treturn {
\t\t\t\tresult: await requestWithChatNotFound(() => api.sendMessage(chatId, chunk.text, messageParams), "message"),
\t\t\t\tacceptedParams: params
\t\t\t};
\t\t};
\t\tconst buildTextParams = (isLastChunk) => hasThreadParams || isLastChunk && replyMarkup ? {
\t\t\t...threadParams,
\t\t\t...(isLastChunk && replyMarkup ? { reply_markup: replyMarkup } : {})
\t\t} : void 0;`;

function listJsFiles(dir) {
  const entries = readdirSync(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...listJsFiles(fullPath));
      continue;
    }
    if (entry.isFile() && entry.name.endsWith(".js")) files.push(fullPath);
  }
  return files;
}

function patchFile(file, patcher) {
  const original = readFileSync(file, "utf8");
  const result = patcher(original, file);
  if (!result) return "missing";
  if (result.source === original) {
    console.log(`[openclaw-patch] already applied: ${file}`);
    return "already";
  }
  const backup = `${file}.orig`;
  if (!existsSync(backup)) copyFileSync(file, backup);
  writeFileSync(file, result.source);
  console.log(`[openclaw-patch] patched: ${file}`);
  return "patched";
}

function patchDeliverySender(source) {
  if (source.includes("bot.api.sendMessage(chatId, text") && source.includes("telegram sendMessage ok chat=")) {
    return { source };
  }
  const pattern = /async function sendTelegramText\(bot, chatId, text, runtime, opts\) \{[\s\S]*?\n\}\n\/\/#endregion\n\/\/#region extensions\/telegram\/src\/bot\/reply-threading\.ts/;
  if (!pattern.test(source)) return null;
  return { source: source.replace(pattern, deliveryFunctionReplacement) };
}

function patchDirectTextSender(source, file) {
  if (
    source.includes("async function sendMessageTelegram(to, text, opts)") &&
    source.includes("api.sendMessage(chatId, chunk.text, messageParams)") &&
    source.includes('operation: "sendMessage",\n\t\t\t\tdeliveryKind: "text"')
  ) {
    return { source };
  }
  const functionMarker = "async function sendMessageTelegram(to, text, opts) {";
  const functionStart = source.indexOf(functionMarker);
  if (functionStart === -1) return null;
  const sendChunkMarker = "\t\tconst sendTelegramTextChunk = async (chunk, params) => {";
  const textChunksMarker = "\t\tconst sendTelegramTextChunks = async (chunks, context) => {";
  const sendChunkStart = source.indexOf(sendChunkMarker, functionStart);
  const textChunksStart = source.indexOf(textChunksMarker, sendChunkStart);
  if (sendChunkStart === -1 || textChunksStart === -1) {
    throw new Error(`${file}: text sender markers were not found`);
  }
  let patched = `${source.slice(0, sendChunkStart)}\t\t${sendTextChunkReplacement}\n${source.slice(textChunksStart)}`;
  const logMarker = 'operation: "sendRichMessage",\n\t\t\t\tdeliveryKind: "text",';
  const logStart = patched.indexOf(logMarker, sendChunkStart);
  if (logStart === -1) {
    throw new Error(`${file}: text send log marker was not found`);
  }
  patched = `${patched.slice(0, logStart)}operation: "sendMessage",\n\t\t\t\tdeliveryKind: "text",${patched.slice(logStart + logMarker.length)}`;
  return { source: patched };
}

function countMatches(statuses) {
  return statuses.filter((status) => status === "patched" || status === "already").length;
}

if (!existsSync(distDir) || !statSync(distDir).isDirectory()) {
  throw new Error(`OpenClaw dist directory not found: ${distDir}`);
}

const files = listJsFiles(distDir);
const deliveryStatuses = files.map((file) => patchFile(file, patchDeliverySender));
const directTextStatuses = files.map((file) => patchFile(file, patchDirectTextSender));

if (countMatches(deliveryStatuses) === 0) {
  throw new Error("Could not find OpenClaw Telegram delivery sender to patch");
}
if (countMatches(directTextStatuses) === 0) {
  throw new Error("Could not find OpenClaw Telegram direct text sender to patch");
}

console.log("[openclaw-patch] Telegram text delivery uses plain sendMessage");
