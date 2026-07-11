import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const siteDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const distDir = path.join(siteDir, "dist");
const siteOrigin = "https://irigate.io";

const htmlRoutes = [
  { route: "/", file: "index.html", canonical: `${siteOrigin}/`, jsonLdType: "SoftwareApplication" },
  { route: "/benchmarks/", file: "benchmarks/index.html" },
  { route: "/docs/", file: "docs/index.html" },
  { route: "/docs/agent-selection/", file: "docs/agent-selection/index.html" },
  { route: "/docs/configuration/", file: "docs/configuration/index.html" },
  { route: "/docs/faq/", file: "docs/faq/index.html", jsonLdType: "FAQPage" },
  { route: "/docs/getting-started/", file: "docs/getting-started/index.html" },
  { route: "/docs/operations/", file: "docs/operations/index.html" },
  { route: "/docs/safety/", file: "docs/safety/index.html" },
].map((entry) => ({ ...entry, canonical: entry.canonical ?? `${siteOrigin}${entry.route}` }));

const requiredFiles = [
  "CNAME",
  "favicon.svg",
  "logo.svg",
  "logo-mark.svg",
  "robots.txt",
  "sitemap-index.xml",
  "sitemap-0.xml",
  "llms.txt",
  "og-default.png",
];

const expectedLlmsSections = ["Docs", "Evidence", "Source", "Optional"];
const expectedLlmsSummary =
  "> Irigate is a loopback-only local MCP broker for developers running multiple AI coding agents with selected stdio MCP servers.";
const expectedLlmsBoundary =
  "Current measurements support Context7 process and memory consolidation for identical contexts; they do not establish a latency improvement.";

const failures = [];

function fail(message) {
  failures.push(message);
}

async function readText(filePath) {
  return readFile(filePath, "utf8");
}

function assertExists(relativePath) {
  if (!existsSync(path.join(distDir, relativePath))) {
    fail(`Missing built file: ${relativePath}`);
  }
}

function countMatches(text, regex) {
  return [...text.matchAll(regex)].length;
}

function decodeAttribute(value) {
  return value
    .replaceAll("&amp;", "&")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">");
}

