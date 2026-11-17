// Copies the face-api weights the portal loads at runtime into public/models/.
// Only the three nets used by src/face/engine.ts are copied.
import { copyFile, mkdir, readFile, rm, stat } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MODELS = ["ssd_mobilenetv1_model", "face_landmark_68_model", "face_recognition_model"];

const require = createRequire(import.meta.url);
const source = join(dirname(require.resolve("@vladmandic/face-api/package.json")), "model");
const target = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "models");

await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });

let total = 0;
for (const model of MODELS) {
  const manifest = `${model}-weights_manifest.json`;
  const groups = JSON.parse(await readFile(join(source, manifest), "utf8"));
  const files = [manifest, ...groups.flatMap((group) => group.paths)];
  for (const file of files) {
    await copyFile(join(source, file), join(target, file));
    total += (await stat(join(target, file))).size;
  }
}

console.log(`face models: ${MODELS.length} nets, ${(total / 1024 / 1024).toFixed(1)} MB -> public/models/`);
