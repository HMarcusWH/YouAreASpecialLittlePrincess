// The saved, validated Premium overlay (N11): AI-assisted prose labelled as
// such, each answer with its state and the measured facts it rests on, and
// explicit omissions. Rendering never calls a model; the text is shown only
// as plain text, never as markup.
import type { PremiumContent } from "@princess/api-client";
import type { Fact } from "@princess/contracts";
import { featureName, t as reportText, type Locale } from "@princess/report-core";
import { Text, View } from "react-native";

import { useApp } from "../bootstrap/AppProvider.tsx";
import { Banner, Body, EditorialSection, EditorialStatement, Paper, styles as base } from "./components.tsx";
import { EvidenceBadge } from "./dossier.tsx";

export function PremiumOverlay({ content, facts, locale }: { content: PremiumContent; facts: readonly Fact[];
                                                             locale: Locale }) {
  const { theme } = useApp();
  const byId = new Map(facts.map((fact) => [fact.fact_id, fact] as const));
  const supportLabels = (ids: readonly string[]) => ids.map((id) => {
    const fact = byId.get(id);
    return { id, label: fact ? featureName(fact.feature_id, locale) : id };
  });

  function SupportFacts({ ids }: { ids: readonly string[] }) {
    if (ids.length === 0) return null;
    return (
      <View style={{ gap: 6 }}>
        <Text style={[base.label, { color: theme.color["text-muted"], fontFamily: theme.mono }]}>
          {reportText(locale, "premium.support")}
        </Text>
        {supportLabels(ids).map((item) => (
          <View key={item.id} style={{
            alignSelf: "flex-start", maxWidth: "100%", borderWidth: 1, borderColor: theme.color.border,
            paddingHorizontal: 10, paddingVertical: 8, borderRadius: 2,
          }}>
            <Text style={[base.small, { color: theme.color["text-muted"], fontFamily: theme.mono }]}>
              — {item.label}
            </Text>
          </View>
        ))}
      </View>
    );
  }
  const badge = { evidenceClass: "AI_SYNTHESIS" as const, evidenceIcon: "✦",
                  evidenceText: reportText(locale, "evidence.AI_SYNTHESIS") };
  return (
    <Paper style={{ borderColor: theme.color["evidence-ai"], borderWidth: 1 }}>
      <EvidenceBadge fact={badge} />
      <EditorialStatement>{reportText(locale, "premium.title")}</EditorialStatement>
      <Body muted>{reportText(locale, "premium.intro")}</Body>
      {content.soft_fields.map((field) => (
        <View key={field.field_id} style={{ gap: 4 }}>
          <Body>{field.text}</Body>
          <SupportFacts ids={field.support_fact_ids} />
        </View>
      ))}
      {content.answers.map((answer) => (
        <EditorialSection key={answer.question_id} style={{ gap: 4 }}>
          <Text style={[base.label, { color: theme.color["evidence-ai"], fontFamily: theme.mono }]}>
            {reportText(locale, "premium.question")} · {answer.question_id}
          </Text>
          {answer.prose !== null ? <Body>{answer.prose}</Body> : null}
          {answer.answer_state !== "ANSWERED" ? (
            <Body muted>{reportText(locale, `premium.answer.${answer.answer_state}`)}</Body>
          ) : null}
          <SupportFacts ids={answer.support_fact_ids} />
        </EditorialSection>
      ))}
      {content.omissions.length > 0 ? (
        <Banner tone="info">{`${reportText(locale, "premium.omitted")}: ${content.omissions.length}. ${reportText(locale, "premium.omission")}`}</Banner>
      ) : null}
    </Paper>
  );
}
