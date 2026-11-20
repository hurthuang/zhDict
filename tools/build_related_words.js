// 產生 globalPlugins/moeDict/related_words.txt：每個字最常用的詞語（只取這個字讀本音的詞）
//
// 資料來源：
//   - 小麥注音詞庫（McBopomofoWeb，MIT）：詞、讀音、常用程度
//   - 萌典詞目清單 https://www.moedict.tw/a/index.json（教育部國語辭典）：只留真的是詞的
//
// 用法：node tools/build_related_words.js <McBopomofoWeb 資料夾> <萌典 index.json>
//   McBopomofoWeb 要先 build 過（用 dist/src 底下的檔案）
//
// 本音：這個字在常用詞裡最常讀的音。詞裡讀輕聲、或「一」「不」變調的，同一個音就算本音。

const fs = require("fs");
const path = require("path");

const [mcDir, indexPath] = process.argv.slice(2);
if (!mcDir || !indexPath) {
  console.error("用法：node tools/build_related_words.js <McBopomofoWeb 資料夾> <萌典 index.json>");
  process.exit(1);
}

const PER_CHAR = 40; // 每個字最多存幾個詞
const MIN_LEN = 2;
const MAX_LEN = 4;
const SANDHI = new Set(["一", "不"]);

// WebData.js 是 `const source = \`{...}\`; exports.webData = JSON.parse(source);`
// 同一個讀音的鍵會出現不只一次，JSON.parse 只留最後一筆，所以自己逐筆讀 source。
const webSrc = fs.readFileSync(path.resolve(mcDir, "dist/src/McBopomofo/WebData.js"), "utf8")
  .replace("exports.webData = JSON.parse(source);", "return source;");
const source = new Function("exports", webSrc)({});
const pairs = [];
for (const m of source.matchAll(/("(?:[^"\\]|\\.)*"):("(?:[^"\\]|\\.)*")/g)) {
  pairs.push([JSON.parse(m[1]), JSON.parse(m[2])]);
}
const { BopomofoSyllable } = require(path.resolve(mcDir, "dist/src/Mandarin"));
const dict = new Set(JSON.parse(fs.readFileSync(indexPath, "utf8")));

const HAN = /^[㐀-鿿豈-﫿]+$/;
const TONES = /[ˊˇˋ˙]/g;
const base = (s) => s.replace(TONES, "");

const decodeCache = new Map();
function decode(key) {
  if (decodeCache.has(key)) return decodeCache.get(key);
  let out = null;
  // 標點、假名等特殊鍵；注音編碼本身也可能以 _ 開頭（例如「再」是 _d），不能整批跳過
  const special = /^_(kana|punctuation|half|number|letter|numpad|ctrl)_/.test(key);
  if (key.length % 2 === 0 && !special) {
    out = [];
    for (let i = 0; i < key.length; i += 2) {
      out.push(BopomofoSyllable.FromAbsoluteOrderString(key.substring(i, i + 2)).composedString);
    }
  }
  decodeCache.set(key, out);
  return out;
}

// 單字各讀音的最高分 → 本音
const charReadings = new Map(); // 字 → Map(讀音 → 分數)
// 詞 → { score, readings[] }（同一個詞有不同讀音時取分數高的）
const words = new Map();

for (const [key, value] of pairs) {
  const readings = decode(key);
  if (!readings) continue;
  const t = value.split(" ");
  for (let i = 0; i + 1 < t.length; i += 2) {
    const w = t[i];
    const score = Number(t[i + 1]);
    if (!HAN.test(w)) continue;
    const chars = [...w];
    if (chars.length !== readings.length) continue;
    if (chars.length === 1) {
      const m = charReadings.get(w) || new Map();
      if (!m.has(readings[0]) || m.get(readings[0]) < score) m.set(readings[0], score);
      charReadings.set(w, m);
      continue;
    }
    if (chars.length < MIN_LEN || chars.length > MAX_LEN || !dict.has(w)) continue;
    const old = words.get(w);
    if (!old || old.score < score) words.set(w, { score, readings });
  }
}

// 本音：單字常用程度最高的讀音（小麥注音的分數是 log10 機率）。
// 最高分有兩個以上讀音同分（例如「了」）時，看哪個音在詞裡比較常用（依詞的常用程度加權，輕聲併到同一個音）。
// 小麥注音資料明顯不對的字在 OVERRIDE 指定。
const OVERRIDE = { 藉: "ㄐㄧㄝˋ" };
const weight = new Map(); // 字 → Map(無輕聲讀音 → 權重)
for (const [w, { score, readings }] of words) {
  [...w].forEach((ch, i) => {
    const r = readings[i].replace("˙", "");
    const m = weight.get(ch) || new Map();
    m.set(r, (m.get(r) || 0) + Math.pow(10, score));
    weight.set(ch, m);
  });
}
function argmax(m, keys) {
  let best = null;
  for (const r of keys || m.keys()) {
    const s = m.get(r) || 0;
    if (!best || s > best[1]) best = [r, s];
  }
  return best && best[0];
}
const mainReading = new Map();
for (const ch of new Set([...charReadings.keys(), ...weight.keys()])) {
  if (OVERRIDE[ch]) { mainReading.set(ch, OVERRIDE[ch]); continue; }
  const single = charReadings.get(ch);
  const used = weight.get(ch);
  let main = null;
  if (single) {
    const top = Math.max(...single.values());
    const ties = [...single].filter(([, s]) => s === top).map(([r]) => r.replace("˙", ""));
    main = ties.length > 1 && used ? argmax(used, ties) : ties[0];
  } else {
    main = argmax(used);
  }
  mainReading.set(ch, main);
}

function isMain(ch, r) {
  const main = mainReading.get(ch);
  if (!main) return false;
  if (r === main) return true;
  if (base(r) !== base(main)) return false;
  return r.includes("˙") || SANDHI.has(ch);
}

const byChar = new Map(); // 字 → [[詞, 分數]]
for (const [w, { score, readings }] of words) {
  const chars = [...w];
  const seen = new Set();
  chars.forEach((ch, i) => {
    if (seen.has(ch) || !isMain(ch, readings[i])) return;
    seen.add(ch);
    const list = byChar.get(ch) || [];
    list.push([w, score]);
    byChar.set(ch, list);
  });
}

const lines = [];
for (const ch of [...byChar.keys()].sort()) {
  const list = byChar.get(ch).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  lines.push(ch + "\t" + mainReading.get(ch) + "\t" + list.slice(0, PER_CHAR).map((x) => x[0]).join(" "));
}

const out = path.resolve(__dirname, "../globalPlugins/moeDict/related_words.txt");
fs.writeFileSync(out, lines.join("\n") + "\n", "utf8");
console.log(`詞 ${words.size}、字 ${lines.length}，寫到 ${out}（${fs.statSync(out).size} bytes）`);
