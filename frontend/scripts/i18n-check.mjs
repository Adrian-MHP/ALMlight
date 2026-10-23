// Checks that every interface text passed to tx() has a German translation (and lists unused ones).
//   node scripts/i18n-check.mjs            -> exit 1 when translations are missing
//   node scripts/i18n-check.mjs --keys     -> print the missing keys as JSON
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../src");
const files = [];
(function walk(d) {
  for (const f of fs.readdirSync(d)) {
    const p = path.join(d, f);
    if (fs.statSync(p).isDirectory()) walk(p);
    else if (/\.(tsx?|ts)$/.test(f) && !p.includes(`${path.sep}locales${path.sep}`)) files.push(p);
  }
})(root);

const used = new Map();
for (const file of files) {
  const src = ts.createSourceFile(file, fs.readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  (function visit(n) {
    if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "tx" && n.arguments.length) {
      const a = n.arguments[0];
      if (ts.isStringLiteral(a) || ts.isNoSubstitutionTemplateLiteral(a)) {
        if (!used.has(a.text)) used.set(a.text, path.relative(root, file));
      }
    }
    ts.forEachChild(n, visit);
  })(src);
}

// the dictionary is a plain object literal of string keys
const dictSrc = ts.createSourceFile("de.ts", fs.readFileSync(path.join(root, "locales/de.ts"), "utf8"), ts.ScriptTarget.Latest, true);
const known = new Set();
(function visit(n) {
  if (ts.isPropertyAssignment(n) && (ts.isStringLiteral(n.name) || ts.isIdentifier(n.name))) known.add(n.name.text);
  ts.forEachChild(n, visit);
})(dictSrc);

const missing = [...used.keys()].filter((k) => !known.has(k)).sort();
const unused = [...known].filter((k) => !used.has(k));
if (process.argv.includes("--keys")) {
  console.log(JSON.stringify(missing, null, 1));
  process.exit(0);
}
console.log(`i18n: ${used.size} texts, ${known.size} German translations, ${missing.length} missing, ${unused.length} unused`);
if (missing.length) {
  for (const k of missing.slice(0, 40)) console.log(`  missing: ${JSON.stringify(k)} (${used.get(k)})`);
  process.exit(1);
}
