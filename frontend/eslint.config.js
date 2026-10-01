import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default [
  { ignores: ["dist"] },
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: "latest",
        ecmaFeatures: { jsx: true },
        sourceType: "module",
      },
    },
    plugins: {
      "react-hooks":    reactHooks,
      "react-refresh":  reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // a name used but never defined only shows up when that screen is opened (it crashed My Reports once)
      "no-undef": "error",
      // Context/shared modules deliberately co-export hooks and helpers; the
      // rule only affects dev-time fast refresh, so it stays off.
      "react-refresh/only-export-components": "off",
    },
  },
  {
    files: ["vite.config.js", "scripts/**", "**/*.test.js"],
    languageOptions: { globals: globals.node },
  },
];
