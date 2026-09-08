import { defineConfig } from "astro/config";

export default defineConfig({
  site: process.env.SITE_URL || "https://cyruscook.github.io",
  base: process.env.BASE_PATH || undefined,
  output: "static",
});
