// The saved, validated Premium overlay (N11): AI-assisted prose labelled as
// such, each answer with its state and the measured facts it rests on, and
// explicit omissions. Rendering never calls a model; the text is shown only
// as plain text, never as markup.
import type { PremiumContent } from "@princess/api-client";
import type { Fact } from "@princess/contracts";
import { featureName, t as reportText, type Locale } from "@princess/report-core";
import { Text, View } from "react-native";

import { useApp } from "../bootstrap/AppProvider.tsx";
import { Banner, Body, Card, Heading, styles as base } from "./components.tsx";
import { EvidenceBadge } from "./dossier.tsx";

export function PremiumOverlay({ content, facts, locale }: { content: PremiumContent; facts: readonly Fact[];
                                                             locale: Locale }) {
  const { theme } = useApp();
  const byId = new Map(facts.map((fact) => [fact.fact_id, fact] as const));
  const support = (ids: readonly string[]) => ids.map((id) => {
    const fact = byId.get(id);
    return fact ? featureName(fact.feature_id, locale) : id;
  }).join(", ");
  const badge = { evidenceClass: "AI_SYNTHESIS" as const, evidenceIcon: "✦",
                  evidenceText: reportText(locale, "evidence.AI_SYNTHESIS") };
  return (
    <Card style={{ borderColor: theme.color["evidence-ai"], borderWidth: 1 }}>
      <EvidenceBadge fact={badge} />
      <Heading>{reportText(locale, "premium.title")}</Heading>
      <Body muted>{reportText(locale, "premium.intro")}</Body>
      {content.soft_fields.map((field) => (
        <View key={field.field_id} style={{ gap: 4 }}>
          <Body>{field.text}</Body>
          {field.support_fact_ids.length > 0 ? (
            <Text style={[base.small, { color: theme.color["text-muted"] }]}>
              {reportText(locale, "premium.support")}: {support(field.support_fact_ids)}
            </Text>
          ) : null}
        </View>
      ))}
      {content.answers.map((answer) => (
        <View key={answer.question_id} accessible style={{ gap: 4, borderTopWidth: 1, borderColor: theme.color.border,
                                                           paddingTop: 8 }}>
          <Text style={[base.label, { color: theme.color["text-muted"] }]}>
            {reportText(locale, "premium.question")} · {answer.question_id}
          </Text>
          {answer.prose !== null ? <Body>{answer.prose}</Body> : null}
          {answer.answer_state !== "ANSWERED" ? (
            <Body muted>{reportText(locale, `premium.answer.${answer.answer_state}`)}</Body>
          ) : null}
          {answer.support_fact_ids.length > 0 ? (
            <Text style={[base.small, { color: theme.color["text-muted"] }]}>
              {reportText(locale, "premium.support")}: {support(answer.support_fact_ids)}
            </Text>
          ) : null}
        </View>
      ))}
      {content.omissions.length > 0 ? (
        <Banner tone="info">{`${reportText(locale, "premium.omitted")}: ${content.omissions.length}. ${reportText(locale, "premium.omission")}`}</Banner>
      ) : null}
    </Card>
  );
}
