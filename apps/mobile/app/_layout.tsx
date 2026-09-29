import { Stack } from "expo-router";
import { useColorScheme } from "react-native";

import { dossierColors } from "../src/theme.ts";

export default function RootLayout() {
  const theme = useColorScheme() === "dark" ? "dark" : "light";
  const colors = dossierColors(theme);
  return (
    <Stack screenOptions={{
      headerStyle: { backgroundColor: colors["surface-raised"] },
      headerTintColor: colors.text,
      contentStyle: { backgroundColor: colors.surface },
      headerBackTitle: "Back",
    }}>
      <Stack.Screen name="index" options={{ title: "Inktrospect" }} />
      <Stack.Screen name="capture" options={{ title: "Capture" }} />
      <Stack.Screen name="reports" options={{ title: "Reports" }} />
      <Stack.Screen name="history" options={{ title: "History" }} />
      <Stack.Screen name="settings" options={{ title: "Settings" }} />
    </Stack>
  );
}
