import { Link } from "expo-router";
import { StyleSheet, useColorScheme, View } from "react-native";

import { dossierColors } from "../src/theme.ts";
import { DossierCopy, DossierScreen } from "../src/ui/DossierScreen.tsx";

const routes = [
  ["Capture handwriting", "/capture"],
  ["Reports", "/reports"],
  ["History", "/history"],
  ["Settings", "/settings"],
] as const;

export default function Home() {
  const theme = useColorScheme() === "dark" ? "dark" : "light";
  const colors = dossierColors(theme);
  return (
    <DossierScreen eyebrow="Inktrospect" title="Your handwriting, measured.">
      <DossierCopy>
        Native T29 foundation. Deterministic report facts remain server-owned; this shell does not measure,
        grant credits, or authorize content.
      </DossierCopy>
      <View style={styles.links}>
        {routes.map(([label, href]) => (
          <Link key={href} href={href} style={[styles.link, { color: colors.accent, borderColor: colors.border }]}>
            {label}
          </Link>
        ))}
      </View>
    </DossierScreen>
  );
}

const styles = StyleSheet.create({
  links: { gap: 12 },
  link: { minHeight: 44, paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth, fontSize: 17 },
});
