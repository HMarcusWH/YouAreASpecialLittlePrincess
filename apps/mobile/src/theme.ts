import { tokens } from "@princess/design-tokens";

export type NativeTheme = "light" | "dark";

export function dossierColors(theme: NativeTheme) {
  return tokens.color[theme];
}

export const dossierSpacing = tokens.space;
export const dossierRadius = tokens.radius;
