import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useMemo } from "react";
import { Text, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AppProvider, useApp } from "../src/bootstrap/AppProvider.tsx";
import { loadConfig } from "../src/bootstrap/native.ts";
import { copy, resolveLocale } from "../src/i18n/copy.ts";
import { Busy, Screen } from "../src/ui/components.tsx";
import { themeFor } from "../src/ui/theme.ts";

function ConfigError({ code }: { code: string }) {
  // Rendered before any service exists: plain components, device language only.
  const locale = resolveLocale("system", Intl.DateTimeFormat().resolvedOptions().locale);
  const theme = themeFor("light");
  return (
    <View accessibilityRole="alert" style={{ flex: 1, padding: 24, justifyContent: "center", gap: 12,
                                             backgroundColor: theme.color.surface }}>
      <Text style={{ fontSize: 22, color: theme.color.text, fontFamily: theme.serif }}>{copy(locale, "app.config_error")}</Text>
      <Text style={{ fontSize: 15, color: theme.color["text-muted"], fontFamily: theme.mono }}>
        {copy(locale, "app.config_code")}: {code}
      </Text>
    </View>
  );
}

function Shell() {
  const { theme, t, session } = useApp();
  if (session.status === "LOADING") {
    return <Screen title={t("app.name")}><Busy label={t("app.loading")} /></Screen>;
  }
  return (
    <>
      <StatusBar style={theme.scheme === "dark" ? "light" : "dark"} />
      <Stack screenOptions={{
        headerStyle: { backgroundColor: theme.color["surface-raised"] },
        headerTintColor: theme.color.text,
        headerTitleStyle: { fontFamily: theme.serif },
        contentStyle: { backgroundColor: theme.color.surface },
      }}>
        <Stack.Screen name="index" options={{ title: t("app.name") }} />
        <Stack.Screen name="capture" options={{ title: t("capture.title") }} />
        <Stack.Screen name="review" options={{ title: t("review.title") }} />
        <Stack.Screen name="work/[opId]" options={{ title: t("work.title") }} />
        <Stack.Screen name="reports/index" options={{ title: t("history.title") }} />
        <Stack.Screen name="reports/[reportId]/index" options={{ title: t("report.title") }} />
        <Stack.Screen name="reports/[reportId]/feedback" options={{ title: t("feedback.title"), presentation: "modal" }} />
        <Stack.Screen name="reports/[reportId]/premium" options={{ title: t("premium.title") }} />
        <Stack.Screen name="compare" options={{ title: t("compare.title") }} />
        <Stack.Screen name="settings" options={{ title: t("settings.title") }} />
        <Stack.Screen name="account" options={{ title: t("account.title"), presentation: "modal" }} />
      </Stack>
    </>
  );
}

export default function RootLayout() {
  const config = useMemo(loadConfig, []);
  if (!config.ok) return <ConfigError code={config.code} />;
  return (
    <SafeAreaProvider>
      <AppProvider config={config.config}>
        <Shell />
      </AppProvider>
    </SafeAreaProvider>
  );
}
