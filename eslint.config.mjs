import tseslint from "typescript-eslint";

export default [
  ...tseslint.configs.recommended,
  {
    files: ["**/*.mjs"],
    languageOptions: { sourceType: "module", ecmaVersion: "latest" },
  },
];
