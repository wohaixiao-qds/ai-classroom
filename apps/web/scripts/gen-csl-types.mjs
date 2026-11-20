import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const apiRoot = fileURLToPath(new URL("../../api/", import.meta.url));
const target = fileURLToPath(new URL("../src/types/csl.gen.ts", import.meta.url));
const schema = JSON.parse(execFileSync("uv", ["run", "python", "scripts/export_csl_schema.py"], {
  cwd: apiRoot,
  encoding: "utf8",
}));
const output = "// Generated from apps/api/app/schemas/csl.py. Run pnpm gen-csl-types.\n"
  + astToString(await openapiTS(schema));

if (process.argv.includes("--check")) {
  let current = "";
  try { current = readFileSync(target, "utf8"); } catch { /* Report missing output as drift. */ }
  if (current !== output) {
    console.error("CSL types are stale. Run pnpm -C apps/web gen-csl-types and commit the output.");
    process.exitCode = 1;
  } else {
    console.log("CSL types match the Python schema.");
  }
} else {
  writeFileSync(target, output);
  console.log("Generated src/types/csl.gen.ts");
}
