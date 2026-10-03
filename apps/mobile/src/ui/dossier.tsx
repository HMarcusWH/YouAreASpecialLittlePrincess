// Native Dossier renderer (N04). Everything shown comes from the saved,
// authorized projection and its stored evidence: the server-selected First
// Reveal, every Free measurement with its evidence class and availability,
// notices, actions with their reasons, and evidence drawn from stored points.
// Missing values render as gaps with a reason, never as zero.
import type { EvidenceBundle } from "@princess/contracts";
import {
  baselineTraces, mapToAncestor, spacingBrackets, t as reportText, type BaselineTrace, type DossierModel,
  type DossierSection, type FactPresentation, type Locale,
} from "@princess/report-core";
import { useEffect, useState, type ReactNode } from "react";
import { Image, Pressable, ScrollView, StyleSheet, Text, View, type LayoutChangeEvent } from "react-native";

import { useApp } from "../bootstrap/AppProvider.tsx";
import { Banner, Body, Button, Card, Heading, Mono, styles as base } from "./components.tsx";
import { EVIDENCE_COLOR, fontSize, MIN_TOUCH, radius, space } from "./theme.ts";

function numberText(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "sv" ? "sv-SE" : "en-GB", { maximumFractionDigits: 2 }).format(value);
}

export function EvidenceBadge({ fact }: { fact: Pick<FactPresentation, "evidenceClass" | "evidenceIcon" | "evidenceText"> }) {
  const { theme } = useApp();
  const color = theme.color[EVIDENCE_COLOR[fact.evidenceClass]];
  return (
    <View style={[local.badge, { borderColor: color }]}>
      <Text aria-hidden style={{ color, fontSize: fontSize("sm") }}>{fact.evidenceIcon}</Text>
      <Text style={[local.badgeText, { color, fontFamily: theme.sans }]}>{fact.evidenceText}</Text>
    </View>
  );
}

export function FactRow({ fact, locale }: { fact: FactPresentation; locale: Locale }) {
  const { theme } = useApp();
  const value = fact.value ?? fact.availabilityText;
  const calibration = fact.value !== null && !fact.calibrated ? reportText(locale, "availability.UNCALIBRATED") : null;
  const label = [fact.label, value, calibration, fact.evidenceText,
                 `${reportText(locale, "fact.observations")} ${fact.observations}`].filter(Boolean).join(", ");
  return (
    <View accessible accessibilityLabel={label} style={[local.factRow, { borderColor: theme.color.border }]}>
      <View style={local.factMain}>
        <Text style={[base.copy, { color: theme.color.text, fontFamily: theme.serif }]}>{fact.label}</Text>
        <View style={local.factMeta}>
          <EvidenceBadge fact={fact} />
          <Text style={[base.small, { color: theme.color["text-muted"], fontFamily: theme.mono }]}>n = {fact.observations}</Text>
        </View>
      </View>
      <View style={local.factValue}>
        {fact.value !== null ? (
          <Text style={[local.value, { color: theme.color.text, fontFamily: theme.mono }]}>{fact.value}</Text>
        ) : (
          <Text style={[base.small, { color: theme.color["state-locked"], fontFamily: theme.serif }]}>— {fact.availabilityText}</Text>
        )}
        {calibration ? <Text style={[base.small, { color: theme.color["state-attention"], fontFamily: theme.sans }]}>{calibration}</Text> : null}
      </View>
    </View>
  );
}

function SectionView({ section, locale }: { section: DossierSection; locale: Locale }) {
  const { theme } = useApp();
  const highlight = section.kind !== "SECTION";
  return (
    <Card style={highlight ? { borderColor: theme.color.accent, borderWidth: 1 } : undefined}>
      <Heading level={highlight ? 2 : 3}>{section.title}</Heading>
      {section.copy.map((text, index) => (
        <View key={`${section.sectionId}-copy-${index}`} style={local.copyRow}>
          <EvidenceBadge fact={{ evidenceClass: "AUTHORED_CONTENT", evidenceIcon: "✎",
                                 evidenceText: reportText(locale, "evidence.AUTHORED_CONTENT") }} />
          <Body>{text}</Body>
        </View>
      ))}
      {section.premiumSectionId !== null ? (
        <Body muted>{reportText(locale, "report.premium_saved")}</Body>
      ) : null}
      {section.facts.length === 0 && section.availability !== "READY" && section.availability !== "UNCALIBRATED" ? (
        <Body muted>{section.availabilityText}</Body>
      ) : null}
      {section.facts.map((fact) => <FactRow key={fact.factId} fact={fact} locale={locale} />)}
    </Card>
  );
}

