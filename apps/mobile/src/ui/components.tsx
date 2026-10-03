// Shared native primitives in the Dossier language: a centered reading column
// on tablets, 44 pt touch targets, text that scales with the system setting,
// icon + text status (never colour alone) and announced errors.
import type { PropsWithChildren, ReactNode } from "react";
import {
  AccessibilityInfo, ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Switch, Text, TextInput,
  View, type StyleProp, type TextStyle, type ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useEffect } from "react";

import { useApp } from "../bootstrap/AppProvider.tsx";
import { fontSize, MAX_COLUMN, MIN_TOUCH, radius, space } from "./theme.ts";

export function Screen({ title, eyebrow, children, refreshing, onRefresh, footer }: PropsWithChildren<{
  title?: string; eyebrow?: string; refreshing?: boolean; onRefresh?: () => void; footer?: ReactNode;
}>) {
  const { theme } = useApp();
  return (
    <SafeAreaView edges={["left", "right", "bottom"]} style={[styles.safe, { backgroundColor: theme.color.surface }]}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
        {...(onRefresh ? { refreshControl: <RefreshControl refreshing={refreshing ?? false} onRefresh={onRefresh}
                                                           tintColor={theme.color.accent} /> } : {})}>
        <View style={styles.column}>
          {(title || eyebrow) ? (
            <View style={styles.header}>
              {eyebrow ? <Text style={[styles.eyebrow, { color: theme.color.accent, fontFamily: theme.sans }]}>{eyebrow}</Text> : null}
              {title ? <Text accessibilityRole="header" style={[styles.title, { color: theme.color.text, fontFamily: theme.serif }]}>{title}</Text> : null}
            </View>
          ) : null}
          <View style={styles.body}>{children}</View>
        </View>
      </ScrollView>
      {footer ? <View style={[styles.footer, { borderColor: theme.color.border, backgroundColor: theme.color["surface-raised"] }]}>
        <View style={styles.column}>{footer}</View>
      </View> : null}
    </SafeAreaView>
  );
}

export function Heading({ children, level = 2 }: PropsWithChildren<{ level?: 2 | 3 }>) {
  const { theme } = useApp();
  return (
    <Text accessibilityRole="header"
          style={[level === 2 ? styles.h2 : styles.h3, { color: theme.color.text, fontFamily: theme.serif }]}>
      {children}
    </Text>
  );
}

export function Body({ children, muted = false, style }: PropsWithChildren<{ muted?: boolean; style?: StyleProp<TextStyle> }>) {
  const { theme } = useApp();
  return (
    <Text style={[styles.copy, { color: muted ? theme.color["text-muted"] : theme.color.text, fontFamily: theme.serif }, style]}>
      {children}
    </Text>
  );
}

export function Mono({ children, style }: PropsWithChildren<{ style?: StyleProp<TextStyle> }>) {
  const { theme } = useApp();
  return <Text style={[styles.mono, { color: theme.color.text, fontFamily: theme.mono }, style]}>{children}</Text>;
}

type Tone = "primary" | "secondary" | "danger";

export function Button({ label, onPress, tone = "primary", disabled = false, busy = false, hint }: {
  label: string; onPress: () => void; tone?: Tone; disabled?: boolean; busy?: boolean; hint?: string;
}) {
  const { theme } = useApp();
  const filled = tone === "primary";
  const color = tone === "danger" ? theme.color["state-danger"] : theme.color.accent;
  const inactive = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: inactive, busy }}
      {...(hint ? { accessibilityHint: hint } : {})}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => [styles.button, {
        backgroundColor: filled ? color : "transparent", borderColor: color,
        opacity: inactive ? 0.45 : pressed ? 0.8 : 1,
      }]}>
      {busy ? <ActivityIndicator color={filled ? theme.color["accent-contrast"] : color} /> : null}
      <Text style={[styles.buttonText, { color: filled ? theme.color["accent-contrast"] : color, fontFamily: theme.sans }]}>
        {label}
      </Text>
    </Pressable>
  );
}

