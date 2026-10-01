// Lets `node --test` import the app's plain .js modules, which (like Vite) use extensionless
// relative imports. Only used by `npm test`; the app itself is always built by Vite.
import { register } from "node:module";

register("./resolve-extensionless.mjs", import.meta.url);
