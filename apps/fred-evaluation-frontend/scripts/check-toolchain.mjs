import { fileURLToPath } from "node:url";

// Match Weaver: Node 24 from 24.21 on; .nvmrc and the image pin 24.22.2.
export const REQUIRED_MAJOR = 24;
export const MINIMUM_MINOR = 21;

export function assertSupportedNode(version) {
  const [major, minor] = version.split(".").map(Number);
  if (major !== REQUIRED_MAJOR || minor < MINIMUM_MINOR) {
    throw new Error(
      `Node ${REQUIRED_MAJOR}.x from ${REQUIRED_MAJOR}.${MINIMUM_MINOR} is required; found ${version}.`,
    );
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  assertSupportedNode(process.versions.node);
}
