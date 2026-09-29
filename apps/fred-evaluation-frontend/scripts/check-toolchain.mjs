import { fileURLToPath } from "node:url";

// Node 22 from 22.13 on, the release the image pins; any later 22.x works for
// local development.
export const REQUIRED_MAJOR = 22;
export const MINIMUM_MINOR = 13;

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
