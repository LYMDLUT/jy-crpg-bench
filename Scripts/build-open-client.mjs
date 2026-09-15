#!/usr/bin/env node
import { cp, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const runtime = process.env.QUNXIA_CONTAINER_RUNTIME || "docker";
const image = process.env.QUNXIA_CLIENT_IMAGE || "jy-crpg-pi-client:0.84.4";
if (!["docker", "podman"].includes(runtime)) throw new Error("use docker or podman");
if (image.startsWith("-")) throw new Error("invalid image name");
const context = await mkdtemp(join(tmpdir(), "qunxia-client-image-"));
try {
  // An explicit build context keeps game data, credentials and other runs
  // out of both the image and the container engine's build cache.
  for (const name of ["package.json", "package-lock.json"]) {
    await cp(join(root, name), join(context, name));
  }
  for (const name of ["Dockerfile", "bridge.mjs"]) {
    await cp(join(root, "pi-agent/open-client", name), join(context, name));
  }
  await cp(join(root, "pi-agent/extensions/qunxia"), join(context, "qunxia"), { recursive: true });
  const child = spawn(runtime, ["build", "--tag", image, context], { stdio: "inherit" });
  process.exitCode = await new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("exit", code => resolve(code ?? 1));
  });
} finally {
  await rm(context, { recursive: true, force: true });
}
