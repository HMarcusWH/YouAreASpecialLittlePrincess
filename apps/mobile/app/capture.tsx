import { useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, useColorScheme, View } from "react-native";

import { ExpoCaptureClient } from "../src/platform/native/capture.ts";
import type { LocalCapture } from "../src/platform/contracts.ts";
import { dossierColors } from "../src/theme.ts";
import { DossierCopy, DossierScreen } from "../src/ui/DossierScreen.tsx";

export default function Capture() {
  const client = useMemo(() => new ExpoCaptureClient(), []);
  const [capture, setCapture] = useState<LocalCapture | null>(null);
  const [message, setMessage] = useState("No photo selected.");
  const theme = useColorScheme() === "dark" ? "dark" : "light";
  const colors = dossierColors(theme);

  const run = async (source: "camera" | "library") => {
    const result = source === "camera" ? await client.takePhoto() : await client.pickPhoto();
    setCapture(result);
    setMessage(result
      ? "Prepared " + result.width + "×" + result.height + " JPEG derivative for safe server upload."
      : "No authorized photo was returned.");
  };

  return (
    <DossierScreen eyebrow="Local preparation only" title="Capture">
      <DossierCopy>
        HEIC/HEIF or other picker input is normalized to a JPEG derivative. The server still verifies bytes,
        dimensions, media type, permissions and ownership before analysis.
      </DossierCopy>
      <View style={styles.row}>
        <Pressable accessibilityRole="button" style={[styles.button, { borderColor: colors.accent }]} onPress={() => void run("camera")}>
          <Text style={{ color: colors.accent }}>Take photo</Text>
        </Pressable>
        <Pressable accessibilityRole="button" style={[styles.button, { borderColor: colors.accent }]} onPress={() => void run("library")}>
          <Text style={{ color: colors.accent }}>Choose photo</Text>
        </Pressable>
      </View>
      <Text accessibilityLiveRegion="polite" style={{ color: colors["text-muted"] }}>{message}</Text>
      {capture ? <Text style={{ color: colors.text }}>Source: {capture.source} · original {capture.originalMimeType ?? "unknown"}</Text> : null}
    </DossierScreen>
  );
}

const styles = StyleSheet.create({
  row: { gap: 12 },
  button: { minHeight: 44, justifyContent: "center", paddingHorizontal: 16, borderWidth: 1, borderRadius: 4 },
});