/** A baseline trace drawn from stored points only: dots, and segments between consecutive stored points. */
export function TraceDrawing({ points, width, height, color, thickness = 2 }: {
  points: readonly (readonly [number, number])[]; width: number; height: number; color: string; thickness?: number;
}) {
  return (
    <View pointerEvents="none" style={{ position: "absolute", left: 0, top: 0, width, height }}>
      {points.slice(1).map(([x2, y2], index) => {
        const [x1, y1] = points[index]!;
        const length = Math.hypot(x2 - x1, y2 - y1);
        const angle = Math.atan2(y2 - y1, x2 - x1);
        return (
          <View key={`s${index}`} style={{
            position: "absolute", left: (x1 + x2) / 2 - length / 2, top: (y1 + y2) / 2 - thickness / 2, width: length,
            height: thickness, backgroundColor: color, transform: [{ rotate: `${angle}rad` }] }} />
        );
      })}
      {points.map(([x, y], index) => (
        <View key={`p${index}`} style={{ position: "absolute", left: x - thickness * 1.5, top: y - thickness * 1.5,
                                         width: thickness * 3, height: thickness * 3, borderRadius: thickness * 1.5,
                                         backgroundColor: color }} />
      ))}
    </View>
  );
}

function BaselineFigure({ trace, index, bundle, locale }: { trace: BaselineTrace; index: number; bundle: EvidenceBundle;
                                                           locale: Locale }) {
  const { theme } = useApp();
  const [available, setAvailable] = useState(0);
  const frame = bundle.frames.find((f) => f.frame_id === trace.frameId);
  if (!frame) return null;
  const scale = available > 0 ? available / frame.width : 0;
  const caption = `${reportText(locale, "evidence.baseline_line")} ${index + 1} · ${trace.points.length} ${reportText(locale, "evidence.points")}`
    + (trace.angleDegrees === null ? ` · ${reportText(locale, "evidence.angle_missing")}`
      : ` · ${numberText(trace.angleDegrees, locale)}°`);
  return (
    <View accessible accessibilityRole="image" accessibilityLabel={caption} style={local.figure}>
      <View onLayout={(e: LayoutChangeEvent) => setAvailable(e.nativeEvent.layout.width)}
            style={[local.canvas, { height: Math.max(48, frame.height * scale), borderColor: theme.color.border,
                                    backgroundColor: theme.color["surface-sunken"] }]}>
        {scale > 0 ? <TraceDrawing points={trace.points.map(([x, y]) => [x * scale, y * scale] as const)}
                                   width={available} height={frame.height * scale}
                                   color={theme.color["evidence-measured"]} /> : null}
      </View>
      <Text style={[base.small, { color: theme.color["text-muted"], fontFamily: theme.serif }]}>{caption}</Text>
    </View>
  );
}

function ObservationTable({ title, rows, locale }: { title: string; locale: Locale;
  rows: ReadonlyArray<{ key: string; label: string; value: string; accepted: boolean; reason: string | null }> }) {
  const { theme } = useApp();
  if (rows.length === 0) return null;
  return (
    <View style={local.table}>
      <Heading level={3}>{title}</Heading>
      {rows.map((row) => {
        const status = row.accepted ? reportText(locale, "evidence.accepted")
          : `${reportText(locale, "evidence.rejected")}: ${row.reason ?? ""}`;
        return (
          <View key={row.key} accessible accessibilityLabel={`${row.label}, ${row.value}, ${status}`}
                style={[local.tableRow, { borderColor: theme.color.border }]}>
            <Text style={[base.small, local.tableCell, { color: theme.color["text-muted"], fontFamily: theme.mono }]}>{row.label}</Text>
            <Text style={[base.small, { color: theme.color.text, fontFamily: theme.mono }]}>{row.value}</Text>
            <Text style={[base.small, { color: row.accepted ? theme.color["state-ready"] : theme.color["state-attention"],
                                        fontFamily: theme.sans }]}>{row.accepted ? "✓ " : "✕ "}{status}</Text>
          </View>
        );
      })}
    </View>
  );
}

