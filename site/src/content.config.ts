import { defineCollection } from "astro:content";
import { glob } from "astro/loaders";
import { z } from "astro/zod";

const routeSchema = z.object({
  path: z.string().startsWith("/"),
  slug: z.string(),
});

const baseSchema = z.object({
  title: z.string().min(1),
  description: z.string().min(1),
  seoDescription: z.string().min(1).max(180),
  order: z.number().int().nonnegative(),
  route: routeSchema,
});

const pages = defineCollection({
  loader: glob({ pattern: "*.mdx", base: "./src/content/pages" }),
  schema: baseSchema.extend({
    section: z.enum(["landing", "evidence"]),
  }),
});

const docs = defineCollection({
  loader: glob({ pattern: "*.md", base: "./src/content/docs" }),
  schema: baseSchema.extend({
    navTitle: z.string().min(1),
    source: z.url().optional(),
  }),
});

export const collections = { pages, docs };
