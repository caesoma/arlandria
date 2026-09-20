const [maj, min] = process.versions.node.split(".").map(Number);
if (maj < 22 || (maj === 22 && min < 19) || maj > 24) {
  console.error(`arlandria supports Node 22.19-24.x (detected ${process.versions.node}).`);
  process.exit(1);
}
