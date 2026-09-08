import latestChanges from "../../../data/changes/latest.json";

const categoryLabels = {
  addedPartitions: "Added partitions",
  addedRegions: "Added regions",
  changedPartitions: "Changed partitions",
  changedRegions: "Changed regions",
  removedPartitions: "Removed partitions",
  removedRegions: "Removed regions",
};

const historicalChanges = import.meta.glob("../../../data/changes/history/*.json", {
  eager: true,
  import: "default",
});

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function atomDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new Error(`Invalid change timestamp: ${value}`);
  }
  return date.toISOString();
}

function changeRuns() {
  return [
    ...Object.values(historicalChanges),
    latestChanges,
  ].filter((changes) => changes && typeof changes === "object");
}

function eventsFor(category) {
  const events = new Map();
  for (const changes of changeRuns()) {
    const timestamp = atomDate(changes.retrievedAt);
    for (const value of changes[category] || []) {
      const name = String(value);
      const id = `${timestamp}:${category}:${name}`;
      events.set(id, { id, name, timestamp });
    }
  }
  return [...events.values()].sort((a, b) =>
    b.timestamp.localeCompare(a.timestamp) || a.name.localeCompare(b.name),
  );
}

export function feedPath(category) {
  return `${import.meta.env.BASE_URL.replace(/\/$/, "")}/feeds/${category}.xml`;
}

export function renderAtomFeed(category, selfUrl) {
  const label = categoryLabels[category];
  if (!label) {
    throw new Error(`Unknown change category: ${category}`);
  }

  const events = eventsFor(category);
  const updated = events[0]?.timestamp || atomDate(latestChanges.retrievedAt);
  const feedId = new URL(selfUrl).href;
  const entries = events
    .map(
      (event) => `
  <entry>
    <id>${escapeXml(`${feedId}#${event.id}`)}</id>
    <title>${escapeXml(`${label}: ${event.name}`)}</title>
    <link href="${escapeXml(`${feedId}#${event.id}`)}" />
    <updated>${event.timestamp}</updated>
    <author><name>AWS Region Watch</name></author>
    <content type="text">${escapeXml(`${label}: ${event.name}`)}</content>
  </entry>`,
    )
    .join("");

  return `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>${escapeXml(feedId)}</id>
  <title>${escapeXml(`AWS Region Watch · ${label}`)}</title>
  <link href="${escapeXml(feedId)}" rel="self" />
  <link href="${escapeXml(new URL(import.meta.env.BASE_URL, new URL(selfUrl)).href)}" />
  <updated>${updated}</updated>
  <author><name>AWS Region Watch</name></author>${entries}
</feed>
`;
}
