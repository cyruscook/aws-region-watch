const byId = (id) => document.getElementById(id);
const regionElements = [...document.querySelectorAll(".region")];
const partitionElements = [...document.querySelectorAll(".partition")];

const regions = regionElements.map((element) => {
  const partition = element.closest(".partition");
  return {
    element,
    partition: element.dataset.partition,
    unpublished: element.dataset.unpublished === "true",
    searchableText: `${element.textContent} ${partition.querySelector(".partition__facts").textContent}`.toLowerCase(),
  };
});

const state = { query: "", partition: "", unpublishedOnly: false };

function render() {
  const visibleByPartition = new Map(partitionElements.map((element) => [element.dataset.partition, 0]));

  for (const region of regions) {
    const visible =
      (!state.partition || region.partition === state.partition) &&
      (!state.unpublishedOnly || region.unpublished) &&
      (!state.query || region.searchableText.includes(state.query));
    region.element.hidden = !visible;
    if (visible) visibleByPartition.set(region.partition, visibleByPartition.get(region.partition) + 1);
  }

  let visibleRegions = 0;
  let visiblePartitions = 0;
  for (const partition of partitionElements) {
    const count = visibleByPartition.get(partition.dataset.partition);
    partition.hidden = count === 0;
    partition.querySelector("[data-region-count]").textContent = `${count} region${count === 1 ? "" : "s"}`;
    visibleRegions += count;
    if (count) visiblePartitions += 1;
  }

  byId("result-count").textContent = `${visibleRegions} regions across ${visiblePartitions} partitions`;
  byId("empty-state").hidden = visibleRegions !== 0;
}

byId("search").addEventListener("input", (event) => {
  state.query = event.target.value.trim().toLowerCase();
  render();
});

byId("partition-filter").addEventListener("change", (event) => {
  state.partition = event.target.value;
  render();
});

byId("unpublished-only").addEventListener("change", (event) => {
  state.unpublishedOnly = event.target.checked;
  render();
});
