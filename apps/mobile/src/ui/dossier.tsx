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
import {
  Banner, Body, Button, EditorialSection, EditorialStatement, Heading, MarginNote, Mono, Paper, SectionLabel,
  styles as base,
} from "./components.tsx";
import { evidencePosition, stepEvidenceIndex } from "./evidence-inspector.ts";
import { EVIDENCE_COLOR, fontSize, MIN_TOUCH, radius, space } from "./theme.ts";

function numberText(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "sv" ? "sv-SE" : "en-GB", { maximumFractionDigits: 2 }).format(value);
}

function fixedPosition(value: number, min: number, max: number): number {
  if (!Number.isFinite(value) || !(max > min)) return 0;
  return Math.max(0, Math.min(1, (value - min) / (max - min)));
}

function percent(value: number): `${number}%` {
  return `${value}%`;
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
  const highlight = section.kind !== "SECTION";
  return (
    <EditorialSection style={highlight ? local.highlightSection : undefined}>
      <SectionLabel>{section.title}</SectionLabel>
      {section.copy.map((text, index) => (
        <View key={`${section.sectionId}-copy-${index}`} style={local.copyRow}>
          <EvidenceBadge fact={{ evidenceClass: "AUTHORED_CONTENT", evidenceIcon: "✎",
                                 evidenceText: reportText(locale, "evidence.AUTHORED_CONTENT") }} />
          {highlight && index === 0 ? (
            <EditorialStatement secondary={section.kind === "HIGHLIGHT_SECONDARY"}>{text}</EditorialStatement>
          ) : (
            <MarginNote index={index + 1}><Body>{text}</Body></MarginNote>
          )}
        </View>
      ))}
      {section.premiumSectionId !== null ? <Body muted>{reportText(locale, "report.premium_saved")}</Body> : null}
      {section.facts.length === 0 && section.availability !== "READY" && section.availability !== "UNCALIBRATED" ? (
        <Body muted>{section.availabilityText}</Body>
      ) : null}
      {section.facts.map((fact) => <FactRow key={fact.factId} fact={fact} locale={locale} />)}
    </EditorialSection>
  );
}

