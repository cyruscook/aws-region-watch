import { renderAtomFeed } from "../../lib/atom.js";

export function GET({ site, url }) {
  return new Response(renderAtomFeed("changedPartitions", new URL(url.pathname, site).href), {
    headers: { "Content-Type": "application/atom+xml; charset=utf-8" },
  });
}