export type BannerTone = "info" | "attention" | "danger" | "ready";
const BANNER_ICON: Record<BannerTone, string> = { info: "ℹ︎", attention: "⚠︎", danger: "✕", ready: "✓" };

/** A status message. Errors are announced to screen readers when they appear. */
export function Banner({ tone = "info", children, action }: PropsWithChildren<{ tone?: BannerTone; action?: ReactNode }>) {
  const { theme } = useApp();
  const color = theme.color[tone === "info" ? "state-info" : tone === "attention" ? "state-attention"
    : tone === "danger" ? "state-danger" : "state-ready"];
  useEffect(() => {
    if (tone === "danger" && typeof children === "string") AccessibilityInfo.announceForAccessibility(children);
  }, [tone, children]);
  return (
    <View accessibilityRole={tone === "danger" ? "alert" : "text"} accessibilityLiveRegion="polite"
          style={[styles.banner, { borderColor: color, backgroundColor: theme.color["surface-raised"] }]}>
      <Text aria-hidden style={[styles.bannerIcon, { color }]}>{BANNER_ICON[tone]}</Text>
      <View style={styles.bannerBody}>
        <Text style={[styles.copy, { color: theme.color.text, fontFamily: theme.serif }]}>{children}</Text>
        {action}
      </View>
    </View>
  );
}

export function Card({ children, style }: PropsWithChildren<{ style?: StyleProp<ViewStyle> }>) {
  const { theme } = useApp();
  return <View style={[styles.card, { backgroundColor: theme.color["surface-raised"], borderColor: theme.color.border }, style]}>{children}</View>;
}

export function Toggle({ label, hint, value, onChange, disabled = false }: {
  label: string; hint?: string; value: boolean; onChange: (value: boolean) => void; disabled?: boolean;
}) {
  const { theme } = useApp();
  return (
    <View style={styles.toggle}>
      <View style={styles.toggleText}>
        <Text style={[styles.copy, { color: theme.color.text, fontFamily: theme.serif }]}>{label}</Text>
        {hint ? <Text style={[styles.small, { color: theme.color["text-muted"], fontFamily: theme.serif }]}>{hint}</Text> : null}
      </View>
      <Switch accessibilityLabel={label} {...(hint ? { accessibilityHint: hint } : {})} value={value}
              onValueChange={onChange} disabled={disabled}
              trackColor={{ true: theme.color.accent, false: theme.color["border-strong"] }} />
    </View>
  );
}