/** A baseline trace drawn from stored points only: dots, and segments between consecutive stored points. */
export function TraceDrawing({ points, width, height, color, thickness = 2, opacity = 1 }: {
  points: readonly (readonly [number, number])[]; width: number; height: number; color: string; thickness?: number;
  opacity?: number;
}) {
  return (
    <View pointerEvents="none" style={{ position: "absolute", left: 0, top: 0, width, height, opacity }}>
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

function PageMap({ bundle, locale }: { bundle: EvidenceBundle; locale: Locale }) {
  const { theme } = useApp();
  const [available, setAvailable] = useState(0);
  const frame = bundle.frames.find((f) => f.frame_id === "frame_analysis")
    ?? bundle.frames.find((f) => f.parent_frame_id !== null)
    ?? bundle.frames[0];
  if (!frame) return null;
  const lines = bundle.regions.filter((r) => r.scope === "LINE" && r.frame_id === frame.frame_id);
  if (lines.length === 0) return null;
  const width = available;
  const height = width > 0 ? Math.max(80, Math.min(220, width * frame.height / frame.width)) : 140;
  const sx = width > 0 ? width / frame.width : 0;
  const sy = height / frame.height;
  const label = `${reportText(locale, "evidence.regions")}: ${lines.length}`;
  return (
    <View accessible accessibilityRole="image" accessibilityLabel={label} style={local.figure}>
      <SectionLabel>{reportText(locale, "evidence.regions")}</SectionLabel>
      <View onLayout={(event: LayoutChangeEvent) => setAvailable(event.nativeEvent.layout.width)}
            style={[local.pageMap, { width: "100%", height, borderColor: theme.color.border,
                                    backgroundColor: theme.color["surface-sunken"] }]}>
        {sx > 0 ? lines.map((line) => (
          <View key={line.region_id} aria-hidden style={{
            position: "absolute", left: line.x * sx, top: line.y * sy,
            width: Math.max(1, line.width * sx), height: Math.max(2, line.height * sy),
            borderWidth: 1, borderColor: theme.color["evidence-measured"],
            backgroundColor: "transparent",
          }} />
        )) : null}
      </View>
      <Body muted>{label}</Body>
    </View>
  );
}

function SlantRange({ bundle, locale }: { bundle: EvidenceBundle; locale: Locale }) {
  const { theme } = useApp();
  const observations = bundle.observations.filter((o) => o.feature_id === "SLANT_ANGLE_MEAN"
    && typeof o.value === "number");
  if (observations.length === 0) return null;
  const accepted = observations.filter((o) => o.accepted).length;
  const rejected = observations.length - accepted;
  const label = `${reportText(locale, "evidence.slant_observations")}: ${accepted} ${reportText(locale, "evidence.accepted")}, ${rejected} ${reportText(locale, "evidence.rejected")}`;
  return (
    <View accessible accessibilityRole="image" accessibilityLabel={label} style={local.figure}>
      <SectionLabel>{reportText(locale, "evidence.slant_observations")}</SectionLabel>
      <View style={local.slantAxis}>
        <View aria-hidden style={[local.slantLine, { backgroundColor: theme.color.border }]} />
        <View aria-hidden style={[local.slantAcceptedBand, {
          left: percent(fixedPosition(-60, -90, 90) * 100),
          width: percent((fixedPosition(60, -90, 90) - fixedPosition(-60, -90, 90)) * 100),
          backgroundColor: theme.color["evidence-measured"],
        }]} />
        {observations.map((obs) => {
          const value = obs.value as number;
          const left = fixedPosition(value, -90, 90) * 100;
          return (
            <View key={obs.observation_id} aria-hidden style={[local.slantMarker, {
              left: percent(left),
              backgroundColor: obs.accepted ? theme.color.accent : theme.color["surface-raised"],
              borderColor: obs.accepted ? theme.color.accent : theme.color["state-attention"],
            }]} />
          );
        })}
      </View>
      <View style={local.slantTicks}>
        <Mono style={local.slantTick}>−90°</Mono>
        <Mono style={local.slantTick}>−60°</Mono>
        <Mono style={local.slantTick}>0°</Mono>
        <Mono style={local.slantTick}>+60°</Mono>
        <Mono style={local.slantTick}>+90°</Mono>
      </View>
      <Body muted>{label}</Body>
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
    <Paper>
      <SectionLabel>{reportText(locale, "evidence.title")}</SectionLabel>
      <Body muted>{reportText(locale, "evidence.intro")}</Body>
      <Heading level={3}>{reportText(locale, "evidence.baseline")}</Heading>
      {traces.length === 0 ? <Body muted>{reportText(locale, "evidence.none")}</Body> : null}
      {traces.map((trace, index) => (
        <BaselineFigure key={trace.lineRegionId} trace={trace} index={index} bundle={bundle} locale={locale} />
      ))}
      <PageMap bundle={bundle} locale={locale} />
      <ObservationTable title={reportText(locale, "evidence.regions")} rows={[...spacing("LINE_SPACING_PX"),
                                                                              ...spacing("WORD_SPACING_PX")]}
                        locale={locale} />
      <SlantRange bundle={bundle} locale={locale} />
      {slant.length > 0 ? <Body muted>{reportText(locale, "evidence.no_histogram")}</Body> : null}
      <ObservationTable title={reportText(locale, "evidence.slant_observations")} rows={slant} locale={locale} />
    </Paper>
  );
}

/**
 * The retained source image, fetched with the current credential through the
 * report-scoped route. Evidence is drawn on it only when the stored frame
 * matches the delivered image exactly; otherwise the image is shown plain.
 */
export function SourceImage({ reportId, bundle, locale }: { reportId: string; bundle: EvidenceBundle | null; locale: Locale }) {
  const { services, theme, t } = useApp();
  const [state, setState] = useState<{ uri: string; width: number; height: number } | "loading" | "unavailable">("loading");
  const [overlay, setOverlay] = useState(true);
  const [selectedTrace, setSelectedTrace] = useState(0);
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
  const traces = matches && bundle ? baselineTraces(bundle).map((trace) => ({
    trace,
    points: trace.points.map(([x, y]) => {
      const [mx, my] = mapToAncestor(bundle.frames, trace.frameId, root!.frame_id, x, y);
      return [mx * scale, my * scale] as const;
    }),
  })) : [];
  const selected = traces.length > 0 ? Math.min(selectedTrace, traces.length - 1) : 0;
  return (
    <Paper>
      <SectionLabel>{reportText(locale, "image.title")}</SectionLabel>
      <ScrollView maximumZoomScale={4} minimumZoomScale={1} bouncesZoom
                  accessibilityLabel={reportText(locale, "image.title")}>
        <View onLayout={(e: LayoutChangeEvent) => setAvailable(e.nativeEvent.layout.width)}
              style={[local.sourcePlate, { width: "100%", height: scale > 0 ? state.height * scale : 200,
                                          backgroundColor: theme.color["surface-sunken"] }]}>
          {scale > 0 ? <Image source={{ uri: state.uri }} accessibilityIgnoresInvertColors
                              style={{ width: state.width * scale, height: state.height * scale }} /> : null}
          {scale > 0 && overlay ? traces.map((entry, index) => (
            <TraceDrawing key={entry.trace.lineRegionId} points={entry.points}
                          width={state.width * scale} height={state.height * scale}
                          color={index === selected ? theme.color.accent : theme.color["evidence-measured"]}
                          thickness={index === selected ? 3 : 1.5} opacity={index === selected ? 1 : 0.42} />
          )) : null}
        </View>
      </ScrollView>
      {!matches && bundle ? <Body muted>{reportText(locale, "image.frame_mismatch")}</Body> : null}
      {matches && traces.length > 0 ? (
        <>
          <View style={local.inspector} accessible accessibilityRole="adjustable"
                accessibilityLabel={`${t("report.evidence_inspector")}: ${evidencePosition(selected, traces.length)}`}
                accessibilityActions={[
                  { name: "decrement", label: t("report.evidence_previous") },
                  { name: "increment", label: t("report.evidence_next") },
                ]}
                onAccessibilityAction={(event) => {
                  if (event.nativeEvent.actionName === "decrement") {
                    setSelectedTrace(stepEvidenceIndex(selected, "PREVIOUS", traces.length));
                  }
                  if (event.nativeEvent.actionName === "increment") {
                    setSelectedTrace(stepEvidenceIndex(selected, "NEXT", traces.length));
                  }
                }}>
            <View style={local.inspectorHeading}>
              <SectionLabel>{t("report.evidence_inspector")}</SectionLabel>
              <Mono style={{ color: theme.color["text-muted"], fontSize: fontSize("sm") }}>
                {evidencePosition(selected, traces.length)}
              </Mono>
            </View>
            <Body muted>{`${reportText(locale, "evidence.baseline_line")} ${selected + 1} · ${traces[selected]!.trace.points.length} ${reportText(locale, "evidence.points")}`}</Body>
          </View>
          <View style={local.inspectorActions}>
            <Button tone="secondary" label={t("report.evidence_previous")} disabled={selected <= 0}
                    onPress={() => setSelectedTrace(stepEvidenceIndex(selected, "PREVIOUS", traces.length))} />
            <Button tone="secondary" label={t("report.evidence_next")} disabled={selected >= traces.length - 1}
                    onPress={() => setSelectedTrace(stepEvidenceIndex(selected, "NEXT", traces.length))} />
          </View>
          <Button tone="secondary" label={reportText(locale, overlay ? "image.overlay_off" : "image.overlay_on")}
                  onPress={() => setOverlay(!overlay)} />
        </>
      ) : null}
    </Paper>
  );
}

export function DossierView({ model, onAction, busyAction }: {
  model: DossierModel; onAction: (kind: string) => void; busyAction?: string | null;
}) {
  const { theme } = useApp();
  const locale = model.locale;
  return (
    <Paper style={local.dossier} elevated>
      <View style={local.header}>
        <SectionLabel>{reportText(locale, "report.dossier")}</SectionLabel>
        <Text accessibilityRole="header" style={[base.title, { color: theme.color.text, fontFamily: theme.serif }]}>
          {reportText(locale, `projection.${model.projection}`)}
        </Text>
        <Mono style={{ color: theme.color["text-muted"], fontSize: fontSize("sm") }}>
          {reportText(locale, "report.revision")} {model.revision}
        </Mono>
      </View>
      {model.highlights.length > 0 ? (
        <View style={local.group} accessibilityLabel={reportText(locale, "report.first_reveal")}>
          <SectionLabel>{reportText(locale, "report.first_reveal")}</SectionLabel>
          {model.highlights.map((section) => <SectionView key={section.sectionId} section={section} locale={locale} />)}
        </View>
      ) : null}
      <View style={local.notices}>
        {model.notices.map((notice) => <Banner key={notice.notice_id} tone={notice.class === "PRIVACY" ? "ready" : "info"}>{notice.text}</Banner>)}
      </View>
      <View style={local.group}>
        <SectionLabel>{reportText(locale, "report.mechanical_dossier")}</SectionLabel>
        {model.sections.map((section) => <SectionView key={section.sectionId} section={section} locale={locale} />)}
      </View>
      <EditorialSection>
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
      </EditorialSection>
    </Paper>
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
  dossier: { gap: space("6") },
  header: { gap: space("2") },
  highlightSection: { borderTopWidth: 0, paddingTop: 0 },
  group: { gap: space("4") },
  notices: { gap: space("2") },
  badge: { flexDirection: "row", alignItems: "center", gap: space("1"), borderWidth: 1, borderRadius: radius("xs"),
           paddingHorizontal: space("2"), paddingVertical: 3, alignSelf: "flex-start" },
  badgeText: { fontSize: fontSize("xs"), fontWeight: "600" },
  factRow: { flexDirection: "row", flexWrap: "wrap", gap: space("3"), paddingVertical: space("3"),
             borderTopWidth: StyleSheet.hairlineWidth, minHeight: MIN_TOUCH },
  factMain: { flexGrow: 1, flexBasis: 200, gap: space("1") },
  factMeta: { flexDirection: "row", alignItems: "center", gap: space("2"), flexWrap: "wrap" },
  factValue: { alignItems: "flex-end", justifyContent: "center", flexShrink: 0, maxWidth: "100%" },
  value: { fontSize: fontSize("value"), fontVariant: ["tabular-nums"] },
  copyRow: { gap: space("3") },
  figure: { gap: space("2") },
  canvas: { width: "100%", borderWidth: StyleSheet.hairlineWidth, borderRadius: radius("xs"), overflow: "hidden" },
  sourcePlate: { overflow: "hidden", borderRadius: 0 },
  pageMap: { alignSelf: "center", borderWidth: StyleSheet.hairlineWidth, overflow: "hidden" },
  slantAxis: { height: 36, justifyContent: "center", position: "relative" },
  slantLine: { position: "absolute", left: 0, right: 0, height: StyleSheet.hairlineWidth },
  slantAcceptedBand: { position: "absolute", height: 8, opacity: 0.18 },
  slantMarker: { position: "absolute", top: 11, width: 12, height: 12, marginLeft: -6,
                 borderRadius: 6, borderWidth: 2 },
  slantTicks: { flexDirection: "row", justifyContent: "space-between", gap: space("1") },
  slantTick: { fontSize: fontSize("xs") },
  inspector: { gap: space("1") },
  inspectorHeading: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", gap: space("3") },
  inspectorActions: { flexDirection: "row", gap: space("2"), flexWrap: "wrap" },
  table: { gap: space("2") },
  tableRow: { borderTopWidth: StyleSheet.hairlineWidth, paddingVertical: space("2"), gap: 2 },
  tableCell: { flexShrink: 1 },
  actions: { gap: space("3") },
  action: { gap: space("1") },
  selectable: { flexDirection: "row", alignItems: "center", gap: space("3"), borderWidth: 1, borderRadius: radius("xs"),
                padding: space("3"), minHeight: MIN_TOUCH },
});