export function EvidencePanel({ bundle, locale }: { bundle: EvidenceBundle; locale: Locale }) {
  const traces = baselineTraces(bundle);
  const spacing = (featureId: "LINE_SPACING_PX" | "WORD_SPACING_PX") => spacingBrackets(bundle, featureId)
    .map((row, index) => ({ key: `${featureId}-${index}`, label: `${row.from.region_id} → ${row.to.region_id}`,
                            value: `${numberText(row.gap, locale)} px`, accepted: row.accepted,
                            reason: row.rejectionReason }));
  const slant = bundle.observations.filter((o) => o.feature_id === "SLANT_ANGLE_MEAN").map((o) => ({
    key: o.observation_id, label: o.observation_id,
    value: typeof o.value === "number" ? `${numberText(o.value, locale)}${o.unit ? ` ${o.unit}` : ""}` : String(o.value),
    accepted: o.accepted, reason: o.rejection_reason }));
  return (
    <Card>
      <Heading>{reportText(locale, "evidence.title")}</Heading>
      <Body muted>{reportText(locale, "evidence.intro")}</Body>
      <Heading level={3}>{reportText(locale, "evidence.baseline")}</Heading>
      {traces.length === 0 ? <Body muted>{reportText(locale, "evidence.none")}</Body> : null}
      {traces.map((trace, index) => (
        <BaselineFigure key={trace.lineRegionId} trace={trace} index={index} bundle={bundle} locale={locale} />
      ))}
      <ObservationTable title={reportText(locale, "evidence.regions")} rows={[...spacing("LINE_SPACING_PX"),
                                                                              ...spacing("WORD_SPACING_PX")]}
                        locale={locale} />
      {slant.length > 0 ? <Body muted>{reportText(locale, "evidence.no_histogram")}</Body> : null}
      <ObservationTable title={reportText(locale, "evidence.slant_observations")} rows={slant} locale={locale} />
    </Card>
  );
}

/**
 * The retained source image, fetched with the current credential through the
 * report-scoped route. Evidence is drawn on it only when the stored frame
 * matches the delivered image exactly; otherwise the image is shown plain.
 */
export function SourceImage({ reportId, bundle, locale }: { reportId: string; bundle: EvidenceBundle | null; locale: Locale }) {
  const { services, theme } = useApp();
  const [state, setState] = useState<{ uri: string; width: number; height: number } | "loading" | "unavailable">("loading");
  const [overlay, setOverlay] = useState(true);
  const [available, setAvailable] = useState(0);
  useEffect(() => {
    let alive = true;
    let downloaded: string | null = null;
    void (async () => {
      try {
        const file = await services.ports.downloads.download(await services.api.sourceImageDownload(reportId),
                                                             `source-${reportId.replace(/[^A-Za-z0-9._-]/g, "_")}.img`,
                                                             { maxBytes: 20 * 1024 * 1024, mediaTypes: ["image/jpeg", "image/png"] });
        downloaded = file.uri;
        Image.getSize(file.uri, (width, height) => { if (alive) setState({ uri: file.uri, width, height }); },
                      () => { if (alive) setState("unavailable"); });
      } catch {
        if (alive) setState("unavailable");
      }
    })();
    return () => {
      alive = false;
      // The private copy lives only while the report is open (and is swept at launch otherwise).
      if (downloaded) void services.ports.downloads.remove(downloaded).catch(() => undefined);
    };
  }, [reportId, services]);

  if (state === "loading") return null;
  if (state === "unavailable") return <Body muted>{reportText(locale, "image.unavailable")}</Body>;
  const root = bundle?.frames.find((f) => f.parent_frame_id === null && f.unit === "px");
  const matches = root !== undefined && root.width === state.width && root.height === state.height;
  const scale = available > 0 ? available / state.width : 0;
  const traces = matches && bundle ? baselineTraces(bundle).map((trace) => trace.points.map(([x, y]) => {
    const [mx, my] = mapToAncestor(bundle.frames, trace.frameId, root!.frame_id, x, y);
    return [mx * scale, my * scale] as const;
  })) : [];
  return (
    <Card>
      <Heading>{reportText(locale, "image.title")}</Heading>
      <ScrollView maximumZoomScale={4} minimumZoomScale={1} bouncesZoom
                  accessibilityLabel={reportText(locale, "image.title")}>
        <View onLayout={(e: LayoutChangeEvent) => setAvailable(e.nativeEvent.layout.width)}
              style={{ width: "100%", height: scale > 0 ? state.height * scale : 200 }}>
          {scale > 0 ? <Image source={{ uri: state.uri }} accessibilityIgnoresInvertColors
                              style={{ width: state.width * scale, height: state.height * scale,
                                       borderRadius: radius("xs") }} /> : null}
          {scale > 0 && overlay ? traces.map((points, index) => (
            <TraceDrawing key={index} points={points} width={state.width * scale} height={state.height * scale}
                          color={theme.color.accent} />
          )) : null}
        </View>
      </ScrollView>
      {!matches && bundle ? <Body muted>{reportText(locale, "image.frame_mismatch")}</Body> : null}
      {matches && traces.length > 0 ? (
        <Button tone="secondary" label={reportText(locale, overlay ? "image.overlay_off" : "image.overlay_on")}
                onPress={() => setOverlay(!overlay)} />
      ) : null}
    </Card>
  );
}