function attributesFromTag(tag) {
  const attributes = new Map();
  const attributePattern = /([:\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
  for (const match of tag.matchAll(attributePattern)) {
    const [, name, doubleQuoted, singleQuoted, bare] = match;
    attributes.set(name.toLowerCase(), decodeAttribute(doubleQuoted ?? singleQuoted ?? bare ?? ""));
  }
  return attributes;
}

function exactlyOne(text, regex, label, route) {
  const count = countMatches(text, regex);
  if (count !== 1) {
    fail(`${route} expected exactly one ${label}, found ${count}`);
  }
}

function builtPathForRootRelative(rawUrl) {
  const parsed = new URL(rawUrl, siteOrigin);
  const pathname = parsed.pathname;
  if (pathname.endsWith("/")) {
    return path.join(distDir, pathname.slice(1), "index.html");
  }
  return path.join(distDir, pathname.slice(1));
}

function assertLocalSiteUrlResolves(url, source) {
  const parsed = new URL(url);
  if (parsed.origin !== siteOrigin) return;
  const builtPath = builtPathForRootRelative(parsed.pathname);
  if (!existsSync(builtPath)) {
    fail(`${source} references ${url}, but ${path.relative(distDir, builtPath)} does not exist`);
  }
}

function isAllowedLlmsUrl(url) {
  const parsed = new URL(url);
  if (parsed.protocol !== "https:") return false;
  if (parsed.origin === siteOrigin) return true;
  if (parsed.origin !== "https://github.com") return false;
  if (parsed.pathname === "/irigate/irigate-mcp-proxy") return true;
  return /^\/irigate\/irigate-mcp-proxy\/blob\/main\/(README\.md|IMPLEMENTATION\.md|MARKET-RESEARCH\.md|scripts\/benchmark\.py)$/.test(
    parsed.pathname,
  );
}

function jsonLdTypes(value) {
  const values = Array.isArray(value) ? value : [value];
  const types = [];
  for (const item of values) {
    if (!item || typeof item !== "object") continue;
    const type = item["@type"];
    if (Array.isArray(type)) types.push(...type);
    else if (typeof type === "string") types.push(type);
    if (Array.isArray(item["@graph"])) types.push(...jsonLdTypes(item["@graph"]));
  }
  return types;
}

function extractJsonLd(html, route) {
  const blocks = [];
  const scriptPattern = /<script\b[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  for (const match of html.matchAll(scriptPattern)) {
    try {
      blocks.push(JSON.parse(match[1].trim()));
    } catch (error) {
      fail(`${route} has invalid JSON-LD: ${error.message}`);
    }
  }
  return blocks;
}

function assertPngDimensions(buffer, expectedWidth, expectedHeight, relativePath) {
  const signature = "89504e470d0a1a0a";
  if (buffer.subarray(0, 8).toString("hex") !== signature) {
    fail(`${relativePath} is not a PNG file`);
    return;
  }
  const width = buffer.readUInt32BE(16);
  const height = buffer.readUInt32BE(20);
  if (width !== expectedWidth || height !== expectedHeight) {
    fail(`${relativePath} expected ${expectedWidth}x${expectedHeight}, found ${width}x${height}`);
  }
}

async function verifyPackageManager() {
  const packageJson = JSON.parse(await readText(path.join(siteDir, "package.json")));
  const packageManager = packageJson.packageManager;
  if (!/^pnpm@\d+\.\d+\.\d+$/.test(packageManager ?? "")) {
    fail(`package.json packageManager must be pinned as pnpm major.minor.patch, found ${JSON.stringify(packageManager)}`);
    return;
  }

  const lockfile = await readText(path.join(siteDir, "pnpm-lock.yaml"));
  const header = lockfile.split("\nimporters:\n", 1)[0];
  const lockVersion = header.match(/^lockfileVersion:\s*'([^']+)'/m)?.[1];
  if (lockVersion !== "9.0") {
    fail(`pnpm-lock.yaml lockfileVersion must be '9.0', found ${JSON.stringify(lockVersion)}`);
  }
  const lockPnpm = header.match(/^pnpm:\s*([^\n]+)/m)?.[1]?.trim();
  if (lockPnpm && lockPnpm !== packageManager.replace("pnpm@", "")) {
    fail(`pnpm-lock.yaml pnpm line ${lockPnpm} does not match packageManager ${packageManager}`);
  }
}

async function verifyRequiredFiles() {
  for (const route of htmlRoutes) assertExists(route.file);
  for (const file of requiredFiles) assertExists(file);

  const cname = await readText(path.join(distDir, "CNAME"));
  if (cname !== "irigate.io\n") {
    fail("CNAME must be exactly 'irigate.io\\n'");
  }

  const ogImage = await readFile(path.join(distDir, "og-default.png"));
  assertPngDimensions(ogImage, 1200, 630, "og-default.png");
}

async function verifyHtmlRoutes() {
  const seenTitles = new Map();
  const seenCanonicals = new Map();

  for (const entry of htmlRoutes) {
    const html = await readText(path.join(distDir, entry.file));
    exactlyOne(html, /<title\b[^>]*>[\s\S]*?<\/title>/gi, "title", entry.route);
    exactlyOne(html, /<link\b(?=[^>]*\brel=["']canonical["'])[^>]*>/gi, "canonical", entry.route);
    exactlyOne(html, /<meta\b(?=[^>]*\bname=["']description["'])[^>]*>/gi, "description", entry.route);
    exactlyOne(html, /<h1\b[^>]*>[\s\S]*?<\/h1>/gi, "H1", entry.route);

    if (/noindex/i.test(html)) fail(`${entry.route} must not contain noindex`);
    const title = html.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i)?.[1]?.trim();
    if (title) {
      if (seenTitles.has(title)) fail(`${entry.route} duplicates title with ${seenTitles.get(title)}: ${title}`);
      seenTitles.set(title, entry.route);
    }

    const canonicalTag = html.match(/<link\b(?=[^>]*\brel=["']canonical["'])[^>]*>/i)?.[0];
    const canonical = canonicalTag ? attributesFromTag(canonicalTag).get("href") : undefined;
    if (canonical !== entry.canonical) {
      fail(`${entry.route} canonical expected ${entry.canonical}, found ${JSON.stringify(canonical)}`);
    }
    if (canonical) {
      if (seenCanonicals.has(canonical)) fail(`${entry.route} duplicates canonical with ${seenCanonicals.get(canonical)}: ${canonical}`);
      seenCanonicals.set(canonical, entry.route);
    }

    verifyRootRelativeReferences(html, entry.route);
    verifyImagesHaveAlt(html, entry.route);
    verifyThemeControls(html, entry.route);
    verifyJsonLd(html, entry);
  }
}

function verifyRootRelativeReferences(html, route) {
  const tagPattern = /<(a|link|script|img|source)\b[^>]*>/gi;
  for (const match of html.matchAll(tagPattern)) {
    const tag = match[0];
    const attrs = attributesFromTag(tag);
    for (const attr of ["href", "src", "srcset"]) {
      const value = attrs.get(attr);
      if (!value) continue;
      const candidates = attr === "srcset" ? value.split(",").map((item) => item.trim().split(/\s+/, 1)[0]) : [value];
      for (const candidate of candidates) {
        if (!candidate.startsWith("/") || candidate.startsWith("//")) continue;
        const pathname = candidate.split(/[?#]/, 1)[0];
        if (pathname.startsWith("/irigate-mcp-proxy/")) {
          fail(`${route} ${attr}=${JSON.stringify(candidate)} uses the repository base path`);
          continue;
        }
        const builtPath = builtPathForRootRelative(pathname);
        if (!existsSync(builtPath)) {
          fail(`${route} ${attr}=${JSON.stringify(candidate)} does not resolve to a built file or endpoint`);
        }
      }
    }
  }
}

function verifyImagesHaveAlt(html, route) {
  for (const match of html.matchAll(/<img\b[^>]*>/gi)) {
    const attrs = attributesFromTag(match[0]);
    if (!attrs.has("alt")) {
      fail(`${route} image is missing alt: ${match[0]}`);
    }
  }
}

function verifyThemeControls(html, route) {
  const head = html.match(/<head\b[^>]*>([\s\S]*?)<\/head>/i)?.[1] ?? "";
  if (!head.includes("irigate.theme") || !head.includes("root.dataset.theme")) {
    fail(`${route} is missing the early theme bootstrap in <head>`);
  }
  for (const value of ["light", "dark", "system"]) {
    if (!html.includes(`data-theme-choice="${value}"`)) {
      fail(`${route} is missing the ${value} theme control`);
    }
  }
  if (/<script\b(?=[^>]*\bsrc=)/i.test(html)) {
    fail(`${route} must not depend on external or bundled client-side framework script files`);
  }
}

function verifyJsonLd(html, entry) {
  const blocks = extractJsonLd(html, entry.route);
  if (entry.jsonLdType) {
    if (blocks.length !== 1) {
      fail(`${entry.route} expected exactly one JSON-LD block, found ${blocks.length}`);
    }
    const types = blocks.flatMap(jsonLdTypes);
    if (!types.includes(entry.jsonLdType)) {
      fail(`${entry.route} JSON-LD must include @type ${entry.jsonLdType}, found ${types.join(", ") || "none"}`);
    }
    if (!html.includes("application/ld+json")) {
      fail(`${entry.route} JSON-LD script must use application/ld+json`);
    }
  } else if (blocks.length !== 0 || html.includes("application/ld+json")) {
    fail(`${entry.route} must not include JSON-LD`);
  }
}

async function verifyHomepageText() {
  const html = await readText(path.join(distDir, "index.html"));
  for (const text of [
    "loopback Streamable HTTP",
    "selected stdio MCP servers",
    "upstream-throttled",
    "does not support a latency improvement claim",
  ]) {
    if (!html.includes(text)) {
      fail(`Homepage is missing required boundary/evidence text: ${text}`);
    }
  }
}

async function verifyLlms() {
  const llms = await readText(path.join(distDir, "llms.txt"));
  if (countMatches(llms, /^# /gm) !== 1) fail("llms.txt must contain exactly one H1");
  if (!llms.includes(expectedLlmsSummary)) fail("llms.txt is missing the required Irigate summary blockquote");
  if (!llms.includes(expectedLlmsBoundary)) fail("llms.txt is missing the benchmark boundary sentence");
  if (llms.includes("GITHUB-PAGES")) fail("llms.txt must not reference GITHUB-PAGES.md");

  const sections = [...llms.matchAll(/^## (.+)$/gm)].map((match) => match[1]);
  if (JSON.stringify(sections) !== JSON.stringify(expectedLlmsSections)) {
    fail(`llms.txt sections expected ${expectedLlmsSections.join(", ")}, found ${sections.join(", ")}`);
  }

  const urls = [...llms.matchAll(/\[[^\]]+\]\((https:\/\/[^)\s]+)\)/g)].map((match) => match[1]);
  const seen = new Set();
  for (const url of urls) {
    if (seen.has(url)) fail(`llms.txt duplicates URL: ${url}`);
    seen.add(url);
    if (!isAllowedLlmsUrl(url)) fail(`llms.txt URL is outside the approved allowlist: ${url}`);
    assertLocalSiteUrlResolves(url, "llms.txt");
  }
}

async function verifySitemapAndRobots() {
  const robots = await readText(path.join(distDir, "robots.txt"));
  const expectedSitemap = `${siteOrigin}/sitemap-index.xml`;
  if (!new RegExp(`^Sitemap:\\s*${expectedSitemap.replaceAll(".", "\\.")}$`, "m").test(robots)) {
    fail(`robots.txt must target ${expectedSitemap}`);
  }

  const sitemapIndex = await readText(path.join(distDir, "sitemap-index.xml"));
  if (!sitemapIndex.includes(`<loc>${siteOrigin}/sitemap-0.xml</loc>`)) {
    fail("sitemap-index.xml must reference sitemap-0.xml");
  }

  const sitemap = await readText(path.join(distDir, "sitemap-0.xml"));
  const urls = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
  const expected = htmlRoutes.map((entry) => entry.canonical).sort();
  const actual = [...urls].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    fail(`sitemap-0.xml URLs expected ${expected.join(", ")}, found ${actual.join(", ")}`);
  }
  if (new Set(urls).size !== urls.length) fail("sitemap-0.xml contains duplicate URLs");
}

await verifyPackageManager();
await verifyRequiredFiles();
await verifyHtmlRoutes();
await verifyHomepageText();
await verifyLlms();
await verifySitemapAndRobots();

if (failures.length > 0) {
  console.error("Built-site verification failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log(`Built-site verification passed for ${htmlRoutes.length} HTML routes and ${requiredFiles.length} required assets/endpoints.`);
