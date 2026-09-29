import type { PropsWithChildren } from "react";
import { SafeAreaView, ScrollView, StyleSheet, Text, useColorScheme, View } from "react-native";

import { dossierColors } from "../theme.ts";

export function DossierScreen({ title, eyebrow, children }: PropsWithChildren<{ title: string; eyebrow?: string }>) {
  const theme = useColorScheme() === "dark" ? "dark" : "light";
  const colors = dossierColors(theme);
  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: colors.surface }]}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.header}>
          {eyebrow ? <Text style={[styles.eyebrow, { color: colors.accent }]}>{eyebrow}</Text> : null}
          <Text accessibilityRole="header" style={[styles.title, { color: colors.text }]}>{title}</Text>
        </View>
        <View style={styles.body}>{children}</View>
      </ScrollView>
    </SafeAreaView>
  );
}

export function DossierCopy({ children }: PropsWithChildren) {
  const theme = useColorScheme() === "dark" ? "dark" : "light";
  return <Text style={[styles.copy, { color: dossierColors(theme)["text-muted"] }]}>{children}</Text>;
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: { paddingHorizontal: 24, paddingVertical: 32, gap: 28 },
  header: { gap: 8 },
  eyebrow: { fontSize: 12, fontWeight: "700", letterSpacing: 1.2, textTransform: "uppercase" },
  title: { fontSize: 44, lineHeight: 46, fontWeight: "400", letterSpacing: -1 },
  body: { gap: 16 },
  copy: { fontSize: 16, lineHeight: 24 },
});
