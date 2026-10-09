// Fred ships this UI's building blocks as published npm packages: consume them
// by exact version from the public registry, never from a local checkout.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const EXPECTED = Object.freeze({
  "@fred-oss/design-tokens": "0.1.0-alpha.4",
  "@fred-oss/ui": "0.1.0-alpha.4",
  "@fred-oss/iframe-sdk": "0.1.0-alpha.4",
  react: "19.2.4",
  "react-dom": "19.2.4",
});

const forbidden =
  /(?:^|[/:])(file:|workspace:|link:)|\.tgz(?:$|[?#])|fred-frontend-packaging/i;
const registry = "https://registry.npmjs.org/";

function checkReference(reference, label) {
  if (typeof reference !== "string" || forbidden.test(reference)) {
    throw new Error(`Local or invalid dependency reference at ${label}`);
  }
  if (reference.startsWith("http:") || reference.startsWith("https:")) {
    if (!reference.startsWith(registry)) {
      throw new Error(`Non-registry dependency reference at ${label}`);
    }
  } else if (
    reference.startsWith(".") ||
    reference.startsWith("/") ||
    reference.includes("node_modules/")
  ) {
    throw new Error(`Local dependency reference at ${label}`);
  }
}

function checkDependencies(dependencies, label) {
  for (const [name, version] of Object.entries(dependencies ?? {})) {
    checkReference(version, `${label}.${name}`);
  }
}

export function validateBoundary(manifest, lockfile) {
  if (
    !manifest?.private ||
    lockfile?.lockfileVersion !== 3 ||
    !lockfile?.packages
  ) {
    throw new Error("Expected a private npm workspace with a v3 lockfile");
  }
  const root = lockfile.packages[""];
  if (!root) throw new Error("Missing lockfile root");
  for (const [name, version] of Object.entries(EXPECTED)) {
    if (
      manifest.dependencies?.[name] !== version ||
      root.dependencies?.[name] !== version
    ) {
      throw new Error(
        `Expected exact ${name}@${version} in manifest and lockfile`,
      );
    }
    const member = lockfile.packages[`node_modules/${name}`];
    if (!member || member.version !== version) {
      throw new Error(`Missing locked ${name}@${version}`);
    }
  }
  for (const [name, version] of Object.entries(manifest.dependencies ?? {})) {
    if (root.dependencies?.[name] !== version) {
      throw new Error(`Manifest/lockfile dependency mismatch: ${name}`);
    }
  }
  checkDependencies(manifest.dependencies, "manifest.dependencies");
  checkDependencies(manifest.devDependencies, "manifest.devDependencies");
  for (const [name, entry] of Object.entries(lockfile.packages)) {
    if (
      entry.link ||
      name.includes("..") ||
      (name && !name.startsWith("node_modules/"))
    ) {
      throw new Error(`Unexpected lockfile link or package path: ${name}`);
    }
    checkDependencies(entry.dependencies, `${name}.dependencies`);
    checkDependencies(
      entry.optionalDependencies,
      `${name}.optionalDependencies`,
    );
    if (name) {
      if (
        typeof entry.resolved !== "string" ||
        !entry.resolved.startsWith(registry)
      ) {
        throw new Error(`Package ${name} must resolve from the npm registry`);
      }
      if (!/^sha512-[A-Za-z0-9+/]+={0,2}$/.test(entry.integrity ?? "")) {
        throw new Error(`Package ${name} lacks registry SHA-512 integrity`);
      }
    }
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const manifest = JSON.parse(
    readFileSync(new URL("../package.json", import.meta.url), "utf8"),
  );
  const lockfile = JSON.parse(
    readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"),
  );
  validateBoundary(manifest, lockfile);
  console.log(
    "Published FRED coordinates and registry dependency boundary verified",
  );
}
