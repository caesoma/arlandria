const [maj, min] = process.versions.node.split(".").map(Number);
if (maj < 20 || (maj === 20 && min < 19) || maj > 24) {
  console.error(`arlandria supports Node 20.19-24.x (detected ${process.versions.node}).`);
  process.exit(1);
}
