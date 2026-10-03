import { router } from "expo-router";

import { useApp } from "../src/bootstrap/AppProvider.tsx";
import { Body, Button, Screen } from "../src/ui/components.tsx";

export default function NotFound() {
  const { t } = useApp();
  return (
    <Screen title={t("report.unavailable")}>
      <Body muted>{t("report.unavailable")}</Body>
      <Button label={t("common.back_home")} onPress={() => router.replace("/")} />
    </Screen>
  );
}