export function Choice<T extends string>({ label, options, value, onChange }: {
  label: string; options: ReadonlyArray<{ value: T; label: string }>; value: T; onChange: (value: T) => void;
}) {
  const { theme } = useApp();
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={label} style={styles.choice}>
      <Text style={[styles.label, { color: theme.color["text-muted"], fontFamily: theme.sans }]}>{label}</Text>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <Pressable key={option.value} accessibilityRole="radio" accessibilityState={{ checked: selected }}
                     onPress={() => onChange(option.value)}
                     style={[styles.choiceRow, { borderColor: selected ? theme.color.accent : theme.color.border }]}>
            <Text aria-hidden style={{ color: theme.color.accent, fontSize: fontSize("lg") }}>{selected ? "●" : "○"}</Text>
            <Text style={[styles.copy, { color: theme.color.text, fontFamily: theme.serif }]}>{option.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Field({ label, value, onChange, maxLength, multiline = false, hint }: {
  label: string; value: string; onChange: (value: string) => void; maxLength?: number; multiline?: boolean; hint?: string;
}) {
  const { theme } = useApp();
  return (
    <View style={styles.field}>
      <Text style={[styles.label, { color: theme.color["text-muted"], fontFamily: theme.sans }]}>{label}</Text>
      <TextInput accessibilityLabel={label} value={value} onChangeText={onChange} multiline={multiline}
                 {...(maxLength ? { maxLength } : {})} autoCapitalize="none" autoCorrect={false}
                 style={[styles.input, multiline ? styles.inputMultiline : null, {
                   color: theme.color.text, borderColor: theme.color["border-strong"], fontFamily: theme.serif,
                   backgroundColor: theme.color["surface-raised"] }]} />
      {hint ? <Text style={[styles.small, { color: theme.color["text-muted"] }]}>{hint}</Text> : null}
    </View>
  );
}

export function Busy({ label }: { label: string }) {
  const { theme } = useApp();
  return (
    <View accessibilityRole="progressbar" accessibilityLabel={label} style={styles.busy}>
      <ActivityIndicator color={theme.color.accent} />
      <Text style={[styles.copy, { color: theme.color["text-muted"], fontFamily: theme.serif }]}>{label}</Text>
    </View>
  );
}

export function KeyValue({ label, value }: { label: string; value: string }) {
  const { theme } = useApp();
  return (
    <View accessible accessibilityLabel={`${label}: ${value}`} style={styles.keyValue}>
      <Text style={[styles.small, { color: theme.color["text-muted"], fontFamily: theme.sans }]}>{label}</Text>
      <Text style={[styles.copy, { color: theme.color.text, fontFamily: theme.mono }]}>{value}</Text>
    </View>
  );
}

export const styles = StyleSheet.create({
  safe: { flex: 1 },
  scroll: { paddingHorizontal: space("5"), paddingVertical: space("6"), alignItems: "center" },
  column: { width: "100%", maxWidth: MAX_COLUMN, alignSelf: "center" },
  header: { gap: space("2"), marginBottom: space("5") },
  eyebrow: { fontSize: fontSize("cap"), fontWeight: "700", letterSpacing: 1.2, textTransform: "uppercase" },
  title: { fontSize: fontSize("display-sm") * 0.8, lineHeight: fontSize("display-sm") * 0.86, letterSpacing: -0.5 },
  body: { gap: space("4") },
  h2: { fontSize: fontSize("xl"), lineHeight: fontSize("xl") * 1.25, marginTop: space("3") },
  h3: { fontSize: fontSize("lg"), lineHeight: fontSize("lg") * 1.3 },
  copy: { fontSize: fontSize("md"), lineHeight: fontSize("md") * 1.5, flexShrink: 1 },
  small: { fontSize: fontSize("sm"), lineHeight: fontSize("sm") * 1.45 },
  mono: { fontSize: fontSize("md"), lineHeight: fontSize("md") * 1.4 },
  label: { fontSize: fontSize("cap"), fontWeight: "700", letterSpacing: 1, textTransform: "uppercase" },
  button: { minHeight: MIN_TOUCH, paddingHorizontal: space("4"), borderWidth: 1, borderRadius: radius("sm"),
            flexDirection: "row", alignItems: "center", justifyContent: "center", gap: space("2") },
  buttonText: { fontSize: fontSize("md"), fontWeight: "600", textAlign: "center" },
  banner: { flexDirection: "row", gap: space("3"), borderLeftWidth: 4, borderWidth: StyleSheet.hairlineWidth,
            borderRadius: radius("sm"), padding: space("3") },
  bannerIcon: { fontSize: fontSize("lg"), lineHeight: fontSize("md") * 1.5 },
  bannerBody: { flex: 1, gap: space("2") },
  card: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius("md"), padding: space("4"), gap: space("3") },
  toggle: { flexDirection: "row", alignItems: "center", gap: space("3"), minHeight: MIN_TOUCH },
  toggleText: { flex: 1, gap: space("1") },
  choice: { gap: space("2") },
  choiceRow: { flexDirection: "row", alignItems: "center", gap: space("3"), minHeight: MIN_TOUCH, borderWidth: 1,
               borderRadius: radius("sm"), paddingHorizontal: space("3") },
  field: { gap: space("2") },
  input: { minHeight: MIN_TOUCH, borderWidth: 1, borderRadius: radius("sm"), paddingHorizontal: space("3"),
           fontSize: fontSize("md") },
  inputMultiline: { minHeight: 120, paddingVertical: space("3"), textAlignVertical: "top" },
  busy: { flexDirection: "row", alignItems: "center", gap: space("3"), minHeight: MIN_TOUCH },
  keyValue: { gap: space("1") },
  footer: { borderTopWidth: StyleSheet.hairlineWidth, paddingHorizontal: space("5"), paddingVertical: space("3") },
});
