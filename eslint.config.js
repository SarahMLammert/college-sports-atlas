// The site's linter: npm run lint   (npm install once; tests/test_atlas.py runs it too: test_site_code_is_clean)
// Rules: ESLint's recommended set (https://eslint.org/docs/latest/rules/): names used but never defined, variables
// never used, code that can't run, empty blocks, and similar slips. The scripts inside the pages are checked too.
import js from "@eslint/js";
import html from "eslint-plugin-html";
import globals from "globals";

export default [
  { ignores: ["docs/sports.js"] },          // written by build.py pages from the settings
  js.configs.recommended,
  {
    files: ["docs/**/*.js", "docs/**/*.html"],
    plugins: { html },
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "script",
      globals: {
        ...globals.browser,
        d3: "readonly",                     // the libraries the pages load from the CDN
        topojson: "readonly",
        GP: "readonly",                     // docs/common.js's helpers, shared by every page
      },
    },
  },
];
