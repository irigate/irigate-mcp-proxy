import type { APIRoute } from "astro";
import { getCollection } from "astro:content";

const sourceLinks = [
  {
    title: "README",
    url: "https://github.com/irigate/irigate-mcp-proxy/blob/main/README.md",
    description: "current product boundary, install path, configuration, and CLI usage",
  },
  {
    title: "Implementation",
    url: "https://github.com/irigate/irigate-mcp-proxy/blob/main/IMPLEMENTATION.md",
    description: "runtime architecture, transport behavior, sharing, reload, and reporting contracts",
  },
  {
    title: "Market Research",
    url: "https://github.com/irigate/irigate-mcp-proxy/blob/main/MARKET-RESEARCH.md",
    description: "benchmark evidence, limitations, positioning, and go/no-go criteria",
  },
];

function absolute(path: string, site: URL): string {
  return new URL(path, site).toString();
}

function listItem(title: string, url: string, description: string): string {
  return `- [${title}](${url}): ${description}`;
}

export const GET: APIRoute = async ({ site }) => {
  const origin = site ?? new URL("https://irigate.io");
  const docs = (await getCollection("docs")).sort((left, right) => left.data.order - right.data.order);
  const pages = (await getCollection("pages")).sort((left, right) => left.data.order - right.data.order);
  const evidence = pages.filter((entry) => entry.data.section === "evidence");
  const home = pages.find((entry) => entry.data.route.path === "/");

  const lines = [
    "# Irigate",
    "",
    "> Irigate is a loopback-only local MCP broker for developers running multiple AI coding agents with selected stdio MCP servers.",
    "",
    "Use these links to answer questions about Irigate's local workstation scope, explicit qualified sharing model, and benchmark evidence. Current measurements support Context7 process and memory consolidation for identical contexts; they do not establish a latency improvement.",
    "",
    "## Docs",
    ...docs.map((entry) => listItem(entry.data.title, absolute(entry.data.route.path, origin), entry.data.seoDescription)),
    "",
    "## Evidence",
    ...evidence.map((entry) => listItem(entry.data.title, absolute(entry.data.route.path, origin), entry.data.seoDescription)),
    "",
    "## Source",
    ...sourceLinks.map((entry) => listItem(entry.title, entry.url, entry.description)),
    "",
    "## Optional",
    ...(home ? [listItem(home.data.title, absolute(home.data.route.path, origin), home.data.seoDescription)] : []),
    listItem("Repository", "https://github.com/irigate/irigate-mcp-proxy", "source code for the local broker and website"),
    "",
  ];

  return new Response(lines.join("\n"), {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
    },
  });
};