export function DossierView({ model, onAction, busyAction }: {
  model: DossierModel; onAction: (kind: string) => void; busyAction?: string | null;
}) {
  const { theme } = useApp();
  const locale = model.locale;
  return (
    <View style={local.dossier}>
      <View style={local.header}>
        <Text style={[base.eyebrow, { color: theme.color.accent }]}>{reportText(locale, "report.dossier")}</Text>
        <Text accessibilityRole="header" style={[base.title, { color: theme.color.text, fontFamily: theme.serif }]}>
          {reportText(locale, `projection.${model.projection}`)}
        </Text>
        <Mono style={{ color: theme.color["text-muted"], fontSize: fontSize("sm") }}>
          {reportText(locale, "report.revision")} {model.revision}
        </Mono>
      </View>
      {model.highlights.length > 0 ? (
        <View style={local.group} accessibilityLabel={reportText(locale, "report.first_reveal")}>
          <Text style={[base.eyebrow, { color: theme.color.accent }]}>{reportText(locale, "report.first_reveal")}</Text>
          {model.highlights.map((section) => <SectionView key={section.sectionId} section={section} locale={locale} />)}
        </View>
      ) : null}
      <View style={local.notices}>
        {model.notices.map((notice) => <Banner key={notice.notice_id} tone={notice.class === "PRIVACY" ? "ready" : "info"}>{notice.text}</Banner>)}
      </View>
      <View style={local.group}>
        <Text style={[base.eyebrow, { color: theme.color.accent }]}>{reportText(locale, "report.mechanical_dossier")}</Text>
        {model.sections.map((section) => <SectionView key={section.sectionId} section={section} locale={locale} />)}
      </View>
      <View accessibilityRole="toolbar" style={local.actions}>
        {model.actions.map((action) => (
          <View key={action.action_id} style={local.action}>
            <Button tone="secondary" label={action.label} disabled={!action.enabled} busy={busyAction === action.kind}
                    onPress={() => onAction(action.kind)}
                    {...(action.reasonText ? { hint: action.reasonText } : {})} />
            {action.reasonText ? <Text style={[base.small, { color: theme.color["text-muted"] }]}>{action.reasonText}</Text> : null}
          </View>
        ))}
      </View>
    </View>
  );
}

export function SelectableRow({ selected, onPress, children, label }: {
  selected: boolean; onPress: () => void; label: string; children: ReactNode;
}) {
  const { theme } = useApp();
  return (
    <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: selected }} accessibilityLabel={label}
               onPress={onPress}
               style={[local.selectable, { borderColor: selected ? theme.color.accent : theme.color.border }]}>
      <Text aria-hidden style={{ color: theme.color.accent, fontSize: fontSize("lg") }}>{selected ? "☑" : "☐"}</Text>
      <View style={{ flex: 1 }}>{children}</View>
    </Pressable>
  );
}

const local = StyleSheet.create({
  dossier: { gap: space("5") },
  header: { gap: space("2") },
  group: { gap: space("3") },
  notices: { gap: space("2") },
  badge: { flexDirection: "row", alignItems: "center", gap: space("1"), borderWidth: 1, borderRadius: radius("pill"),
           paddingHorizontal: space("2"), paddingVertical: 2, alignSelf: "flex-start" },
  badgeText: { fontSize: fontSize("xs"), fontWeight: "600" },
  factRow: { flexDirection: "row", flexWrap: "wrap", gap: space("3"), paddingVertical: space("3"),
             borderTopWidth: StyleSheet.hairlineWidth, minHeight: MIN_TOUCH },
  factMain: { flexGrow: 1, flexBasis: 200, gap: space("1") },
  factMeta: { flexDirection: "row", alignItems: "center", gap: space("2"), flexWrap: "wrap" },
  factValue: { alignItems: "flex-end", justifyContent: "center", flexShrink: 0, maxWidth: "100%" },
  value: { fontSize: fontSize("lg"), fontVariant: ["tabular-nums"] },
  copyRow: { gap: space("2") },
  figure: { gap: space("2") },
  canvas: { width: "100%", borderWidth: StyleSheet.hairlineWidth, borderRadius: radius("sm"), overflow: "hidden" },
  table: { gap: space("2") },
  tableRow: { borderTopWidth: StyleSheet.hairlineWidth, paddingVertical: space("2"), gap: 2 },
  tableCell: { flexShrink: 1 },
  actions: { gap: space("3") },
  action: { gap: space("1") },
  selectable: { flexDirection: "row", alignItems: "center", gap: space("3"), borderWidth: 1, borderRadius: radius("sm"),
                padding: space("3"), minHeight: MIN_TOUCH },
});
